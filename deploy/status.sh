#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Angelina Finance Agent - Status Check Script
# =============================================================================
# Provides a one-glance overview of system health including:
#   - Container status and health
#   - Disk and memory usage
#   - Last backup and analysis dates
#   - Cron jobs and vector count
#
# Usage:
#   ./deploy/status.sh
# =============================================================================

# --- Configuration ---
APP_DIR="/opt/angelina"
CONTAINER_NAME="angelina-app"
HEALTH_URL="http://localhost:8080/health"
BACKUP_BASE="${APP_DIR}/backups"
DB_PATH="${APP_DIR}/data/conversations.db"
VECTOR_DIR="${APP_DIR}/data/vector_store"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# --- Functions ---
ok()      { echo -e "  ${GREEN}●${NC} $1: ${GREEN}$2${NC}"; }
fail()    { echo -e "  ${RED}●${NC} $1: ${RED}$2${NC}"; }
warn()    { echo -e "  ${YELLOW}●${NC} $1: ${YELLOW}$2${NC}"; }
info()    { echo -e "  ${CYAN}●${NC} $1: $2"; }
header()  { echo -e "\n${BOLD}${BLUE}─── $1 ───${NC}"; }

# =============================================================================
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║     Angelina Finance Agent - Status      ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo -e "  $(date '+%Y-%m-%d %H:%M:%S %Z')"

# =============================================================================
header "Container"
# =============================================================================

# Container status
if podman container exists "${CONTAINER_NAME}" 2>/dev/null; then
    CONTAINER_STATUS=$(podman inspect "${CONTAINER_NAME}" --format '{{.State.Status}}' 2>/dev/null || echo "unknown")
    CONTAINER_UPTIME=$(podman inspect "${CONTAINER_NAME}" --format '{{.State.StartedAt}}' 2>/dev/null || echo "")

    if [[ "${CONTAINER_STATUS}" == "running" ]]; then
        ok "Status" "Running"
        if [[ -n "${CONTAINER_UPTIME}" ]]; then
            # Calculate uptime
            START_EPOCH=$(date -d "${CONTAINER_UPTIME}" +%s 2>/dev/null || echo "0")
            NOW_EPOCH=$(date +%s)
            if [[ ${START_EPOCH} -gt 0 ]]; then
                UPTIME_SECS=$((NOW_EPOCH - START_EPOCH))
                UPTIME_DAYS=$((UPTIME_SECS / 86400))
                UPTIME_HOURS=$(((UPTIME_SECS % 86400) / 3600))
                info "Uptime" "${UPTIME_DAYS}d ${UPTIME_HOURS}h"
            fi
        fi
    elif [[ "${CONTAINER_STATUS}" == "exited" ]]; then
        fail "Status" "Stopped"
    else
        warn "Status" "${CONTAINER_STATUS}"
    fi
else
    fail "Status" "Not found"
fi

# Health check
if curl -sf "${HEALTH_URL}" > /dev/null 2>&1; then
    ok "Health" "Healthy"
else
    fail "Health" "Unreachable"
fi

# =============================================================================
header "Resources"
# =============================================================================

# Disk usage for app directory
if [[ -d "${APP_DIR}" ]]; then
    APP_DISK=$(du -sh "${APP_DIR}" 2>/dev/null | cut -f1)
    info "App disk usage" "${APP_DISK}"
fi

# Disk usage for data directory
if [[ -d "${APP_DIR}/data" ]]; then
    DATA_DISK=$(du -sh "${APP_DIR}/data" 2>/dev/null | cut -f1)
    info "Data directory" "${DATA_DISK}"
fi

# Overall disk space
DISK_USAGE=$(df -h "${APP_DIR}" 2>/dev/null | awk 'NR==2 {print $5 " used of " $2}')
if [[ -n "${DISK_USAGE}" ]]; then
    DISK_PCT=$(df "${APP_DIR}" 2>/dev/null | awk 'NR==2 {print $5}' | tr -d '%')
    if [[ ${DISK_PCT:-0} -gt 90 ]]; then
        fail "Disk space" "${DISK_USAGE}"
    elif [[ ${DISK_PCT:-0} -gt 75 ]]; then
        warn "Disk space" "${DISK_USAGE}"
    else
        ok "Disk space" "${DISK_USAGE}"
    fi
fi

