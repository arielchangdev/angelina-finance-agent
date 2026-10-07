# Nine Bugs That Taught Me Reliability: Post-Mortem of a Zero-Cost Hybrid AI System

> A war-stories write-up. The system was fun to design. The *interesting* part was the nine ways it quietly broke — and what each one taught me about where reliability actually lives.

I spent a few months building and operating a small AI agent under two rules that never moved:

1. **It must cost exactly $0.** Every component lives inside a provider's always-free tier, with a $1 budget alert sitting on top as a tripwire.
2. **It must never regress the running production service.** There's a live daily job that real usage depends on. Every change had to ship without breaking what was already working.

Those two constraints turned out to be the whole story. When you can't throw money or a staging cluster at a problem, you're forced to get the boring details right. This post is about the boring details — specifically, the nine production bugs I had to fight, written up so you can skip the ones I didn't.

If you want the full architecture and trade-off write-up, that's in a separate case study (linked at the bottom). Here I'll keep the system context short and spend the words on the failures.

---

## The system, in one paragraph

It's a self-hosted AI agent (Python + FastAPI, a hosted LLM on its free tier, a vector DB for retrieval, SQLite for state). A cron job runs a scheduled daily task, logs results to a shared spreadsheet, and keeps a small knowledge base in sync. Over three iterations it grew from one home-lab VM into a **hybrid topology**: a *local* VM is the primary and does all the real work; a *cloud* always-free VM sits passive and only takes over if the local node goes dark. Coordination happens through a heartbeat written to a shared sheet; data moves through a token-gated HTTPS sync endpoint. That's it. Everything below is about keeping that two-node, zero-budget setup correct.

Here's roughly how a normal day flows:

```
local VM  ──(daily task + heartbeat stamp)──▶  shared sheet  ◀──(23:00 read)──  cloud VM (passive)
   └──────────────── token-gated HTTPS sync (last-write-wins) ────────────────┘
```

Now the fun part.

---

## Bug 1 — The deploy that clobbered its own credentials

**Symptom.** I pushed a cleaned-up, "ready for GitHub" copy of the code onto the production box. The next daily run died: the LLM call came back `400 "API key not valid"`, and the downstream notification returned `404`. Nothing in the diff *looked* like it touched credentials.

**Investigation.** The code logic was identical. So it wasn't logic. I diffed the deployed files against what had been running and found the clean copy carried **placeholder** credential values — the ones I'd scrubbed in for the public repo.

**Root cause.** Credentials were living *in source*. "Deploy the latest code" therefore also meant "overwrite the real keys with placeholders." The deploy did exactly what I told it to; I'd just told it something stupid.

**Fix.** Pull every secret out of source and into the environment / a git-ignored `.env`. Committed files carry placeholders only; real values never enter the repo.

```
# committed (safe)
API_KEY=replace-me

# on the box, in a git-ignored .env (never committed)
API_KEY=<the real value>
```

**Takeaway.** Config is not code. The moment you can deploy code without touching config, "deploy latest" becomes a safe, boring operation instead of a loaded gun. This single separation prevented a whole category of future incidents.

---

## Bug 2 — Cron ran, but with none of my environment

**Symptom.** The app worked perfectly when I ran it by hand. The cron-triggered run behaved as if its configuration didn't exist.

**Investigation.** Classic "works in my shell, not in cron." I dumped the environment the cron process actually saw. It was nearly empty — none of the variables I rely on from `.env` were present.

**Root cause.** The cron entry invoked `python` directly without sourcing `.env` first. cron runs in a minimal, non-login shell: your `.bashrc`, your profile, your exported variables — none of it comes along.

**Fix.** Source the environment inside the cron command before launching:

```
0 23 * * *  cd /opt/app && . /opt/app/.env && /opt/app/venv/bin/python -m app.daily >> /var/log/app.log 2>&1
```

**Takeaway.** cron is not your shell. If a job depends on environment, make the job load that environment explicitly. Don't assume anything from an interactive session is inherited.

---

## Bug 3 — "Works on my machine" had a version number attached

**Symptom.** Code that ran clean locally threw a `SyntaxError` on the cloud VM — at *import* time, before any logic executed.

**Investigation.** A `SyntaxError` on identical source means the parser differs, which means the interpreter version differs. Local was Python 3.12; the cloud VM was on 3.11.

**Root cause.** An f-string containing a backslash. Python 3.12 relaxed the f-string grammar and accepts it; 3.11 does not. Same characters, different verdict.

