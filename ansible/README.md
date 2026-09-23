# Angelina Hybrid Cloud — Ansible provisioning

One-command, idempotent provisioning of the Angelina **Cloud_Instance** on a
fresh GCP Rocky Linux 9 `e2-micro`. This replaces the 8 manual steps
(timezone → swap → firewall → SSH hardening → app deploy → `.env` → systemd →
cron/DuckDNS/Caddy) with a single `ansible-playbook` run.

> **This targets a FRESH VM.** Do **not** run it against the live production VM
> (`YOUR_CLOUD_VM_IP`) or the local VM (`YOUR_LOCAL_VM_IP`). It is safe to re-run
> against the VM it provisions (every role is idempotent).

---

## What it does (role order = manual runbook order)

| Order | Role | Purpose |
|---|---|---|
| 1 | `common` | Set timezone `Asia/Taipei` (so the `0 23` failover cron fires at TW 23:00); install `gcc`/`gcc-c++`/`git`/`curl`; create the `angelina` user/group and log dir. Restarts `crond`. |
| 2 | `swap` | Idempotent 2GB `/swapfile` (`fallocate` → `dd` fallback), `chmod 600`, `mkswap`, `swapon`, persist in `/etc/fstab`. |
| 3 | `firewall` | In-VM `firewalld`: allow only `22/80/443`. `8080` stays loopback-only (never opened). |
| 4 | `ssh_hardening` | Drop-in `60-angelina-hardening.conf` (pubkey on, password/root/kbd-interactive off); `sshd -t` validate; reload via handler. **Guard refuses to run unless an authorized key exists.** |
| 5 | `app_deploy` | `python3.11` + devel; `/opt/angelina/{app,config,data,deploy}`; deploy code (git or tarball); venv; **CPU-only torch first**, then `requirements.txt`, then `gspread google-auth pysqlite3-binary`; venv `sitecustomize.py` sqlite shim; copy `service-account.json`; render `.env` (0600). |
| 6 | `systemd_service` | Install `angelina.service` (uvicorn on `127.0.0.1:8080`, `MemoryMax=2G`, `Restart=always`); `daemon-reload`; enable `--now`. |
| 7 | `cron_jobs` | `23:00` → `failover.run_daily_push` (sources `.env` first); DuckDNS updater script + `*/5` + `@reboot` cron. |
| 8 | `caddy` | Install Caddy (Rocky 9 COPR); template `Caddyfile` (DuckDNS name → `127.0.0.1:8080`, ACME email from `CADDY_EMAIL`); enable `--now`; reload on config change. |

The `06:00` bi-directional sync cron is **intentionally omitted on the cloud**:
the local instance initiates the HTTPS sync, so the cloud side is passive.

---

## Prerequisites (operator, once)

Manual prerequisites (P-A … P-E from the spec) must be done first:

- **GCP account + billing** enabled; Compute Engine API on.
- **DuckDNS subdomain** registered + token.
- **Operator SSH key** and a **budget-alert / ACME email**.
- **Secrets**: Gemini key, Telegram token + chat id, `ANGELINA_ACCESS_TOKEN`,
  DuckDNS token, spreadsheet/drive/sync folder ids, `service-account.json`.

### 1. Create the fresh VM (out of scope for the in-VM playbook)

```bash
gcloud compute instances create angelina-cloud \
  --machine-type=e2-micro \
  --zone=us-west1-b \
  --image-family=rocky-linux-9 \
  --image-project=rocky-linux-cloud \
  --boot-disk-size=30GB \
  --boot-disk-type=pd-standard \
  --tags=angelina-web
```

### 2. Create the GCP network firewall rule (out of scope for the in-VM playbook)

```bash
gcloud compute firewall-rules create angelina-allow-web \
  --allow=tcp:22,tcp:80,tcp:443 \
  --target-tags=angelina-web \
  --description="Angelina: SSH + ACME HTTP + HTTPS only"
```

> `8080` is never opened at the GCP firewall. The in-VM `firewalld` (role
> `firewall`) also only allows `22/80/443`.

