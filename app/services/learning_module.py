"""
Angelina AI Financial Expert Agent -- Learning Module.

Non-blocking background knowledge extraction that analyzes conversation
turns after the response is delivered to the user. Identifies financial
knowledge points, deduplicates against the existing vector store, and
writes novel points to the Knowledge_Base via RAGEngine.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from app.services.gemini_gateway import GeminiGateway
    from app.services.rag_engine import RAGEngine

from app.models import Chunk, LearningStats, Turn

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Deduplication threshold: if cosine similarity >= this, the point is a duplicate
DEDUP_SIMILARITY_THRESHOLD = 0.85

# After this many new points since last rebuild, trigger index rebuild
REBUILD_THRESHOLD = 50

# Path to NotebookLM data for rebuild
NOTEBOOKLM_DATA_PATH = "data/notebooklm"

# System prompt for knowledge extraction from conversation turns
_EXTRACTION_SYSTEM_PROMPT = """\
You are a financial knowledge extraction engine. Analyze the following conversation turn \
and extract distinct financial knowledge points.

ONLY extract knowledge points that fall into these domains:
- Investment strategies (stock, fund, portfolio allocation, asset classes)
- Tax rules (tax planning, deductions, brackets, capital gains)
- Budgeting principles (saving rates, expense categories, emergency funds)
- Risk management guidelines (diversification, hedging, insurance, stop-loss)
- Market data facts (interest rates, index values, economic indicators, historical returns)

For each knowledge point, output a JSON array of objects with:
- "text": the knowledge point as a concise, self-contained statement (1-3 sentences)
- "source_type": one of "user_input" or "assistant_response" depending on who provided the information

If no financial knowledge points are found, return an empty JSON array: []

