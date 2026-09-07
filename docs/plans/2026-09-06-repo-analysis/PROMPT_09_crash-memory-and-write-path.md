# Prompt 09 — The crash-brief remainder: memory, the write path, and the exclusive hold

> **Scope:** `src/scheduler/`, `src/database/writer.py`, `src/api/*` handler shapes, the memory budget.
> **Gated on:** nothing. Every slice here is buildable now.
> **Sequencing:** never concurrent with prompts 07 or 08. Its S1 is the single largest measured defect class
> still open in the backend.

> ### STALENESS SWEEP, 2026-09-07 — five of the seven slices below were ALREADY BUILT
>
> Executed against `main` @ `690920e2`. Read this before the slices: the prompt's own status
> text was a claim, and the tree disagreed with it on five counts. Verdicts, each with the
> anchor that proves it:
>
> | slice | verdict | the anchor that settles it |
> |---|---|---|
> | **S1** — 56 `async def` handlers + the AST guard | **was genuinely open; BUILT 2026-09-07** | count re-derived by parsing signatures: 56, exactly as recorded. Now 4 — see below |
> | **S2** — the lock-state cache | **ALREADY BUILT** (PR-10, `d447fe6d`, 2026-09-03) | `src/database/connect.py:394-437` — `main_header_state` + `invalidate_header_cache`, with BOTH belts (per-mutator invalidation and a 5 s TTL); reached from `src/api/unlock.py:53` |
> | **S3** — the exclusive hold's remaining entry points | **ALREADY BUILT** (S6.1, 2026-09-03) | `src/analytics/serve_gate.py:80 exclusive_verdict()`, consulted by BOTH `rollup_serve._build_and_swap` and `map_serve._build_and_swap`. Its docstring already records the briefing-recompute non-extension for the reason this prompt gives |
> | **S4** — the memory budget and the honest decline (R1/R2) | **ALREADY BUILT** (S1.1–S1.5, 2026-09-02/03) | `src/config/memory_budget.py` (tiers, DuckDB `memory_limit`+`threads`), `src/config/machine_floor.py` (`machine_floor`/`scan_budget`/`capped_workers` + override), `src/scheduler/release.py`, `src/monitoring/swap.py`, `renderMachineFloor` in `app-sources.js`, `docs/USER_MANUAL.md:1713` (`systemd-run … MemoryMax`) |
> | **S5** — the two `SQLITE_BUSY_SNAPSHOT` call sites | **ALREADY BUILT** (S2.4, 2026-09-02) | `src/discovery/channels.py:528-531` (`with write_lock(), session.begin_nested():` — the gate taken BEFORE the first read) and `src/analytics/source_topics.py:110-121` (same shape) |
> | **S6** — the WAL inference in three places | **ALREADY BUILT** (S0.1, 2026-09-02) | `src/monitoring/forensics.py:386-455` (three states, and `absent` now says NOTHING can be concluded), `src/monitoring/p0_validation.py:570-608`, `docs/product/P0_VALIDATION_RUNBOOK.md` §8.2 ("What `absent` does not prove") |
> | **S7** — PRH-23, the inline first-run preflight | **was genuinely open; BUILT 2026-09-07** | was `src/scheduler/runner.py:1997-2020` |
>
> **The half-shipped one, named as §2 of the working mode requires.** S3.6 shipped as
> PR-10's third slice, and its commit message describes only the lock-state cache. The
> handler conversion — the larger half, and the one the prompt calls the largest measured
> defect class still open — was not in that diff. `shipped.csv` carries no `S3.6` row at all,
> which is why neither half showed as done.
>
> **What S1 turned out to be, once counted rather than assumed.** 51 of the 56 had no
> `await` anywhere in their bodies — pure synchronous handlers that were `async def` by
> habit. Those are now plain `def`. Of the remaining 5: two (`import_prices_csv`,
> `import_csv`) genuinely await the upload stream but were doing their DB work on the loop
> afterwards, and now hand it to `run_in_threadpool`; one (`import_pdf_folder`) took a JSON
> body and awaited nothing but its own threadpool hop, so it became a plain `def`; and
> `import_newsletters` — whose own test already claimed it ran off the loop — still did a
> get-or-create (which COMMITS) and a rollback on the loop. Final count: **4**, each of
> which awaits the request stream, and none of which touches its session on the loop.

## 0. Working mode

Read `_WORKING_MODE.md`, then `docs/design/AUTONOMOUS_SESSION_BRIEF_2026-09-02_CRASH_ROOT_CAUSE.md` in full,
then the CLAUDE.md entry **"SYSTEMATIC CRASHES ACROSS FOUR MACHINES"** with its eight rulings.