### 3. Install the operator SSH key on the VM (BEFORE hardening)

Install your public key for the `angelina` user (via `gcloud compute ssh`,
instance metadata, or `ansible.posix.authorized_key`) so the `ssh_hardening`
role's safety guard passes and you are not locked out when password auth is
disabled.

### 4. (Optional) Budget alert — `$1` threshold

Create a `$1` budget on the billing account with an email notification channel
to the operator address (spec Task 13.1). This is a billing-account operation,
done via the GCP console or `gcloud billing budgets create`, separate from
the in-VM playbook.

---

## Secrets

```bash
cp group_vars/all/vault.example.yml group_vars/all/vault.yml
# edit vault.yml -> replace every YOUR_* with the real value
# (vault.yml is git-ignored; vault.example.yml holds only placeholders)

# Optional: encrypt at rest
ansible-vault encrypt group_vars/all/vault.yml
```

Also set `service_account_json_src` in `vault.yml` to the path of your
`service-account.json` **on the controller** (or leave the `YOUR_` placeholder
to skip copying and place it on the VM manually).

---

## Run

```bash
# 1. install the two required collections
ansible-galaxy collection install -r requirements.yml

# 2. point the inventory at the FRESH VM
cp inventory.example.ini inventory.ini
# edit inventory.ini -> set ansible_host to the fresh VM IP

# 3. provision (add --ask-vault-pass if you encrypted vault.yml)
ansible-playbook -i inventory.ini site.yml
```

### Validate without connecting (safe; no prod contact)

```bash
ansible-playbook --syntax-check -i inventory.example.ini site.yml
```

`--syntax-check` does **not** open an SSH connection. Do **not** run a real
`--check` (dry-run) against the running production VM — check mode still
connects. Connection-level validation should be run by the operator against a
**fresh** VM only.

### Run a subset by tag

```bash
ansible-playbook -i inventory.ini site.yml --tags caddy
ansible-playbook -i inventory.ini site.yml --tags swap,firewall
ansible-playbook -i inventory.ini site.yml --tags app,systemd
```

Available tags: `common base swap firewall ssh hardening app deploy systemd
service cron duckdns caddy tls`.

---

## Idempotency & rollback notes

- **Idempotent:** every role is safe to re-run. `swap` is guarded by
  `swapon --show`; `firewalld`/`cron`/`lineinfile`/`template` are declarative;
  Caddy/COPR installs are guarded by `rpm -q` and `creates:`.
- **SSH lock-out guard:** `ssh_hardening` refuses to disable password auth
  unless `~angelina/.ssh/authorized_keys` exists. Override only if you manage
  keys another way: `-e ssh_hardening_force=true`.
- **App data preserved:** git deploy uses `force: false` so runtime `data/`,
  `config/`, `.env`, and `venv/` are not clobbered on re-run.
- **Rollback:**
  - Service: `sudo systemctl disable --now angelina caddy`.
  - Swap: `sudo swapoff /swapfile`, remove the `/etc/fstab` line, `rm /swapfile`.
  - SSH: delete `/etc/ssh/sshd_config.d/60-angelina-hardening.conf` and
    `systemctl reload sshd` to restore defaults.
  - Cron: `crontab -u angelina -e` and remove the Ansible-managed lines.

---

## Collection dependencies

`requirements.yml` pulls exactly what the roles use:

- `ansible.posix` → `ansible.posix.firewalld` (firewall role).
- `community.general` → `community.general.timezone` (common role).

Everything else uses `ansible.builtin`. If a collection cannot be installed on
the controller, the `firewall` role degrades gracefully (it skips when
`firewalld` is absent and notes that the GCP network firewall governs ingress),
and the timezone step is the only hard dependency on `community.general`.

---

## Line endings

All Linux-bound files (scripts, unit, Caddyfile, `.env`, templates) are written
with **LF and no BOM**. A BOM breaks `#!` shebangs and systemd/Caddy parsing.
