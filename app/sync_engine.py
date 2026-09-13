"""
Angelina Hybrid Cloud -- sync engine.

This module owns the cross-instance synchronization logic. The two Angelina
instances (``local`` and ``cloud``) periodically exchange portable JSON
exports via a shared Google Drive folder and reconcile them with a
last-write-wins strategy.

Task 4.1 (this file) provides ONLY the pure :func:`merge` function -- it has
no I/O and no side effects, which makes it directly property-testable.

The transport / persistence functions (``export_state``, ``upload_export``,
``download_peer_export``, ``import_merged``, ``run_sync``) are added later in
Task 5.1 and layer Drive + ChromaDB + SQLite I/O on top of this pure core.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, TypeVar

import structlog

from app.models import Chunk, MergeResult, SyncPayload, Turn

log = structlog.get_logger(__name__)

R = TypeVar("R")


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def _ensure_aware(dt: datetime) -> datetime:
    """Return a timezone-aware datetime, assuming UTC when naive.

    Comparing naive and aware datetimes raises ``TypeError``; normalizing to
    UTC keeps last-write-wins comparisons total and deterministic.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _chunk_ts(chunk: Chunk) -> datetime:
    """Parse a :class:`Chunk`'s ISO-8601 ``last_modified`` into aware UTC."""
    raw = chunk.last_modified or chunk.created_at
    dt = datetime.fromisoformat(raw)
    return _ensure_aware(dt)


def _turn_ts(turn: Turn) -> datetime:
    """Return a :class:`Turn`'s ``last_modified`` as an aware UTC datetime."""
    dt = turn.last_modified or turn.created_at
    return _ensure_aware(dt)


def _chunk_id(chunk: Chunk) -> str:
    """Merge key for a knowledge chunk."""
    return chunk.id


def _turn_id(turn: Turn) -> object:
    """Merge key for a conversation record.

    The design uses namespaced ids (e.g. ``"local:1187"``) for cross-instance
    matching, but the :class:`Turn` model carries an ``int | None`` ``id``.
    We key by whatever id is present so records with a matching id resolve via
    last-write-wins; records lacking an id fall back to their python identity
    so they are treated as distinct and preserved (never merged away).
    """
    return turn.id if turn.id is not None else id(turn)


# ---------------------------------------------------------------------------
# Pure merge core
# ---------------------------------------------------------------------------


def _merge_records(
    local_recs: list[R],
    peer_recs: list[R],
    get_id: Callable[[R], object],
    get_ts: Callable[[R], datetime],
) -> tuple[list[R], dict[str, int]]:
    """Last-write-wins merge of two record lists keyed by ``get_id``.

    Rules:
    - Records present on only one side are kept as-is (never a deletion).
    - When both sides carry the same id, the record with the more recent
      timestamp (``get_ts``) wins.
    - On an identical timestamp, the local record wins (local is
      authoritative).

    Returns ``(merged_records, stats)`` where ``stats`` counts
    ``kept_local``, ``kept_peer``, ``tie_local_wins`` and ``peer_only_added``.
    """
    stats = {
        "kept_local": 0,
        "kept_peer": 0,
        "tie_local_wins": 0,
        "peer_only_added": 0,
    }

    local_map = {get_id(r): r for r in local_recs}
    peer_map = {get_id(r): r for r in peer_recs}

    result: dict[object, R] = {}
    # Preserve a stable, deterministic ordering: local ids first (in order),
    # then peer-only ids (in order). Dict insertion order gives us this.
    all_ids: list[object] = list(local_map)
    all_ids.extend(rid for rid in peer_map if rid not in local_map)

    for rid in all_ids:
        local_rec = local_map.get(rid)
        peer_rec = peer_map.get(rid)

        if local_rec is not None and peer_rec is None:
            result[rid] = local_rec
            stats["kept_local"] += 1
        elif peer_rec is not None and local_rec is None:
            result[rid] = peer_rec
            stats["peer_only_added"] += 1
        else:
            # Both sides carry this id -> last-write-wins.
            local_ts = get_ts(local_rec)  # type: ignore[arg-type]
            peer_ts = get_ts(peer_rec)  # type: ignore[arg-type]
            if local_ts > peer_ts:
                result[rid] = local_rec  # type: ignore[assignment]
                stats["kept_local"] += 1
            elif peer_ts > local_ts:
                result[rid] = peer_rec  # type: ignore[assignment]
                stats["kept_peer"] += 1
            else:
                # Identical timestamp -> local is authoritative.
                result[rid] = local_rec  # type: ignore[assignment]
                stats["tie_local_wins"] += 1

    return list(result.values()), stats


