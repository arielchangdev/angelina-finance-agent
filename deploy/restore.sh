#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Angelina Finance Agent - Restore Script
# =============================================================================
# Restores a backup archive to the application directory.
# Stops the container, extracts data, restarts, and verifies health.
#
# Usage:
#   ./deploy/restore.sh latest
#   ./deploy/restore.sh /opt/angelina/backups/2026-07-22/backup.tar.gz
# =============================================================================

# --- Configuration ---
APP_DIR="/opt/angelina"
BACKUP_BASE="${APP_DIR}/backups"
CONTAINER_NAME="angelina-app"
HEALTH_URL="http://localhost:8080/health"
HEALTH_TIMEOUT=30

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# --- Functions ---
success() { echo -e "${GREEN}✓ $1${NC}"; }
error()   { echo -e "${RED}✗ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠ $1${NC}"; }
info()    { echo -e "  $1"; }

usage() {
    echo "Usage: $0 <backup-path|latest>"
    echo ""
    echo "Arguments:"
    echo "  latest                  Restore the most recent backup"
    echo "  /path/to/backup.tar.gz  Restore a specific backup archive"
    echo ""
    echo "Examples:"
    echo "  $0 latest"
    echo "  $0 /opt/angelina/backups/2026-07-22/backup.tar.gz"
    exit 1
}

wait_for_health() {
    local elapsed=0
    while [[ ${elapsed} -lt ${HEALTH_TIMEOUT} ]]; do
        if curl -sf "${HEALTH_URL}" > /dev/null 2>&1; then
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    return 1
}

# --- Validate arguments ---
if [[ $# -lt 1 ]]; then
    error "Missing argument."
    usage
fi

ARCHIVE_PATH="$1"

echo ""
echo "============================================"
echo "  Angelina Restore"
echo "============================================"
echo ""

# --- Resolve "latest" to actual path ---
if [[ "${ARCHIVE_PATH}" == "latest" ]]; then
    LATEST_DIR=$(find "${BACKUP_BASE}" -maxdepth 1 -mindepth 1 -type d | sort | tail -n 1)

    if [[ -z "${LATEST_DIR}" ]]; then
        error "No backups found in ${BACKUP_BASE}"
        exit 1
    fi

    ARCHIVE_PATH="${LATEST_DIR}/backup.tar.gz"
    success "Resolved 'latest' to: ${ARCHIVE_PATH}"
fi

# --- Validate archive exists ---
if [[ ! -f "${ARCHIVE_PATH}" ]]; then
    error "Backup archive not found: ${ARCHIVE_PATH}"
    exit 1
fi

ARCHIVE_SIZE=$(du -h "${ARCHIVE_PATH}" | cut -f1)
info "Archive: ${ARCHIVE_PATH} (${ARCHIVE_SIZE})"

# --- Verify checksum if available ---
CHECKSUM_FILE="$(dirname "${ARCHIVE_PATH}")/checksum.sha256"
if [[ -f "${CHECKSUM_FILE}" ]]; then
    if (cd "$(dirname "${ARCHIVE_PATH}")" && sha256sum -c "${CHECKSUM_FILE}" > /dev/null 2>&1); then
        success "Checksum verification passed"
    else
        error "Checksum verification FAILED! Archive may be corrupted."
        echo -n "Continue anyway? [y/N]: "
        read -r REPLY
        if [[ "${REPLY}" != "y" && "${REPLY}" != "Y" ]]; then
            echo "Aborting."
            exit 1
        fi
    fi
else
    warning "No checksum file found - skipping verification"
fi

# --- Confirm restore ---
echo ""
warning "This will overwrite current data files!"
echo -n "Proceed with restore? [y/N]: "
read -r REPLY
if [[ "${REPLY}" != "y" && "${REPLY}" != "Y" ]]; then
    echo "Aborting."
    exit 0
fi

echo ""

# --- Stop container ---
info "Stopping container: ${CONTAINER_NAME}..."
if podman stop "${CONTAINER_NAME}" > /dev/null 2>&1; then
    success "Container stopped"
else
    warning "Container was not running or doesn't exist"
fi

# --- Create pre-restore backup of current state ---
PRE_RESTORE_DIR="${BACKUP_BASE}/pre-restore-$(date +%Y%m%d-%H%M%S)"
mkdir -p "${PRE_RESTORE_DIR}"
info "Saving current state to: ${PRE_RESTORE_DIR}"

cd "${APP_DIR}"
if [[ -f "data/conversations.db" ]] || [[ -d "data/vector_store" ]]; then
    tar -czf "${PRE_RESTORE_DIR}/pre-restore.tar.gz" \
        --ignore-failed-read \
        data/conversations.db \
        data/vector_store/ \
        data/drive_sync_state.json \
        config/service-account.json \
        .env 2>/dev/null || true
    success "Pre-restore backup saved"
else
    warning "No existing data to backup"
fi

# --- Extract backup ---
info "Extracting backup..."
cd "${APP_DIR}"
tar -xzf "${ARCHIVE_PATH}" --overwrite
success "Backup extracted to ${APP_DIR}"

# --- Verify extracted files ---
echo ""
info "Verifying restored files:"
for item in "data/conversations.db" "data/vector_store/" "config/service-account.json" ".env"; do
    if [[ -e "${APP_DIR}/${item}" ]]; then
        success "  ${item}"
    else
        warning "  ${item} (not in backup)"
    fi
done

# --- Start container ---
echo ""
info "Starting container: ${CONTAINER_NAME}..."
if podman start "${CONTAINER_NAME}" > /dev/null 2>&1; then
    success "Container started"
else
    error "Failed to start container!"
    error "Try: podman start ${CONTAINER_NAME}"
    exit 1
fi

# --- Verify health ---
info "Waiting for health check (timeout: ${HEALTH_TIMEOUT}s)..."
if wait_for_health; then
    success "Health check passed - application is running"
else
    error "Health check failed after ${HEALTH_TIMEOUT}s!"
    warning "Check logs: podman logs ${CONTAINER_NAME}"
    warning "Pre-restore backup available at: ${PRE_RESTORE_DIR}"
    exit 1
fi

# --- Summary ---
echo ""
echo "============================================"
echo "  Restore Complete"
echo "============================================"
echo ""
success "Restored from: $(basename "$(dirname "${ARCHIVE_PATH}")")"
success "Application is healthy and running"
info "Pre-restore backup: ${PRE_RESTORE_DIR}"
echo ""