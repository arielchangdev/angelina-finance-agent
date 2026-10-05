# Case Study: "Angelina" — A Zero-Cost, Self-Hosted AI Financial-Analysis Agent

> A resilient hybrid local+cloud AI agent built and operated under two hard constraints: stay **100% inside free tiers**, and **never regress the running production service**. This document is a de-identified technical write-up of the engineering decisions, trade-offs, and the real bugs fought along the way.

---

## 1. Summary

**Angelina** is a self-hosted AI financial-analysis agent (Python + FastAPI + Google Gemini 2.5 Flash free tier + ChromaDB for RAG + SQLite for state). It performs a scheduled daily market analysis, maintains a retrievable knowledge base, and exposes a phone-friendly chat interface over HTTPS.

What makes it interesting is not the model call — it is the operations engineering around it. Over three major iterations the system grew from a single home-lab VM into a **hybrid local-primary / cloud-passive-backup** deployment with heartbeat-based failover, authenticated bi-directional sync, HTTPS remote access, and fully idempotent infrastructure-as-code — all delivered while honoring two non-negotiable constraints:

- **Constraint 1 — Zero cost.** Every component must live inside a provider's always-free tier. A $1 budget alert sits on top as a tripwire. To date the system has produced **zero spend**.
- **Constraint 2 — No production regressions.** There is a live daily push that real usage depends on. Every change had to be shippable without breaking the running service, which drove disciplined config management, secret hygiene, and conservative distributed-systems choices.

These two constraints are the lens for every decision below.

---

## 2. What It Does

- Runs a **daily market-analysis push** at 23:00 (Taiwan time), delivered via a messaging channel and logged to Google Sheets.
- Maintains a **RAG knowledge base** (ChromaDB vectors) and a **conversation history** (SQLite), kept in sync across two nodes.
- Serves a **phone-friendly chat UI** over HTTPS, gated by a shared access token.
- Serves a **token-protected security/audit page** with a weekly report.
- Provisions and heals itself through **Ansible playbooks** that mirror enterprise orchestration patterns on free, open-source tooling.

---

## 3. Architecture (v3)

The v3 topology is **local-primary, cloud-passive-backup**. The local VM does all the real work on a normal day. The cloud VM stays quiet unless the local node goes dark, and only then takes over. A heartbeat written to a shared Google Sheet is the coordination channel; a token-gated HTTPS endpoint handles data sync.

```
                         ┌──────────────────────────────────────┐
                         │        Shared Google Sheet            │
                         │  (heartbeat / presence relay +        │
                         │   analysis + audit logging)           │
                         └───────────────▲──────────▲────────────┘
                 stamp heartbeat          │          │  read heartbeat
                 after each push          │          │  at 23:00 check
                                          │          │
   ┌──────────────────────────────┐      │          │     ┌──────────────────────────────┐
   │   LOCAL  (PRIMARY)            │      │          │     │   CLOUD  (PASSIVE BACKUP)      │
   │   home-lab RHEL VM            │──────┘          └─────│   GCP e2-micro, Rocky Linux 9  │
   │                               │                       │   always-free, 2GB swap        │
   │  • uvicorn/FastAPI (LAN port) │                       │  • app bound to 127.0.0.1      │
   │  • cron 23:00 daily push      │                       │  • Caddy -> HTTPS (Let's Encrypt)│
   │  • Google Sheets / Drive sync │                       │  • DuckDNS dynamic DNS         │
   │  • token NO-OP in local role  │                       │  • ports 22/80/443 only        │
   └───────────────┬───────────────┘                       │  • SSH key-only, root disabled │
                   │                                        └───────────────┬───────────────┘
                   │        token-gated HTTPS sync                          │
                   │   POST /sync/exchange  (last-write-wins merge,         │
                   └───────────────  re-embed on import)  ──────────────────┘

   Remote user ── HTTPS (DuckDNS name) ──▶ Caddy ──▶ cloud app ──▶ Chat UI + /audit
```

