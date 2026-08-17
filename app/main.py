"""
Angelina AI Financial Expert Agent -- FastAPI Main Application.

Serves the Chat UI, provides API endpoints for conversation, memory
management, knowledge base operations, and system health/stats.

Requirements: 1.1, 2.2, 2.3, 2.4, 2.5, 3.3, 3.4, 3.5, 3.6, 4.2, 4.4, 4.5, 5.4, 5.7, 6.4
"""

from __future__ import annotations

import asyncio
import re
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from app.models import ChatRequest, ChatResponse, SourceRef
from app.services.conversation_memory import ConversationMemory
from app.services.gemini_gateway import (
    GeminiAPIError,
    GeminiGateway,
    GeminiQueueFullError,
    GeminiQuotaExhaustedError,
    GeminiTimeoutError,
)
from app.services.learning_module import LearningModule
from app.services.rag_engine import RAGEngine


# ---------------------------------------------------------------------------
# Structured logging configuration (structlog JSON)
# ---------------------------------------------------------------------------


def _configure_logging() -> None:
    """Configure structlog with JSON output to /var/log/angelina/app.log."""
    log_dir = Path("/var/log/angelina")
    log_file_path = log_dir / "app.log"

    # Try to create log directory; fall back to local logging on failure
    # (e.g., on Windows or when permissions are insufficient)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = open(log_file_path, "a", encoding="utf-8")  # noqa: SIM115
    except (PermissionError, OSError):
        # Fallback: log to stderr if /var/log/angelina is not writable
        log_file = sys.stderr  # type: ignore[assignment]

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),  # Allow all levels
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=log_file),
        cache_logger_on_first_use=True,
    )


_configure_logging()
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Singleton service instances (populated during lifespan)
# ---------------------------------------------------------------------------

_memory: ConversationMemory | None = None
_rag_engine: RAGEngine | None = None
_gemini_gateway: GeminiGateway | None = None
_learning_module: LearningModule | None = None


# ---------------------------------------------------------------------------
# FastAPI Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize and tear down service singletons."""
    global _memory, _rag_engine, _gemini_gateway, _learning_module

    logger.info("application_startup", message="Initializing services...")

    # Initialize ConversationMemory
    _memory = ConversationMemory()
    await _memory.initialize()
    logger.info("service_ready", service="ConversationMemory")

    # Initialize RAGEngine
    _rag_engine = RAGEngine()
    await _rag_engine.initialise()
    logger.info("service_ready", service="RAGEngine")

    # Initialize GeminiGateway
    _gemini_gateway = GeminiGateway()
    logger.info("service_ready", service="GeminiGateway")

    # Initialize LearningModule
    _learning_module = LearningModule(rag_engine=_rag_engine, gemini_gateway=_gemini_gateway)
    logger.info("service_ready", service="LearningModule")

    logger.info("application_startup_complete", message="All services initialized.")

    yield

    # Teardown
    logger.info("application_shutdown", message="Shutting down services...")
    if _gemini_gateway:
        await _gemini_gateway.close()
    logger.info("application_shutdown_complete", message="All services shut down.")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Angelina AI Financial Expert Agent",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint. Returns HTTP 200 with status ok."""
    return {"status": "ok"}