def _merge_drive_state(local_state: dict, peer_state: dict) -> dict:
    """Union two ``file_id -> modifiedTime`` maps, keeping the newest time.

    ``modifiedTime`` values are ISO-8601 strings. On an identical time (or an
    unparseable value) the local entry is retained, matching the
    local-authoritative tie rule used for records.
    """
    merged = dict(local_state)
    for file_id, peer_time in peer_state.items():
        if file_id not in merged:
            merged[file_id] = peer_time
            continue
        local_time = merged[file_id]
        try:
            keep_peer = _ensure_aware(
                datetime.fromisoformat(str(peer_time))
            ) > _ensure_aware(datetime.fromisoformat(str(local_time)))
        except (ValueError, TypeError):
            # Unparseable timestamp -> keep local (authoritative).
            keep_peer = False
        if keep_peer:
            merged[file_id] = peer_time
    return merged


def merge(local: SyncPayload, peer: SyncPayload) -> MergeResult:
    """Merge local and peer sync payloads using last-write-wins.

    This is a PURE function: it reads only its arguments, performs no I/O, and
    returns a fresh :class:`MergeResult`. That makes it directly property
    testable (Properties 3-6).

    Rules (Req 6.2-6.5, 9.4):

    - Knowledge chunks are keyed by ``Chunk.id``; conversation records by
      ``Turn.id`` (namespaced ids resolve to the same key once propagated).
    - Last-write-wins: the record with the more recent ``last_modified`` wins.
    - On an identical ``last_modified`` timestamp, the local record wins
      (local is authoritative and the outcome is deterministic).
    - Records present on only one side are always kept -- a missing record is
      never treated as a deletion.
    - ``drive_sync_state`` is unioned per ``file_id``, keeping the newest
      ``modifiedTime``.

    ``stats`` aggregates counts across both record types: ``kept_local``,
    ``kept_peer``, ``tie_local_wins``, ``peer_only_added``.
    """
    merged_chunks, chunk_stats = _merge_records(
        local.knowledge_chunks,
        peer.knowledge_chunks,
        _chunk_id,
        _chunk_ts,
    )
    merged_turns, turn_stats = _merge_records(
        local.conversation_records,
        peer.conversation_records,
        _turn_id,
        _turn_ts,
    )
    merged_drive_state = _merge_drive_state(
        local.drive_sync_state,
        peer.drive_sync_state,
    )

    stats = {
        key: chunk_stats[key] + turn_stats[key]
        for key in ("kept_local", "kept_peer", "tie_local_wins", "peer_only_added")
    }

    log.info(
        "sync_merge_complete",
        local_instance=local.instance_id,
        peer_instance=peer.instance_id,
        knowledge_chunks=len(merged_chunks),
        conversation_records=len(merged_turns),
        drive_files=len(merged_drive_state),
        **stats,
    )

    return MergeResult(
        knowledge_chunks=merged_chunks,
        conversation_records=merged_turns,
        drive_sync_state=merged_drive_state,
        stats=stats,
    )


