# Angelina Hybrid Cloud — Security Audit Playbook

A **strictly read-only** Ansible playbook that collects the security posture of
both Angelina VMs (the local production RHEL host and the cloud Rocky host),
applies rule-based risk scoring, and produces, per host:

- a **structured JSON artifact** (`audit_reports/<host>.json`), and
- a **phone-friendly Markdown report** (`audit_reports/<host>.md`).

This is the **data-collection layer**. A future AI-narration step will consume
the JSON to produce a plain-language briefing — that AI part is **not** built here.

---

## ⚠️ READ-ONLY guarantee

This playbook **only gathers/reads** state. It **never**:

- changes any configuration,
- restarts / starts / stops any service,
- installs, updates, or removes any package (it does **not** run `dnf update`),
- reads or prints any **secret value**.

The only thing it writes to a managed host is a single JSON file under `/tmp`
(the artifact for the future AI layer), and that is left for the operator to
remove out of band. Every command/shell task is marked `changed_when: false`.

Sensitive files (`/opt/angelina/.env`,
`/opt/angelina/config/service-account.json`) are inspected with `stat`
(**metadata only**: existence, mode, owner). Their **contents are never read** —
no `cat`, no `slurp`. Reports therefore contain **zero secret values**.

It is safe to run against the **live production** VM precisely because it is
read-only. Read-only commands do not disturb the running `angelina.service`.

---

## What it checks (security dimensions)

Each finding is scored `OK` / `WARN` / `RISK` / `INFO`. Some rules are
**context-aware** (`local` vs `cloud`), because the two hosts have different
threat models.

| # | Dimension | Source (read-only) | Rule highlights |
|---|-----------|--------------------|-----------------|
| 1 | Listening ports | `ss -Htlnp` | Public bind of a non-22/80/443 port is flagged. **Cloud 8080 must be `127.0.0.1`** (RISK if public). **Local 8080 on `0.0.0.0` is by design** (INFO). |
| 2 | SSH hardening | `sshd -T` | `passwordauthentication=yes` → RISK on **cloud**, WARN on **local** (LAN). `permitrootlogin=yes` → RISK. Checks pubkey / kbd-interactive too. |
| 3 | SELinux | `getenforce` | enforcing=OK, permissive=WARN, disabled=RISK. |
| 4 | firewalld | `firewall-cmd --state` / `--list-all` | Reports open services/ports. Not running → INFO on cloud (GCP VPC firewall also applies), WARN on local. |
| 5 | Security updates | `dnf updateinfo` (cache-only, timeout) | >0 pending security advisories → WARN. Never patches. |
| 6 | Sensitive file perms | `stat` (metadata only) | `.env` / `service-account.json` expected `0600 angelina`. Group/world readable → RISK. **Contents never read.** |
| 7 | Cron | `crontab -l` (angelina + root) | Surfaced for manual review; not auto-flagged (INFO). |
| 8 | Failed SSH logins | `journalctl -u sshd` (7 days) | Count > threshold (default 50) → WARN. |
| 9 | App service | `systemctl is-active/is-enabled angelina.service` | Not active → RISK; active but not enabled → WARN. |
| 10 | Context | `timedatectl`, `uptime` | Timezone + uptime (INFO). |

The overall summary is a count of `RISK / WARN / OK / INFO` findings.

---

## How to run

The playbook lives alongside — but separate from — the provisioning playbook
(`site.yml`). It uses its **own** inventory.

### 1. Validate without connecting

```bash
ansible-playbook --syntax-check -i inventory.audit.example.ini audit.yml
```

### 2. Create the real inventory (git-ignored)

```bash
cp inventory.audit.example.ini inventory.audit.ini
# edit inventory.audit.ini: set YOUR_LOCAL_VM_IP / YOUR_CLOUD_VM_IP + creds
```

`inventory.audit.ini` is listed in `.gitignore` and must **never** be committed
(it holds host addresses and, for the local VM, passwords).

### 3. Run the audit (read-only, safe)

```bash
ansible-playbook -i inventory.audit.ini audit.yml
```

Reports land in `audit_reports/<host>.md` and `audit_reports/<host>.json` on the
controller (also `/tmp/angelina_audit_<host>.json` on each managed host).

### Tunables

- `failed_login_warn_threshold` (default `50`) — WARN above this many failed
  SSH logins in the last 7 days. Override with `-e failed_login_warn_threshold=100`.

---

## JSON artifact schema (`angelina.security-audit/v1`)

```jsonc
{
  "schema": "angelina.security-audit/v1",
  "host": "angelina-cloud",
  "deployment": "cloud",
  "os": "Rocky 9.8",
  "generated_utc": "2025-...Z",
  "summary": { "RISK": 0, "WARN": 2, "OK": 9, "INFO": 4 },
  "findings": [
    {
      "id": "ports_8080",
      "dimension": "Listening ports",
      "title": "Angelina app port 8080 binding",
      "status": "OK",
      "value": "8080 bound to 127.0.0.1",
      "detail": "Cloud app correctly bound to localhost behind Caddy."
    }
    // ... one object per check; cron finding adds cron_angelina/cron_root arrays
  ]
}
```

### How the future AI-narration layer consumes it

A later stage (built separately) will read `audit_reports/*.json` and:

1. Sort findings by severity (`RISK` → `WARN` → `INFO`/`OK`).
2. Feed the **structured, secret-free** findings to an LLM prompt that turns them
   into a spoken/written briefing (e.g. "Your cloud VM has two warnings: …").
3. Compare successive runs (the `generated_utc` + `summary` counts) to describe
   drift over time.

Because the JSON already carries `status`, `value`, and `detail` per finding and
**no secrets**, the AI layer needs no host access — it only reads these files.

---

## Files

```
ansible/
├── audit.yml                         # read-only audit play (hosts: angelina_hosts)
├── inventory.audit.example.ini       # template inventory (local + cloud placeholders)
├── inventory.audit.ini               # REAL inventory — git-ignored, not committed
├── audit_reports/                    # generated per-host .json + .md (fetched here)
└── roles/security_audit/
    ├── tasks/
    │   ├── main.yml                  # orchestrates collect -> score -> report
    │   ├── collect.yml               # read-only gathering of all 10 dimensions
    │   ├── score.yml                 # rule-based OK/WARN/RISK/INFO scoring
    │   └── report.yml                # writes JSON + renders/fetches Markdown
    └── templates/
        ├── score_file.j2             # sensitive-file finding (metadata only)
        └── report.md.j2              # phone-friendly Markdown report
```
