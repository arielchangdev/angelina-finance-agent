#!/bin/bash
# ===========================================================================
# self-audit.sh - self-contained READ-ONLY security self-audit for the
# Angelina CLOUD VM. Generates a phone-friendly static HTML report at
# /opt/angelina/static/audit/index.html for Caddy to serve at /audit.
#
# Mirrors the dimensions of the Ansible security_audit role (collect + score)
# but as a standalone bash script (no ansible needed). CLOUD deployment
# context: 8080 must be loopback-only, SSH password auth is a RISK, etc.
#
# STRICTLY READ-ONLY: never patches, never changes config, never reads the
# CONTENTS of any secret file (only stat metadata). Never prints a secret.
# The HTML is written atomically (temp file + mv) so a half-written report is
# never served.
# ===========================================================================

set -u

# --- Configuration ---------------------------------------------------------
OUT_DIR="/opt/angelina/static/audit"
OUT_FILE="${OUT_DIR}/index.html"
TMP_FILE="$(mktemp "${OUT_DIR}.tmp.XXXXXX.html" 2>/dev/null || mktemp)"
FAILED_LOGIN_THRESHOLD=50
ALLOWED_PUBLIC_PORTS="22 80 443"
HOSTNAME_VAL="$(hostname 2>/dev/null || echo unknown)"
NOW_UTC="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"

# Findings accumulate into parallel arrays.
F_STATUS=(); F_DIM=(); F_TITLE=(); F_VALUE=(); F_DETAIL=()

add_finding() {
  # $1=status $2=dimension $3=title $4=value $5=detail
  F_STATUS+=("$1"); F_DIM+=("$2"); F_TITLE+=("$3"); F_VALUE+=("$4"); F_DETAIL+=("$5")
}

# --- Ensure output dir exists ----------------------------------------------
mkdir -p "$OUT_DIR" 2>/dev/null

# ===========================================================================
# 1. Listening TCP ports (ss -Htlnp) - READ-ONLY
# ===========================================================================
SS_OUT="$(ss -Htlnp 2>/dev/null || true)"
# Column 4 = local Address:Port. Detect 8080 binding and public non-standard.
has_public_8080=0
has_localhost_8080=0
public_extra=""
while IFS= read -r line; do
  [ -z "$line" ] && continue
  local_addr="$(echo "$line" | awk '{print $4}')"
  [ -z "$local_addr" ] && continue
  port="${local_addr##*:}"
  addr="${local_addr%:*}"
  case "$addr" in
    0.0.0.0|"*"|"[::]"|"::")
      if [ "$port" = "8080" ]; then has_public_8080=1; fi
      is_allowed=0
      for ap in $ALLOWED_PUBLIC_PORTS; do [ "$port" = "$ap" ] && is_allowed=1; done
      if [ "$is_allowed" = "0" ] && [ "$port" != "8080" ]; then
        case " $public_extra " in *" $port "*) : ;; *) public_extra="$public_extra $port" ;; esac
      fi
      ;;
    127.0.0.1|"[::1]"|"::1")
      if [ "$port" = "8080" ]; then has_localhost_8080=1; fi
      ;;
  esac
done <<< "$SS_OUT"

if [ "$has_public_8080" = "1" ]; then
  add_finding "RISK" "Listening ports" "Angelina app port 8080 binding" "8080 bound to a public address" \
    "On the cloud VM 8080 must be bound to 127.0.0.1 behind Caddy; a public 8080 exposes the app directly."
elif [ "$has_localhost_8080" = "1" ]; then
  add_finding "OK" "Listening ports" "Angelina app port 8080 binding" "8080 bound to 127.0.0.1" \
    "Cloud app correctly bound to localhost behind Caddy."
else
  add_finding "INFO" "Listening ports" "Angelina app port 8080 binding" "8080 not detected as listening" \
    "No 8080 listener seen in ss output; the app may bind elsewhere or was not listening at scan time."
fi

public_extra="$(echo "$public_extra" | xargs 2>/dev/null || echo "")"
if [ -n "$public_extra" ]; then
  add_finding "RISK" "Listening ports" "Public-bound non-standard ports" "Public ports (excl. 22/80/443/8080): ${public_extra// /, }" \
    "Ports bound to a public address other than the expected 22/80/443. Review whether they should be firewalled or bound to localhost."
else
  add_finding "OK" "Listening ports" "Public-bound non-standard ports" "Only expected ports public (22/80/443)" \
    "No unexpected public-bound listeners detected."
fi

