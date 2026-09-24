# Angelina Hybrid Cloud — Ops Workflow Playbooks

Two lightweight **ansible-core only** playbooks (no AWX/AAP) that mirror the
Ansible Automation Platform orchestrator-demo pattern:

> **CHECK → ROUTE BY STATE → REMEDIATE / NOTIFY → SUMMARISE**

They extend the existing Angelina Ansible tooling (`audit.yml`, `site.yml`) and
reuse its conventions: a git-ignored `group_vars/all/vault.yml` for secrets
(placeholders in `vault.example.yml`) and an `inventory.*.example.ini` template.

| Playbook | Pattern | Target | Mutating? |
|----------|---------|--------|-----------|
| `ops-heal.yml`   | Service State Routing (self-healing) | `angelina.service` on each host | **Yes — one gated restart** |
| `cert-check.yml` | Proactive Assessment (cert expiry)   | public HTTPS cert for `cert_domain` | **No — read-only** |

---

## 1. `ops-heal.yml` — service self-healing

**Flow**

1. **CHECK** — `systemctl is-active angelina.service` (read-only).
2. **ROUTE** — `active` → healthy path (no action); anything else
   (`inactive` / `failed` / …) → remediation path.
3. **REMEDIATE (gated)** — `systemctl restart angelina.service` **only when the
   service is genuinely not active**. Then re-check `is-active`.
   - recovered (now `active`) → Telegram: *"⚠️ … was down …, auto-restarted, now active."*
   - still down → Telegram: *"🔴 … DOWN … and auto-restart FAILED. Manual intervention needed."* (escalation)
4. **NOTIFY** — healthy path stays quiet unless `-e notify_on_healthy=true`.
5. **SUMMARY** — one `debug` line per host: `state_before / state_after / action`.

### Safety model (important)

- **The only mutating action is `systemctl restart angelina.service`.** No
  config, no packages, no other services are touched.
- **The restart is gated** behind `when:` the service is not active. On a
  healthy host the playbook makes **zero changes** (`changed=0`).
- **Preview mode:** `-e heal_enabled=false` disables the restart entirely. A
  down service is then only *reported* ("would restart"), never restarted. Use
  this to preview safely against production.
- **No auto-scheduling.** This is a manual / on-demand playbook. It installs
  **no cron and no timer**. Auto-triggering remediation (e.g. a systemd timer or
  cron that runs this playbook periodically) is a **separate, deliberate
  opt-in** the operator adds later — it is intentionally *not* wired up here,
  because unattended service restarts should be an explicit decision.

### Run

```bash
# validate only (no connection)
ansible-playbook --syntax-check -i inventory.ops.example.ini ops-heal.yml

# SAFE PREVIEW against the real hosts — reports only, restarts nothing
ansible-playbook -i inventory.ops.ini ops-heal.yml -e heal_enabled=false

# live self-healing — restarts ONLY a service that is actually down
ansible-playbook -i inventory.ops.ini ops-heal.yml

# also ping Telegram on a healthy host (noisy; off by default)
ansible-playbook -i inventory.ops.ini ops-heal.yml -e notify_on_healthy=true
```

---

## 2. `cert-check.yml` — proactive TLS-expiry check

**Flow**

1. **CHECK** — read the live cert's `notAfter` date from the public endpoint:
   `echo | openssl s_client -connect <domain>:443 -servername <domain> | openssl x509 -noout -enddate`,
   then compute **days remaining** (read-only).
2. **ROUTE** by days remaining:
   - `> cert_warn_days` (default **21**) → **OK** (quiet unless `notify_on_healthy`)
   - `cert_crit_days … cert_warn_days` (**7…21**) → 🔶 reminder ("Caddy should auto-renew; monitoring")
   - `< cert_crit_days` (default **7**) → 🔴 warning ("Verify Caddy auto-renewal")
3. **NOTIFY** — Telegram on the crossed threshold.
4. **SUMMARY** — one `debug` line: `domain / expires / days_remaining / branch`.

### Safety model

- **Strictly read-only.** The only remote action is an `openssl` query of the
  live endpoint. Caddy owns renewal — this playbook never restarts Caddy, edits
  config, or touches the cert store.
- Safe to run against production and safe to schedule later if desired (again,
  scheduling is an opt-in the operator adds; nothing is installed here).

### Run

```bash
# validate only (no connection)
ansible-playbook --syntax-check -i inventory.ops.example.ini cert-check.yml

# LOGIC DRY-RUN — compute + print days remaining, send NO Telegram
ansible-playbook -i inventory.ops.ini cert-check.yml -e cert_notify=false

# real proactive check — sends ONE Telegram only if a threshold is crossed
ansible-playbook -i inventory.ops.ini cert-check.yml
```

---

## Configuration

### Secrets & the cert domain (git-ignored vault)

Telegram credentials and the public cert domain are **secrets / deployment
specific** and never committed. They live in `group_vars/all/vault.yml`
(git-ignored); only the placeholder template `vault.example.yml` is committed:

```yaml
# group_vars/all/vault.yml  (copy from vault.example.yml, fill in real values)
telegram_bot_token: "<real bot token>"
telegram_chat_id:   "<real chat id>"
cert_domain:        "<real public FQDN>"
```

```bash
cp group_vars/all/vault.example.yml group_vars/all/vault.yml
# edit vault.yml -> real values   (optionally: ansible-vault encrypt group_vars/all/vault.yml)
```

If Telegram creds are unset (still `YOUR_*` placeholders), the notify step
**logs and skips** rather than failing — a heal/check run never aborts because
notifications are unconfigured.

### Inventory

Copy the template and fill in real hosts:

```bash
cp inventory.ops.example.ini inventory.ops.ini   # inventory.ops.ini is git-ignored
```

- `ops-heal.yml` targets the **`angelina_hosts`** group (both VMs).
- `cert-check.yml` targets the **`cloud_hosts`** group (the cloud VM that serves
  the public cert).

### Tunable variables (override with `-e`)

| Variable | Default | Playbook | Meaning |
|----------|---------|----------|---------|
| `heal_enabled` | `true` | ops-heal | `false` = preview only (no restart) |
| `notify_on_healthy` | `false` | both | notify even on the healthy/OK branch |
| `ops_service` | `angelina.service` | ops-heal | systemd unit to heal |
| `cert_notify` | `true` | cert-check | `false` = compute only, no Telegram |
| `cert_domain` | (from vault) | cert-check | public FQDN to probe |
| `cert_port` | `443` | cert-check | TLS port |
| `cert_warn_days` | `21` | cert-check | reminder threshold (days) |
| `cert_crit_days` | `7` | cert-check | warning threshold (days) |

---

## Requirements

- `ansible-core` (tested on 2.21.x) on the controller.
- `ansible.posix` + `community.general` collections (already installed for the
  existing tooling; these playbooks use only `ansible.builtin`).
- `openssl` on the cert-check target host.
- Outbound HTTPS from the controller to `api.telegram.org` for notifications
  (the Telegram call is delegated to the controller / `localhost`).
