# Reliable, Low-Cost, Self-Hosted Systems — Engineering Services

**I help individuals and small teams run reliable, low-cost, self-hosted systems** — the kind that stay up, stay cheap, and don't surprise you at 3am. My background is hands-on operations engineering: hybrid on-prem + cloud architectures, infrastructure-as-code, failover and resilience, and the unglamorous production debugging that keeps a service honest. If you want serious reliability without a serious cloud bill, that's the work I do.

The proof is a real system I designed, built, and have operated: a hybrid local+cloud AI agent running at **sustained $0 cost** inside provider free tiers, with verified multi-day failover and a disciplined release history. The engineering patterns behind it are the services below.

---

## What I can help with

**Cost-optimized cloud architecture**
Design systems that live inside always-free tiers or minimal-spend budgets without sacrificing reliability. I've run a full two-node production system at $0 with a budget tripwire that has never fired — so this isn't theory, it's a shipped result. Good for solo founders, home labs, and small teams who want to stop over-provisioning.

**Resilience & failover engineering**
Hybrid on-prem + cloud topologies with heartbeat-based presence detection and *at-most-once* failover — the backup takes over cleanly when the primary goes dark, and never produces duplicate work. I design the coordination rules, the presence windows, and the trade-offs (what you're willing to miss vs. what you must never double-do).

**Infrastructure as Code & automation**
Idempotent provisioning that stands up an entire host in a single run — timezone, swap, firewall, SSH hardening, runtime, app, service units, scheduling, TLS. Plus ops automation: read-only security auditing, gated service self-healing with a preview mode, and proactive TLS-expiry checks. Enterprise-style orchestration patterns, implemented on free, open-source tooling.

**Secure remote access**
HTTPS with automatic certificate management (reverse proxy + Let's Encrypt), token-based auth with constant-time comparison, SSH key-only access with root login disabled, and tight firewalling (only the ports you actually need). Safe exposure of a home-lab or small-cloud service to the internet.

**Production debugging & reliability reviews**
I find the failures that hide in the plumbing — config/code separation, cron environments, runtime-version drift, database upsert semantics, sync identity, request-path latency, presence-signal ownership, retry/backoff, timezone handling. I've got a documented track record of nine distinct production bugs found, root-caused, and fixed. I'll review your system and tell you where it's quietly fragile.

**Self-hosted AI / RAG integration**
FastAPI + a vector database + a hosted LLM, wired together and operated on free-tier infrastructure. Scheduled jobs, retrievable knowledge bases, and bi-directional data sync between nodes — practical, maintainable AI plumbing without a platform bill.

---

## Proof / case study

- **$0 sustained cost** — a complete two-node production system running entirely inside always-free tiers; the budget tripwire has never fired.
- **Multi-day failover, verified in production** — the at-most-once design was exercised during a real extended outage; the backup took over correctly with **no duplicate output** confirmed in the logs.
- **At-most-once guarantee** — never a duplicate daily job across two nodes, by design.
- **Disciplined release history** — tagged iterations from v1.0.0 → v3.4.1, each secret-scanned before commit.

Full technical write-up: see **CASE_STUDY.md** in the repository · Code & details: **[your GitHub repo link]**

---

## How we can work together

- **One-off architecture review** — I look at your current (or planned) setup and deliver concrete findings: cost reductions, reliability gaps, security issues, and a prioritized list of fixes.
- **Build / implementation** — I design and implement the system: provisioning, failover, secure access, automation. You get working infrastructure-as-code you can re-run and understand.
- **Ongoing support / retainer** — periodic reliability and security reviews, help with incidents, and steady improvement over time.
- **Technical writing** — case studies, post-mortems, runbooks, and architecture docs that your team (or your users) can actually follow.

Pricing is scope-based — **contact me for a quote** once we've talked through what you need.

---

## Tech I work with

Python · FastAPI / uvicorn · Ansible (idempotent provisioning + ops automation) · SQLite · vector databases (RAG) · hosted LLM integration · Caddy / Let's Encrypt (HTTPS) · systemd · cron · firewalld / SSH hardening · dynamic DNS · GCP always-free tier · RHEL / Rocky Linux · Linux ops generally.

---

## Get in touch

- Email: **[your-email@example.com]**
- LinkedIn: **[your LinkedIn]**
- GitHub: **[your GitHub]**

Tell me what you're running (or want to run), your constraints, and what "reliable enough" means for you. I'll come back with a scoped approach.

---

*A note on scope: engagements are scoped to engineering, DevOps, and reliability work. I build and operate the systems — I don't provide financial, investment, legal, or other regulated professional advice. If a project touches a regulated domain, the engineering is mine; the domain/compliance decisions stay with you and your advisors.*