# ===========================================================================
# 2. SSH hardening (sshd -T effective config) - READ-ONLY
# ===========================================================================
SSHD_OUT="$(sudo -n sshd -T 2>/dev/null | grep -iE '^(passwordauthentication|permitrootlogin|pubkeyauthentication|kbdinteractiveauthentication) ' || sshd -T 2>/dev/null | grep -iE '^(passwordauthentication|permitrootlogin|pubkeyauthentication|kbdinteractiveauthentication) ' || true)"
SSHD_LC="$(echo "$SSHD_OUT" | tr '[:upper:]' '[:lower:]')"
ssh_pwauth="$(echo "$SSHD_LC" | grep -E '^passwordauthentication ' | awk '{print $2}')"
ssh_root="$(echo "$SSHD_LC" | grep -E '^permitrootlogin ' | awk '{print $2}')"
ssh_pubkey="$(echo "$SSHD_LC" | grep -E '^pubkeyauthentication ' | awk '{print $2}')"
[ -z "$ssh_pwauth" ] && ssh_pwauth="unknown"
[ -z "$ssh_root" ] && ssh_root="unknown"
[ -z "$ssh_pubkey" ] && ssh_pubkey="unknown"

if [ "$ssh_pwauth" = "no" ]; then
  add_finding "OK" "SSH hardening" "SSH password authentication" "passwordauthentication=no" \
    "Password auth disabled; key-based auth only."
elif [ "$ssh_pwauth" = "yes" ]; then
  add_finding "RISK" "SSH hardening" "SSH password authentication" "passwordauthentication=yes" \
    "The internet-facing cloud VM allows SSH password auth - should be key-only."
else
  add_finding "WARN" "SSH hardening" "SSH password authentication" "passwordauthentication=unknown" \
    "Could not determine PasswordAuthentication from sshd -T."
fi

if [ "$ssh_root" = "yes" ]; then
  add_finding "RISK" "SSH hardening" "SSH root login (PermitRootLogin)" "permitrootlogin=yes" \
    "Direct root SSH login is enabled - should be no or prohibit-password."
elif [ "$ssh_root" = "unknown" ]; then
  add_finding "WARN" "SSH hardening" "SSH root login (PermitRootLogin)" "permitrootlogin=unknown" \
    "Could not determine PermitRootLogin from sshd -T."
else
  add_finding "OK" "SSH hardening" "SSH root login (PermitRootLogin)" "permitrootlogin=${ssh_root}" \
    "Direct root SSH login is not fully open."
fi

if [ "$ssh_pubkey" = "yes" ]; then
  add_finding "OK" "SSH hardening" "SSH public-key authentication" "pubkeyauthentication=yes" \
    "Key-based auth enabled."
else
  add_finding "WARN" "SSH hardening" "SSH public-key authentication" "pubkeyauthentication=${ssh_pubkey}" \
    "Public-key auth appears disabled or undetermined."
fi

# ===========================================================================
# 3. SELinux (getenforce) - READ-ONLY
# ===========================================================================
SE="$(getenforce 2>/dev/null | tr '[:upper:]' '[:lower:]' | xargs 2>/dev/null || echo unknown)"
case "$SE" in
  enforcing) add_finding "OK" "SELinux" "SELinux enforcement mode" "enforcing" "SELinux is enforcing." ;;
  permissive) add_finding "WARN" "SELinux" "SELinux enforcement mode" "permissive" "SELinux logs but does not block - enable enforcing." ;;
  disabled) add_finding "RISK" "SELinux" "SELinux enforcement mode" "disabled" "SELinux is disabled - no mandatory access control." ;;
  *) add_finding "WARN" "SELinux" "SELinux enforcement mode" "${SE:-unknown}" "Could not read SELinux mode." ;;
esac

# ===========================================================================
# 4. firewalld (state + list-all) - READ-ONLY (sudo, passwordless)
# ===========================================================================
FW_STATE="$(sudo -n firewall-cmd --state 2>/dev/null | xargs 2>/dev/null || echo notrunning)"
if [ "$FW_STATE" = "running" ]; then
  FW_LISTALL="$(sudo -n firewall-cmd --list-all 2>/dev/null || true)"
  FW_ZONE="$(echo "$FW_LISTALL" | grep -E '^[^ ].*\(' | head -1 | awk '{print $1}')"
  FW_SERVICES="$(echo "$FW_LISTALL" | grep -E '^\s*services:' | sed 's/^\s*services:\s*//')"
  FW_PORTS="$(echo "$FW_LISTALL" | grep -E '^\s*ports:' | sed 's/^\s*ports:\s*//')"
  [ -z "$FW_SERVICES" ] && FW_SERVICES="(none)"
  [ -z "$FW_PORTS" ] && FW_PORTS="(none)"
  add_finding "OK" "firewalld" "Host firewall (firewalld)" "running (zone: ${FW_ZONE:-default})" \
    "Open services: ${FW_SERVICES} | Open ports: ${FW_PORTS}"