**Fix.** Rewrite the expression to be valid on the *older* interpreter — pull the backslash out of the f-string into a named variable — so it parses everywhere.

```python
# fails to parse on 3.11
msg = f"line one{'\n'}line two"

# version-safe
nl = "\n"
msg = f"line one{nl}line two"
```

**Takeaway.** "Works on my machine" always has a version number attached. Either match the runtime across environments, or write to the lowest version you have to support. Runtime parity is part of the contract, not a detail.

---

## Bug 4 — SQLite refused my upsert because the index was *partial*

**Symptom.** An `ON CONFLICT` upsert on sync records failed outright. The error pointed at the conflict target.

**Investigation.** The `sync_id` column had a unique index, so an upsert *should* have an arbiter to key on. Reading the SQLite docs more carefully: the conflict target of an upsert must map to a specific kind of index.

**Root cause.** The unique index was a **partial** index (it had a `WHERE` clause). SQLite will not use a partial index as an upsert conflict arbiter. It wasn't a bug in my SQL so much as a bug in my assumption that "unique index" and "upsert arbiter" are the same thing.

**Fix.** Convert the index to a **full** unique index, plus a self-healing migration that detects the old partial index on startup and repairs existing databases in place.

```
-- won't arbitrate an upsert
CREATE UNIQUE INDEX ix_sync ON records(sync_id) WHERE sync_id IS NOT NULL;

-- will
CREATE UNIQUE INDEX ix_sync ON records(sync_id);
```

**Takeaway.** Upsert arbiters have precise requirements, and they differ by engine. When the database rejects something that "should" work, read the exact constraints before you reach for a workaround.

---

## Bug 5 — The sync table that grew forever (namespace bounce)

**Symptom.** Every daily sync, the conversation table got bigger. Not from new activity — from the *same* records multiplying.

**Investigation.** I traced individual records across sync rounds. A record that originated on local showed up on cloud, then came *back* to local, then went out to cloud again — each hop with a slightly different id. The system saw each hop as a brand-new record and inserted it.

**Root cause.** On each export, records were re-namespaced (`local:N` → `cloud:M` → `local:P` → …). Because identity changed every round-trip, nothing was ever recognized as "already seen." Classic bi-directional-sync duplication.

**Fix.** Two rules: (1) preserve the **original origin id** on re-export so identity is stable for the life of the record, and (2) when exporting, **skip records that originated on this instance** — don't ship something back to where it was born.

**Takeaway.** In bi-directional sync, identity must be stable and origin-aware. If a record's identity mutates as it travels, you don't have sync — you have a photocopier.

---

## Bug 6 — The sync endpoint timed out because it did the heavy work inline

**Symptom.** Sync requests started timing out, specifically on the small (1GB RAM) VM.

**Investigation.** The round-trip did an exchange *and* re-embedded the imported text into vectors synchronously, inside the request handler. Re-embedding a few hundred chunks on a CPU-only, memory-starved box takes real wall-clock time — well past the HTTP timeout. On a beefier node it squeaked by, which is why it hid for a while.

**Root cause.** Expensive, variable-duration work (re-embedding) was sitting directly on the request path. The response couldn't return until the slowest possible operation finished.

**Fix.** Return the pre-exchange snapshot *immediately*, and move the import + re-embed into a background task. The HTTP round-trip now returns in seconds; the heavy lifting completes eventually, off the wire.

```
POST /sync/exchange
  ├─ read peer payload
  ├─ respond NOW with our pre-exchange snapshot   ← bounded
  └─ enqueue import + re-embed as background work  ← eventual
```

**Takeaway.** Keep slow, unbounded work off the request path. A response time should be bounded by design; the work behind it can be eventual. If a handler's latency depends on data volume, that's a smell.

---

## Bug 7 — Failover that only delivered every *other* day

This is my favorite, because the bug was *subtle* and the symptom was *weird*.

**Symptom.** During an extended local outage, the cloud backup delivered the daily task — but only on alternating days. Day 1: delivered. Day 2: skipped. Day 3: delivered. Like a metronome.

**Investigation.** The failover logic reads a heartbeat the local node stamps after each successful run; if local has been silent past a ~25-hour window, cloud declares it offline and takes over. So why the oscillation? I looked at *who writes the heartbeat*. When cloud failed over, it was stamping the "local presence" heartbeat too.

