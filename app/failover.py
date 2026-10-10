"""
Failover daily-push orchestration (local + cloud share this file).
Role-gated via INSTANCE_ROLE. Guarantees at-most-one daily push via a shared
dedup marker (Heartbeat!B2) plus heartbeat-based presence detection.
"""
import asyncio
import os
import structlog
from app.daily_analysis import main as run_daily_analysis
from app.heartbeat import (
    is_local_online,
    write_heartbeat,
    already_pushed_today,
    write_last_push_date,
)

logger = structlog.get_logger(__name__)
INSTANCE_ROLE = os.getenv("INSTANCE_ROLE", "local")
_QUOTA_MARKERS = ("quota", "resource_exhausted", "resourceexhausted", "429",
                  "rate limit", "rate_limit")


def _is_quota_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _QUOTA_MARKERS)


async def _run_analysis_and_push() -> bool:
    try:
        await run_daily_analysis()
        write_last_push_date()  # dedup marker: a successful push happened today
        return True
    except Exception as exc:  # noqa: BLE001
        if _is_quota_error(exc):
            logger.warning("gemini_quota_exhausted", error=str(exc))
            return False
        raise


async def run_daily_push() -> dict:
    if INSTANCE_ROLE == "cloud":
        return await _run_cloud_push()
    return await _run_local_push()


async def _run_local_push() -> dict:
    # If someone (the cloud failover) already pushed today, don't double-push.
    # Still stamp the heartbeat so the cloud sees local is back online.
    if already_pushed_today():
        logger.info("dedup_skip", role="local", reason="already_pushed_today")
        write_heartbeat()
        logger.info("heartbeat_written", role="local")
        return {"role": "local", "action": "dedup_skip", "heartbeat_written": True}
    pushed = False
    try:
        pushed = await _run_analysis_and_push()
    except Exception as exc:  # noqa: BLE001
        logger.error("local_push_failed", error=str(exc))
    finally:
        write_heartbeat()
        logger.info("heartbeat_written", role="local")
    return {"role": "local", "pushed": pushed, "heartbeat_written": True}


async def _run_cloud_push() -> dict:
    if already_pushed_today():
        logger.info("dedup_skip", role="cloud", reason="already_pushed_today")
        return {"role": "cloud", "action": "dedup_skip"}
    if is_local_online():
        logger.info("passive_skip", role="cloud")
        return {"role": "cloud", "action": "passive_skip"}
    logger.info("failover_push", role="cloud")
    pushed = await _run_analysis_and_push()
    return {"role": "cloud", "action": "failover_push", "pushed": pushed}


if __name__ == "__main__":
    asyncio.run(run_daily_push())