@app.get("/stats")
async def get_stats() -> dict:
    """Return system statistics: memory turn count and vector count."""
    assert _memory is not None
    assert _rag_engine is not None

    memory_turns = await _memory.get_turn_count()
    vector_count = await _rag_engine.get_collection_count()

    return {"memory_turns": memory_turns, "vector_count": vector_count}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Core conversation endpoint.

    Flow:
    1. Validate ChatRequest (handled by Pydantic model)
    2. Check for special commands (/learning-stats)
    3. Load last 20 turns from ConversationMemory
    4. Semantic search via RAG Engine (top_k=5, similarity >= 0.5)
    5. Call Gemini Gateway with system_prompt + context + chunks + message
    6. Save turn (user + assistant) to ConversationMemory
    7. Return ChatResponse
    8. Fire asyncio.create_task(learning.extract_and_store(turn)) - non-blocking
    """
    assert _memory is not None
    assert _rag_engine is not None
    assert _gemini_gateway is not None
    assert _learning_module is not None

    session_id = request.session_id
    message = request.message
    language = request.language

    # Req 1.6: Reject whitespace-only messages
    if not message.strip():
        raise HTTPException(
            status_code=422,
            detail="Message cannot be empty or contain only whitespace characters.",
        )

    # Handle special command: /learning-stats
    if message.strip() == "/learning-stats":
        stats = await _learning_module.get_stats(session_id)
        return ChatResponse(
            reply=(
                f"\U0001f4ca Learning Statistics:\n"
                f"\u2022 Total knowledge points: {stats.total_learned}\n"
                f"\u2022 Session knowledge points: {stats.session_learned}\n"
                f"\u2022 Last rebuild: {stats.last_rebuild_at or 'Never'}"
            ),
            sources=[],
            used_general_knowledge=False,
            timestamp=datetime.now(timezone.utc),
            session_id=session_id,
        )

    # Handle special command: /learn <content>
    # Allows users to paste knowledge directly into the chat
    if message.strip().startswith("/learn "):
        learn_content = message.strip()[7:]  # Remove "/learn " prefix
        if not learn_content.strip():
            return ChatResponse(
                reply="Please provide content after /learn. Usage: /learn <knowledge content>",
                sources=[],
                used_general_knowledge=False,
                timestamp=datetime.now(timezone.utc),
                session_id=session_id,
            )
        try:
            from app.models import Chunk
            import uuid as _uuid

            # Split content into chunks by paragraphs
            chunks_to_add = []
            paragraphs = [p.strip() for p in learn_content.split("\n\n") if p.strip()]
            if not paragraphs:
                paragraphs = [learn_content]

            for para in paragraphs:
                chunk = Chunk(
                    id=str(_uuid.uuid4()),
                    text=para[:2000],
                    source_type="user_input",
                    created_at=datetime.now(timezone.utc).isoformat(),
                    similarity=0.0,
                )
                chunks_to_add.append(chunk)

            await _rag_engine.add_chunks(chunks_to_add)
            count = len(chunks_to_add)
            logger.info("learn_command_success", session_id=session_id, chunks_added=count)
            return ChatResponse(
                reply=f"\u2705 Learned {count} knowledge segment(s). Added to knowledge base.",
                sources=[],
                used_general_knowledge=False,
                timestamp=datetime.now(timezone.utc),
                session_id=session_id,
            )
        except Exception as exc:
            logger.error("learn_command_failed", error=str(exc), exc_info=True)
            return ChatResponse(
                reply=f"\u274c Learning failed: {str(exc)}",
                sources=[],
                used_general_knowledge=False,
                timestamp=datetime.now(timezone.utc),
                session_id=session_id,
            )

    # Handle special command: /fetch-url <url>
    if message.strip().startswith("/fetch-url "):
        url = message.strip()[11:].strip()
        if not url:
            return ChatResponse(
                reply="Please provide a URL. Usage: /fetch-url https://example.com",
                sources=[],
                used_general_knowledge=False,
                timestamp=datetime.now(timezone.utc),
                session_id=session_id,
            )
        try:
            import httpx as _httpx
            from app.models import Chunk
            import uuid as _uuid

            async with _httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "Angelina-KnowledgeBot/1.0"})
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                raw_text = resp.text

            if "html" in content_type:
                raw_text = re.sub(r"<script[^>]*>.*?</script>", "", raw_text, flags=re.DOTALL)
                raw_text = re.sub(r"<style[^>]*>.*?</style>", "", raw_text, flags=re.DOTALL)
                raw_text = re.sub(r"<[^>]+>", " ", raw_text)
                raw_text = re.sub(r"\s+", " ", raw_text).strip()

            if not raw_text.strip():
                return ChatResponse(
                    reply="\u274c No text content found at that URL.",
                    sources=[],
                    used_general_knowledge=False,
                    timestamp=datetime.now(timezone.utc),
                    session_id=session_id,
                )

            # Chunk the content
            paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
            if not paragraphs:
                paragraphs = [raw_text]

            chunks_to_add = []
            current_chunk = ""
            for para in paragraphs:
                if len(current_chunk) + len(para) < 1500:
                    current_chunk += para + "\n\n"
                else:
                    if current_chunk.strip():
                        chunks_to_add.append(current_chunk.strip())
                    current_chunk = para + "\n\n"
            if current_chunk.strip():
                chunks_to_add.append(current_chunk.strip())

            chunk_objects = [
                Chunk(
                    id=str(_uuid.uuid4()),
                    text=text[:2000],
                    source_type="document_upload",
                    created_at=datetime.now(timezone.utc).isoformat(),
                    similarity=0.0,
                )
                for text in chunks_to_add
            ]

            await _rag_engine.add_chunks(chunk_objects)
            logger.info("fetch_url_chat_success", url=url, chunks=len(chunk_objects))
            return ChatResponse(
                reply=f"\u2705 Successfully fetched and learned {len(chunk_objects)} knowledge chunks from:\n{url}",
                sources=[],
                used_general_knowledge=False,
                timestamp=datetime.now(timezone.utc),
                session_id=session_id,
            )
        except Exception as exc:
            logger.error("fetch_url_chat_failed", url=url, error=str(exc))
            return ChatResponse(
                reply=f"\u274c Failed to fetch URL: {str(exc)}",
                sources=[],
                used_general_knowledge=False,
                timestamp=datetime.now(timezone.utc),
                session_id=session_id,
            )

    # Step 1: Load context (last 20 turns)
    context_turns = await _memory.load_context(session_id, limit=20)
    logger.info(
        "context_loaded",
        session_id=session_id,
        turn_count=len(context_turns),
    )

    # Step 2: Semantic search via RAG Engine
    knowledge_chunks = await _rag_engine.search(query=message, top_k=5)
    used_general_knowledge = len(knowledge_chunks) == 0
    logger.info(
        "rag_search_complete",
        session_id=session_id,
        chunks_found=len(knowledge_chunks),
        used_general_knowledge=used_general_knowledge,
    )

    # Step 3: Call Gemini Gateway
    try:
        gemini_response = await _gemini_gateway.generate(
            system_prompt="",
            context_turns=context_turns,
            knowledge_chunks=knowledge_chunks,
            user_message=message,
            language=language,
        )
        reply_text = gemini_response.text
    except GeminiQuotaExhaustedError:
        logger.error("gemini_quota_exhausted", session_id=session_id)
        raise HTTPException(
            status_code=429,
            detail="Gemini API daily quota exhausted. Service will resume at UTC midnight.",
        )
    except GeminiQueueFullError:
        logger.warning("gemini_queue_full", session_id=session_id)
        raise HTTPException(
            status_code=429,
            detail="System is currently at capacity. Please try again later.",
        )
    except GeminiTimeoutError:
        logger.error("gemini_timeout", session_id=session_id)
        raise HTTPException(
            status_code=504,
            detail="Response timed out. Please try again later.",
        )
    except GeminiAPIError as exc:
        logger.error(
            "gemini_api_error",
            session_id=session_id,
            status_code=exc.status_code,
            message=exc.message,
        )
        raise HTTPException(
            status_code=502,
            detail="An error occurred while generating a response. Please try again later.",
        )

    # Step 4: Save turns to ConversationMemory
    try:
        await _memory.save_turn(session_id, "user", message)
        await _memory.save_turn(session_id, "assistant", reply_text)
        logger.info("turns_saved", session_id=session_id)
    except Exception as exc:
        # Req 3.4: if write fails, preserve in-memory state, signal storage error
        logger.warning(
            "turn_save_failed",
            session_id=session_id,
            error=str(exc),
        )

    # Step 5: Build response
    sources = [
        SourceRef(
            type=chunk.source_type if chunk.source_type in ("notebooklm", "learning") else "learning",
            chunk=chunk.text[:200],
        )
        for chunk in knowledge_chunks
    ]

    response = ChatResponse(
        reply=reply_text,
        sources=sources,
        used_general_knowledge=used_general_knowledge,
        timestamp=datetime.now(timezone.utc),
        session_id=session_id,
    )

    # Step 6: Fire background learning task (non-blocking) - Req 5.4
    from app.models import Turn

    assistant_turn = Turn(
        session_id=session_id,
        role="assistant",
        content=reply_text,
        created_at=datetime.now(timezone.utc),
    )
    asyncio.create_task(_learning_module.extract_and_store(assistant_turn, session_id))
    logger.info("learning_task_fired", session_id=session_id)

    return response


@app.post("/memory/clear")
async def memory_clear() -> dict:
    """
    Clear conversation memory.

    Req 3.5: delete all records and display confirmation.
    Req 3.6: if deletion fails, preserve records and inform user.
    """
    assert _memory is not None

    success = await _memory.clear_history()

    if success:
        logger.info("memory_cleared")
        return {"status": "success", "message": "Conversation memory cleared successfully."}
    else:
        logger.warning("memory_clear_failed")
        return {"status": "error", "message": "Failed to clear conversation memory. Records preserved."}


@app.post("/knowledge/update")
async def knowledge_update() -> dict:
    """
    Trigger knowledge base rebuild from the latest NotebookLM export.

    Req 4.5: re-chunk, re-embed, and replace the vector index.
    """
    assert _rag_engine is not None

    # Find the latest export file
    from app.services.rag_engine import NOTEBOOKLM_DATA_PATH, _find_latest_export

    export_path = _find_latest_export(NOTEBOOKLM_DATA_PATH)

    if export_path is None:
        logger.warning("knowledge_update_no_export", path=NOTEBOOKLM_DATA_PATH)
        raise HTTPException(
            status_code=404,
            detail="No NotebookLM export file found. Please add an export to data/notebooklm/.",
        )

    try:
        await _rag_engine.rebuild_index(export_path)
        logger.info("knowledge_update_complete", export_path=export_path)
        return {"status": "success", "message": f"Knowledge base rebuilt from: {export_path}"}
    except Exception as exc:
        logger.error("knowledge_update_failed", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to rebuild knowledge base. Check logs for details.",
        )


# ---------------------------------------------------------------------------
# Static files (must be mounted LAST to avoid overriding API routes)
# ---------------------------------------------------------------------------

# Mount static files at "/" to serve the Chat UI
_static_dir = Path(__file__).resolve().parent.parent / "static"
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