IMPORTANT: Return ONLY the JSON array, no other text. Example:
[{"text": "The S&P 500 has historically returned about 10% annually before inflation.", "source_type": "assistant_response"}]
"""


# ---------------------------------------------------------------------------
# LearningModule class
# ---------------------------------------------------------------------------


class LearningModule:
    """
    Non-blocking background knowledge extraction module.

    Called via `asyncio.create_task` after a conversation response is delivered.
    Extracts financial knowledge points from conversation turns, deduplicates
    them against the existing vector store, and writes novel points.

    Every 50 new knowledge points accumulated since last rebuild, triggers
    a RAGEngine index rebuild.
    """

    def __init__(self, rag_engine: "RAGEngine", gemini_gateway: "GeminiGateway") -> None:
        self._rag_engine = rag_engine
        self._gemini_gateway = gemini_gateway

        # Counters
        self._new_points_since_rebuild: int = 0
        self._session_points: dict[str, int] = {}  # session_id -> count of new points

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def extract_and_store(self, turn: Turn, session_id: str) -> None:
        """
        Extract financial knowledge points from a conversation turn and store
        novel points in the knowledge base.

        This method is designed to be called as a background task via
        `asyncio.create_task` and will not raise exceptions to the caller.
        All errors are silently logged.

        Args:
            turn: The conversation turn to analyze.
            session_id: The session identifier for tracking stats.
        """
        try:
            # Step 1: Call Gemini API to extract knowledge points
            knowledge_points = await self._extract_knowledge_points(turn)

            if not knowledge_points:
                log.debug(
                    "No knowledge points extracted",
                    session_id=session_id,
                    turn_role=turn.role,
                )
                return

            log.info(
                "Knowledge points extracted",
                session_id=session_id,
                count=len(knowledge_points),
            )

            # Step 2: Deduplicate and store each knowledge point
            new_chunks: list[Chunk] = []
            for point in knowledge_points:
                is_duplicate = await self._is_duplicate(point["text"])
                if not is_duplicate:
                    chunk = Chunk(
                        id=str(uuid.uuid4()),
                        text=point["text"],
                        source_type=point.get("source_type", self._infer_source_type(turn)),
                        created_at=datetime.now(timezone.utc).isoformat(),
                        similarity=0.0,
                    )
                    new_chunks.append(chunk)

            # Step 3: Write non-duplicate chunks to the knowledge base
            if new_chunks:
                await self._rag_engine.add_chunks(new_chunks)
                added_count = len(new_chunks)
                self._new_points_since_rebuild += added_count

                # Track session stats
                if session_id not in self._session_points:
                    self._session_points[session_id] = 0
                self._session_points[session_id] += added_count

                log.info(
                    "Knowledge points stored",
                    session_id=session_id,
                    new_count=added_count,
                    total_since_rebuild=self._new_points_since_rebuild,
                )

                # Step 4: Trigger rebuild if threshold reached
                if self._new_points_since_rebuild >= REBUILD_THRESHOLD:
                    await self._trigger_rebuild()

        except Exception as exc:
            # Background task: silently log errors without crashing
            log.error(
                "Learning module extraction failed",
                session_id=session_id,
                error=str(exc),
                exc_info=True,
            )

    async def get_stats(self, session_id: str) -> LearningStats:
        """
        Return learning statistics.

        Args:
            session_id: The session to get stats for.

        Returns:
            LearningStats with total_learned (all knowledge points in vector store)
            and session_learned (new points added in this session).
        """
        try:
            total_learned = await self._rag_engine.get_collection_count()
        except Exception as exc:
            log.error("Failed to get collection count", error=str(exc))
            total_learned = 0

        session_learned = self._session_points.get(session_id, 0)

        return LearningStats(
            total_learned=total_learned,
            session_learned=session_learned,
            last_rebuild_at=None,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _extract_knowledge_points(self, turn: Turn) -> list[dict]:
        """
        Call Gemini API to identify financial knowledge points in the turn.

        Returns a list of dicts with 'text' and 'source_type' keys.
        """
        try:
            response = await self._gemini_gateway.generate(
                system_prompt=_EXTRACTION_SYSTEM_PROMPT,
                context_turns=[],
                knowledge_chunks=[],
                user_message=turn.content,
                language="en",  # Use English for extraction to keep prompts consistent
            )

            # Parse JSON response
            return self._parse_extraction_response(response.text, turn)

        except Exception as exc:
            log.warning(
                "Knowledge extraction Gemini call failed",
                error=str(exc),
            )
            return []

    def _parse_extraction_response(self, response_text: str, turn: Turn) -> list[dict]:
        """
        Parse the Gemini extraction response into a list of knowledge points.

        Expected format: JSON array of {"text": "...", "source_type": "..."}
        """
        try:
            # Try to extract JSON from the response
            text = response_text.strip()

            # Handle cases where model wraps JSON in markdown code blocks
            if text.startswith("```"):
                # Remove markdown code block markers
                lines = text.split("\n")
                # Remove first and last line if they are code block markers
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines).strip()

            points = json.loads(text)

            if not isinstance(points, list):
                log.warning("Extraction response is not a list", response=response_text[:200])
                return []

            # Validate and normalize each point
            valid_points: list[dict] = []
            valid_source_types = {"user_input", "assistant_response", "document_upload"}

            for point in points:
                if not isinstance(point, dict):
                    continue
                if "text" not in point or not point["text"].strip():
                    continue

                source_type = point.get("source_type", self._infer_source_type(turn))
                if source_type not in valid_source_types:
                    source_type = self._infer_source_type(turn)

                valid_points.append({
                    "text": point["text"].strip(),
                    "source_type": source_type,
                })

            return valid_points

        except (json.JSONDecodeError, ValueError) as exc:
            log.warning(
                "Failed to parse extraction response",
                error=str(exc),
                response=response_text[:200],
            )
            return []

    async def _is_duplicate(self, text: str) -> bool:
        """
        Check if a knowledge point is a duplicate by computing its embedding
        and querying ChromaDB for the closest match.

        Returns True if max cosine similarity >= 0.85.
        """
        try:
            # Use RAG engine search to find closest match
            # We query with top_k=1 to find the most similar existing entry
            results = await self._rag_engine.search(query=text, top_k=1)

            if not results:
                return False

            # Check if the closest match exceeds dedup threshold
            max_similarity = results[0].similarity
            return max_similarity >= DEDUP_SIMILARITY_THRESHOLD

        except Exception as exc:
            log.warning(
                "Deduplication check failed, allowing write",
                error=str(exc),
            )
            # On error, allow the write (fail-open for knowledge acquisition)
            return False

    def _infer_source_type(self, turn: Turn) -> str:
        """Infer the source_type from the turn's role."""
        if turn.role == "user":
            return "user_input"
        elif turn.role == "assistant":
            return "assistant_response"
        else:
            return "user_input"

    async def _trigger_rebuild(self) -> None:
        """
        Trigger a RAG index rebuild when the accumulated new-point count
        reaches the threshold (50).
        """
        try:
            # Find the latest export file
            export_path = await asyncio.to_thread(
                self._find_latest_export, NOTEBOOKLM_DATA_PATH
            )

            if export_path is None:
                log.warning(
                    "No NotebookLM export found for rebuild; skipping",
                    path=NOTEBOOKLM_DATA_PATH,
                )
                # Still reset counter to avoid repeated attempts
                self._new_points_since_rebuild = 0
                return

            log.info(
                "Triggering index rebuild",
                export_path=export_path,
                new_points_since_last=self._new_points_since_rebuild,
            )

            await self._rag_engine.rebuild_index(export_path)
            self._new_points_since_rebuild = 0

            log.info("Index rebuild complete after learning threshold reached")

        except Exception as exc:
            log.error(
                "Index rebuild failed",
                error=str(exc),
                exc_info=True,
            )
            # Reset counter to avoid tight rebuild loop on persistent errors
            self._new_points_since_rebuild = 0

    @staticmethod
    def _find_latest_export(notebooklm_path: str) -> str | None:
        """Return the most recently modified .txt or .md file under notebooklm_path."""
        import glob
        import os

        patterns = [
            os.path.join(notebooklm_path, "**", "*.txt"),
            os.path.join(notebooklm_path, "**", "*.md"),
        ]
        candidates: list[str] = []
        for pattern in patterns:
            candidates.extend(glob.glob(pattern, recursive=True))
        if not candidates:
            return None
        return max(candidates, key=os.path.getmtime)