else
  add_finding "INFO" "firewalld" "Host firewall (firewalld)" "not running" \
    "firewalld not running; the cloud VM also relies on the cloud network firewall (VPC rules) for perimeter control."
fi

# ===========================================================================
# 5. Pending security updates (dnf, cached only, timeout) - READ-ONLY
# ===========================================================================
UPD_RAW="$(timeout 45 dnf -q --cacheonly updateinfo list security 2>/dev/null || true)"
UPD_COUNT="$(echo "$UPD_RAW" | grep -iE '(sec|security|important|moderate|critical|low)' | grep -viE 'updateinfo|summary|last metadata|available|^security:? *$' | grep -c . 2>/dev/null || echo 0)"
UPD_COUNT="$(echo "$UPD_COUNT" | xargs 2>/dev/null || echo 0)"
if [ -z "$(echo "$UPD_RAW" | xargs 2>/dev/null)" ]; then
  add_finding "INFO" "Patch level" "Pending security updates" "no cached updateinfo available" \
    "dnf security metadata was not available from cache within the timeout; run a manual dnf check-update out of band."
elif [ "${UPD_COUNT:-0}" -gt 0 ] 2>/dev/null; then
  add_finding "WARN" "Patch level" "Pending security updates" "${UPD_COUNT} security-related advisory line(s)" \
    "Pending security updates detected. Schedule patching out of band (this audit does not patch)."
else
  add_finding "OK" "Patch level" "Pending security updates" "0 pending security updates" \
    "No pending security advisories found in cached metadata."
fi

# ===========================================================================
# 6. Sensitive file permissions (METADATA ONLY - never read contents)
# ===========================================================================
score_file() {
  # $1=path
  local path="$1"
  if [ ! -e "$path" ]; then
    add_finding "WARN" "Sensitive files" "Permissions of ${path}" "missing" \
      "${path} does not exist on this host. Expected if the feature is unused; otherwise investigate."
    return
  fi
  local mode owner group
  mode="$(stat -c '%a' "$path" 2>/dev/null)"
  owner="$(stat -c '%U' "$path" 2>/dev/null)"
  group="$(stat -c '%G' "$path" 2>/dev/null)"
  # Normalise mode to 4 digits for group/other digit checks.
  local mode4="$mode"
  while [ "${#mode4}" -lt 4 ]; do mode4="0${mode4}"; done
  local gdig="${mode4:2:1}" odig="${mode4:3:1}"
  local group_readable=0 world_readable=0
  case "$gdig" in 4|5|6|7) group_readable=1 ;; esac
  case "$odig" in 4|5|6|7) world_readable=1 ;; esac
  if [ "$world_readable" = "1" ] || [ "$group_readable" = "1" ]; then
    add_finding "RISK" "Sensitive files" "Permissions of ${path}" "mode ${mode} owner ${owner}:${group}" \
      "${path} is group/world readable. Secrets must be 0600. Tighten to owner-only (chmod 600, chown angelina)."
  elif [ "$gdig" = "0" ] && [ "$odig" = "0" ] && [ "$owner" = "angelina" ]; then
    add_finding "OK" "Sensitive files" "Permissions of ${path}" "mode ${mode} owner ${owner}:${group}" \
      "Permissions are owner-only (group/world = 0) and owned by angelina, as expected. Contents were NOT read."
  elif [ "$owner" != "angelina" ]; then
    add_finding "WARN" "Sensitive files" "Permissions of ${path}" "mode ${mode} owner ${owner}:${group}" \
      "Not group/world readable, but owner is ${owner} (expected angelina). Verify ownership."
  else
    add_finding "OK" "Sensitive files" "Permissions of ${path}" "mode ${mode} owner ${owner}:${group}" \
      "Not group/world readable. Contents were NOT read."
  fi
}
score_file "/opt/angelina/.env"
score_file "/opt/angelina/config/service-account.json"

# ===========================================================================
# 7. Cron entries (surface only, INFO) - READ-ONLY
# ===========================================================================
CRON_A="$(crontab -l -u angelina 2>/dev/null || true)"
CRON_A_COUNT="$(echo "$CRON_A" | grep -vE '^\s*#' | grep -vE '^\s*$' | grep -c . 2>/dev/null || echo 0)"
CRON_A_COUNT="$(echo "$CRON_A_COUNT" | xargs 2>/dev/null || echo 0)"
add_finding "INFO" "Cron" "Scheduled jobs (operator review)" "${CRON_A_COUNT} angelina cron entries" \
  "Surfaced for manual review; not auto-flagged."

