#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Angelina Finance Agent - Update/Redeploy Script
# =============================================================================
# Rebuilds and redeploys the container with zero-downtime approach:
#   1. Stop current container
#   2. Rebuild image from latest code
#   3. Remove old container
#   4. Create new container with same configuration
#   5. Verify health
#
# Usage:
#   ./deploy/update.sh
# =============================================================================

# --- Configuration ---
APP_DIR="/opt/angelina"
CONTAINER_NAME="angelina-app"
IMAGE_NAME="angelina"
IMAGE_TAG="latest"
HEALTH_URL="http://localhost:8080/health"
HEALTH_TIMEOUT=60
ENV_FILE="${APP_DIR}/.env"
CONTAINERFILE="${APP_DIR}/Containerfile"

# --- Volumes ---
# Persistent data volumes mounted into the container
VOLUME_MOUNTS=(
    "${APP_DIR}/data:/app/data:Z"
    "${APP_DIR}/config:/app/config:Z"
    "${APP_DIR}/logs:/app/logs:Z"
)

# --- Ports ---
PORT_MAPPING="8080:8080"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# --- Functions ---
success() { echo -e "${GREEN}✓ $1${NC}"; }
error()   { echo -e "${RED}✗ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠ $1${NC}"; }
info()    { echo -e "${BLUE}→ $1${NC}"; }

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

rollback() {
    error "Update failed! Attempting rollback..."

    # Try to start the old container if it still exists
    if podman container exists "${CONTAINER_NAME}" 2>/dev/null; then
        podman start "${CONTAINER_NAME}" > /dev/null 2>&1 && \
            warning "Rolled back to previous container" || \
            error "Rollback failed - manual intervention required"
    else
        error "Old container removed - manual intervention required"
        error "Try: podman run with the previous image"
    fi

    exit 1
}

# --- Pre-flight checks ---
echo ""
echo "============================================"
echo "  Angelina Update/Redeploy"
echo "============================================"
echo ""

# Check Containerfile exists
if [[ ! -f "${CONTAINERFILE}" ]]; then
    error "Containerfile not found: ${CONTAINERFILE}"
    exit 1
fi

# Check env file exists
if [[ ! -f "${ENV_FILE}" ]]; then
    error "Environment file not found: ${ENV_FILE}"
    exit 1
fi

success "Pre-flight checks passed"
echo ""

# --- Step 1: Stop current container ---
info "Step 1: Stopping current container..."
if podman container exists "${CONTAINER_NAME}" 2>/dev/null; then
    if podman stop "${CONTAINER_NAME}" > /dev/null 2>&1; then
        success "Container stopped"
    else
        warning "Container was already stopped"
    fi
else
    warning "No existing container found (first deploy?)"
fi

# --- Step 2: Rebuild container image ---
info "Step 2: Building new image..."
echo ""

BUILD_START=$(date +%s)
if podman build \
    -t "${IMAGE_NAME}:${IMAGE_TAG}" \
    -f "${CONTAINERFILE}" \
    "${APP_DIR}"; then
    BUILD_END=$(date +%s)
    BUILD_DURATION=$((BUILD_END - BUILD_START))
    echo ""
    success "Image built in ${BUILD_DURATION}s: ${IMAGE_NAME}:${IMAGE_TAG}"
else
    echo ""
    error "Image build failed!"
    # Try to restart old container
    if podman container exists "${CONTAINER_NAME}" 2>/dev/null; then
        podman start "${CONTAINER_NAME}" > /dev/null 2>&1
        warning "Restarted old container"
    fi
    exit 1
fi

# --- Step 3: Remove old container ---
info "Step 3: Removing old container..."
if podman container exists "${CONTAINER_NAME}" 2>/dev/null; then
    podman rm "${CONTAINER_NAME}" > /dev/null 2>&1
    success "Old container removed"
else
    success "No old container to remove"
fi

# --- Step 4: Create new container ---
info "Step 4: Creating new container..."

# Build volume mount arguments
VOLUME_ARGS=()
for vol in "${VOLUME_MOUNTS[@]}"; do
    VOLUME_ARGS+=("-v" "${vol}")
done

if podman run -d \
    --name "${CONTAINER_NAME}" \
    --env-file "${ENV_FILE}" \
    -p "${PORT_MAPPING}" \
    "${VOLUME_ARGS[@]}" \
    --restart unless-stopped \
    "${IMAGE_NAME}:${IMAGE_TAG}"; then
    success "New container created and started"
else
    error "Failed to create new container!"
    rollback
fi

# --- Step 5: Verify health ---
info "Step 5: Verifying health (timeout: ${HEALTH_TIMEOUT}s)..."
if wait_for_health; then
    success "Health check passed"
else
    error "Health check failed after ${HEALTH_TIMEOUT}s!"
    warning "Check logs: podman logs ${CONTAINER_NAME}"
    warning "Consider rolling back: podman stop ${CONTAINER_NAME} && restore from backup"
    exit 1
fi

# --- Cleanup old images ---
info "Cleaning up dangling images..."
CLEANED=$(podman image prune -f 2>/dev/null | wc -l)
if [[ ${CLEANED} -gt 0 ]]; then
    success "Removed ${CLEANED} dangling image(s)"
else
    success "No dangling images to clean"
fi

# --- Summary ---
echo ""
echo "============================================"
echo "  Update Complete"
echo "============================================"
echo ""
success "Image: ${IMAGE_NAME}:${IMAGE_TAG}"
success "Container: ${CONTAINER_NAME}"
success "Health: OK"
success "Build time: ${BUILD_DURATION}s"
echo ""

# Show container info
info "Container details:"
podman ps --filter "name=${CONTAINER_NAME}" --format "  ID: {{.ID}}\n  Status: {{.Status}}\n  Ports: {{.Ports}}"
echo ""