# ===========================================================================
# Task 5.1 -- I/O and orchestration layer
#
# Everything below layers Google Drive transport + ChromaDB + SQLite
# persistence on top of the pure :func:`merge` core above. None of it touches
# or reimplements ``merge`` / ``_merge_records`` / ``_merge_drive_state``.
#
# Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.6
# ===========================================================================

import asyncio
import json as _json
import os
import uuid as _uuid
from datetime import datetime as _dt, timezone as _tz

from app.models import namespaced_turn_id

# ---------------------------------------------------------------------------
# Configuration (env-driven so the same code runs as ``local`` and ``cloud``)
# ---------------------------------------------------------------------------

# Google Drive folder used as the sync relay (Req 5.2). When unset, run_sync
# short-circuits with a warning rather than crashing (see run_sync).
SYNC_FOLDER_ID = os.getenv("ANGELINA_SYNC_FOLDER_ID")

# Identity of this instance -- "local" or "cloud". Determines our export
# filename and which peer file we pull.
INSTANCE_ID = os.getenv("INSTANCE_ID", "local")

# Each instance writes to its own namespaced file so the two never clobber
# one another in the shared folder.
EXPORT_FILENAME = f"angelina_export_{INSTANCE_ID}.json"

# Read-WRITE Drive scope. The existing app/drive_sync.py deliberately uses the
# read-only ``drive.readonly`` scope for knowledge ingestion; uploads need
# write access, so we mint a *separate* credential with the narrower
# ``drive.file`` scope (only files this app creates/opens are visible).
DRIVE_RW_SCOPE = "https://www.googleapis.com/auth/drive.file"

# Service-account path is shared with the existing Drive integration.
_SERVICE_ACCOUNT_PATH = os.getenv(
    "ANGELINA_SERVICE_ACCOUNT_PATH", "/opt/angelina/config/service-account.json"
)

_DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
_DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"

# On-disk drive sync state shared with app/drive_sync.py (single source of
# truth for the ``file_id -> modifiedTime`` map plus our own sync bookkeeping).
_SYNC_STATE_FILE = os.getenv(
    "ANGELINA_SYNC_STATE_FILE", "/opt/angelina/data/drive_sync_state.json"
)

# ChromaDB upsert batch size. The cloud VM has only 1GB RAM (+swap); embedding
# and inserting in small batches bounds peak memory during import.
_IMPORT_BATCH_SIZE = int(os.getenv("ANGELINA_SYNC_BATCH_SIZE", "20"))


def _peer_instance_id() -> str:
    """Return the counterpart instance id ('cloud' <-> 'local')."""
    return "cloud" if INSTANCE_ID == "local" else "local"


def _peer_export_filename() -> str:
    """Filename of the peer's export in the shared Drive folder."""
    return f"angelina_export_{_peer_instance_id()}.json"


def _now_iso() -> str:
    """Current instant as an explicit-offset UTC ISO-8601 string (Req 6.1)."""
    return _dt.now(_tz.utc).isoformat()


# ---------------------------------------------------------------------------
# Local drive_sync_state helpers
# ---------------------------------------------------------------------------


def _load_drive_sync_state() -> dict:
    """Load ``drive_sync_state.json`` from disk; empty dict when absent/bad."""
    if not os.path.exists(_SYNC_STATE_FILE):
        return {}
    try:
        with open(_SYNC_STATE_FILE, "r", encoding="utf-8") as fh:
            data = _json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        log.warning("drive_sync_state_unreadable", error=str(exc))
        return {}


def _save_drive_sync_state(state: dict) -> None:
    """Persist the merged drive_sync_state back to disk."""
    os.makedirs(os.path.dirname(_SYNC_STATE_FILE), exist_ok=True)
    with open(_SYNC_STATE_FILE, "w", encoding="utf-8") as fh:
        _json.dump(state, fh, indent=2, default=str)


# ---------------------------------------------------------------------------
# ChromaDB / SQLite access (imported defensively -- these depend on chromadb
# and aiosqlite which may not be installed in a bare dev environment).
# ---------------------------------------------------------------------------


