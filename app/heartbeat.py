"""
Heartbeat and presence detection.

Writes/reads a single ISO-8601 UTC timestamp to a dedicated "Heartbeat" tab in
the existing Google Sheets spreadsheet and classifies whether the local instance
is currently "online" based on how recently it stamped its heartbeat.

Reuses the gspread service-account client construction pattern from
``app/sheets_tracker.py``. This module is intended for LOCAL usage (the local
instance stamps the heartbeat; the cloud instance reads it to decide failover).
"""

import os
from datetime import datetime, timedelta, timezone

import gspread
import structlog
from google.oauth2.service_account import Credentials

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration (mirrors app/sheets_tracker.py conventions, env-overridable)
# ---------------------------------------------------------------------------

SERVICE_ACCOUNT_PATH = os.getenv(
    "SERVICE_ACCOUNT_PATH", "/opt/angelina/config/service-account.json"
)
SPREADSHEET_ID = os.getenv(
    "SPREADSHEET_ID", "YOUR_SPREADSHEET_ID"
)
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

HEARTBEAT_WORKSHEET = "Heartbeat"
HEARTBEAT_CELL = "B1"
PRESENCE_WINDOW_HOURS = int(os.getenv("PRESENCE_WINDOW_HOURS", "25"))


def _open_spreadsheet() -> "gspread.Spreadsheet":
    """
    Construct a gspread client from the service account and open the spreadsheet.

    Returns:
        gspread.Spreadsheet: The opened spreadsheet.
    """
    credentials = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_PATH, scopes=SCOPES
    )
    client = gspread.authorize(credentials)
    return client.open_by_key(SPREADSHEET_ID)


def _get_heartbeat_worksheet(
    spreadsheet: "gspread.Spreadsheet", create: bool = False
) -> "gspread.Worksheet":
    """
    Get the Heartbeat worksheet, optionally creating it if missing.

    Args:
        spreadsheet: The opened spreadsheet.
        create: When True, create the worksheet if it does not exist.

    Returns:
        gspread.Worksheet: The heartbeat worksheet.

    Raises:
        gspread.exceptions.WorksheetNotFound: If missing and create is False.
    """
    try:
        return spreadsheet.worksheet(HEARTBEAT_WORKSHEET)
    except gspread.exceptions.WorksheetNotFound:
        if not create:
            raise
        logger.info(
            "heartbeat_worksheet_creating", worksheet=HEARTBEAT_WORKSHEET
        )
        return spreadsheet.add_worksheet(
            title=HEARTBEAT_WORKSHEET, rows=10, cols=4
        )


def write_heartbeat(now_utc: datetime | None = None) -> None:
    """
    Write an ISO-8601 UTC timestamp (with explicit offset) to ``Heartbeat!B1``.

    Creates the Heartbeat worksheet if it does not exist. Local-only usage.

    Args:
        now_utc: Optional timestamp to write. Defaults to ``datetime.now(timezone.utc)``.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    try:
        spreadsheet = _open_spreadsheet()
        worksheet = _get_heartbeat_worksheet(spreadsheet, create=True)
        timestamp = now_utc.isoformat()
        worksheet.update_acell(HEARTBEAT_CELL, timestamp)
        logger.info("heartbeat_written", cell=HEARTBEAT_CELL, timestamp=timestamp)
    except Exception as exc:  # noqa: BLE001 - heartbeat must not crash callers
        logger.error("heartbeat_write_failed", error=str(exc))


def read_heartbeat() -> datetime | None:
    """
    Read and parse the heartbeat timestamp from ``Heartbeat!B1``.

    Returns:
        A timezone-aware UTC datetime, or None if the value is missing,
        unparseable, or unreadable for any reason.
    """
    try:
        spreadsheet = _open_spreadsheet()
        worksheet = _get_heartbeat_worksheet(spreadsheet, create=False)
        raw = worksheet.acell(HEARTBEAT_CELL).value
    except Exception as exc:  # noqa: BLE001 - unreadable => treat as offline
        logger.warning("heartbeat_read_failed", error=str(exc))
        return None

    if not raw:
        logger.warning("heartbeat_missing", cell=HEARTBEAT_CELL)
        return None

    try:
        parsed = datetime.fromisoformat(raw.strip())
    except (ValueError, TypeError) as exc:
        logger.warning("heartbeat_unparseable", raw=raw, error=str(exc))
        return None

    # Normalize to a timezone-aware UTC datetime.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_local_online(now_utc: datetime | None = None) -> bool:
    """
    Determine whether the local instance is currently online.

    Returns True iff a heartbeat is present AND its age is within
    ``PRESENCE_WINDOW_HOURS``. An unreadable/missing heartbeat is treated as
    offline (returns False).

    Args:
        now_utc: Optional reference "now". Defaults to ``datetime.now(timezone.utc)``.

    Returns:
        bool: True if the local instance is considered online, else False.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    heartbeat = read_heartbeat()
    if heartbeat is None:
        return False

    age = now_utc - heartbeat
    online = age <= timedelta(hours=PRESENCE_WINDOW_HOURS)
    logger.info(
        "presence_classified",
        online=online,
        age_hours=age.total_seconds() / 3600.0,
        window_hours=PRESENCE_WINDOW_HOURS,
    )
    return online
