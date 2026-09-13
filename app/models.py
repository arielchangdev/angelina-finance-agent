"""
Angelina AI Financial Expert Agent -- Pydantic data models.

All domain objects shared across services are defined here to avoid
circular imports and to provide a single source of truth for the API
contract.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Conversation / Chat models
# ---------------------------------------------------------------------------


class Turn(BaseModel):
    """A single conversation turn persisted in SQLite."""

    # Local persistence uses the SQLite integer rowid; the sync layer carries a
    # namespaced cross-instance id (e.g. "local:1187"), so accept both.
    id: int | str | None = None
    session_id: str
    role: str          # "user" | "assistant" | "summary"
    content: str       # max 10,000 chars
    created_at: datetime
    # UTC last-modified timestamp used for last-write-wins sync (Req 6.1).
    # Defaults to created_at for records that have never been edited.
    last_modified: datetime | None = None
    is_summary: bool = False

    @model_validator(mode="after")
    def _default_last_modified(self) -> "Turn":
        """When last_modified is unset, mirror created_at (Req 6.1)."""
        if self.last_modified is None:
            self.last_modified = self.created_at
        return self


class ChatRequest(BaseModel):
    """Payload for POST /chat."""

    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str    # UUID v4
    language: str = "zh-TW"  # "zh-TW" | "en"


class SourceRef(BaseModel):
    """Reference to a knowledge chunk cited in a ChatResponse."""

    type: str          # "notebooklm" | "learning"
    chunk: str         # first 200 chars of source chunk


class ChatResponse(BaseModel):
    """Response payload returned by POST /chat."""

    reply: str
    sources: list[SourceRef]
    used_general_knowledge: bool
    timestamp: datetime
    session_id: str


# ---------------------------------------------------------------------------
# RAG / Knowledge-base models
# ---------------------------------------------------------------------------


class Chunk(BaseModel):
    """A single vector knowledge chunk stored in ChromaDB."""

    id: str            # UUID v4
    text: str          # max ~500 tokens
    source_type: str   # "notebooklm"|"user_input"|"assistant_response"|"document_upload"
    created_at: str    # UTC ISO 8601
    # UTC ISO 8601 last-modified timestamp used for last-write-wins sync (Req 6.1).
    # Defaults to created_at for records that have never been edited.
    last_modified: str | None = None
    similarity: float = 0.0  # populated during search; 0.0 at rest

    @model_validator(mode="after")
    def _default_last_modified(self) -> "Chunk":
        """When last_modified is unset, mirror created_at (Req 6.1)."""
        if self.last_modified is None:
            self.last_modified = self.created_at
        return self


# ---------------------------------------------------------------------------
# Learning module models
# ---------------------------------------------------------------------------


class LearningStats(BaseModel):
    """Statistics returned by /learning-stats command."""

    total_learned: int        # total knowledge points in Knowledge_Base
    session_learned: int      # new points added in the current Session
    last_rebuild_at: str | None  # UTC ISO 8601, or None if never rebuilt


# ---------------------------------------------------------------------------
# Gemini gateway models
# ---------------------------------------------------------------------------


class GeminiResponse(BaseModel):
    """Parsed response from the Gemini 1.5 Flash API."""

    text: str
    model: str         # "gemini-1.5-flash"
    prompt_tokens: int
    candidates_tokens: int
    finish_reason: str


# ---------------------------------------------------------------------------
# Hybrid-cloud sync models
# ---------------------------------------------------------------------------


class SyncPayload(BaseModel):
    """Portable JSON export exchanged between instances via Google Drive.

    Vector embeddings are intentionally omitted; the receiving side re-embeds
    each chunk's ``text`` on import to keep egress within the free-tier limit.
    """

    schema_version: int = 1
    instance_id: str                          # "local" | "cloud"
    exported_at: str                          # UTC ISO 8601, explicit offset
    knowledge_chunks: list[Chunk] = Field(default_factory=list)
    conversation_records: list[Turn] = Field(default_factory=list)
    drive_sync_state: dict = Field(default_factory=dict)


class MergeResult(BaseModel):
    """Result of merging a local and peer :class:`SyncPayload`.

    ``stats`` summarizes the resolution: ``kept_local``, ``kept_peer``,
    ``tie_local_wins``, and ``peer_only_added``.
    """

    knowledge_chunks: list[Chunk] = Field(default_factory=list)
    conversation_records: list[Turn] = Field(default_factory=list)
    drive_sync_state: dict = Field(default_factory=dict)
    stats: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Namespaced conversation-id convention
# ---------------------------------------------------------------------------


def namespaced_turn_id(instance_id: str, row_id: int) -> str:
    """Create a stable cross-instance conversation id.

    SQLite autoincrement row ids collide across the two instances, so each
    exported conversation record is keyed by an origin-namespaced id such as
    ``"local:1187"`` or ``"cloud:42"``. This keeps the merge key unique and
    lets last-write-wins match records across instances once propagated.
    """
    return f"{instance_id}:{row_id}"