**Primary (local).** A home-lab RHEL VM runs the app under `systemd` (uvicorn/FastAPI on a LAN-bound port). A cron job fires the daily push at 23:00 local time, logs to Google Sheets, and syncs a knowledge base from Google Drive.

**Passive backup (cloud).** A GCP `e2-micro` always-free instance (Rocky Linux 9) in a free-eligible US region, 30GB standard disk, with **2GB swap** added because 1GB of RAM is too small to load the embedding model. The app binds to `127.0.0.1` only; a **Caddy** reverse proxy terminates HTTPS with automatic Let's Encrypt certificates, reached through a **DuckDNS** dynamic-DNS name. Only ports 22/80/443 are open at the firewall, SSH is key-only, and root login is disabled.

**Failover (heartbeat presence relay).** The local instance stamps a heartbeat in the shared sheet after each successful daily push. At its own 23:00 check the cloud instance reads that heartbeat; if local has been silent beyond a **25-hour presence window** (24h + 1h buffer) it classifies local as offline and performs a `failover_push`. Otherwise it records a `passive_skip` and stays quiet. This guarantees **at most one daily push** across both nodes — never a duplicate.

**Sync.** A daily bi-directional exchange of the ChromaDB vectors and the SQLite conversation history. The initiator POSTs its export to the peer's token-gated `/sync/exchange` endpoint, receives the peer's pre-exchange snapshot in response, and both sides merge with **last-write-wins** (local wins ties). Text is **re-embedded on import** rather than transporting vectors over the wire, and the heavy re-embed runs as a background task so the HTTP round-trip returns in seconds.

**Remote access.** The chat UI is served over HTTPS and protected by a shared access token compared in constant time. A token-protected `/audit` page (HTTP basic auth) serves a weekly security report.

---

## 4. Key Engineering Decisions & Trade-offs

| Decision | Alternative | Why this way |
|---|---|---|
| **At-most-once** failover (heartbeat + 25h window) | At-least-once (both can push) | The product requirement is "never double-post." A missed day right after an unexpected shutdown is tolerable; a duplicate daily report is not. Conservative by design. |
| **Re-embed text on import** | Transport raw vectors between nodes | Keeps payloads small to stay under egress limits, and sidesteps embedding-format drift between nodes. Costs CPU on import, which is acceptable off the request path. |
| **Direct authenticated HTTPS sync** | Google Drive relay | A free Gmail service account has **no Drive storage quota** (`files.create` → 403). The relay assumption broke; re-architected to a direct token-gated exchange. |
| **CPU-only PyTorch** | Default PyTorch wheels | Default wheels pull ~5GB of CUDA dependencies that a CPU-only `e2-micro` will never use. CPU-only keeps the 30GB disk and install time sane. |
| **25-hour presence window** (24h + 1h buffer) | A tighter window | The buffer absorbs clock skew and push-duration jitter so a healthy-but-slightly-late local push is never misread as an outage. |
| **2GB swap on a 1GB VM** | Run as-is | The embedding model needs more than 1GB resident. Swap trades latency for the ability to run at all on always-free hardware. |
| **Free `ansible-core`** | AWX / AAP | Reproduces enterprise orchestration patterns at zero cost. The playbooks are structured to mirror AAP-style workflows without the platform. |

---

## 5. Challenges & Resolutions

The system's reliability was earned by finding and fixing concrete failures. Each is framed as **problem → root cause → fix → lesson**.

### 5.1 Credential clobbering on deploy
- **Problem:** Deploying a "GitHub-clean" copy of the code over production silently broke the daily push — Gemini returned HTTP 400 "API key not valid," then the messaging channel returned 404.
- **Root cause:** The clean copy carried **placeholder credentials** that overwrote the real hardcoded keys on the production box.
- **Fix:** Moved all credentials out of source and into the environment / a git-ignored `.env`. Real values never live in the repo; committed files carry placeholders only.
- **Lesson:** Config is not code. Separating the two makes "deploy latest code" safe to run against production.

