# Angelina Hybrid Cloud — Cloud_Instance apply runbook

**Spec:** angelina-hybrid-cloud · **Covers Tasks:** 11.2, 12.2, 12.3, 12.4

**Status: STAGED ARTIFACTS ONLY.** Nothing in this directory has been applied
to any machine. No VM was touched (not the local VM `YOUR_LOCAL_VM_IP`, not the
controller `YOUR_ANSIBLE_VM_IP`), nothing was provisioned on GCP, and no
`gcloud`/`ansible` ran against live infra. Every file here is a reviewable
artifact on the workstation. A human runs them **on the cloud VM** after it
exists (Task 11.1) and after the operator prerequisites are met.

These artifacts are **pending prerequisites**: GCP account + billing (P-A/P-B),
the DuckDNS token (P-C), the SSH key + budget notification email (P-D), and the
app secrets (P-E), plus the VM itself (Task 11.1).

---

## Files in this directory

| File | Task | Purpose |
|---|---|---|
| `setup-swap.sh` | 11.2 | Idempotent 2GB `/swapfile` (fallocate→dd fallback), `mkswap`, `swapon`, persist in `/etc/fstab`. |
| `setup-timezone.sh` | — | Set the VM timezone to `Asia/Taipei` so the failover `0 23` cron fires at Taiwan 23:00 (GCP defaults to UTC). Idempotent; restarts crond. |
| `angelina-cloud.service` | 12.2 | systemd unit mirroring local, but `ExecStart` binds uvicorn to **127.0.0.1** (never public). |
| `cloud-crontab` | 12.2 | Cron fragment: 23:00 `failover.run_daily_push`, 06:00 `sync_engine.run_sync`. |
| `install-cloud-cron.sh` | 12.2 | Idempotent, confirmation-gated cron installer (appends only missing lines). |
| `duckdns-update.sh` | 12.3 | Reads `DUCKDNS_TOKEN` from `.env`, updates `YOUR_SUBDOMAIN.duckdns.org` (auto IP), logs OK/KO. |
| `duckdns-cron` | 12.3 | Cron fragment: every 5 min + `@reboot`. |
| `Caddyfile` | 12.4 | HTTPS (auto Let's Encrypt) reverse-proxy for the DuckDNS name → `127.0.0.1:8080`. |
| `install-caddy.sh` | 12.4 | Idempotent Caddy install (Rocky 9 COPR), installs the Caddyfile, enable/reload. |

---

## Values the operator must supply

Placed in `/opt/angelina/.env` (outside version control) unless noted:

| Value | Where | Used by |
|---|---|---|
| `DUCKDNS_TOKEN` | `/opt/angelina/.env` | `duckdns-update.sh` (never printed/hardcoded). |
| `ANGELINA_ACCESS_TOKEN` | `/opt/angelina/.env` | Cloud auth; the app refuses to start in cloud role if unset. |
| `CADDY_EMAIL` | env or `/etc/caddy/caddy.env` | Caddy ACME contact for Let's Encrypt (`{$CADDY_EMAIL}` in the Caddyfile). |

Also required in the cloud `.env` (from Task 12.1 / prereq P-E):
`INSTANCE_ROLE=cloud`, `INSTANCE_ID=cloud`, `ANGELINA_SYNC_FOLDER_ID`, the
Gemini API key, and the Telegram Bot token. **`INSTANCE_ROLE` is `cloud` on
this VM — never `local`.**

---

## Apply order (run by a human, on the cloud VM, after review)

> Prereq: the VM exists (Task 11.1), you can SSH in as `angelina`, and you have
> reviewed every file above.

1. **Set timezone** (so the failover `0 23` cron fires at Taiwan 23:00, not UTC 23:00):
   ```bash
   bash setup-timezone.sh
   date   # expect CST (+0800)
   ```

2. **Swap** (before the RAM-heavy app is installed):
   ```bash
   bash setup-swap.sh
   swapon --show   # expect >= 2G
   ```

3. **App deploy** (Task 12.1 — separate): clone repo to `/opt/angelina`, create
   `venv`, `pip install -r requirements.txt`, copy `config/service-account.json`.

4. **.env with secrets**: write `/opt/angelina/.env` with `INSTANCE_ROLE=cloud`,
   `INSTANCE_ID=cloud`, `ANGELINA_ACCESS_TOKEN`, `DUCKDNS_TOKEN`,
   `ANGELINA_SYNC_FOLDER_ID`, Gemini key, Telegram token. Keep it out of git.

5. **systemd**: install the unit and start the service.
   ```bash
   sudo cp angelina-cloud.service /etc/systemd/system/angelina.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now angelina
   systemctl status angelina
   ```

6. **Cron** (failover push + sync):
   ```bash
   bash install-cloud-cron.sh --dry-run   # preview
   bash install-cloud-cron.sh             # apply (asks y/N)
   ```

7. **DuckDNS**: place the updater and schedule it.
   ```bash
   sudo mkdir -p /opt/angelina/deploy
   sudo cp duckdns-update.sh /opt/angelina/deploy/duckdns-update.sh
   sudo chmod +x /opt/angelina/deploy/duckdns-update.sh
   /opt/angelina/deploy/duckdns-update.sh   # expect: OK
   # then append duckdns-cron into the crontab (every 5 min + @reboot)
   crontab -l 2>/dev/null | { cat; cat duckdns-cron; } | crontab -
   ```

8. **Caddy** (last — needs the DuckDNS name resolving and 80/443 reachable):
   ```bash
   export CADDY_EMAIL='<operator-acme-email>'   # or set it in /etc/caddy/caddy.env
   bash install-caddy.sh
   curl -I https://YOUR_SUBDOMAIN.duckdns.org/health
   ```

---

## Network / security notes

- **Port 8080 stays bound to `127.0.0.1`** on the cloud (the systemd
  `ExecStart` uses `--host 127.0.0.1`). It is never exposed publicly; only Caddy
  reaches it over loopback.
- **Firewall opens only 22 / 80 / 443** (SSH, ACME HTTP-01 challenge, HTTPS).
  Opening those ports is **Task 11.3**, handled separately from this directory.
- No secrets are embedded in any file here — tokens and the ACME email are read
  from the environment / `.env` or left as clearly-marked placeholders.

All shell scripts, the systemd unit, the Caddyfile, and the cron fragments are
written with **LF line endings and no UTF-8 BOM** (a BOM breaks the `#!` shebang
and systemd/Caddy parsing).
