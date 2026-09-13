# Task 9.1 — Apply Plan (review-then-apply)

**Spec:** angelina-hybrid-cloud · **Task:** 9.1 "Add heartbeat write and sync cron on local"

**Status:** LOCAL ARTIFACTS ONLY. Nothing here has been applied to the live VM
(`YOUR_LOCAL_VM_IP`). No `angelina.service` restart, no VM file edits, no
network calls to the VM have been performed. The steps below are what a human
would run *after review* to apply the change.

---

## What changed locally (reviewable now)

| Artifact | Path | Purpose |
|---|---|---|
| Code edit | `app/daily_analysis.py` | Best-effort `write_heartbeat()` after a successful Telegram push. Isolated try/except + import guard; never blocks or breaks the push. |
| Cron fragment | `deploy/hybrid/angelina-hybrid.cron` | The single new 06:00 bi-directional sync job (reviewable text). |
| Cron installer | `deploy/hybrid/install-local-cron.sh` | Idempotent, confirmation-gated installer for the 06:00 job. Not auto-run. |
| .env snippet | `deploy/hybrid/env-additions.local.snippet` | The two vars to append to the prod `.env` (`INSTANCE_ROLE=local`, `INSTANCE_ID=local`). |

### Design decision worth noting for the reviewer
Task 9.1 asks to stamp the heartbeat "after the 23:00 daily push." There are
two clean ways to do that, and both already exist in the codebase:

1. **In-app (chosen here):** `app/daily_analysis.py` calls `write_heartbeat()`
   right after `send_telegram(...)` returns success. This makes the heartbeat
   fire regardless of *how* the daily job is invoked, and requires **no change
   to the existing 23:00 cron line** — the lowest-regression option.
2. **Via the role-gated wrapper:** `app/failover.py::run_daily_push()` (already
   implemented in Task 3.1) runs the analysis then always stamps the heartbeat.
   Switching the 23:00 cron to call this is optional and is left as a commented
   reference line in `angelina-hybrid.cron`. **Do not enable it without first
   removing the current 23:00 `daily_analysis` line**, or you would get a
   double push.

The in-app approach (1) and the wrapper approach (2) both stamp the same
heartbeat cell; running only one of them is correct. This plan applies (1).

---

## Apply steps (run by a human, on/against the VM, after review)

> Prereq: you are at the workspace root on the workstation, SSH to the VM works
> (`ssh angelina@YOUR_LOCAL_VM_IP`), and you have reviewed the diffs above.

### Step 1 — Ship the updated `daily_analysis.py`
Only one file changed in `app/`. Copy just that file (least blast radius):

```powershell
scp .\app\daily_analysis.py angelina@YOUR_LOCAL_VM_IP:/opt/angelina/app/daily_analysis.py
```

Sanity-check it parses on the VM (uses the VM's Python; BOM-safe):

```powershell
ssh angelina@YOUR_LOCAL_VM_IP "cd /opt/angelina && ./venv/bin/python -c \"import ast; ast.parse(open('app/daily_analysis.py', encoding='utf-8-sig').read()); print('VM parse OK')\""
```

No service restart is required for the daily job — `daily_analysis` runs as a
cron process, not inside the long-running `angelina.service`. (If you *also*
adopt the optional failover wrapper, still no restart is needed.)

### Step 2 — Append the two `.env` vars
Review `deploy/hybrid/env-additions.local.snippet`, then append (do not
overwrite) on the VM:

```powershell
ssh angelina@YOUR_LOCAL_VM_IP "grep -q '^INSTANCE_ROLE=' /opt/angelina/.env || printf '\n# Angelina Hybrid Cloud (local)\nINSTANCE_ROLE=local\nINSTANCE_ID=local\n' >> /opt/angelina/.env"
```

Because `require_token` is a no-op when `INSTANCE_ROLE=local`, this cannot
regress local behavior. These vars are read by the cron python processes via
`os.getenv`; the `angelina.service` process only needs them if you later route
`/status` through the heartbeat, which is Task 8.x, not 9.1. A restart is
therefore **not** required for Task 9.1.

### Step 3 — Install the 06:00 sync cron
Upload the hybrid deploy dir and run the installer *interactively on the VM*:

```powershell
scp -r .\deploy\hybrid angelina@YOUR_LOCAL_VM_IP:/opt/angelina/deploy/hybrid
ssh -t angelina@YOUR_LOCAL_VM_IP "bash /opt/angelina/deploy/hybrid/install-local-cron.sh --dry-run"   # preview
ssh -t angelina@YOUR_LOCAL_VM_IP "bash /opt/angelina/deploy/hybrid/install-local-cron.sh"             # apply (asks y/N)
```

Verify:

```powershell
ssh angelina@YOUR_LOCAL_VM_IP "crontab -l | grep -n 'sync_engine\|daily\|23'"
```

You should see the existing 23:00 line unchanged plus the new `0 6 * * *`
sync line.

---

## Verification after apply (optional, human-run)

- **Heartbeat path:** trigger a manual run of the daily job on the VM and
  confirm the log shows `Heartbeat stamped` and the Google Sheet `Heartbeat!B1`
  updates. Because the write is best-effort, a Sheets failure only logs a
  warning and does not fail the push.
- **Sync cron:** wait for 06:00 (or run the one-liner from the cron manually)
  and confirm `/var/log/angelina/sync.log` shows a `sync` summary. With
  `ANGELINA_SYNC_FOLDER_ID` unset, `run_sync` will short-circuit with a warning
  — expected until the cloud side exists.

## Rollback

- Code: `scp` the previous `app/daily_analysis.py` back (or `git checkout`).
- Cron: `crontab -e` and delete the two added lines (the comment + the
  `0 6 * * *` job).
- .env: remove the two appended lines.

None of these touch `angelina.service`, the 23:00 push logic, Sheets tracking,
or Drive knowledge sync.
