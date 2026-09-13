"""
Failover daily-push orchestration.

Role-gated wrapper around the existing daily analysis pipeline
(``app/daily_analysis.py``) that guarantees *at most one* Daily_Push per day
across the Local_Instance and the Cloud_Instance.

Behavior is driven entirely by configuration (the ``INSTANCE_ROLE`` env flag)
and the runtime heartbeat, not by forked code — the same repository runs on
both sides.

Roles:
  * ``local``  (default): always run the daily analysis + Telegram push, then
                stamp the heartbeat. Ordering is critical — push FIRST, then
                stamp. Even if the push raises, the heartbeat is still written
                so the cloud does not double-push for a transient local error.
  * ``cloud``: passive backup. Read the heartbeat; if the local instance is
                online, skip (``passive_skip``). Only when local is offline /
                unreadable does the cloud run the analysis + push
                (``failover_push``).

Requirements: 2.2, 4.1, 4.2, 4.3, 4.4, 4.5, 9.1, 9.2, 9.3
"""

import asyncio
import os

import structlog

from app.daily_analysis import main as run_daily_analysis
from app.heartbeat import is_local_online, write_heartbeat

logger = structlog.get_logger(__name__)

# Role flag: "local" (primary, default) or "cloud" (passive backup).
INSTANCE_ROLE = os.getenv("INSTANCE_ROLE", "local")

# Substrings that identify a Gemini quota / rate-limit exhaustion in an error
# message. On these we log ``gemini_quota_exhausted`` and skip generation
# without crashing the cron.
_QUOTA_MARKERS = (
    "quota",
    "resource_exhausted",
    "resourceexhausted",
    "429",
    "rate limit",
    "rate_limit",
)


def _is_quota_error(exc: Exception) -> bool:
    """Return True if the exception looks like a Gemini quota exhaustion."""
    message = str(exc).lower()
    return any(marker in message for marker in _QUOTA_MARKERS)


async def _run_analysis_and_push() -> bool:
    """
    Run the existing daily analysis + Telegram push pipeline.

    Wraps the existing ``daily_analysis.main()`` (fetch -> analyze -> telegram
    -> sheets -> store). On Gemini quota exhaustion, logs
    ``gemini_quota_exhausted`` and returns False without raising so the cron
    does not crash. Other exceptions are re-raised to the caller so role logic
    can decide how to handle them (e.g. local still stamps the heartbeat).

    Returns:
        bool: True if the analysis/push completed, False if generation was
        skipped due to quota exhaustion.
    """
    try:
        await run_daily_analysis()
        return True
    except Exception as exc:  # noqa: BLE001 - inspect for quota, else re-raise
        if _is_quota_error(exc):
            logger.warning("gemini_quota_exhausted", error=str(exc))
            return False
        raise


async def run_daily_push() -> dict:
    """
    Orchestrate the daily push with role-based gating.

    Local role:
        Run daily_analysis + push, then ``write_heartbeat()``. Push happens
        FIRST, then the heartbeat is stamped. If the push raises, the heartbeat
        is still written (local is alive) so cloud won't double-push for a
        transient error.

    Cloud role:
        Read the heartbeat. If ``is_local_online()`` -> skip (log
        ``passive_skip``). Otherwise run daily_analysis + push (log
        ``failover_push``).

    Returns:
        dict: A summary of what happened, suitable for logging.
    """
    if INSTANCE_ROLE == "cloud":
        return await _run_cloud_push()
    return await _run_local_push()


async def _run_local_push() -> dict:
    """
    Local role: push first, then always stamp the heartbeat.

    Even when the push raises, the heartbeat is written so the cloud does not
    double-push for a transient error.
    """
    pushed = False
    try:
        pushed = await _run_analysis_and_push()
    except Exception as exc:  # noqa: BLE001 - still stamp heartbeat below
        logger.error("local_push_failed", error=str(exc))
    finally:
        # CRITICAL ORDERING: always stamp the heartbeat after the push attempt.
        write_heartbeat()
        logger.info("heartbeat_written", role="local")

    return {"role": "local", "pushed": pushed, "heartbeat_written": True}


async def _run_cloud_push() -> dict:
    """
    Cloud role: passive backup. Skip when local is online, else failover push.
    """
    if is_local_online():
        logger.info("passive_skip", role="cloud")
        return {"role": "cloud", "action": "passive_skip"}

    logger.info("failover_push", role="cloud")
    pushed = await _run_analysis_and_push()
    return {"role": "cloud", "action": "failover_push", "pushed": pushed}


if __name__ == "__main__":
    asyncio.run(run_daily_push())
