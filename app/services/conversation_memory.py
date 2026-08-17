"""
Conversation Memory service for Angelina AI Financial Expert Agent.

Persists all conversation turns to a local SQLite database via aiosqlite.
Provides async methods for saving, loading, clearing, and summarising turns.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite

from app.models import Turn

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL - created once on first init
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    role        TEXT    NOT NULL CHECK(role IN ('user', 'assistant', 'summary')),
    content     TEXT    NOT NULL CHECK(length(content) <= 10000),
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'utc')),
    is_summary  INTEGER NOT NULL DEFAULT 0
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_session_created
    ON conversations(session_id, created_at DESC);
"""


class ConversationMemory:
    """Async conversation persistence backed by SQLite.

    Usage
    -----
    memory = ConversationMemory()
    await memory.initialize()           # create schema if needed
    await memory.save_turn(session_id, "user", "Hello!")
    turns = await memory.load_context(session_id)
    """

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            # Default: <workspace_root>/data/conversations.db
            workspace_root = Path(__file__).resolve().parents[2]
            db_path = workspace_root / "data" / "conversations.db"
        self._db_path = Path(db_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the SQLite schema (table + index) if it does not exist.

        Called once at application startup.  Safe to call multiple times.
        """
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_TABLE_SQL)
            await db.execute(_CREATE_INDEX_SQL)
            await db.commit()
        logger.info("ConversationMemory initialised at %s", self._db_path)

    async def save_turn(self, session_id: str, role: str, content: str, is_summary: bool = False) -> None:
        """Persist a single conversation turn.

        Req 3.1  store all completed turns including timestamps, roles, and
        content (up to 10,000 chars).
        Req 3.3  must complete within 1 second of the turn completing.
        Req 3.4  if the write fails, raise the exception so the caller can
        preserve in-memory state and signal a storage error.

        Raises
        ------
        ValueError
            If content exceeds 10,000 characters (early validation).
        aiosqlite.Error
            Propagated on any database write failure (Req 3.4).
        """
        if len(content) > 10_000:
            raise ValueError(
                f"Turn content exceeds 10,000 characters (got {len(content)})."
            )

        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """
                    INSERT INTO conversations
                        (session_id, role, content, created_at, is_summary)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (session_id, role, content, created_at, int(is_summary)),
                )
                await db.commit()
        except aiosqlite.Error as exc:
            logger.error(
                "Failed to write turn to SQLite: %s", exc, exc_info=True
            )
            raise  # Req 3.4 - let caller handle in-memory fallback

    async def load_context(self, session_id: str, limit: int = 20) -> list[Turn]:
        """Return the most recent *limit* turns for a session.

        Req 3.2  load the most recent 20 turns ordered by timestamp.
        Req 3.7  must support 10,000 turns without degradation.
        Req 3.8  must complete within 500 ms under a 10,000-turn dataset
                 (ensured by the idx_session_created index).
        Req 3.9  summary turns are included so the Context_Window can
                 contain the compressed history.

        Returns
        -------
        list[Turn]
            Turns in ascending chronological order (oldest first).
        """
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, session_id, role, content, created_at, is_summary
                FROM   conversations
                WHERE  session_id = ?
                ORDER  BY created_at DESC, id DESC
                LIMIT  ?
                """,
                (session_id, limit),
            ) as cursor:
                rows = await cursor.fetchall()

        # Rows arrive newest-first; reverse so the list is chronological.
        turns: list[Turn] = []
        for row in reversed(rows):
            turns.append(
                Turn(
                    id=row["id"],
                    session_id=row["session_id"],
                    role=row["role"],
                    content=row["content"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                    is_summary=bool(row["is_summary"]),
                )
            )
        return turns

    async def clear_history(self, session_id: str | None = None) -> bool:
        """Delete conversation records.

        Req 3.5  delete all records and confirm success.
        Req 3.6  if deletion fails, preserve records and return False.

        Parameters
        ----------
        session_id:
            When provided, only that session is cleared.
            When None, all records are deleted.

        Returns
        -------
        bool
            True on success, False on failure (Req 3.6).
        """
        try:
            async with aiosqlite.connect(self._db_path) as db:
                if session_id is None:
                    await db.execute("DELETE FROM conversations")
                else:
                    await db.execute(
                        "DELETE FROM conversations WHERE session_id = ?",
                        (session_id,),
                    )
                await db.commit()
            return True
        except aiosqlite.Error as exc:
            logger.error(
                "Failed to clear conversation history: %s", exc, exc_info=True
            )
            return False  # Req 3.6 - preserve records, return False

    async def get_turn_count(self, session_id: str | None = None) -> int:
        """Return the total number of stored turns.

        Parameters
        ----------
        session_id:
            When provided, count only that session's turns.
            When None, count across all sessions.
        """
        async with aiosqlite.connect(self._db_path) as db:
            if session_id is None:
                async with db.execute(
                    "SELECT COUNT(*) FROM conversations"
                ) as cursor:
                    row = await cursor.fetchone()
            else:
                async with db.execute(
                    "SELECT COUNT(*) FROM conversations WHERE session_id = ?",
                    (session_id,),
                ) as cursor:
                    row = await cursor.fetchone()
        return row[0] if row else 0

    async def summarize_if_needed(self, session_id: str) -> None:
        """Compress conversation history when it grows too long.

        Req 3.9  when same-session turn count >= 101, compress all turns
        except the most recent 20 into a single summary turn, resulting
        in exactly 21 turns (1 summary + 20 recent).

        The summary is currently produced by concatenating turn content.
        Once GeminiGateway is available, this will call Gemini API for a
        proper NLP summary.
        """
        count = await self.get_turn_count(session_id=session_id)
        if count < 101:
            return

        # Keep only the most recent 20 turns; summarize everything else.
        # This ensures the final count is always 21 (1 summary + 20 recent).
        turns_to_summarize = count - 20

        # Retrieve the oldest (count - 20) turns for this session.
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, role, content, created_at
                FROM   conversations
                WHERE  session_id = ?
                ORDER  BY created_at ASC, id ASC
                LIMIT  ?
                """,
                (session_id, turns_to_summarize),
            ) as cursor:
                oldest_rows = await cursor.fetchall()

        if not oldest_rows:
            return

        oldest_ids = [row["id"] for row in oldest_rows]

        # Build a summary of the turns.
        # TODO: Replace with real Gemini API summarisation call.
        summary_parts: list[str] = []
        for row in oldest_rows:
            summary_parts.append(f"[{row['role']}] {row['content']}")
        raw_summary = "\n".join(summary_parts)

        # Truncate to stay within the 10,000-character column limit.
        summary_text = raw_summary[:10_000]

        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # Atomically: delete the old turns, insert the summary turn.
        placeholders = ",".join("?" * len(oldest_ids))
        async with aiosqlite.connect(self._db_path) as db:
            try:
                await db.execute(
                    f"DELETE FROM conversations WHERE id IN ({placeholders})",
                    oldest_ids,
                )
                await db.execute(
                    """
                    INSERT INTO conversations
                        (session_id, role, content, created_at, is_summary)
                    VALUES (?, 'summary', ?, ?, 1)
                    """,
                    (session_id, summary_text, created_at),
                )
                await db.commit()
                logger.info(
                    "Summarised %d turns for session %s",
                    len(oldest_ids),
                    session_id,
                )
            except aiosqlite.Error as exc:
                await db.rollback()
                logger.error(
                    "Failed to summarise conversation for session %s: %s",
                    session_id,
                    exc,
                    exc_info=True,
                )
                raise