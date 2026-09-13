#!/usr/bin/env bash
# ===========================================================================
# Angelina Hybrid Cloud — install the LOCAL 06:00 sync cron (Task 9.1)
# ===========================================================================
# REVIEWABLE ARTIFACT — this script is NOT run automatically by any deploy
# step. A human runs it ON THE VM only after reviewing deploy/hybrid/*.
#
# What it does (idempotent, additive):
#   * Appends the single 06:00 sync job from angelina-hybrid.cron into the
#     angelina user's crontab, IF that exact job is not already present.
#   * Leaves every other crontab line (including the existing 23:00 push)
#     completely untouched.
#   * Ensures /var/log/angelina exists for the sync log.
#
# It intentionally does NOT:
#   * touch angelina.service
#   * modify or remove the existing 23:00 Daily_Push cron line
#   * write the .env (see APPLY_PLAN.md for the .env step)
#
# Safety: prints the resulting crontab and asks for confirmation before
# installing. Run with --dry-run to preview without changing anything.
# ===========================================================================
set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

SYNC_JOB='0 6 * * * cd /opt/angelina && /opt/angelina/venv/bin/python -c "import asyncio; from app.sync_engine import run_sync; asyncio.run(run_sync())" >> /var/log/angelina/sync.log 2>&1'

echo "=== Angelina Hybrid: local 06:00 sync cron installer ==="
echo "Target crontab user: $(whoami)"
echo

# Ensure log dir exists (matches angelina.service log location).
if [[ "${DRY_RUN}" -eq 0 ]]; then
    sudo mkdir -p /var/log/angelina
    sudo chown "$(whoami):$(whoami)" /var/log/angelina 2>/dev/null || true
fi

CURRENT="$(crontab -l 2>/dev/null || true)"

if grep -Fq "from app.sync_engine import run_sync" <<< "${CURRENT}"; then
    echo "[SKIP] A sync_engine.run_sync cron job already exists. No change made."
    echo
    echo "Current angelina cron lines:"
    grep -i "angelina\|sync_engine\|daily" <<< "${CURRENT}" || true
    exit 0
fi

NEW_CRON="${CURRENT}"$'\n'"# Angelina Hybrid Cloud: 06:00 daily bi-directional sync (Task 9.1)"$'\n'"${SYNC_JOB}"

echo "--- Proposed crontab (new lines marked with >>) ---"
diff <(printf '%s\n' "${CURRENT}") <(printf '%s\n' "${NEW_CRON}") | sed 's/^> />> /' || true
echo "----------------------------------------------------"

if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "[DRY-RUN] No changes written."
    exit 0
fi

read -r -p "Install the 06:00 sync job into this crontab? [y/N] " ans
if [[ "${ans}" =~ ^[Yy]$ ]]; then
    printf '%s\n' "${NEW_CRON}" | crontab -
    echo "[OK] Installed. Verify with: crontab -l"
else
    echo "[ABORTED] No changes written."
fi
