#!/usr/bin/env bash
# ===========================================================================
# Angelina Hybrid Cloud — set the Cloud_Instance timezone to Asia/Taipei
# ===========================================================================
# STAGED ARTIFACT — run ON the GCP Rocky Linux 9 e2-micro instance during
# provisioning (any time after the VM exists).
#
# Why: GCP VMs default to UTC. The failover cron uses "0 23 * * *", which on a
# UTC box fires at Taiwan 07:00 (UTC+8). Setting the system timezone to
# Asia/Taipei makes the cron line "0 23" fire at Taiwan 23:00 — matching the
# local instance and Angelina's report timezone (TW_TZ) — and makes all logs
# read in Taiwan time.
#
# Idempotent: safe to re-run; skips if already Asia/Taipei. Restarts crond so
# the scheduler picks up the new timezone immediately.
# ===========================================================================
set -euo pipefail

TARGET_TZ="Asia/Taipei"

CURRENT_TZ="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo unknown)"
echo "=== Angelina Cloud: timezone setup ==="
echo "[INFO] Current timezone: ${CURRENT_TZ}"

if [[ "${CURRENT_TZ}" == "${TARGET_TZ}" ]]; then
    echo "[SKIP] Timezone already ${TARGET_TZ}."
else
    echo "[INFO] Setting timezone to ${TARGET_TZ}..."
    sudo timedatectl set-timezone "${TARGET_TZ}"
    echo "[INFO] Restarting crond so scheduled jobs use the new timezone..."
    sudo systemctl restart crond
fi

echo
echo "[OK] Timezone now:"
timedatectl | grep -i "time zone" || date
echo "[OK] The failover cron (0 23 * * *) will fire at Taiwan 23:00."