**Root cause.** The failover push also stamped the local-presence signal. So after cloud covered Day 1, the heartbeat looked fresh — "local is alive!" — and on Day 2 cloud dutifully skipped. But local was still down, so by Day 3 the heartbeat was stale again and cloud failed over again. The presence signal was lying because the wrong actor was writing it.

**Fix.** Only the local role may stamp the local-presence heartbeat. A failover push does its job and does **not** touch the local heartbeat. Now an extended outage reads as a continuous outage, and cloud covers every day until local comes back.

**Takeaway.** A presence signal must be written *only by the entity whose presence it represents*. The moment a second actor can write "I'm here" on someone else's behalf, your liveness detection is corrupted. This generalizes well beyond failover — any time you have a "last seen" field, guard who's allowed to touch it.

---

## Bug 8 — A momentary 503 cost me a whole day

**Symptom.** One day: no output at all. The upstream model provider had a brief hiccup right when the job ran.

**Investigation.** The logs showed a short burst of `503`s during the daily window. My retry logic gave up after too few attempts, so a transient outage that lasted a couple of minutes turned into a missed day.

**Root cause.** Thin retries. A single scheduled attempt with minimal backoff can't ride out even a short 5xx burst, and a once-a-day job has no second chance.

**Fix.** Harden the retry/backoff: 5 attempts with capped backoff (roughly 20/40/60/90/120s), covering `500/502/503/504/429` and network errors.

```
attempt 1 → 503 → wait 20s
attempt 2 → 503 → wait 40s
attempt 3 → 200 ✓   (delivered on time)
```

**Takeaway.** For infrequent, high-stakes jobs, retries aren't optional polish — they're the difference between "delivered" and "silently missed." And the payoff was real: the hardened logic later rode out an actual 3×-503 event and still delivered on schedule. Backoff earns its keep on the day you forgot it was there.

---

## Bug 9 — The scheduler fired at the wrong hour because UTC

**Symptom.** The cloud failover check, meant to run at 23:00 local, was firing at 07:00 local. Eight hours off, consistently.

**Investigation.** Eight hours is a timezone offset, not a bug in the cron expression. I checked the VM's clock: it was on UTC.

**Root cause.** Cloud VMs commonly default to UTC. My `23 0 * * *` cron was correct — against the *wrong wall clock*. The scheduler was doing exactly what I asked, in a timezone I didn't mean.

**Fix.** Set the VM timezone explicitly to the intended local zone so the cron expression lines up with the real-world time I care about.

```
timedatectl set-timezone <intended/zone>
```

**Takeaway.** A scheduler is only as correct as the clock beneath it. Never assume the host's timezone — set it explicitly, and write schedules against a timezone you've verified.

---

## Meta-lessons: reliability lives in the boring details

Step back from the nine and a pattern shows up. None of these were exotic. Not one was in the "AI" part. Every single one lived in plumbing:

- **Separate config from code.** Then deploying code can't poison production config. (Bug 1)
- **cron carries no environment.** Load it explicitly; inherit nothing. (Bug 2)
- **Pin and match your runtime versions.** "Works on my machine" has a version number. (Bug 3)
- **Know your database's exact rules.** Upsert arbiters, index types — read the fine print instead of assuming. (Bug 4)
- **Make identity stable and origin-aware in sync.** Mutating identity means multiplying records. (Bug 5)
- **Keep slow work off the request path.** Bounded responses, eventual work. (Bug 6)
- **Presence signals belong to their owner.** Only the subject writes "I'm here." (Bug 7)
- **Retry with backoff for anything that matters and runs rarely.** (Bug 8)
- **Set timezones explicitly.** Schedulers trust the clock blindly. (Bug 9)

The through-line: the model call was never the hard part. Keeping a free, two-node system correct, secure, and cheap through nine real failures was the hard part — and the fixes were almost all about discipline in the unglamorous layer. Config hygiene, environment, runtime parity, database semantics, identity, request-path discipline, signal ownership, backoff, clocks.

That's where reliability actually lives. Not in the clever bits. In the boring ones you were tempted to skip.

---

## Takeaway

If you're building something small and constrained — a side project, a home lab, a lean production service — resist the urge to treat the plumbing as beneath you. The constraints ($0, don't break prod) didn't make the system worse; they forced the discipline that made it reliable. Nine bugs later, it's run at zero cost, survived a multi-day failover with no duplicate output, and shipped a disciplined release history.

Boring is a feature.

*Code & full case study: https://github.com/arielchangdev/angelina-finance-agent*