### 5.2 Cron ran without the environment
- **Problem:** Env-based config was missing at runtime even though it worked in an interactive shell.
- **Root cause:** The cron job invoked `python` without sourcing `.env`, so the process started with none of the expected variables.
- **Fix:** Source `.env` in the cron entry before launching the app.
- **Lesson:** cron is a minimal, non-login shell. Nothing from your shell profile comes along for free.

### 5.3 Python 3.11 vs 3.12 syntax drift
- **Problem:** Code that ran fine locally raised a `SyntaxError` on the cloud VM.
- **Root cause:** An f-string containing a backslash is a `SyntaxError` on Python 3.11 (cloud) but valid on 3.12 (local).
- **Fix:** Rewrote the expression to be version-safe across both interpreters.
- **Lesson:** "Works on my machine" has a version number attached. Match the runtime, or write to the lowest supported version.

### 5.4 SQLite upsert rejected by a partial index
- **Problem:** An `ON CONFLICT` upsert on sync records failed.
- **Root cause:** The `sync_id` index was a **partial** unique index, which SQLite will not accept as an upsert conflict arbiter.
- **Fix:** Converted it to a **full** unique index, with a self-healing migration that repairs existing databases on startup.
- **Lesson:** Upsert arbiters have precise requirements. A partial index is not a drop-in substitute for a full one.

### 5.5 Namespace-bounce duplication
- **Problem:** The conversation table kept growing on every sync.
- **Root cause:** Synced records bounced between nodes being re-namespaced each round (`local:N` → `cloud:M` → …), so each round looked like a brand-new record.
- **Fix:** Preserve the **original origin id** on re-export, and skip records that originated on the current instance.
- **Lesson:** In bi-directional sync, identity must be stable and origin-aware, or records multiply.

### 5.6 HTTP sync timeout under synchronous re-embed
- **Problem:** Sync requests timed out on the 1GB VM.
- **Root cause:** Re-embedding hundreds of chunks **synchronously inside the request** blew past the HTTP timeout.
- **Fix:** Return the pre-exchange snapshot immediately and move the import/re-embed to a **background task**.
- **Lesson:** Keep expensive, variable-duration work off the request path. The response should be bounded; the work can be eventual.

### 5.7 Failover heartbeat double-stamp (every-other-day gap)
- **Problem:** During an extended local outage, the cloud delivered the push only every *other* day.
- **Root cause:** When the cloud failed over it **also** stamped the "local presence" heartbeat. That made local look alive, so the next day the cloud skipped — then local was still down, so it failed over again, oscillating.
- **Fix:** Only stamp the local-presence heartbeat **in the local role**. Failover pushes do not touch the local heartbeat.
- **Lesson:** A presence signal must be written only by the entity whose presence it represents. Mixing roles corrupts the signal.

### 5.8 Transient Gemini 503s caused a missed push
- **Problem:** A momentary upstream outage caused a day with no analysis.
- **Root cause:** The retry logic was too thin to ride out a short burst of 5xx responses.
- **Fix:** Hardened retries to **5 attempts** with capped backoff (20/40/60/90/120s), covering 500/502/503/504/429 and network errors.
- **Lesson:** Hardening paid off — the new logic later rode out a real **3× 503** event and still delivered on time.

### 5.9 Timezone: UTC default fired failover at the wrong hour
- **Problem:** The cloud failover check ran at 07:00 local instead of 23:00.
- **Root cause:** GCP VMs default to **UTC**, so the 23:00 cron fired against the wrong wall clock.
- **Fix:** Set the VM timezone to match the intended local time.
- **Lesson:** Schedulers are only as correct as the clock underneath them. Set the timezone explicitly; never assume.

---

## 6. Infrastructure as Code & Ops Automation

