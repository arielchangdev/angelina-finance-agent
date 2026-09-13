"""
In-memory fixed-window rate limiter for the Cloud_Instance chat endpoint.

Protects the Always_Free_Tier Gemini quota from abuse by capping the number of
authenticated chat requests per client within a fixed time window (default:
60 requests per hour per client, configurable via the ``RATE_LIMIT_PER_HOUR``
environment variable).

Client identity is the presented Access_Token (``X-Angelina-Token`` header) when
available, falling back to the request source IP. When the configured cap is
exceeded, the FastAPI helper raises ``HTTPException(429)``.

This is a LOCAL, per-process, in-memory limiter: counters live in the running
process and are not shared across workers or restarts. That is sufficient for
the single-worker Cloud_Instance deployment and keeps the limiter dependency-free
and easily unit-testable (see ``RateLimiter.reset``).

Requirements: 8.8, 10.4
"""

import os
import threading
import time

import structlog
from fastapi import HTTPException, Request

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration (env-overridable)
# ---------------------------------------------------------------------------

RATE_LIMIT_PER_HOUR = int(os.getenv("RATE_LIMIT_PER_HOUR", "60"))
WINDOW_SECONDS = 3600

# Header carrying the Access_Token, consistent with app/auth.py.
TOKEN_HEADER = "X-Angelina-Token"


class RateLimiter:
    """In-memory fixed-window rate limiter (per-client, per-hour).

    Uses a fixed window keyed by client identity: the first request from a client
    opens a window; subsequent requests within ``window_seconds`` increment the
    counter; once the window elapses the counter resets on the next request.
    """

    def __init__(
        self,
        limit: int = RATE_LIMIT_PER_HOUR,
        window_seconds: int = WINDOW_SECONDS,
    ):
        self._limit = limit
        self._window = window_seconds
        # client_id -> (window_start_epoch, count)
        self._counts: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def check(self, client_id: str) -> bool:
        """Return True if the request is allowed, False if rate-limited.

        Uses a fixed window: when the current window expires, the counter resets.

        Args:
            client_id: Identity of the client (token or source IP).

        Returns:
            bool: True if the request is within the cap, False if it exceeds it.
        """
        now = time.time()
        with self._lock:
            window_start, count = self._counts.get(client_id, (now, 0))
            # If the window has expired, reset it.
            if now - window_start >= self._window:
                window_start, count = now, 0
            if count >= self._limit:
                return False
            self._counts[client_id] = (window_start, count + 1)
            return True

    def reset(self) -> None:
        """Clear all counters (useful for tests)."""
        with self._lock:
            self._counts.clear()


# Module-level singleton shared across requests in this process.
_limiter = RateLimiter()


def check_rate_limit(client_id: str) -> bool:
    """Return True if allowed, False if the client exceeded the limit.

    Args:
        client_id: Identity of the client (token or source IP).

    Returns:
        bool: True if the request is allowed, False if rate-limited.
    """
    return _limiter.check(client_id)


def reset_rate_limits() -> None:
    """Clear the module-level limiter's counters (useful for tests)."""
    _limiter.reset()


def _client_id_from_request(request: Request) -> str:
    """Derive a client identity from the request.

    Prefers the presented Access_Token header; falls back to the source IP, and
    finally to ``"unknown"`` when neither is available.

    Args:
        request: The incoming FastAPI request.

    Returns:
        str: The client identity used as the rate-limit key.
    """
    token = request.headers.get(TOKEN_HEADER)
    if token:
        return token
    if request.client:
        return request.client.host
    return "unknown"


async def enforce_rate_limit(request: Request) -> None:
    """FastAPI dependency: identify client, check limit, raise 429 if exceeded.

    Args:
        request: The incoming FastAPI request.

    Raises:
        HTTPException: With status code 429 when the client exceeds the cap.
    """
    client_id = _client_id_from_request(request)
    if not check_rate_limit(client_id):
        logger.warning("rate_limit_exceeded", client_id=client_id)
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Try again later.",
        )
