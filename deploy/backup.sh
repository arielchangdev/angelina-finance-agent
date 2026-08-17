#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Angelina Finance Agent - Backup Script
# =============================================================================
# Creates timestamped backups of all critical data and configuration.
# Keeps only the last 7 backups to conserve disk space.
#
# Cron entry (runs every Sunday at 03:00 UTC / 11:00 TST):
#   0 3 * * 0 /opt/angelina/deploy/backup.sh
#
# Files backed up:
#   - data/conversations.db       (conversation history)
#   - data/vector_store/          (RAG embeddings)
#   - data/drive_sync_state.json  (Google Drive sync state)
#   - config/service-account.json (GCP credentials)
#   - .env                        (environment configuration)
# =============================================================================

# --- Configuration ---
APP_DIR="/opt/angelina"
BACKUP_BASE="${APP_DIR}/backups"
LOG_FILE="/var/log/angelina/backup.log"
MAX_BACKUPS=7
TIMESTAMP=$(date +"%Y-%m-%d")
BACKUP_DIR="${BACKUP_BASE}/${TIMESTAMP}"
ARCHIVE_NAME="backup.tar.gz"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# --- Functions ---
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo -e "$msg" | tee -a "${LOG_FILE}"
}

success() {
    echo -e "${GREEN}✓ $1${NC}"
    log "SUCCESS: $1"
}

error() {
    echo -e "${RED}✗ $1${NC}"
    log "ERROR: $1"
}

warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
    log "WARNING: $1"
}

cleanup_on_error() {
    error "Backup failed! Cleaning up partial backup..."
    rm -rf "${BACKUP_DIR}"
    exit 1
}

trap cleanup_on_error ERR

# --- Ensure log directory exists ---
mkdir -p "$(dirname "${LOG_FILE}")"
mkdir -p "${BACKUP_BASE}"

echo ""
echo "============================================"
echo "  Angelina Backup - ${TIMESTAMP}"
echo "============================================"
echo ""

log "Starting backup..."

# --- Create backup directory ---
mkdir -p "${BACKUP_DIR}"
success "Created backup directory: ${BACKUP_DIR}"

# --- Verify source files exist ---
FILES_TO_BACKUP=()
MISSING_FILES=()

declare -A BACKUP_ITEMS=(
    ["data/conversations.db"]="Conversation database"
    ["data/vector_store/"]="Vector store (RAG)"
    ["data/drive_sync_state.json"]="Drive sync state"
    ["config/service-account.json"]="Service account credentials"
    [".env"]="Environment configuration"
)

cd "${APP_DIR}"

for item in "${!BACKUP_ITEMS[@]}"; do
    if [[ -e "${item}" ]]; then
        FILES_TO_BACKUP+=("${item}")
        success "Found: ${item} (${BACKUP_ITEMS[$item]})"
    else
        MISSING_FILES+=("${item}")
        warning "Missing: ${item} (${BACKUP_ITEMS[$item]}) - skipping"
    fi
done

if [[ ${#FILES_TO_BACKUP[@]} -eq 0 ]]; then
    error "No files found to backup! Aborting."
    exit 1
fi

# --- Create compressed archive ---
log "Creating archive: ${BACKUP_DIR}/${ARCHIVE_NAME}"
tar -czf "${BACKUP_DIR}/${ARCHIVE_NAME}" "${FILES_TO_BACKUP[@]}" 2>/dev/null
ARCHIVE_SIZE=$(du -h "${BACKUP_DIR}/${ARCHIVE_NAME}" | cut -f1)
success "Archive created: ${ARCHIVE_SIZE}"

# --- Generate checksum ---
sha256sum "${BACKUP_DIR}/${ARCHIVE_NAME}" > "${BACKUP_DIR}/checksum.sha256"
success "Checksum generated"

# --- Cleanup old backups (keep only last MAX_BACKUPS) ---
BACKUP_COUNT=$(find "${BACKUP_BASE}" -maxdepth 1 -mindepth 1 -type d | sort | wc -l)

if [[ ${BACKUP_COUNT} -gt ${MAX_BACKUPS} ]]; then
    DELETE_COUNT=$((BACKUP_COUNT - MAX_BACKUPS))
    log "Removing ${DELETE_COUNT} old backup(s) (keeping last ${MAX_BACKUPS})..."

    find "${BACKUP_BASE}" -maxdepth 1 -mindepth 1 -type d | sort | head -n "${DELETE_COUNT}" | while read -r old_backup; do
        rm -rf "${old_backup}"
        warning "Deleted old backup: $(basename "${old_backup}")"
    done

    success "Cleanup complete"
else
    success "No cleanup needed (${BACKUP_COUNT}/${MAX_BACKUPS} backups stored)"
fi

# --- Print summary ---
echo ""
echo "============================================"
echo "  Backup Summary"
echo "============================================"
echo ""
success "Date: ${TIMESTAMP}"
success "Location: ${BACKUP_DIR}/${ARCHIVE_NAME}"
success "Size: ${ARCHIVE_SIZE}"
success "Files backed up: ${#FILES_TO_BACKUP[@]}"
if [[ ${#MISSING_FILES[@]} -gt 0 ]]; then
    warning "Files missing: ${#MISSING_FILES[@]}"
fi
echo ""

TOTAL_BACKUPS=$(find "${BACKUP_BASE}" -maxdepth 1 -mindepth 1 -type d | wc -l)
success "Total backups stored: ${TOTAL_BACKUPS}/${MAX_BACKUPS}"
echo ""

log "Backup completed successfully."