**Provisioning.** A single idempotent `ansible-core` playbook stands up the entire cloud VM in one run: timezone, swap, `firewalld`, SSH hardening, a Python 3.11 venv (CPU-only PyTorch; a `pysqlite3` shim because RHEL9/Rocky 9 ships SQLite 3.34 while ChromaDB needs ≥ 3.35), the app deploy, a `systemd` unit, cron, the DuckDNS updater, and Caddy. Secrets come from a **git-ignored Ansible vault**; committed files use placeholders only.

**Ops automation (AAP patterns on free tooling).**
- A strictly **read-only security audit** playbook scores roughly ten dimensions as OK/WARN/RISK: listening ports, SSH hardening, SELinux, firewalld, pending security updates, sensitive-file permissions (**metadata only, never contents**), cron, failed logins, and service state.
- A **service self-healing** playbook: check → gated auto-restart *only* when the service is down → notify/escalate, with a **preview mode** that changes nothing.
- A proactive **TLS-expiry check**.

---

## 7. Results & Metrics

- **Zero cost sustained.** The entire system runs inside always-free tiers; the $1 budget tripwire has never fired. Cumulative spend: **$0**.
- **Failover verified in production.** The at-most-once design was exercised over a real multi-day local outage and the cloud took over correctly, with **no duplicate pushes** confirmed in the logs.
- **Retry hardening verified.** The retry/backoff logic rode out a real **3× 503** burst and still delivered the daily analysis on time.
- **Knowledge base kept in sync.** Hundreds of knowledge vectors and the conversation history stay consistent across both nodes via the daily authenticated exchange.
- **Disciplined release history.** Tagged iterations from **v1.0.0 → v3.3.0**, each secret-scanned before commit.

---

## 8. Tech Stack

| Layer | Choice |
|---|---|
| Language / runtime | Python 3.11 (cloud) / 3.12 (local) |
| Web framework | FastAPI + uvicorn |
| LLM | Google Gemini 2.5 Flash (free tier) |
| Vector store / RAG | ChromaDB |
| State / history | SQLite (`pysqlite3` shim on RHEL9/Rocky 9) |
| Embeddings | CPU-only PyTorch |
| Reverse proxy / TLS | Caddy + Let's Encrypt |
| Dynamic DNS | DuckDNS |
| Scheduling | cron + systemd |
| Infra as code | Ansible (`ansible-core`), git-ignored vault |
| Cloud | GCP `e2-micro` always-free (Rocky Linux 9) |
| Local | home-lab RHEL VM |
| Logging / coordination | Google Sheets (heartbeat relay) |

---

## 9. Honest Limitations & Future Work

This is a well-engineered **single-operator** system, not a product — and it is worth being precise about the gap:

- **Single-user by design.** There is no multi-tenancy, per-user auth, or billing. Turning this into a product would require all three, plus data isolation.
- **Cloud RAM ceiling.** The always-free `e2-micro` (1GB RAM + swap) can run the embedding model but is not a home for a local LLM. Heavy inference stays on the hosted model.
- **Daily, not real-time, sync.** The two nodes reconcile once a day. That is sufficient for the daily-push use case but is not suitable for interactive multi-writer scenarios.
- **Failover is intentionally conservative.** The at-most-once guarantee can skip a day immediately after an unexpected shutdown. That is a deliberate trade, not an oversight.
- **Not investment advice.** The agent produces analysis for personal, informational use only. Any production or public offering of financial analysis would need appropriate regulatory review; this is noted neutrally and left out of scope.

**Natural next steps** would be real-time or event-driven sync, per-user authentication and tenancy, observability (metrics/tracing) beyond the current log-based checks, and a managed secrets store in place of the vault file.

---

## 10. Closing

Angelina is a study in **reliability under hard constraints**: the interesting work was not calling a model, it was keeping a free, two-node system correct, secure, and cheap through nine real failures. The recurring lesson — cron environments, SQLite versions, timezones, retry/backoff — is that **the boring details are where reliability actually lives.**