def _read_all_chunks() -> list[Chunk]:
    """Read every Knowledge_Chunk out of ChromaDB as :class:`Chunk` objects.

    Embeddings are intentionally NOT read -- only text + metadata travel in the
    payload; the receiving side re-embeds on import (Req 5.2, egress budget).
    ``last_modified`` is taken from metadata when present, otherwise it defaults
    to ``created_at`` via the Chunk model validator (Req 6.1).
    """
    from app.services.rag_engine import _get_or_create_collection, VECTOR_STORE_PATH

    _, collection = _get_or_create_collection(VECTOR_STORE_PATH)
    raw = collection.get(include=["documents", "metadatas"])

    ids = raw.get("ids") or []
    documents = raw.get("documents") or []
    metadatas = raw.get("metadatas") or []

    chunks: list[Chunk] = []
    for chunk_id, text, meta in zip(ids, documents, metadatas):
        meta = meta or {}
        created_at = meta.get("created_at") or _now_iso()
        chunks.append(
            Chunk(
                id=chunk_id,
                text=text or "",
                source_type=meta.get("source_type", "notebooklm"),
                created_at=created_at,
                last_modified=meta.get("last_modified") or created_at,
            )
        )
    return chunks


async def _read_all_turns() -> list[Turn]:
    """Read every Conversation_Record out of SQLite as namespaced :class:`Turn`.

    Each turn's cross-instance id is namespaced with this instance's origin
    (e.g. ``"local:1187"``) so the merge key stays unique across instances
    while remaining stable under re-export.
    """
    import aiosqlite

    from app.services.conversation_memory import ConversationMemory

    memory = ConversationMemory()
    db_path = memory._db_path  # default path convention shared with the app

    turns: list[Turn] = []
    if not os.path.exists(db_path):
        return turns

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        # Include sync_id when present so records that ARRIVED from the peer
        # keep their ORIGINAL origin namespace on re-export (prevents the
        # namespace-bounce duplication where local:N becomes cloud:M and back).
        _has_sync = await _column_exists(db, "conversations", "sync_id")
        _cols = "id, session_id, role, content, created_at, is_summary"
        if _has_sync:
            _cols += ", sync_id"
        async with db.execute(
            f"SELECT {_cols} FROM conversations ORDER BY id ASC"
        ) as cursor:
            rows = await cursor.fetchall()

    for row in rows:
        created_at = _dt.fromisoformat(row["created_at"])
        # Preserve the original origin id for peer-synced rows (their sync_id
        # already carries e.g. "local:1187"); mint a new namespaced id only for
        # this instance's OWN native rows (sync_id NULL/absent).
        _row_keys = row.keys()
        _existing = row["sync_id"] if ("sync_id" in _row_keys and row["sync_id"]) else None
        turns.append(
            Turn(
                id=_existing or namespaced_turn_id(INSTANCE_ID, row["id"]),  # type: ignore[arg-type]
                session_id=row["session_id"],
                role=row["role"],
                content=row["content"],
                created_at=created_at,
                last_modified=created_at,
                is_summary=bool(row["is_summary"]),
            )
        )
    return turns


# ---------------------------------------------------------------------------
# Drive read-write transport (separate drive.file credential)
# ---------------------------------------------------------------------------


def _get_drive_rw_token() -> str:
    """Mint a Drive access token with the read-WRITE ``drive.file`` scope.

    This is deliberately independent of ``app/drive_sync.get_drive_credentials``
    (which is read-only) so knowledge ingestion keeps its least-privilege
    read-only scope while sync uploads get exactly the write access they need.
    """
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request as _GoogleAuthRequest

    credentials = service_account.Credentials.from_service_account_file(
        _SERVICE_ACCOUNT_PATH, scopes=[DRIVE_RW_SCOPE]
    )
    credentials.refresh(_GoogleAuthRequest())
    return credentials.token


