#!/usr/bin/env bash
# ===========================================================================
# Angelina Hybrid Cloud — install the CLOUD cron jobs (Task 12.2)
# ===========================================================================
# STAGED ARTIFACT — NOT run automatically by any deploy step. A human runs
# this ON the cloud VM only after reviewing deploy/hybrid/cloud/*.
#
# What it does (idempotent, additive — same safe pattern as the local
# install-local-cron.sh):
#   * Dumps the existing crontab.
#   * Appends ONLY the cron lines that are not already present:
#       - 23:00  app.failover.run_daily_push  (failover Daily_Push)
#       - 06:00  app.sync_engine.run_sync      (bi-directional sync)
#   * Leaves every other crontab line completely untouched.
#   * Ensures /var/log/angelina exists for the logs.
#
# It intentionally does NOT:
#   * touch angelina.service
#   * remove or modify any existing crontab line
#   * write the .env (see README.md for the .env step)
#
# Safety: prints the proposed crontab diff and asks for confirmation before
# installing. Run with --dry-run to preview without changing anything.
# ===========================================================================
set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

PUSH_JOB='0 23 * * * cd /opt/angelina && /opt/angelina/venv/bin/python -c "import asyncio; from app.failover import run_daily_push; asyncio.run(run_daily_push())" >> /var/log/angelina/daily.log 2>&1'
SYNC_JOB='0 6 * * * cd /opt/angelina && /opt/angelina/venv/bin/python -c "import asyncio; from app.sync_engine import run_sync; asyncio.run(run_sync())" >> /var/log/angelina/sync.log 2>&1'

echo "=== Angelina Cloud: cron installer (failover push + sync) ==="
echo "Target crontab user: $(whoami)"
echo

# Ensure log dir exists (matches angelina.service log location).
if [[ "${DRY_RUN}" -eq 0 ]]; then
    sudo mkdir -p /var/log/angelina
    sudo chown "$(whoami):$(whoami)" /var/log/angelina 2>/dev/null || true
fi

CURRENT="$(crontab -l 2>/dev/null || true)"
NEW_CRON="${CURRENT}"

# --- Append the failover push job only if absent ------------------------------
if grep -Fq "from app.failover import run_daily_push" <<< "${NEW_CRON}"; then
    echo "[SKIP] A failover.run_daily_push cron job already exists."
else
    NEW_CRON="${NEW_CRON}"$'\n'"# Angelina Hybrid Cloud: 23:00 failover Daily_Push (Task 12.2)"$'\n'"${PUSH_JOB}"
    echo "[ADD]  23:00 failover.run_daily_push"
fi

# --- Append the sync job only if absent ---------------------------------------
if grep -Fq "from app.sync_engine import run_sync" <<< "${NEW_CRON}"; then
    echo "[SKIP] A sync_engine.run_sync cron job already exists."
else
    NEW_CRON="${NEW_CRON}"$'\n'"# Angelina Hybrid Cloud: 06:00 bi-directional sync (Task 12.2)"$'\n'"${SYNC_JOB}"
    echo "[ADD]  06:00 sync_engine.run_sync"
fi

echo

if [[ "${NEW_CRON}" == "${CURRENT}" ]]; then
    echo "[OK] Nothing to do — both cron jobs already present."
    exit 0
fi

echo "--- Proposed crontab (new lines marked with >>) ---"
diff <(printf '%s\n' "${CURRENT}") <(printf '%s\n' "${NEW_CRON}") | sed 's/^> />> /' || true
echo "---------------------------------------------------"

if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "[DRY-RUN] No changes written."
    exit 0
fi

read -r -p "Install the above cron job(s) into this crontab? [y/N] " ans
if [[ "${ans}" =~ ^[Yy]$ ]]; then
    printf '%s\n' "${NEW_CRON}" | crontab -
    echo "[OK] Installed. Verify with: crontab -l"
else
    echo "[ABORTED] No changes written."
fi