# Memory usage (container)
if podman container exists "${CONTAINER_NAME}" 2>/dev/null; then
    MEM_USAGE=$(podman stats "${CONTAINER_NAME}" --no-stream --format '{{.MemUsage}}' 2>/dev/null || echo "N/A")
    if [[ "${MEM_USAGE}" != "N/A" ]]; then
        info "Container memory" "${MEM_USAGE}"
    fi
fi

# System memory
MEM_INFO=$(free -h 2>/dev/null | awk '/^Mem:/ {print $3 " / " $2 " (" int($3/$2*100) "%)"}')
if [[ -n "${MEM_INFO}" ]]; then
    info "System memory" "${MEM_INFO}"
fi

# =============================================================================
header "Backups"
# =============================================================================

if [[ -d "${BACKUP_BASE}" ]]; then
    LATEST_BACKUP=$(find "${BACKUP_BASE}" -maxdepth 1 -mindepth 1 -type d | sort | tail -n 1)
    BACKUP_COUNT=$(find "${BACKUP_BASE}" -maxdepth 1 -mindepth 1 -type d | wc -l)

    if [[ -n "${LATEST_BACKUP}" ]]; then
        BACKUP_DATE=$(basename "${LATEST_BACKUP}")
        BACKUP_SIZE=$(du -sh "${LATEST_BACKUP}" 2>/dev/null | cut -f1)
        ok "Last backup" "${BACKUP_DATE} (${BACKUP_SIZE})"
        info "Total backups" "${BACKUP_COUNT}/7"
    else
        warn "Last backup" "None found"
    fi
else
    fail "Backups" "Directory not found"
fi

# =============================================================================
header "Data"
# =============================================================================

# Database info
if [[ -f "${DB_PATH}" ]]; then
    DB_SIZE=$(du -h "${DB_PATH}" | cut -f1)
    info "Database size" "${DB_SIZE}"

    # Last analysis date (most recent conversation entry)
    if command -v sqlite3 > /dev/null 2>&1; then
        LAST_ANALYSIS=$(sqlite3 "${DB_PATH}" "SELECT MAX(created_at) FROM conversations;" 2>/dev/null || echo "")
        if [[ -n "${LAST_ANALYSIS}" ]]; then
            info "Last analysis" "${LAST_ANALYSIS}"
        else
            warn "Last analysis" "No records found"
        fi
    else
        info "Last analysis" "(sqlite3 not available)"
    fi
else
    warn "Database" "Not found"
fi

# Vector store
if [[ -d "${VECTOR_DIR}" ]]; then
    VECTOR_SIZE=$(du -sh "${VECTOR_DIR}" 2>/dev/null | cut -f1)
    # Count vector files (approximate vector count)
    VECTOR_FILES=$(find "${VECTOR_DIR}" -type f 2>/dev/null | wc -l)
    info "Vector store" "${VECTOR_SIZE} (${VECTOR_FILES} files)"
else
    warn "Vector store" "Not found"
fi

# =============================================================================
header "Cron Jobs"
# =============================================================================

CRON_JOBS=$(crontab -l 2>/dev/null | grep -i "angelina" || true)
if [[ -n "${CRON_JOBS}" ]]; then
    while IFS= read -r line; do
        info "Scheduled" "${line}"
    done <<< "${CRON_JOBS}"
else
    warn "Cron" "No angelina cron jobs found"
fi

# =============================================================================
header "Logs"
# =============================================================================

# Recent errors from container logs
if podman container exists "${CONTAINER_NAME}" 2>/dev/null; then
    ERROR_COUNT=$(podman logs "${CONTAINER_NAME}" --since "24h" 2>&1 | grep -ci "error" || true)
    if [[ ${ERROR_COUNT} -gt 0 ]]; then
        warn "Errors (24h)" "${ERROR_COUNT} error(s) in logs"
    else
        ok "Errors (24h)" "None"
    fi
fi

# Backup log
if [[ -f "/var/log/angelina/backup.log" ]]; then
    LAST_LOG=$(tail -1 /var/log/angelina/backup.log 2>/dev/null || echo "")
    if [[ -n "${LAST_LOG}" ]]; then
        info "Last log entry" "${LAST_LOG}"
    fi
fi

# =============================================================================
echo ""
echo -e "${BOLD}──────────────────────────────────────────${NC}"
echo ""