# ===========================================================================
# 8. Failed SSH logins (last 7 days) - READ-ONLY
# ===========================================================================
FAILS="$(sudo -n journalctl -u sshd --since '7 days ago' --no-pager 2>/dev/null | grep -Ec 'Failed password|authentication failure' 2>/dev/null || journalctl -u sshd --since '7 days ago' --no-pager 2>/dev/null | grep -Ec 'Failed password|authentication failure' 2>/dev/null || echo 0)"
FAILS="$(echo "$FAILS" | xargs 2>/dev/null || echo 0)"
if [ "${FAILS:-0}" -gt "$FAILED_LOGIN_THRESHOLD" ] 2>/dev/null; then
  add_finding "WARN" "Auth logs" "Failed SSH logins (last 7 days)" "${FAILS} failed attempts" \
    "Above the ${FAILED_LOGIN_THRESHOLD} threshold - likely brute-force noise. Consider fail2ban/key-only auth if not already."
else
  add_finding "OK" "Auth logs" "Failed SSH logins (last 7 days)" "${FAILS} failed attempts" \
    "Below the ${FAILED_LOGIN_THRESHOLD} threshold."
fi

# ===========================================================================
# 9. Angelina service state - READ-ONLY
# ===========================================================================
SVC_ACTIVE="$(systemctl is-active angelina.service 2>/dev/null | xargs 2>/dev/null || echo unknown)"
SVC_ENABLED="$(systemctl is-enabled angelina.service 2>/dev/null | xargs 2>/dev/null || echo unknown)"
if [ "$SVC_ACTIVE" = "active" ] && [ "$SVC_ENABLED" = "enabled" ]; then
  add_finding "OK" "Application service" "angelina.service state" "active + enabled" \
    "Service is running and enabled at boot."
elif [ "$SVC_ACTIVE" = "active" ]; then
  add_finding "WARN" "Application service" "angelina.service state" "active but ${SVC_ENABLED}" \
    "Service running but not enabled at boot - it will not survive a reboot."
else
  add_finding "RISK" "Application service" "angelina.service state" "${SVC_ACTIVE} / ${SVC_ENABLED}" \
    "Angelina application service is not active."
fi

# ===========================================================================
# 10. Context: timezone + uptime (INFO) - READ-ONLY
# ===========================================================================
TZ_VAL="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo unknown)"
TZ_VAL="$(echo "$TZ_VAL" | xargs 2>/dev/null || echo unknown)"
UP_VAL="$(uptime -p 2>/dev/null | xargs 2>/dev/null || echo unknown)"
add_finding "INFO" "Context" "Timezone" "${TZ_VAL:-unknown}" "Host timezone (informational)."
add_finding "INFO" "Context" "Uptime" "${UP_VAL:-unknown}" "Host uptime (informational)."

# ===========================================================================
# Summary counts
# ===========================================================================
c_risk=0; c_warn=0; c_ok=0; c_info=0
for s in "${F_STATUS[@]}"; do
  case "$s" in
    RISK) c_risk=$((c_risk+1)) ;;
    WARN) c_warn=$((c_warn+1)) ;;
    OK)   c_ok=$((c_ok+1)) ;;
    INFO) c_info=$((c_info+1)) ;;
  esac
done

# ===========================================================================
# HTML escaping helper
# ===========================================================================
html_escape() {
  local s="$1"
  s="${s//&/&amp;}"
  s="${s//</&lt;}"
  s="${s//>/&gt;}"
  s="${s//\"/&quot;}"
  printf '%s' "$s"
}

status_emoji() {
  case "$1" in
    RISK) printf '\xF0\x9F\x94\xB4' ;;   # red circle
    WARN) printf '\xF0\x9F\x9F\xA1' ;;   # yellow circle
    OK)   printf '\xF0\x9F\x9F\xA2' ;;   # green circle
    INFO) printf '\xF0\x9F\x94\xB5' ;;   # blue circle
    *)    printf '\xE2\x9A\xAA' ;;
  esac
}