Fourteen PRs of that brief shipped. What did not is recorded honestly in the same place, including three
items the executing session refuted rather than built — do not rebuild a refuted item without new evidence.

## 1. Slices

### S1 — S3.6: fifty-six `async def` handlers still take `Depends(get_db)`

Counted 2026-09-06 by parsing the signatures, not by grep: **56** across `src/api/`, of which
`source_management.py` holds **50**, `ingestion.py` 3, and `main.py`, `commodity.py` and `source_io.py` one
each. There is **no AST guard** preventing the fifty-seventh.

Why it matters is recorded twice in the Lessons list and once in a field report: a FastAPI `async def`
handler runs **on** the single event loop, so heavy synchronous DB work inside it — and every one of these
does DB work, through the SQLCipher codec — freezes the entire single-worker server for its duration. Every
other request stalls, the task manager included, and the app looks hung. This is the same family as the
unlock freeze and the restore-preview freeze.

The fix is mechanical (`async def` → plain `def`, letting Starlette use the threadpool, or
`run_in_threadpool` the body) and has one recorded trap: converting a handler breaks any test that slices its
source on the literal anchor `"async def <name>("`. Grep the test tree before each conversion and prefer an
async-agnostic anchor. `@limiter.limit` works on a sync `def`.

Finish with the AST guard, so the count cannot climb again.

### S2 — The lock-state cache

`main.py`'s `_lock_gate` is uncached, so the lock state is re-derived per request. It is the other half of
S3.6 and it is cheap.

### S3 — The exclusive hold's remaining entry points

"Gate every entry point" has now recurred four times in this codebase, each time because the fix was written
while reading one caller. The recorded fourth was the two **rollup builds**, which are kicked from a SERVE —
by any HTTP read that finds the change gate open — so they never appear in a list of "background work" and a
whole-corpus columnar rebuild is the heaviest thing the process does outside a pass.

Before adding any hold, grep for what **starts a thread**, not for what is scheduled. And use
`exclusive_window()` (re-entrant, restores the flag to what it found), never the boolean `hold_exclusive()`
pair directly — a nested caller using the pair clears an outer restore's claim on its own release.

One named non-extension: the briefing recompute deliberately does **not** decline under the hold, because the
Home poll is user work.

### S4 — The memory budget and the honest decline (R1/R2)

Below roughly 4 GB of RAM the app should reduce **and** decline: apply a small-RAM budget (about two pooled
connections, ~16 MiB page cache, no in-memory columnar rollup) and decline the whole-corpus background scans
by default — each refusal stating the real numbers, with a visible translated caveat and an override.
Collection keeps running. Never a hard block; the AI hardware gate is the precedent and it already refuses on
this exact box while saying why.

R2's half: the app caps its own resident budget and actually **releases** when paused, accepting slower
collection on small machines; and the manual documents the operator's real ceiling (a cgroup `MemoryMax`),
which converts a desktop freeze into a clean restart with the corpus intact.

### S5 — The `SQLITE_BUSY_SNAPSHOT` call sites

The fleet's most frequent error (234, 144 and 82 lifetime across three bundles), and it is reproducible: a
`begin_nested()` savepoint taken **outside** a transaction is a `BEGIN DEFERRED`, so a read inside it takes a
snapshot, a concurrent commit invalidates it, and the later write fails **instantly** — the busy handler is
not invoked while a read transaction is open, so the 30-second `busy_timeout` buys nothing. Rolling back
before `begin_nested()` does **not** fix it; the snapshot is taken by the reads inside the savepoint. The fix
is to hold `write_lock()` across the read-then-write at the two identified call sites (R6: targeted; do not
change the engine's transaction mode in this batch).

### S6 — The WAL inference, which is wrong in three places

Unlock's own verify connection is the last to close, so SQLite checkpoints and **deletes** the `-wal` before
the probe reads it. `forensics.py`, `p0_validation.py` and the P0 runbook §8 all read "no WAL" as evidence of
a clean shutdown when it is an artifact of the probe's own ordering. The three-state sentinel was fixed on
2026-08-12; the **inference built on it** was not. Correct all three, and say what each shutdown kind
actually tests.

### S7 — PRH-23: first-run preflight still runs inline

In `src/scheduler/runner.py`, rather than as a visible job. Small, and it is one of the paths that makes a
first launch look stalled.

## 2. Verification

S1 needs a before/after on the same endpoint under a concurrent second request — the property is that the
second request is served, not that the first is faster. S4 and S5 need a reproducer each before the fix.
Mutation-check every guard by name.

## 3. Scope fence

Do not change the engine's transaction mode. Do not add a queueing semaphore in `get_db` (refuted). Do not
add an automatic power-profile switch (refuted). Do not touch the merge windowing (prompt 08).
