# Prompt 09 — The crash-brief remainder: memory, the write path, and the exclusive hold

> **Scope:** `src/scheduler/`, `src/database/writer.py`, `src/api/*` handler shapes, the memory budget.
> **Gated on:** nothing. Every slice here is buildable now.
> **Sequencing:** never concurrent with prompts 07 or 08. Its S1 is the single largest measured defect class
> still open in the backend.

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