# ===========================================================================
# Write HTML atomically (temp then mv)
# ===========================================================================
{
cat <<HTMLHEAD
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Angelina Cloud - Security Audit</title>
<style>
  :root { --bg:#0f1419; --card:#1a2129; --muted:#8b97a5; --fg:#e6edf3; --border:#2a333d;
          --risk:#f85149; --warn:#e3b341; --ok:#3fb950; --info:#58a6ff; }
  * { box-sizing:border-box; }
  body { margin:0; padding:16px; background:var(--bg); color:var(--fg);
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
         line-height:1.5; -webkit-text-size-adjust:100%; }
  .wrap { max-width:760px; margin:0 auto; }
  h1 { font-size:1.35rem; margin:0 0 4px; }
  .meta { color:var(--muted); font-size:0.85rem; margin-bottom:16px; word-break:break-all; }
  .summary { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:20px; }
  .pill { flex:1 1 auto; min-width:70px; text-align:center; padding:12px 8px; border-radius:12px;
          font-weight:600; border:1px solid var(--border); background:var(--card); }
  .pill .n { display:block; font-size:1.5rem; line-height:1.2; }
  .pill .l { font-size:0.72rem; letter-spacing:0.06em; text-transform:uppercase; color:var(--muted); }
  .pill.risk .n { color:var(--risk); }
  .pill.warn .n { color:var(--warn); }
  .pill.ok .n   { color:var(--ok); }
  .pill.info .n { color:var(--info); }
  .card { background:var(--card); border:1px solid var(--border); border-left-width:4px;
          border-radius:12px; padding:12px 14px; margin-bottom:10px; }
  .card.risk { border-left-color:var(--risk); }
  .card.warn { border-left-color:var(--warn); }
  .card.ok   { border-left-color:var(--ok); }
  .card.info { border-left-color:var(--info); }
  .card .top { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
  .card .emoji { font-size:1.05rem; }
  .card .title { font-weight:600; }
  .card .badge { margin-left:auto; font-size:0.68rem; font-weight:700; letter-spacing:0.05em;
                 padding:2px 8px; border-radius:999px; }
  .card.risk .badge { background:rgba(248,81,73,0.15); color:var(--risk); }
  .card.warn .badge { background:rgba(227,179,65,0.15); color:var(--warn); }
  .card.ok   .badge { background:rgba(63,185,80,0.15); color:var(--ok); }
  .card.info .badge { background:rgba(88,166,255,0.15); color:var(--info); }
  .card .dim { color:var(--muted); font-size:0.75rem; margin-top:2px; }
  .card .value { margin-top:6px; font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
                 font-size:0.85rem; word-break:break-word; }
  .card .detail { color:var(--muted); font-size:0.82rem; margin-top:4px; }
  footer { color:var(--muted); font-size:0.75rem; margin-top:20px; text-align:center; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Angelina Cloud - Security Audit</h1>
  <div class="meta">Host: $(html_escape "$HOSTNAME_VAL") &middot; Last updated: $(html_escape "$NOW_UTC") &middot; Read-only self-audit</div>
  <div class="summary">
    <div class="pill risk"><span class="n">${c_risk}</span><span class="l">Risk</span></div>
    <div class="pill warn"><span class="n">${c_warn}</span><span class="l">Warn</span></div>
    <div class="pill ok"><span class="n">${c_ok}</span><span class="l">OK</span></div>
    <div class="pill info"><span class="n">${c_info}</span><span class="l">Info</span></div>
  </div>
HTMLHEAD

i=0
n="${#F_STATUS[@]}"
while [ "$i" -lt "$n" ]; do
  st="${F_STATUS[$i]}"
  cls="$(echo "$st" | tr '[:upper:]' '[:lower:]')"
  emoji="$(status_emoji "$st")"
  cat <<HTMLCARD
  <div class="card ${cls}">
    <div class="top">
      <span class="emoji">${emoji}</span>
      <span class="title">$(html_escape "${F_TITLE[$i]}")</span>
      <span class="badge">${st}</span>
    </div>
    <div class="dim">$(html_escape "${F_DIM[$i]}")</div>
    <div class="value">$(html_escape "${F_VALUE[$i]}")</div>
    <div class="detail">$(html_escape "${F_DETAIL[$i]}")</div>
  </div>
HTMLCARD
  i=$((i+1))
done

cat <<HTMLFOOT
  <footer>Generated by self-audit.sh &middot; READ-ONLY &middot; no secret values are collected or displayed. Regenerated weekly.</footer>
</div>
</body>
</html>
HTMLFOOT
} > "$TMP_FILE"

# Atomic replace + sane perms (world-readable so Caddy can serve it).
chmod 644 "$TMP_FILE" 2>/dev/null
mv -f "$TMP_FILE" "$OUT_FILE"

# Restore SELinux context if applicable so Caddy (file_server) can read it.
command -v restorecon >/dev/null 2>&1 && restorecon "$OUT_FILE" 2>/dev/null || true

echo "self-audit complete: ${c_risk} RISK, ${c_warn} WARN, ${c_ok} OK, ${c_info} INFO -> ${OUT_FILE}"