async def _find_file_id(access_token: str, filename: str) -> str | None:
    """Return the Drive file id for ``filename`` in the sync folder, or None."""
    import httpx

    params = {
        "q": f"'{SYNC_FOLDER_ID}' in parents and name = '{filename}' and trashed = false",
        "fields": "files(id,name,modifiedTime)",
    }
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(f"{_DRIVE_API_BASE}/files", params=params, headers=headers)
        resp.raise_for_status()
        files = resp.json().get("files", [])
    return files[0]["id"] if files else None


# ---------------------------------------------------------------------------
# Public API -- export / upload / download / import / run
# ---------------------------------------------------------------------------


async def export_state() -> SyncPayload:
    """Build a portable :class:`SyncPayload` of this instance's current state.

    Reads all Knowledge_Chunks, all Conversation_Records, and the local
    drive_sync_state, attaching UTC ``last_modified`` timestamps. Vector
    embeddings are omitted -- the peer re-embeds each chunk's text on import
    (Req 5.2). The result is a pure, JSON-serialisable snapshot.
    """
    chunks = await asyncio.to_thread(_read_all_chunks)
    turns = await _read_all_turns()
    drive_state = _load_drive_sync_state()

    payload = SyncPayload(
        schema_version=1,
        instance_id=INSTANCE_ID,
        exported_at=_now_iso(),
        knowledge_chunks=chunks,
        conversation_records=turns,
        drive_sync_state=drive_state,
    )
    log.info(
        "sync_export_built",
        instance=INSTANCE_ID,
        knowledge_chunks=len(chunks),
        conversation_records=len(turns),
        drive_files=len(drive_state),
    )
    return payload


async def upload_export(payload: SyncPayload) -> None:
    """Upsert this instance's export file into the shared Drive folder.

    Serialises ``payload`` to JSON and creates ``EXPORT_FILENAME`` in
    ``SYNC_FOLDER_ID`` (via ``files.create``), or updates it in place when a
    file of that name already exists (via ``files.update``). Both use a
    multipart upload so metadata and content go in a single request. Requires
    the read-write ``drive.file`` scope (Req 5.2).
    """
    import httpx

    body = payload.model_dump_json().encode("utf-8")
    access_token = await asyncio.to_thread(_get_drive_rw_token)
    existing_id = await _find_file_id(access_token, EXPORT_FILENAME)

    # RFC 2387 multipart/related: JSON metadata part + file content part.
    boundary = f"angelina-{_uuid.uuid4().hex}"
    if existing_id is None:
        metadata = {"name": EXPORT_FILENAME, "parents": [SYNC_FOLDER_ID]}
    else:
        # files.update must not repeat 'parents'; name is enough to keep.
        metadata = {"name": EXPORT_FILENAME}

    parts = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{_json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        "Content-Type: application/json\r\n\r\n"
    ).encode("utf-8") + body + f"\r\n--{boundary}--\r\n".encode("utf-8")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": f"multipart/related; boundary={boundary}",
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        if existing_id is None:
            url = f"{_DRIVE_UPLOAD_BASE}/files?uploadType=multipart"
            resp = await client.post(url, content=parts, headers=headers)
        else:
            url = f"{_DRIVE_UPLOAD_BASE}/files/{existing_id}?uploadType=multipart"
            resp = await client.patch(url, content=parts, headers=headers)
        resp.raise_for_status()

    log.info(
        "sync_export_uploaded",
        filename=EXPORT_FILENAME,
        mode="update" if existing_id else "create",
        bytes=len(body),
    )


