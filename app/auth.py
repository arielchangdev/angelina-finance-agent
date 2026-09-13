"""
Authentication for protected Cloud_Instance endpoints.

Provides a FastAPI dependency (``require_token``) that enforces the shared
``Access_Token`` on protected endpoints when running in the cloud role, plus a
startup check (``check_cloud_token_configured``) that fails fast if the cloud
role is missing its token.

Design notes / role gating:
  - LOCAL role (``INSTANCE_ROLE == "local"``, the default): auth is a NO-OP.
    The local instance is LAN-only, so protected endpoints behave exactly as
    they did before this module existed (no regression).
  - CLOUD role (``INSTANCE_ROLE == "cloud"``): every protected endpoint must
    present a valid token, supplied either via the ``X-Angelina-Token`` header
    or via HTTP Basic auth (the password field). The presented value is
    compared to ``ANGELINA_ACCESS_TOKEN`` using ``hmac.compare_digest`` for a
    constant-time comparison that resists timing attacks.

Secrets are read from the environment (populated from an un-committed ``.env``);
the token value itself is never logged.

Requirements: 8.5, 8.6, 8.7, 8.10, 10.3
"""

import base64
import binascii
import hmac
import os

import structlog
from fastapi import HTTPException, Request

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration (env-overridable; secrets live in an un-committed .env)
# ---------------------------------------------------------------------------

# The shared Access_Token. Never committed; sourced from the environment.
ACCESS_TOKEN = os.getenv("ANGELINA_ACCESS_TOKEN")

# Role gate. Local is the default so existing local behavior is unchanged.
INSTANCE_ROLE = os.getenv("INSTANCE_ROLE", "local")

# Header carrying the token on protected requests.
AUTH_HEADER = "X-Angelina-Token"


def _token_matches(presented: str | None) -> bool:
    """
    Constant-time comparison of a presented token against ``ACCESS_TOKEN``.

    Returns False when either the presented token or the configured token is
    missing/empty. Uses ``hmac.compare_digest`` to avoid leaking length or
    content through timing side channels.

    Args:
        presented: The token supplied by the caller, or None.

    Returns:
        bool: True iff a non-empty presented token matches the configured token.
    """
    if not presented or not ACCESS_TOKEN:
        return False
    return hmac.compare_digest(presented, ACCESS_TOKEN)


def _extract_basic_auth_password(request: Request) -> str | None:
    """
    Extract the password field from an HTTP Basic ``Authorization`` header.

    Supports presenting the Access_Token as the Basic-auth password (the
    username is ignored). Returns None when the header is absent, malformed,
    or not a Basic credential.

    Args:
        request: The inbound FastAPI request.

    Returns:
        The decoded password portion, or None if unavailable.
    """
    header = request.headers.get("Authorization")
    if not header:
        return None

    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return None

    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None

    # Format is "username:password"; the token is the password portion.
    _, sep, password = decoded.partition(":")
    if not sep:
        return None
    return password


def _presented_token(request: Request) -> str | None:
    """
    Resolve the token presented on a request.

    Prefers the ``X-Angelina-Token`` header and falls back to the HTTP Basic
    auth password.

    Args:
        request: The inbound FastAPI request.

    Returns:
        The presented token, or None if neither source supplied one.
    """
    header_token = request.headers.get(AUTH_HEADER)
    if header_token:
        return header_token
    return _extract_basic_auth_password(request)


async def require_token(request: Request) -> None:
    """
    FastAPI dependency enforcing the Access_Token on protected endpoints.

    Behavior:
      - NO-OP when ``INSTANCE_ROLE == "local"`` (LAN-only, no auth required).
      - Otherwise, compares the presented ``X-Angelina-Token`` header (or HTTP
        Basic password) to ``ANGELINA_ACCESS_TOKEN`` with a constant-time
        comparison and raises ``HTTPException(401)`` on a missing/mismatched
        token. No side effects are performed on rejection.

    Args:
        request: The inbound FastAPI request (injected by FastAPI).

    Raises:
        HTTPException: 401 Unauthorized when the token is missing or invalid.
    """
    # Local is LAN-only: pass through with no authentication.
    if INSTANCE_ROLE == "local":
        return

    presented = _presented_token(request)
    if not _token_matches(presented):
        # Log the rejection for observability, but never the token value.
        logger.warning(
            "auth_rejected",
            path=request.url.path,
            method=request.method,
            token_present=bool(presented),
        )
        raise HTTPException(status_code=401, detail="Unauthorized")


def check_cloud_token_configured() -> None:
    """
    Fail fast at startup if the cloud role has no Access_Token configured.

    Prevents accidentally exposing an unauthenticated public instance: when
    ``INSTANCE_ROLE == "cloud"`` but ``ANGELINA_ACCESS_TOKEN`` is unset/empty,
    this raises ``RuntimeError`` so the process refuses to start.

    Requirements: 8.10

    Raises:
        RuntimeError: If running in the cloud role without an Access_Token.
    """
    if INSTANCE_ROLE == "cloud" and not ACCESS_TOKEN:
        raise RuntimeError(
            "ANGELINA_ACCESS_TOKEN must be set when INSTANCE_ROLE=cloud; "
            "refusing to start an unauthenticated public instance."
        )
