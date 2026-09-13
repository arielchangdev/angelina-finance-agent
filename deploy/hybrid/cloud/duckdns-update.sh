#!/usr/bin/env bash
# ===========================================================================
# Angelina Hybrid Cloud — DuckDNS A-record updater (Task 12.3)
# ===========================================================================
# STAGED ARTIFACT — not applied to any VM. A human installs this on the cloud
# VM (e.g. at /opt/angelina/deploy/duckdns-update.sh) and schedules it via
# duckdns-cron so the ephemeral GCP public IP always points at the DuckDNS
# name YOUR_SUBDOMAIN.duckdns.org (Req 8.4).
#
# Behavior:
#   * Reads DUCKDNS_TOKEN from /opt/angelina/.env (never hardcoded, never
#     printed).
#   * Calls the DuckDNS update URL with domain label "YOUR_DUCKDNS_SUBDOMAIN" and an
#     EMPTY ip= so DuckDNS auto-detects the caller's public IP — exactly what
#     we want so it picks up the VM's current ephemeral IP.
#   * Appends the result to /var/log/angelina/duckdns.log and echoes OK/KO.
#
# The token is passed to curl via --data-urlencode (from a variable) so it is
# never placed on the command line / process list and is never echoed.
# ===========================================================================
set -euo pipefail

ENV_FILE="/opt/angelina/.env"
DOMAIN_LABEL="YOUR_DUCKDNS_SUBDOMAIN"
LOG_DIR="/var/log/angelina"
LOG_FILE="${LOG_DIR}/duckdns.log"

mkdir -p "${LOG_DIR}" 2>/dev/null || true

TS="$(date -u +%Y-%m-%dT%H:%M:%S%z)"

if [[ ! -r "${ENV_FILE}" ]]; then
    echo "${TS} KO cannot read ${ENV_FILE}" >> "${LOG_FILE}"
    echo "KO"
    exit 1
fi

# Extract only the DUCKDNS_TOKEN value from .env without sourcing the whole
# file (safer than `source`; avoids executing arbitrary env contents). Strips
# an optional surrounding quote pair.
DUCKDNS_TOKEN="$(grep -E '^[[:space:]]*DUCKDNS_TOKEN=' "${ENV_FILE}" | tail -n1 | cut -d= -f2- | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/")"

if [[ -z "${DUCKDNS_TOKEN}" ]]; then
    echo "${TS} KO DUCKDNS_TOKEN not set in ${ENV_FILE}" >> "${LOG_FILE}"
    echo "KO"
    exit 1
fi

# ip= is intentionally blank: DuckDNS auto-detects the caller's public IP.
# --data-urlencode keeps the token off the argv/process list.
RESPONSE="$(curl -s -G "https://www.duckdns.org/update" \
    --data-urlencode "domains=${DOMAIN_LABEL}" \
    --data-urlencode "token=${DUCKDNS_TOKEN}" \
    --data-urlencode "ip=" || true)"

# DuckDNS returns the literal text "OK" or "KO" (never contains the token).
if [[ "${RESPONSE}" == "OK" ]]; then
    echo "${TS} OK duckdns update for ${DOMAIN_LABEL}" >> "${LOG_FILE}"
    echo "OK"
    exit 0
else
    echo "${TS} KO duckdns response='${RESPONSE:-<empty>}' for ${DOMAIN_LABEL}" >> "${LOG_FILE}"
    echo "KO"
    exit 1
fi
