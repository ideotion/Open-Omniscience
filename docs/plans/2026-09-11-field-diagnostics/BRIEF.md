# Field diagnostics brief — 2026-09-11

Source: the operator's `oo-all-diagnostics-20260911-154750` archive (72 members) plus the
`20260911_OOS_*` side files and the session-forensics text export. The bundle is the
maintainer's own field data and is **not committed here** — the hosting stance forbids it.
Only aggregate readings and public catalogue domains are quoted below.

## Vintage, and the gate that follows from it

- Bundle run window: `started_at 2026-09-11T15:48:00` → `ended_at 2026-09-11T16:25:31`
  (`manifest.run`), `app_version 0.3.0`, `schema_head b3e77a91c5d4`.
- Newest merge on `main` when this brief was written: `0628ae21`, 2026-09-11 15:20 +0200.
- So the bundle was produced ~28 minutes after the newest merge — but that does **not**
  prove the running binary contained it. The operator's checkout may be older.

**Vintage is unproven in both directions. Therefore: re-read every named `file:line` on
current `main` before writing a fix.** A defect that is already gone is closed as
already-fixed with the commit that fixed it — never "fixed" twice. A defect that survives
in a new shape is re-described against current `main` first. The diagnostics *numbers*
remain valid field evidence either way; the *code* is what must be re-checked.

Re-verified against `main` during triage (live, not stale):
`src/discovery/channels.py:506` · `src/scheduler/runner.py:577` ·
`src/static/app-core.js:1077` · `src/config/memory_budget.py:60` ·
`src/config/machine_floor.py:172` · `src/api/diagnostics.py:3694` vs `:215` ·
`src/database/session.py:97`.

## The machine

`mem_total_mb 4093.8` · Qubes VM (`Linux-6.18.46-1.qubes.fc41.x86_64`) · Python 3.13.5 ·
corpus 1,341,182 articles / 86,470 sources / 11,003,661 keywords · `db_bytes` 27.7 GB ·
data folder 80.8 GB · `collect_parallelism 50`, `mode crawl`, `continuous`,
`collect_rate_mode maximum`.

## The stall cascade — one causal chain

Every link is measured by the app's own instruments.

1. **`run_discovery` holds the single-writer gate across a whole-corpus scan.**
   `src/discovery/channels.py:506` records the deliberate S2.4 change — "the gate is taken
   BEFORE the first read, not around the write" — which fixed a real `SQLITE_BUSY_SNAPSHOT`
   bug (234/144/82 lifetime occurrences on three field machines). Its cost was never priced.
   Measured now: pass-tail phase `discovery` **1,590,907 ms (26.5 min)**; gate
   `busy_share 0.7936`, `max_hold_s 1329.21`, `max_wait_s 1840.35`, `total_wait_s 3164.94`,
   **7 grants / 6 contended** in a 2,330 s window.
2. **Workers block on the gate while holding a pooled connection** (ordering is
   connection → gate). `SAVEPOINT sa_savepoint_23` measured at **664,207 ms**, `sa_savepoint_5`
   at 660,456 ms, `sa_savepoint_14` at 510,360 ms — a SAVEPOINT cannot execute for eleven
   minutes; the timing is the gate wait inside the statement.
3. **The pool (6+2=8) drains.** All eight slots held, oldest first: `AnyIO worker thread`
   2193.8 s · `oo-scheduler` 2099.7 s · `oo-collect_0/1/5` ~2075 s · `oo-collect_3` 731.3 s ·
   `bgjob-all-diagnostics` 676.8 s · `oo-collect_6` 192.2 s.
4. **Requests wait `pool_timeout` 30 s, then 500.** 160 of 187 recorded stalls are
   `GET /api/scheduler/activity` at status 500; 732 frontend errors, all `fetch-5xx`;
   `performance.json` and `schema-drift.json` could not run at all.
5. **The client amplifies it.** `app-core.js:1077` arms the next tick without awaiting
   `_pollVitals()`, so polls stack: the watchdog caught five concurrent
   `/api/scheduler/activity` requests spaced 6.0 s apart — exactly the closed-panel cadence.
   `p50 26.6 ms` against `p95 30,044.7 ms` over n=234.

**Correction to an earlier read:** this was first characterised as transient contention that
recovered. It is not — holds run to 36 minutes.

## Findings

See the session task list for the full set with per-finding evidence. Headline items:

| Severity | Finding |
|---|---|
| P0 | `run_discovery` holds the write gate across a 26-minute scan |
| P0 | Workers hold a pool slot while waiting on the gate |
| P0 | **932 of 2161 judged sources silently demoted** `qualified`→`unqualified` — reuters.com, apnews.com, afp.com, efe.com among them; `select_sources` scrapes qualified only |
| P0 | `keyword-log-digest.json` uncapped: **73.2 MB**, **+3.4 GB RSS** on a 4,093.8 MB machine — the archive's upload failure and the likeliest OOM |
| P1 | A read transaction open **17.4 hours**, pinning the WAL |
| P1 | 51.6 GB of `pre-restore-*.db` staging beside an orphan scanner reporting "none found" |
| P1 | Incremental vacuum reclaims 1 page of 2000 with 2.2 GB free |
| P1 | 89.6% of the keyword table orphaned (9,863,504 / 11,003,661) |
| P1 | `counter_drift` reports all-clear after `checked: 0` |
| P1 | Snapshot recorder writes ~1.9 samples/day while labelled "hourly" |
| P2 | RAM tier boundary: 4093.8 < 4096 puts a nominal 4 GB box in the sub-4 GB tier |
| P2 | Capacity learner never records; memory guard never engaged at 101%-of-RAM peak |
| P2 | O(n) `count(*)` on 11M-row tables on the stats hot path (4.4–6.1 s each) |
| P2 | Insights/briefing p95 ≈ 60 s = 2× `pool_timeout` |
| P2 | Language auto-cleanup step records a bare `"error"` every run |
| — | Split the diagnostics archive into size-bounded volumes (maintainer request) |

## Rules for the work

- **One PR.** All of it lands on `claude/comprehensive-app-audit-i6hmoc`.
- Ledger protocol applies: `shipped.csv` rows per rule (5a), lessons to `LESSONS.md`,
  pending rulings to `OPEN_QUEUE.md`, and the `CLAUDE.md` line ceiling re-measured if touched.
- Anything needing a maintainer ruling is **recorded, not guessed** — in particular the
  polled-GET admission cap, which `OPEN_QUEUE.md` PROMPT 09 already holds as PENDING and
  whose sizing measurement this bundle now supplies.
- `pytest -q` green; ruff over `src/ tests/`; `node --check` after any UI edit; locales 100%.
