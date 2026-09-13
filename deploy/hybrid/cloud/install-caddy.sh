#!/usr/bin/env bash
# ===========================================================================
# Angelina Hybrid Cloud — install Caddy on Rocky Linux 9 (Task 12.4)
# ===========================================================================
# STAGED ARTIFACT — NOT run automatically. A human runs this ON the cloud VM
# after reviewing deploy/hybrid/cloud/*.
#
# What it does (idempotent, safe to re-run):
#   * Installs Caddy via the documented Rocky 9 COPR method:
#       dnf install 'dnf-command(copr)'  ->  dnf copr enable @caddy/caddy
#       ->  dnf install caddy
#   * Installs the reviewed Caddyfile to /etc/caddy/Caddyfile (from the file
#     next to this script), backing up any existing one.
#   * Ensures CADDY_EMAIL is provided (env or /etc/caddy/caddy.env) so ACME
#     can issue the Let's Encrypt certificate; refuses to (re)start without it.
#   * systemctl enable --now caddy, and reloads Caddy when the config changes.
#
# Firewall (Task 11.3, handled separately): only 22/80/443 are opened; Angelina
# 8080 stays bound to 127.0.0.1.
#
# Requirements: 8.4, 8.7 (auto Let's Encrypt HTTPS reverse-proxy to :8080).
# ===========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_CADDYFILE="${SCRIPT_DIR}/Caddyfile"
DST_CADDYFILE="/etc/caddy/Caddyfile"
CADDY_ENV_FILE="/etc/caddy/caddy.env"

echo "=== Angelina Cloud: Caddy install (Rocky Linux 9) ==="

# --- Install Caddy (documented Rocky 9 COPR method) ---------------------------
if command -v caddy >/dev/null 2>&1; then
    echo "[SKIP] caddy already installed: $(caddy version 2>/dev/null | head -n1)"
else
    echo "[INFO] Enabling COPR support and installing Caddy..."
    sudo dnf install -y 'dnf-command(copr)'
    sudo dnf copr enable -y @caddy/caddy
    sudo dnf install -y caddy
fi

# --- ACME email guard ---------------------------------------------------------
# Caddy needs a contact email for Let's Encrypt. Accept it from the environment
# or from /etc/caddy/caddy.env (EnvironmentFile referenced by the caddy unit).
if [[ -z "${CADDY_EMAIL:-}" ]] && ! grep -qs '^CADDY_EMAIL=' "${CADDY_ENV_FILE}" 2>/dev/null; then
    echo "[ERROR] CADDY_EMAIL is not set."
    echo "        Set it before running, e.g.:"
    echo "          export CADDY_EMAIL='you@example.com'"
    echo "        or add it to ${CADDY_ENV_FILE}:"
    echo "          CADDY_EMAIL=you@example.com"
    echo "        (The Caddyfile reads {\$CADDY_EMAIL} for the ACME contact.)"
    exit 1
fi

# --- Install the reviewed Caddyfile -------------------------------------------
if [[ ! -f "${SRC_CADDYFILE}" ]]; then
    echo "[ERROR] Source Caddyfile not found at ${SRC_CADDYFILE}"
    exit 1
fi

sudo mkdir -p /etc/caddy

CONFIG_CHANGED=0
if [[ -f "${DST_CADDYFILE}" ]] && sudo cmp -s "${SRC_CADDYFILE}" "${DST_CADDYFILE}"; then
    echo "[SKIP] ${DST_CADDYFILE} already matches the reviewed Caddyfile."
else
    if [[ -f "${DST_CADDYFILE}" ]]; then
        BACKUP="${DST_CADDYFILE}.bak.$(date -u +%Y%m%d%H%M%S)"
        echo "[INFO] Backing up existing Caddyfile to ${BACKUP}"
        sudo cp "${DST_CADDYFILE}" "${BACKUP}"
    fi
    echo "[INFO] Installing Caddyfile to ${DST_CADDYFILE}"
    sudo cp "${SRC_CADDYFILE}" "${DST_CADDYFILE}"
    CONFIG_CHANGED=1
fi

# --- Enable + start, or reload on config change -------------------------------
if systemctl is-active --quiet caddy; then
    if [[ "${CONFIG_CHANGED}" -eq 1 ]]; then
        echo "[INFO] Config changed; reloading Caddy..."
        sudo systemctl reload caddy
    else
        echo "[SKIP] Caddy already running and config unchanged."
    fi
else
    echo "[INFO] Enabling and starting Caddy..."
    sudo systemctl enable --now caddy
fi

echo
echo "[OK] Caddy is set up. Verify with:"
echo "     systemctl status caddy"
echo "     curl -I https://YOUR_SUBDOMAIN.duckdns.org/health"
