#!/usr/bin/env bash
# ===========================================================================
# Angelina Hybrid Cloud — 2GB swap setup for the Cloud_Instance (Task 11.2)
# ===========================================================================
# REVIEWABLE ARTIFACT — STAGED ONLY. Nothing here has been applied to any VM.
# A human runs this ON the GCP Rocky Linux 9 e2-micro instance AFTER it exists
# (Task 11.1) and BEFORE deploying the app, so embedding does not OOM-kill the
# 1GB-RAM box (see design "RAM pressure").
#
# What it does (idempotent, safe to re-run):
#   * Creates a 2GB /swapfile via fallocate (falls back to dd on failure).
#   * chmod 600 /swapfile, mkswap, swapon.
#   * Persists in /etc/fstab (appends the fstab line ONLY if not present).
#   * Skips activation cleanly if swap is already on / /swapfile already exists.
#
# Requirements: 1.4 (2GB swap on the memory-constrained e2-micro).
# ===========================================================================
set -euo pipefail

SWAPFILE="/swapfile"
SWAPSIZE_MB=2048
FSTAB_LINE="${SWAPFILE} none swap sw 0 0"

echo "=== Angelina Cloud: 2GB swap setup (Rocky Linux 9) ==="

# --- Guard 1: swap already active? --------------------------------------------
if swapon --show 2>/dev/null | grep -q "${SWAPFILE}"; then
    echo "[SKIP] ${SWAPFILE} is already an active swap device."
    echo
    echo "Current swap:"
    swapon --show
    exit 0
fi

# --- Create the swap file if it does not already exist ------------------------
if [[ -e "${SWAPFILE}" ]]; then
    echo "[INFO] ${SWAPFILE} already exists; will (re)initialize and enable it."
else
    echo "[INFO] Allocating ${SWAPSIZE_MB}MB ${SWAPFILE} via fallocate..."
    if ! sudo fallocate -l "${SWAPSIZE_MB}M" "${SWAPFILE}"; then
        echo "[WARN] fallocate failed; falling back to dd (slower)..."
        sudo dd if=/dev/zero of="${SWAPFILE}" bs=1M count="${SWAPSIZE_MB}" status=progress
    fi
fi

# --- Permissions, format, enable ----------------------------------------------
echo "[INFO] Setting permissions (600)..."
sudo chmod 600 "${SWAPFILE}"

# mkswap is safe to run again; it re-writes the swap signature.
echo "[INFO] Formatting swap area (mkswap)..."
sudo mkswap "${SWAPFILE}"

echo "[INFO] Enabling swap (swapon)..."
sudo swapon "${SWAPFILE}"

# --- Persist across reboot (append fstab line only if absent) -----------------
if grep -qsE "^\s*${SWAPFILE}\s" /etc/fstab; then
    echo "[SKIP] /etc/fstab already references ${SWAPFILE}; not appending."
else
    echo "[INFO] Persisting swap in /etc/fstab..."
    echo "${FSTAB_LINE}" | sudo tee -a /etc/fstab >/dev/null
fi

echo
echo "[OK] Swap configured. Current swap:"
swapon --show