async def download_peer_export() -> SyncPayload | None:
    """Download and parse the peer instance's export, or None if it's absent.

    The peer is ``cloud`` when we are ``local`` and vice-versa. Returns None
    when the peer has not yet published an export (first-ever sync), so the
    caller can skip merging without treating it as an error (Req 5.3).
    """
    import httpx

    filename = _peer_export_filename()
    access_token = await asyncio.to_thread(_get_drive_rw_token)
    file_id = await _find_file_id(access_token, filename)
    if file_id is None:
        log.info("sync_peer_export_absent", filename=filename)
        return None

    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.get(
            f"{_DRIVE_API_BASE}/files/{file_id}",
            params={"alt": "media"},
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()

    payload = SyncPayload.model_validate(data)
    log.info(
        "sync_peer_export_downloaded",
        filename=filename,
        knowledge_chunks=len(payload.knowledge_chunks),
        conversation_records=len(payload.conversation_records),
    )
    return payload


async def import_merged(result: MergeResult) -> None:
    """Persist a merged :class:`MergeResult` into local storage.

    - Knowledge_Chunks are re-embedded and upserted into ChromaDB in bounded
      batches (``_IMPORT_BATCH_SIZE``) to cap peak memory on the 1GB cloud VM.
    - Conversation_Records are upserted into SQLite.
    - The reconciled drive_sync_state is written back to disk (Req 6.6).
    """
    from app.services.rag_engine import RAGEngine

    # --- Knowledge base: batched re-embed + upsert ------------------------
    rag = RAGEngine()
    chunks = result.knowledge_chunks
    for start in range(0, len(chunks), _IMPORT_BATCH_SIZE):
        batch = chunks[start : start + _IMPORT_BATCH_SIZE]
        await rag.add_chunks(batch)
        log.info(
            "sync_import_chunk_batch",
            batch_start=start,
            batch_size=len(batch),
            total=len(chunks),
        )

    # --- Conversation memory: upsert merged records -----------------------
    await _import_turns(result.conversation_records)

    # --- Drive sync state: reconcile on disk ------------------------------
    _save_drive_sync_state(result.drive_sync_state)

    log.info(
        "sync_import_complete",
        knowledge_chunks=len(chunks),
        conversation_records=len(result.conversation_records),
        drive_files=len(result.drive_sync_state),
    )


async def _import_turns(turns: list[Turn]) -> None:
    """Upsert merged conversation records into SQLite by namespaced id.

    A ``sync_id`` column keyed by the namespaced origin id (``local:1187``)
    lets an upsert match a previously imported record so re-runs are
    idempotent (Req 6.6) without colliding with the local autoincrement
    ``id``. Records that originate on this instance are already present, so
    the ``ON CONFLICT`` update is a harmless no-op for them.
    """
    import aiosqlite

    from app.services.conversation_memory import ConversationMemory

    memory = ConversationMemory()
    await memory.initialize()  # ensure base table exists
    db_path = memory._db_path

    async with aiosqlite.connect(db_path) as db:
        # Additive schema: a nullable, unique sync_id used only for merge
        # reconciliation. Existing rows keep sync_id = NULL (no regression).
        if not await _column_exists(db, "conversations", "sync_id"):
            await db.execute("ALTER TABLE conversations ADD COLUMN sync_id TEXT")
        # The unique index MUST be non-partial: SQLite's ``ON CONFLICT(sync_id)``
        # upsert target only accepts a full (non-partial) UNIQUE index or PRIMARY
        # KEY. A partial index (``WHERE sync_id IS NOT NULL``) raises
        # "ON CONFLICT clause does not match any PRIMARY KEY or UNIQUE
        # constraint". A plain UNIQUE index still permits many NULL sync_id rows
        # because SQLite treats NULLs as distinct in unique indexes, so existing
        # local rows (sync_id = NULL) are unaffected.
        #
        # Drop any pre-existing partial index from an earlier build before
        # (re)creating the correct full unique index, so the migration is
        # self-healing on instances that already ran the buggy version.
        await db.execute("DROP INDEX IF EXISTS idx_conversations_sync_id")
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_sync_id "
            "ON conversations(sync_id)"
        )

        _own_prefix = f"{INSTANCE_ID}:"
        for turn in turns:
            sync_id = str(turn.id) if turn.id is not None else namespaced_turn_id(
                INSTANCE_ID, 0
            )
            # Skip records that ORIGINATED on this instance: they already exist
            # here as native rows (sync_id NULL), so re-importing the bounced-back
            # copy would duplicate our own conversation history.
            if sync_id.startswith(_own_prefix):
                continue
            created_at = (
                turn.created_at.isoformat()
                if isinstance(turn.created_at, _dt)
                else str(turn.created_at)
            )
            await db.execute(
                """
                INSERT INTO conversations
                    (session_id, role, content, created_at, is_summary, sync_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(sync_id) DO UPDATE SET
                    session_id = excluded.session_id,
                    role       = excluded.role,
                    content    = excluded.content,
                    created_at = excluded.created_at,
                    is_summary = excluded.is_summary
                """,
                (
                    turn.session_id,
                    turn.role,
                    turn.content,
                    created_at,
                    int(turn.is_summary),
                    sync_id,
                ),
            )
        await db.commit()


