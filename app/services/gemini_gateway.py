"""
Angelina AI Financial Expert Agent -- Gemini Gateway Service.

Encapsulates all interaction with the Google Gemini 1.5 Flash API,
including rate limiting, quota management, system prompt injection,
and error handling.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from math import ceil
from typing import Any

import httpx
import structlog

from app.models import Chunk, GeminiResponse, Turn

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class GeminiError(Exception):
    """Base exception for Gemini Gateway errors."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class GeminiAPIError(GeminiError):
    """Raised on 4xx/5xx responses from the Gemini API."""
    pass


class GeminiTimeoutError(GeminiError):
    """Raised when a request exceeds the 30-second timeout."""

    def __init__(self, message: str = "Gemini API request timed out after 30 seconds."):
        super().__init__(message)


class GeminiQuotaExhaustedError(GeminiError):
    """Raised when the daily free-tier quota is exhausted (429 with quota header)."""

    def __init__(self, message: str = "Gemini API daily quota exhausted. Service will resume at UTC midnight."):
        super().__init__(message, status_code=429)


class GeminiRateLimitError(GeminiError):
    """Raised when the internal rate-limit queue is at capacity."""

    def __init__(self, wait_time: int = 0):
        self.wait_time = wait_time
        super().__init__(
            "System is currently at capacity. Please try again later.",
            status_code=429,
        )


class GeminiQueueFullError(GeminiError):
    """Raised when the request queue exceeds capacity (> 10)."""

    def __init__(self):
        super().__init__(
            "System is currently at capacity. Too many queued requests. Please try again later.",
            status_code=429,
        )

# ---------------------------------------------------------------------------
# Gemini Gateway
# ---------------------------------------------------------------------------

# Default Gemini API endpoint (can be overridden via environment variable)
_DEFAULT_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

# Rate limit constants
_MAX_REQUESTS_PER_MINUTE = 15
_QUEUE_CAPACITY = 10
_REQUEST_TIMEOUT_SECONDS = 30.0


