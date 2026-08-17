"""
Google Drive sync module for Angelina's knowledge base.
Syncs documents from a configured Drive folder into the knowledge base via /learn commands.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

import httpx
from google.oauth2 import service_account
from google.auth.transport.requests import Request

# Configuration
SERVICE_ACCOUNT_PATH = "/opt/angelina/config/service-account.json"
DRIVE_FOLDER_ID = "YOUR_DRIVE_FOLDER_ID"
SYNC_STATE_FILE = "/opt/angelina/data/drive_sync_state.json"
ANGELINA_API_URL = "http://127.0.0.1:8080"
DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
MAX_LEARN_CHUNK = 1500

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def get_drive_credentials() -> str:
    """Load service account credentials and return an access token for Drive API."""
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_PATH, scopes=[DRIVE_SCOPE]
    )
    credentials.refresh(Request())
    return credentials.token


async def list_files(access_token: str) -> list[dict]:
    """List all files in the configured Drive folder."""
    url = f"{DRIVE_API_BASE}/files"
    params = {
        "q": f"'{DRIVE_FOLDER_ID}' in parents",
        "fields": "files(id,name,mimeType,modifiedTime)",
    }
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data.get("files", [])


async def download_file_content(access_token: str, file_id: str, mime_type: str) -> str | None:
    """
    Download file content from Drive.
    - Google Docs: export as text/plain
    - .txt/.md files: direct download
    - Other types: skip
    """
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient() as client:
        if mime_type == "application/vnd.google-apps.document":
            # Export Google Docs as plain text
            url = f"{DRIVE_API_BASE}/files/{file_id}/export"
            params = {"mimeType": "text/plain"}
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.text

        elif mime_type in ("text/plain", "text/markdown"):
            # Direct download for txt/md files
            url = f"{DRIVE_API_BASE}/files/{file_id}"
            params = {"alt": "media"}
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.text

        else:
            logger.info(f"Skipping unsupported mime type: {mime_type}")
            return None


def load_sync_state() -> dict:
    """Load the sync state from disk. Returns dict of file_id -> modifiedTime."""
    if not os.path.exists(SYNC_STATE_FILE):
        return {}
    try:
        with open(SYNC_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load sync state, starting fresh: {e}")
        return {}


def save_sync_state(state: dict) -> None:
    """Persist the sync state to disk."""
    os.makedirs(os.path.dirname(SYNC_STATE_FILE), exist_ok=True)
    with open(SYNC_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


async def sync_to_knowledge(text: str, filename: str) -> None:
    """
    POST content to Angelina's /chat endpoint using /learn command.
    Splits into multiple calls if text exceeds MAX_LEARN_CHUNK characters.
    """
    chunks = []
    while len(text) > MAX_LEARN_CHUNK:
        # Try to split at a newline or space boundary
        split_pos = text.rfind("\n", 0, MAX_LEARN_CHUNK)
        if split_pos == -1:
            split_pos = text.rfind(" ", 0, MAX_LEARN_CHUNK)
        if split_pos == -1:
            split_pos = MAX_LEARN_CHUNK
        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip()
    if text:
        chunks.append(text)

    async with httpx.AsyncClient(timeout=60.0) as client:
        for i, chunk in enumerate(chunks, 1):
            part_label = f" (part {i}/{len(chunks)})" if len(chunks) > 1 else ""
            message = f"/learn [Drive: {filename}{part_label}] {chunk}"
            try:
                response = await client.post(
                    f"{ANGELINA_API_URL}/chat",
                    json={"message": message, "session_id": "drive-sync", "language": "zh-TW"},
                )
                response.raise_for_status()
                logger.info(f"  Ingested chunk {i}/{len(chunks)} for '{filename}'")
            except httpx.HTTPError as e:
                logger.error(f"  Failed to ingest chunk {i}/{len(chunks)} for '{filename}': {e}")
                raise


async def run_sync() -> dict:
    """
    Main sync function:
    1. Gets credentials
    2. Lists files in Drive folder
    3. Compares against sync state
    4. Downloads new/modified files
    5. Ingests content via /learn
    6. Updates sync state
    7. Returns summary
    """
    summary = {"synced": 0, "skipped": 0, "errors": 0, "error_details": []}

    # Step 1: Get credentials
    try:
        logger.info("Obtaining Drive API credentials...")
        access_token = get_drive_credentials()
    except Exception as e:
        logger.error(f"Failed to get credentials: {e}")
        summary["errors"] += 1
        summary["error_details"].append(f"Credentials error: {e}")
        return summary

    # Step 2: List files
    try:
        logger.info(f"Listing files in folder {DRIVE_FOLDER_ID}...")
        files = await list_files(access_token)
        logger.info(f"Found {len(files)} file(s) in Drive folder.")
    except Exception as e:
        logger.error(f"Failed to list files: {e}")
        summary["errors"] += 1
        summary["error_details"].append(f"List files error: {e}")
        return summary

    # Step 3: Load sync state
    sync_state = load_sync_state()

    # Step 4-6: Process each file
    for file_info in files:
        file_id = file_info["id"]
        filename = file_info["name"]
        mime_type = file_info["mimeType"]
        modified_time = file_info["modifiedTime"]

        # Check if file needs syncing
        if file_id in sync_state and sync_state[file_id] == modified_time:
            logger.info(f"Skipping '{filename}' (unchanged)")
            summary["skipped"] += 1
            continue

        logger.info(f"Processing '{filename}' (type: {mime_type})...")

        try:
            # Download content
            content = await download_file_content(access_token, file_id, mime_type)
            if content is None:
                summary["skipped"] += 1
                continue

            # Ingest into knowledge base
            await sync_to_knowledge(content, filename)

            # Update sync state
            sync_state[file_id] = modified_time
            summary["synced"] += 1
            logger.info(f"Successfully synced '{filename}'")

        except Exception as e:
            logger.error(f"Error processing '{filename}': {e}")
            summary["errors"] += 1
            summary["error_details"].append(f"{filename}: {e}")
            continue

    # Step 7: Save sync state
    save_sync_state(sync_state)

    logger.info(
        f"Sync complete: {summary['synced']} synced, "
        f"{summary['skipped']} skipped, {summary['errors']} errors"
    )
    return summary


if __name__ == "__main__":
    result = asyncio.run(run_sync())
    print(f"\nSync Summary: {json.dumps(result, indent=2, default=str)}")