async def _column_exists(db, table: str, column: str) -> bool:
    """Return True if ``column`` already exists on ``table`` (SQLite)."""
    async with db.execute(f"PRAGMA table_info({table})") as cursor:
        rows = await cursor.fetchall()
    return any(row[1] == column for row in rows)


async def run_sync() -> dict:
    """Run one full bi-directional sync cycle (Req 5.1-5.6, 6.6).

    Sequence:
      1. export_state()            -> local snapshot
      2. upload_export(local)      -> publish to the shared Drive folder
      3. download_peer_export()    -> pull the peer's snapshot
      4. if no peer export yet     -> log 'no_peer_export', skip merge, return
      5. merge(local, peer)        -> reuse the pure merge() core
      6. import_merged(merged)     -> persist reconciled state locally
      7. record completion time    -> stamp drive_sync_state

    The entire cycle is wrapped in try/except. On ANY failure we log
    'sync_failed' with a diagnostic reason and return an error summary WITHOUT
    importing partial data, so the last successfully synchronised state is
    retained on this instance (Req 5.5, 5.6).
    """
    if not SYNC_FOLDER_ID:
        log.warning("sync_folder_unset", reason="ANGELINA_SYNC_FOLDER_ID not set")
        return {"status": "skipped", "reason": "ANGELINA_SYNC_FOLDER_ID not set"}

    try:
        local_payload = await export_state()
        await upload_export(local_payload)

        peer_payload = await download_peer_export()
        if peer_payload is None:
            log.info("no_peer_export", peer=_peer_instance_id())
            return {
                "status": "ok",
                "merged": False,
                "reason": "no_peer_export",
                "peer": _peer_instance_id(),
            }

        # Reuse the pure, property-tested merge core.
        merged = merge(local_payload, peer_payload)

        # Record the successful completion time in the reconciled state
        # BEFORE importing so it is persisted atomically with the merge (Req 5.4).
        completed_at = _now_iso()
        merged.drive_sync_state["last_sync_completed_at"] = completed_at

        await import_merged(merged)

        log.info(
            "sync_completed",
            instance=INSTANCE_ID,
            peer=_peer_instance_id(),
            completed_at=completed_at,
            **merged.stats,
        )
        return {
            "status": "ok",
            "merged": True,
            "completed_at": completed_at,
            "stats": merged.stats,
        }

    except Exception as exc:  # noqa: BLE001 -- we must not crash the cron
        # Req 5.5/5.6: leave existing state intact, log with a reason, and
        # return an error summary. No partial import has occurred because
        # import_merged is the last step and any failure before it is a no-op
        # against local storage.
        log.error("sync_failed", reason=str(exc), error_type=type(exc).__name__)
        return {"status": "failed", "reason": str(exc)}