class GeminiGateway:
    """
    Gateway to Google Gemini 1.5 Flash API with built-in rate limiting,
    quota management, and financial expert system prompt injection.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        max_requests_per_minute: int = _MAX_REQUESTS_PER_MINUTE,
        queue_capacity: int = _QUEUE_CAPACITY,
        timeout: float = _REQUEST_TIMEOUT_SECONDS,
    ):
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._base_url = base_url or os.environ.get("GEMINI_API_URL", _DEFAULT_GEMINI_URL)
        self._timeout = timeout
        self._max_rpm = max_requests_per_minute
        self._queue_capacity = queue_capacity

        # Rate limiting: sliding window
        self._semaphore = asyncio.Semaphore(max_requests_per_minute)
        self._request_timestamps: list[float] = []
        self._queued_count: int = 0
        self._lock = asyncio.Lock()

        # Quota exhaustion tracking
        self._quota_exhausted: bool = False
        self._quota_exhausted_date: str | None = None  # UTC date string "YYYY-MM-DD"

        # HTTP client (lazy-initialized)
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the shared httpx.AsyncClient."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def quota_exhausted(self) -> bool:
        """Check if quota is exhausted; auto-clear at UTC midnight."""
        if self._quota_exhausted:
            today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if self._quota_exhausted_date != today_utc:
                # It is a new UTC day -- auto-clear
                self._quota_exhausted = False
                self._quota_exhausted_date = None
                logger.info("gemini_quota_reset", message="Quota auto-cleared at UTC midnight.")
        return self._quota_exhausted

    @property
    def queued_count(self) -> int:
        """Current number of queued requests."""
        return self._queued_count
    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def _build_system_prompt(self, language: str) -> str:
        """
        Build the financial expert system prompt injected into every request.

        Includes:
        - Role definition (Angelina, professional financial advisor)
        - Language instruction (based on language parameter)
        - Source labelling rules
        - Risk disclaimer rules
        - Off-topic refusal rules
        """
        if language == "zh-TW":
            lang_instruction = "You MUST respond in Traditional Chinese (\u7e41\u9ad4\u4e2d\u6587)."
        else:
            lang_instruction = "You MUST respond in English."

        return (
            "You are Angelina, a professional AI financial advisor and expert.\n"
            "\n"
            "## Role Definition\n"
            "You are a knowledgeable, trustworthy financial expert who provides in-depth advice on:\n"
            "- Stock investment and equity analysis\n"
            "- Fund management and portfolio allocation\n"
            "- Foreign exchange trading\n"
            "- Retirement planning\n"
            "- Tax planning and optimization\n"
            "- Asset allocation and wealth management\n"
            "- Risk management strategies\n"
            "- Budgeting principles\n"
            "\n"
            "## Language Instruction\n"
            f"{lang_instruction}\n"
            "\n"
            "## Source Labelling Rules\n"
            "- When citing information from the knowledge base, clearly label the source type.\n"
            '- Use "\u4f86\u6e90: NotebookLM \u7b46\u8a18\u672c" or "Source: NotebookLM notebook" for NotebookLM-sourced knowledge.\n'
            '- Use "\u4f86\u6e90: \u5c0d\u8a71\u5b78\u7fd2" or "Source: Conversation learning" for knowledge learned from previous conversations.\n'
            "\n"
            "## Risk Disclaimer Rules\n"
            "- When the user's question explicitly involves investment risk, you MUST include this disclaimer:\n"
            '  "\u672c\u5efa\u8b70\u50c5\u4f9b\u53c3\u8003\uff0c\u5be6\u969b\u6295\u8cc7\u6c7a\u7b56\u8acb\u8aee\u8a62\u6301\u724c\u7406\u8ca1\u9867\u554f\u3002" (zh-TW)\n'
            '  "This advice is for reference only; for actual investment decisions, please consult a licensed financial advisor." (en)\n'
            "- If the question does NOT explicitly involve investment risk, do NOT append this disclaimer.\n"
            "\n"
            "## Off-Topic Refusal Rules\n"
            "- If the user asks a non-financial question, politely state that the question is outside your scope as a financial expert and prompt the user to restate their request as a financial or investment question.\n"
            "- If a question is beyond your knowledge scope, state that you have insufficient information to answer accurately. Do NOT speculate or fabricate content.\n"
            "\n"
            "## Response Quality Rules\n"
            "- Respond in complete sentences.\n"
            "- Define any financial technical term you introduce in the same response.\n"
            "- Do not use financial jargon without an accompanying explanation.\n"
        )
    # ------------------------------------------------------------------
    # Request payload builder
    # ------------------------------------------------------------------

    def _build_payload(
        self,
        system_prompt: str,
        context_turns: list[Turn],
        knowledge_chunks: list[Chunk],
        user_message: str,
        language: str,
    ) -> dict[str, Any]:
        """Build the Gemini API request payload."""
        # System instruction
        financial_system_prompt = self._build_system_prompt(language)
        if system_prompt:
            full_system_prompt = f"{financial_system_prompt}\n\n{system_prompt}"
        else:
            full_system_prompt = financial_system_prompt

        # Build contents array with conversation history
        contents: list[dict[str, Any]] = []

        # Add knowledge context as a user message if chunks are available
        if knowledge_chunks:
            chunks_text = "\n\n".join(
                f"[Knowledge Source - {chunk.source_type}]: {chunk.text}"
                for chunk in knowledge_chunks
            )
            contents.append({
                "role": "user",
                "parts": [{"text": f"Reference knowledge:\n{chunks_text}"}],
            })
            contents.append({
                "role": "model",
                "parts": [{"text": "I have noted the reference knowledge and will use it to provide accurate answers."}],
            })

        # Add conversation context turns
        for turn in context_turns:
            role = "user" if turn.role == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": turn.content}],
            })

        # Add the current user message
        contents.append({
            "role": "user",
            "parts": [{"text": user_message}],
        })

        payload: dict[str, Any] = {
            "contents": contents,
            "systemInstruction": {
                "parts": [{"text": full_system_prompt}],
            },
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 2048,
            },
        }

        return payload
    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _cleanup_old_timestamps(self) -> None:
        """Remove timestamps older than 60 seconds from the sliding window."""
        now = time.monotonic()
        cutoff = now - 60.0
        self._request_timestamps = [
            ts for ts in self._request_timestamps if ts > cutoff
        ]

    async def _acquire_rate_limit(self) -> int:
        """
        Acquire a rate-limit slot. Returns estimated wait time in seconds.

        Raises GeminiQueueFullError if queue capacity is exceeded.
        """
        async with self._lock:
            self._cleanup_old_timestamps()

            # Check if we are within the per-minute limit
            if len(self._request_timestamps) < self._max_rpm:
                # Slot available immediately
                self._request_timestamps.append(time.monotonic())
                return 0

            # Need to queue -- check capacity
            if self._queued_count >= self._queue_capacity:
                raise GeminiQueueFullError()

            self._queued_count += 1
            wait_time = ceil(self._queued_count / self._max_rpm)

        # Wait for a slot to open
        try:
            await asyncio.sleep(wait_time)
        finally:
            async with self._lock:
                self._queued_count = max(0, self._queued_count - 1)

        # Record the timestamp after waiting
        async with self._lock:
            self._request_timestamps.append(time.monotonic())

        return wait_time
    # ------------------------------------------------------------------
    # Main generate method
    # ------------------------------------------------------------------

    async def generate(
        self,
        system_prompt: str,
        context_turns: list[Turn],
        knowledge_chunks: list[Chunk],
        user_message: str,
        language: str,
    ) -> GeminiResponse:
        """
        Generate a response from Gemini 1.5 Flash.

        Args:
            system_prompt: Additional system prompt (appended to financial expert prompt).
            context_turns: Recent conversation turns for context.
            knowledge_chunks: Relevant RAG knowledge chunks.
            user_message: The user's current message.
            language: Response language ("zh-TW" or "en").

        Returns:
            GeminiResponse with the generated text and token usage.

        Raises:
            GeminiQuotaExhaustedError: Daily quota is exhausted.
            GeminiQueueFullError: Queue capacity exceeded.
            GeminiTimeoutError: Request timed out after 30 seconds.
            GeminiAPIError: API returned 4xx/5xx error.
        """
        # Check quota exhaustion (auto-clears at UTC midnight)
        if self.quota_exhausted:
            raise GeminiQuotaExhaustedError()

        # Acquire rate-limit slot (may queue or reject)
        await self._acquire_rate_limit()

        # Build request
        payload = self._build_payload(
            system_prompt=system_prompt,
            context_turns=context_turns,
            knowledge_chunks=knowledge_chunks,
            user_message=user_message,
            language=language,
        )

        url = f"{self._base_url}?key={self._api_key}"

        try:
            client = await self._get_client()
            response = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
        except httpx.TimeoutException:
            logger.error(
                "gemini_timeout",
                endpoint=self._base_url,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            raise GeminiTimeoutError()

        # Handle error responses
        if response.status_code == 429:
            # Check if this is a quota exhaustion (vs. temporary rate limit)
            resource_exhausted = (
                "quota" in response.text.lower()
                or "RESOURCE_EXHAUSTED" in response.text
            )
            if resource_exhausted:
                self._quota_exhausted = True
                self._quota_exhausted_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                logger.error(
                    "gemini_quota_exhausted",
                    status_code=429,
                    endpoint=self._base_url,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                raise GeminiQuotaExhaustedError()
            else:
                logger.warning(
                    "gemini_rate_limited",
                    status_code=429,
                    endpoint=self._base_url,
                    retry_after=response.headers.get("retry-after", ""),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                raise GeminiAPIError(
                    message="Gemini API rate limited. Please try again shortly.",
                    status_code=429,
                )

        if response.status_code >= 400:
            logger.error(
                "gemini_api_error",
                status_code=response.status_code,
                endpoint=self._base_url,
                timestamp=datetime.now(timezone.utc).isoformat(),
                response_body=response.text[:500],
            )
            raise GeminiAPIError(
                message=f"Gemini API error (HTTP {response.status_code}). Please try again later.",
                status_code=response.status_code,
            )

        # Parse successful response
        data = response.json()
        return self._parse_response(data)
    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, data: dict[str, Any]) -> GeminiResponse:
        """Parse the raw Gemini API JSON response into a GeminiResponse model."""
        # Extract generated text
        candidates = data.get("candidates", [])
        if not candidates:
            raise GeminiAPIError(
                message="Gemini API returned no candidates.",
                status_code=None,
            )

        candidate = candidates[0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        text = "".join(part.get("text", "") for part in parts)

        finish_reason = candidate.get("finishReason", "STOP")

        # Extract token usage
        usage = data.get("usageMetadata", {})
        prompt_tokens = usage.get("promptTokenCount", 0)
        candidates_tokens = usage.get("candidatesTokenCount", 0)

        return GeminiResponse(
            text=text,
            model="gemini-2.5-flash",
            prompt_tokens=prompt_tokens,
            candidates_tokens=candidates_tokens,
            finish_reason=finish_reason,
        )

