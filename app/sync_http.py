"""
Angelina Hybrid Cloud -- HTTPS sync transport (local-initiated client).

This module replaces the Google Drive relay with a direct HTTPS exchange
against the peer instance's token-gated ``/sync/exchange`` endpoint. A free
Gmail service account has no Drive storage quota (``files.create`` returns 403
even into a shared folder), so the Drive relay is not viable; this client
drives the same pure merge logic over HTTPS instead.

The pure export/merge/import core lives in :mod:`app.sync_engine` and is reused
unchanged -- only the TRANSPORT differs. The local instance's 06:00 cron calls
:func:`run_http_sync` (via ``python -m app.sync_http``) to push its state to the
peer, receive the peer's pre-exchange snapshot, merge it, and persist the
reconciled result. Nothing here ever raises out of the cron entrypoint: on any
error we log a reason and return an error summary, leaving local ChromaDB /
SQLite state intact.

Configuration (environment):
  - ``ANGELINA_PEER_URL``      -- e.g. "https://YOUR_SUBDOMAIN.duckdns.org"
  - ``ANGELINA_ACCESS_TOKEN``  -- the shared Access_Token (X-Angelina-Token)
  - ``ANGELINA_SYNC_TIMEOUT``  -- request timeout in seconds (default 120)

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.6
"""

from __future__ import annotations

import os

import structlog

from app.models import SyncPayload
from app.sync_engine import export_state, import_merged, merge

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Configuration (env-driven so the same code runs on either instance)
# ---------------------------------------------------------------------------

# Base URL of the peer instance we exchange state with (its public HTTPS host).
PEER_URL = os.getenv("ANGELINA_PEER_URL")

# Shared Access_Token presented on the X-Angelina-Token header. Never logged.
ACCESS_TOKEN = os.getenv("ANGELINA_ACCESS_TOKEN")

# Request timeout (seconds). Generous default: an export can be large and the
# 1GB cloud VM re-embeds chunks synchronously during its import.
SYNC_TIMEOUT = float(os.getenv("ANGELINA_SYNC_TIMEOUT", "120"))

# Token header name -- matches app/auth.py (AUTH_HEADER).
_AUTH_HEADER = "X-Angelina-Token"


async def run_http_sync() -> dict:
    """Run one full bi-directional HTTPS sync cycle.

    Sequence:
      1. export_state()                 -> this instance's snapshot
      2. POST it to ``{PEER_URL}/sync/exchange`` with the shared token
      3. parse the peer's pre-exchange snapshot from the response
      4. merge(my_payload, peer_payload) -> reuse the pure merge() core
      5. import_merged(result)          -> persist the reconciled state locally

    Safety:
      - If ``ANGELINA_PEER_URL`` or ``ANGELINA_ACCESS_TOKEN`` is unset, this is
        a safe no-op: we log ``http_sync_unconfigured`` and return a skipped
        status (mirroring the old sync_engine short-circuit).
      - On a non-2xx response or any network error, we log ``http_sync_failed``
        with a reason and return a failed status WITHOUT touching local state
        (ChromaDB / SQLite are left exactly as they were).
      - This function never raises; it is safe to invoke directly from cron.

    Returns:
        dict summarising the outcome (``status`` is one of ``ok`` /
        ``skipped`` / ``failed``).
    """
    if not PEER_URL or not ACCESS_TOKEN:
        log.warning(
            "http_sync_unconfigured",
            peer_url_set=bool(PEER_URL),
            token_set=bool(ACCESS_TOKEN),
        )
        return {"status": "skipped", "reason": "peer url or token unset"}

    import httpx

    endpoint = f"{PEER_URL.rstrip('/')}/sync/exchange"
    headers = {
        _AUTH_HEADER: ACCESS_TOKEN,
        "Content-Type": "application/json",
    }

    # Build our own snapshot BEFORE any network I/O so a transport failure
    # leaves local state untouched.
    my_payload = await export_state()

    try:
        async with httpx.AsyncClient(timeout=SYNC_TIMEOUT) as client:
            response = await client.post(
                endpoint,
                headers=headers,
                content=my_payload.model_dump_json(),
            )
    except httpx.HTTPError as exc:
        # Network-level failure (DNS, TLS, connect, read timeout, ...).
        log.error(
            "http_sync_failed",
            reason=str(exc),
            error_type=type(exc).__name__,
            endpoint=endpoint,
        )
        return {"status": "failed", "reason": str(exc)}

    if response.status_code < 200 or response.status_code >= 300:
        # Non-2xx: do NOT import anything; local state stays intact.
        log.error(
            "http_sync_failed",
            reason=f"HTTP {response.status_code}",
            status_code=response.status_code,
            endpoint=endpoint,
        )
        return {
            "status": "failed",
            "reason": f"HTTP {response.status_code}",
        }

    try:
        peer_payload = SyncPayload.model_validate(response.json())
    except Exception as exc:  # noqa: BLE001 -- malformed peer response
        log.error(
            "http_sync_failed",
            reason=f"invalid peer payload: {exc}",
            error_type=type(exc).__name__,
        )
        return {"status": "failed", "reason": f"invalid peer payload: {exc}"}

    try:
        # Reuse the pure, property-tested merge core, then persist locally.
        result = merge(my_payload, peer_payload)
        await import_merged(result)
    except Exception as exc:  # noqa: BLE001 -- must never crash the cron
        # import_merged is the last mutating step; a failure before it leaves
        # local storage untouched, matching sync_engine.run_sync semantics.
        log.error(
            "http_sync_failed",
            reason=str(exc),
            error_type=type(exc).__name__,
            phase="merge_import",
        )
        return {"status": "failed", "reason": str(exc)}

    imported_chunks = len(result.knowledge_chunks)
    imported_turns = len(result.conversation_records)
    log.info(
        "http_sync_complete",
        peer_instance=peer_payload.instance_id,
        imported_chunks=imported_chunks,
        imported_turns=imported_turns,
        **result.stats,
    )
    return {
        "status": "ok",
        "imported_chunks": imported_chunks,
        "imported_turns": imported_turns,
    }


if __name__ == "__main__":
    import asyncio

    print(asyncio.run(run_http_sync()))
