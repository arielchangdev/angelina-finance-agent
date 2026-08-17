"""
Angelina AI Financial Expert Agent -- Pydantic data models.

All domain objects shared across services are defined here to avoid
circular imports and to provide a single source of truth for the API
contract.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Conversation / Chat models
# ---------------------------------------------------------------------------


class Turn(BaseModel):
    """A single conversation turn persisted in SQLite."""

    id: int | None = None
    session_id: str
    role: str          # "user" | "assistant" | "summary"
    content: str       # max 10,000 chars
    created_at: datetime
    is_summary: bool = False


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
    similarity: float = 0.0  # populated during search; 0.0 at rest


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
