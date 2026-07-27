# Hardware Diagnostics Comparison — 2026-07-26

**Executing session: start with the operating manual, not this doc** —
[`AUTONOMOUS_SESSION_BRIEF_2026-07-26_EXECUTION_PLAN.md`](AUTONOMOUS_SESSION_BRIEF_2026-07-26_EXECUTION_PLAN.md)
carries the slice table, sequencing, file-collision map, risk classes, skeptic mandates, and
verification gates; this doc is the fix-specification REFERENCE it routes into (§1.1, §2.1,
§6.1, §7.1, §8.1, §9.1).

**Status:** investigation complete, precise fix specifications complete, nothing built. Seven
`all-diagnostics` exports, one per hardware instance, captured within a ~3-hour window on
2026-07-26 (one instance re-exported ~8 hours later at a much larger corpus size — see instance
1fba378c below), analyzed by seven independent deep-dive agents each scoped to one instance's
directory, then synthesized. This is the companion analysis to the field-remarks brief
([`AUTONOMOUS_SESSION_BRIEF_2026-07-26_FIELD_REMARKS.md`](AUTONOMOUS_SESSION_BRIEF_2026-07-26_FIELD_REMARKS.md)).
An eighth zip (`4f21a37c`, dated 2026-07-10) was excluded — it predates the current
diagnostics-bundle format entirely (no hardware/corpus/run header, only 17 of the current 40+
member files) and isn't comparable.

**Every finding below is cited to a specific file + field from a real export.** Where a pattern
recurs across instances, it is called out explicitly as such — recurrence across independently
provisioned hardware is what makes a finding structural rather than a one-machine fluke.

**This revision (same day) upgrades every buildable finding from "here's the problem, here's a
direction" to a precise, code-cited, directly-implementable fix specification** — exact functions
to add/edit with file:line anchors, exact proposed code shapes, and exact tests to add — each
produced by a dedicated deep-dive investigation against the live `main` tree (not inferred from
this doc's own earlier prose). It also folds in two pieces of new evidence gathered the same day:
an 8-machine parallel-instance confirming experiment (§11) and a live terminal-log capture of the
still-unfiltered `htmldate.meta` noise, which sharpened Finding 8 into a precise fix (§8).

---

## Quick-reference table

| Instance | CPU | Cores | RAM | Swap | Disk free | Schema | Articles | Export wall | `collect_perf` verdict | WAL vs 64MB limit |
|---|---|---|---|---|---|---|---|---|---|---|
| **1fba378c** | i7-13620H | 6 | 15.3 GB | ~1 GB | 172 GB | newer (`4fc4be4dffef`) | **700,522** (the main DB) | 2387s | writer-bound (strong indirect evidence — no explicit field found, but 25h+ aggregate writer-wait) | not captured this run |
| **0bfa36df** | i7-13620H | 4 | 10.4 GB | ~1 GB | 13.27 GB | older (`95120f685050`) | 43,796 | 829s | **writer-bound** (explicit) | 912 MB — **13.6×** |
| **4663bbc5** | i7-13620H | 4 | 10.4 GB | ~1 GB | 11.71 GB | newer (`4fc4be4dffef`) | 42,076 | 850s | writer-bound (strong — a single fetch stuck 112+ min at that moment) | 1.77 GB — **26×** |
| **243c5a14** | i7-1065G7 | 2 | 5.63 GB | ~1 GB | 11.43 GB | older (`95120f685050`) | 30,623 | 901s | no explicit classifier field this build; strong indirect write/WAL contention | 1.95 GB — **29×** |
| **6557d2cf** | i7-1065G7 | 2 | 5.55 GB | ~1 GB | 15.36 GB | newer (`4fc4be4dffef`) | 30,107 | 749s | **writer-bound** ×2 passes (explicit) | not quoted exactly; page_size/auto_vacuum confirm newer-corpus defaults |
| **c1e1a30d** | Pentium Silver N5030 | 4 | 3.92 GB | 8.62 GB | 74.1 GB | older (`95120f685050`) | 25,929 | **1432s — slowest export of all 7** | **writer-bound** (explicit) | 4.43 GB — larger than the machine's **entire RAM** |
| **ea11e68c** | AMD 3020e | 2 | 3.46 GB | 7.6 GB | 33.65 GB | newer (`4fc4be4dffef`) | 16,070 | 702s | **memory-bound** (explicit — the only instance where memory, not the write gate, is the classified bottleneck) | grew to 3.07 GB (~48×) before a single 21.8-minute catch-up checkpoint |

Two "twin pairs" share identical CPU/core-count/RAM but different `schema_head` (a different app
checkout, not the same VM run twice): `0bfa36df`↔`4663bbc5` (i7-13620H 4c/10.4GB) and
`243c5a14`↔`6557d2cf` (i7-1065G7 2c/5.6GB). `1fba378c` is confirmed to be the maintainer's own
"main database" — its article/keyword counts (700,522 / 6,914,218) match exactly.

---

## 1. UNIVERSAL FINDING — WAL/checkpoint starvation, on all 7 instances, no exceptions

Every single instance's `storage-composition.json` shows the WAL file far exceeding the
configured 64 MiB (`journal_size_limit: 67,108,864`) checkpoint target, and the app's own
diagnostic self-flags it identically on every instance: *"the -wal is much larger than
journal_size_limit — a checkpoint may be starved (a long-lived reader blocks it), the workload's
known WAL-growth hazard."* Magnitudes:

- `ea11e68c` (weakest, smallest corpus): 264 MB WAL — 4× the limit
- `0bfa36df`: 912 MB — 13.6×
- `4663bbc5`: 1.77 GB — 26×
- `243c5a14`: 1.95 GB — 29×
- `c1e1a30d`: **4.43 GB — larger than the machine's entire 3.92 GB of RAM**

This is not a per-machine fluke — it recurs on strong hardware (i7-13620H, 10.4–15.3 GB RAM) and
weak hardware alike, on both schema generations, across a corpus-size range of 40×. The
consequences are concrete and consistent everywhere it was measured:

- `c1e1a30d`: `PRAGMA wal_checkpoint(TRUNCATE)` and single-row `UPDATE`s regularly took
  seconds-to-tens-of-seconds; the `insights_map` self-test probe got **44% SLOWER on its warm
  rerun** (32,267ms → 46,511ms) — a textbook cache-thrashing signature, since the combined DB+WAL
  working set (~5.4 GB) cannot fit in this machine's 3.92 GB RAM.
- `ea11e68c`: `debug-bundle.json`'s `scheduler.recent_runs[].hygiene.wal_checkpoint` trail shows
  the WAL climbing continuously across 8 consecutive passes (708 MB → 3.07 GB) with `busy: 1` on
  every checkpoint attempt (unable to truncate), finally resolved by a single **21.8-minute**
  catch-up pass (`duration_s: 1307.41`) whose checkpoint dropped the WAL from 3.07 GB to 0 in one
  shot. This directly correlates with the app's own OOM circuit-breaker
  (`MEMORY GUARD ENGAGED`) firing **8 separate times in ~7 hours** on this instance
  (`avail_mb` 215–253 MB at the threshold `<=256 MB`), one of which (07:00:42→07:04:29) sits
  inside the giant-checkpoint window.
- Every instance's single-row `INSERT`/`UPDATE` statements (by primary key, on a covering index —
  the `EXPLAIN QUERY PLAN`s are confirmed healthy everywhere, `full_scan: false` on every sampled
  case, so this is NOT a missing-index problem) show averages of 2–11 seconds and maxima of
  15–341 seconds for what should be sub-millisecond operations. This is the load-bearing evidence
  for the `writer-bound` verdict on 5 of 7 instances — the "writer-bound" classification and the
  WAL-starvation mechanism are almost certainly the same underlying phenomenon: a long-lived
  reader (the diagnostics export's own heavy analytic scans, or a concurrent in-memory
  `rollup_serve` rebuild — confirmed `building: true` at capture time on 4 of the 7 instances)
  blocks the periodic checkpoint from truncating, the WAL balloons, and every subsequent write
  (and, on the weakest machine, every read too) pays a growing tax until the next successful
  checkpoint.

**This is the single highest-value structural finding across the whole batch** — it's universal,
it now has an evidenced causal chain (below), and it plausibly explains a large share of every
other performance symptom in this doc, including the `writer-bound` bottleneck class (§3) and a
large share of the `/api/database/countries` latency tail (§2, which reads through the same
I/O-starved store).

### 1.1 Precise fix specification

**Root cause, confirmed end-to-end (not a config problem):** the WAL bloat is caused by **two
background "reader" code paths that open one SQLAlchemy `session_scope()` and hold it open across
many sequential, unbounded read queries over the whole corpus** — for tens of minutes at real
scale. While either is open, SQLite's WAL checkpoint mechanism (both the automatic 1000-page
checkpoint and this app's own `TRUNCATE` checkpoint) cannot reclaim WAL space past that reader's
snapshot boundary, so every commit from ongoing parallel collection just appends to the WAL,
unbounded, until the reader closes — at which point one giant checkpoint drains the backlog
(matching the observed 15–341s single-row write stalls and the 21.8-minute giant checkpoint → OOM
guard cycle).

**(a) Where `journal_size_limit` is set** — `src/database/session.py:124-137`, inside the
SQLAlchemy `"connect"` event listener `_sqlite_pragmas`:
```python
# src/database/session.py:133-137
try:
    wal_mb = int(os.getenv("OO_WAL_SIZE_LIMIT_MB", "64"))
except ValueError:
    wal_mb = 64
cursor.execute(f"PRAGMA journal_size_limit={wal_mb * 1024 * 1024 if wal_mb > 0 else -1}")
```
64 MiB by default. This PRAGMA only caps the size the `-wal` is **truncated back to after a
successful checkpoint** — it never bounds growth *during* a long transaction / reader-starvation
window (the code's own comment at `session.py:124-132` already says this correctly). Lowering the
number would make no measurable difference — the ceiling is never *reached and enforced*, it's
being bypassed entirely because a checkpoint literally cannot complete.

**(b) Where checkpoints are triggered** — `wal_autocheckpoint` is never explicitly set anywhere in
`src/database/` (repo-wide grep confirms it), so SQLite's automatic PASSIVE checkpoint (1000-page
threshold) is subject to the same reader-blocking below. The app's own checkpoint,
`checkpoint_wal()` (`src/scheduler/hygiene.py:163-241`), has exactly **one** production call site,
at the tail of every scrape pass (`src/scheduler/runner.py:1485-1494`, `run_pass_hygiene()`):
`PRAGMA wal_checkpoint(TRUNCATE)` under `write_lock()` (`hygiene.py:208-212`), **rate-limited to
once per `OO_WAL_CHECKPOINT_MIN_S` (default 300s)** and bounded to a **5000ms busy-wait**
(`OO_WAL_CHECKPOINT_BUSY_MS`, `hygiene.py:151-160,199,211`). If blocked by a reader it returns
`busy=1` after 5s and gives up silently (INFO log only, `hygiene.py:237`) — **never retried until
the next pass boundary, at least 300s later.**

**(c) The two long-lived readers, both confirmed present:**

1. **`rollup_serve` in-memory rollup rebuild** — `src/analytics/rollup_serve.py:166-199`,
   `_build_inmemory_and_swap()`:
   ```python
   with session_scope() as s:
       token = serve_gate.change_token(s)
       columnar.build_keyword_daily(con, s)   # streams the WHOLE corpus, one open session
       ...
   ```
   `build_keyword_daily` (`src/analytics/columnar.py:737-803`) issues **one SELECT over the
   entire `keyword_mentions` table** streamed via `result.fetchmany(batch_size)` (`columnar.py:
   761-774`) — the underlying read transaction stays open for the *entire* streaming duration
   (20.9M–40.6M mentions per these field exports). Triggered by `_trigger_build_async()` roughly
   every `rollup_serve_ttl_s()` (Optimized default 900s / 15 min). **Corroboration:**
   `columnar.json: rollup_serve.building: true` was observed mid-flight on multiple of the 7
   exports — direct proof the transaction was genuinely open at capture time.

2. **The post-pass briefing refresh** — `src/scheduler/runner.py:1557-1602`,
   `_refresh_briefing_async()`, kicked off as a background thread at the tail of every pass:
   ```python
   with session_scope() as session:
       refresh_briefing(session)
   ```
   `refresh_briefing()` (`src/briefing/service.py:228-269`) runs, on that **one** session,
   sequentially: `evaluate_watches`, then `run_all()` — **every registered Home-card producer, one
   after another, on the same session** (`src/briefing/registry.py:41-87`, the loop at
   `registry.py:54`) — then `warm_cache()` (`service.py:263-268`), which itself, still on the same
   session, runs `refresh_persisted_read_model`, `rollup_serve.refresh`/`map_serve.refresh`,
   `poll_cache.refresh`, and full corpus-wide `trending_windows`/`top_terms` aggregations
   (`src/api/insights.py:1362-1419`). Field-measured cost for just two producers in isolation:
   home-cards up to ~268–400+s, leads-quality ~268s on a 2-core box (`runner.py:1561`) — the
   *production* path runs strictly more work than either isolated measurement, on one session held
   open the whole time. `_bg_refresh()` (`src/briefing/service.py:52-66`) is a second call site
   with the identical shape, for the interactive "Loading the briefing…" HTTP path.

**Why this starves WAL specifically:** `session_scope()` (`session.py:333-345`) uses
`autocommit=False`/`autoflush=False` and commits once, at block exit. Under SQLite, the DBAPI
connection opens an implicit read transaction on the first statement and holds it until
commit/rollback/close — so for the whole duration of `run_all()`+`warm_cache()` or the whole
streamed `keyword_mentions` scan, the connection pins one fixed read snapshot, and neither the
automatic PASSIVE checkpoint nor `PRAGMA wal_checkpoint(TRUNCATE)` can reclaim WAL space past it.
Once the reader finally closes, the next checkpoint attempt (still gated to once per 300s) has to
copy the *entire* accumulated backlog in one pass — the observed single 21.8-minute checkpoint,
run under `write_lock()` (blocking every other write for its whole duration), plausibly the
trigger for the correlated `MEMORY_GUARD_ENGAGED` events on weak machines.

A **third, secondary contributor**: `run_idle_maintenance()` (`src/scheduler/maintenance.py:
34-90+`) also runs several sequential steps (counter reconcile, keyword cleanup, incremental
vacuum, hourly snapshot) inside one `session_scope()` — smaller than (c1)/(c2) since it's
deadline-budgeted and mutually exclusive with a collect pass, but worth checking/instrumenting in
the same pass.

**Recommended fix — restructure the long readers into many short-lived transactions (root-cause
fix; do this, not just a shorter checkpoint interval):**

1. **`run_all` → a commit/checkpoint opportunity between producers.** In `src/briefing/
   registry.py:41-87`, each producer's `try` block already isolates it — nothing requires them to
   share one read snapshot. Add `session.commit()` after each producer's `on_progress` callback
   (`registry.py:63-67`; a no-op for a pure-read producer beyond releasing the transaction), or
   restructure the callers (`runner.py:1583-1592`, `service.py:52-66`) to open a fresh session per
   producer instead of one `session_scope()` around the whole call.
2. **`warm_cache`'s five steps → each releases the transaction.** `insights.py:1362,1372,1386,
   1406-1419` are already structurally independent and should not share `refresh_briefing`'s outer
   transaction — either commit between them or have `warm_cache` open its own `session_scope()`
   per step.
3. **`build_keyword_daily`'s streaming loop → periodic commit.** In `columnar.py:761-774`, after
   every `batch_size` (50,000) chunk is flushed into DuckDB, call `session.commit()` on the
   SQLAlchemy session before resuming the fetch. This needs empirical verification that a still-open
   `SELECT` cursor survives a commit cleanly on this connection (in the same self-verify spirit as
   this repo's `pagesize_bench` probe pattern); if it does not, re-issue the SELECT with a keyset
   cursor (`article_id`/`id` > last-seen) per chunk instead of one held server-side cursor. **This is
   the single highest-value change** — the one place doing tens of millions of row reads in one
   unbroken transaction.

This turns two multi-minute-to-tens-of-minutes readers into many sub-second-to-low-second readers,
giving the existing 300s-cadenced `checkpoint_wal()` (and SQLite's own 1000-page auto-checkpoint)
real, frequent opportunities to complete, so the WAL never has the multi-GB runway to accumulate.

Shrinking `OO_WAL_CHECKPOINT_MIN_S` (e.g. to 60s) alone is a reasonable **secondary** mitigation
(more frequent partial attempts, smaller worst-case backlog) but is **not sufficient** on its own —
as long as (c1)/(c2) can hold a transaction open for many minutes, a shorter retry just burns its
5s busy-timeout every minute and fails every time during that window.

**Watchdog (defense-in-depth, in addition to, not instead of, the restructuring above):** model on
the existing `MemoryGuard` (`src/scheduler/memguard.py:81+` — measured-readings-only, hysteresis
both ways via `trip_after`/`resume_after`, env-tunable thresholds, visible state on the scheduler
status payload, never holds a lock while sampling). Add a `WalGuard`: a lightweight periodic check
(piggyback the scheduler tick, or a small dedicated daemon thread, every 30–60s) reading `wal_bytes`
via the already-existing `storage_composition()` (`src/monitoring/storage.py:104-112`, which
already computes `wal_bytes` vs `journal_size_limit` and emits the `wal_note` self-diagnostic
string). Trip condition: `wal_bytes > N × journal_size_limit` for `trip_after` consecutive samples.
Action on trip: call `checkpoint_wal(force=True)` **bypassing the 300s rate limit** — the
`force=True` escape hatch already exists (`hygiene.py:163-164,188-194`) but nothing currently uses
it outside tests (`tests/test_wal_checkpoint.py:62-69,`). Should still go through `write_lock()` as
today, with a longer, dedicated busy-timeout (`OO_WAL_GUARD_BUSY_MS`) since this is an explicit
escalation path, not a routine attempt. This does not fix the root cause by itself (a forced
checkpoint while the reader is still open will likely still report `busy=1`) — its value is purely
a second, independent monitoring/forcing line, cheap and low-risk. **Ship items 1–3 regardless of
whether this watchdog is built.**

**Interaction with the already-shipped S4.1 duty-cycle fix (do not revert it):**
`refresh_briefing`'s move into a background thread that overlaps the *next* pass (`runner.py:
1557-1578`, the "S4.1" fix, 2026-07-23) was the right call for throughput — this same field
diagnostics batch independently confirms it's working (§4). But it is also, per this
investigation, the change that let the WAL-starving background reader start overlapping *every
subsequent pass boundary's checkpoint attempt* instead of always finishing before the next pass
even started. This is not a bug in S4.1 and nothing here suggests reverting it — restructuring the
readers into short-lived transactions (rather than serializing/blocking them against the
checkpoint) is exactly the shape of fix that preserves S4.1's throughput win while closing the WAL
gap.

**Tests to add** (build on the exact patterns in `tests/test_wal_checkpoint.py` and
`tests/test_wal_ceiling.py` — reuse `_wal_engine`, `_fresh_cadence`, and the raw-`sqlite3`
"hold a `BEGIN` open" reader helper already used by
`test_active_reader_yields_honest_partial_result_not_an_exception`):

1. **Regression test proving the root cause first** (write it, watch it fail on current `main`,
   per this repo's own "stash-verified" discipline) — new `tests/test_wal_reader_starvation.py`:
   a real file-backed WAL engine; a generator mimicking `build_keyword_daily`'s shape (a
   `session.execute(SELECT ...)` held open across a `fetchmany` loop with a deliberate
   `time.sleep()` between chunks) while a second thread does many small commits and periodically
   calls `checkpoint_wal(engine=eng, force=True)` on a 300s-style cadence. Assert `wal_bytes`
   (via `storage_composition` or `Path(...).stat().st_size` on the `-wal` file) grows past
   `N × journal_size_limit` while the reader iterates, and every checkpoint call in that window
   returns `busy=1`.
2. **Prove the fixed `run_all`/producer loop releases the transaction between producers:**
   register two fake producers via `src.briefing.registry.register`; the first holds a real read
   cursor open, the second — from a second thread — attempts
   `checkpoint_wal(engine=..., force=True, busy_timeout_ms=200)` concurrently. Once the fix lands
   (commit-between-producers), a checkpoint attempted **between** two producer calls (not
   mid-producer) must succeed (`busy == 0`) even under concurrent writes.
3. **Prove `build_keyword_daily`'s periodic commit doesn't break correctness:** extend the
   existing `keyword_daily_parity` probe (`columnar.py:887-936`) to run `build_keyword_daily` with
   a small `batch_size` (e.g. 3) against a seeded corpus with more rows than that (forcing several
   mid-stream commits), and assert `keyword_daily_parity(...)` still reports `mentions_exact: True`
   and `distinct_upper_bound_holds: True` — a direct guard against the delete-then-reinsert /
   double-counting class of bug this project's own lessons list already warns about repeatedly.
4. **End-to-end "never exceeds N× the ceiling" soak test**, extending `src/testing/
   collect_soak.py` (already calls `run_pass_hygiene()` at `collect_soak.py:195`) or
   `src/testing/scale_bench.py`: seed a corpus large enough to make `build_keyword_daily`/
   `refresh_briefing` take multiple seconds, run several simulated passes with continuous
   background writes interleaved with real `refresh_briefing`/rollup-rebuild calls on background
   threads (as production does), and assert `wal_bytes <= K × journal_size_limit` at every sampled
   point for a small `K` (e.g. 4). Add as `tests/test_wal_bounded_under_concurrent_long_reader.py`
   (or fold into `test_wal_checkpoint.py`) so it runs in CI, not only on manual request.
5. **Negative-space check on the watchdog (if built):** mirror `MemoryGuard`'s own test suite
   (hysteresis both ways — never trips on one transient sample, always resumes once conditions
   clear), plus a test that its forced checkpoint still correctly serializes through `write_lock()`
   (reuse `test_checkpoint_waits_for_the_write_gate_never_runs_beside_a_writer`'s exact pattern,
   `test_wal_checkpoint.py:96-133`) and never fires more than its configured cadence even under a
   persistently-tripped condition.

**Prior-lesson cross-checks (do not contradict):** `hygiene.py:128-134`'s module-header comment
already names this exact hazard class and states the intended mitigation is the between-pass
`TRUNCATE` checkpoint — confirming the checkpoint mechanism was built with the right intent but
never paired with a fix to the long-reader root cause (this spec completes what that docstring
assumed would be sufficient). `storage.py:92-112`'s `wal_note` is the app's own passive
self-diagnosis of exactly this condition — the watchdog above is its natural active counterpart,
not a duplicate. The "writer-bound... 5/7 instances" classification (§3) is fully consistent with,
and likely partly *caused by*, the giant blocking TRUNCATE checkpoints described here — no new
bottleneck-classification work is implied; the classifier is already telling the truth about the
symptom.

## 2. UNIVERSAL FINDING — `/api/database/countries` is catastrophically slow, on all 7 instances

Every instance's `request-latency.json`/`performance.json` shows this one endpoint as the
dominant, or one of the dominant, server-cost items, and it is the **sole cited cause of the K2
KPI "red" verdict on every instance that has a K2 value** (all 7):

| Instance | Calls | p95 | p99 | max | Cumulative time | Share of uptime |
|---|---|---|---|---|---|---|
| 1fba378c | 4,525* | 40,541 ms | — | 60,826 ms | — | — (429/503 status on ~30%) |
| 0bfa36df | 6,655 | 45,594 ms | 68,761 ms | 137,828 ms (2.3 min) | 35,877 s | ~12h of ~30h uptime |
| 4663bbc5 | 6,662 | 25,485 ms | 49,000 ms | 149,405 ms (2.5 min) | 50,812 s | **14.1 hours** |
| 243c5a14 | 11,230 | 8,820 ms | 18,014 ms | 45,213 ms | 39,177 s | **10.9h of 50.6h uptime (21.5%)** |
| 6557d2cf | 6,597 | 8,616 ms | — | 38,500 ms | 24,733 s | **22.98% of uptime** |
| c1e1a30d | 11,029 | 14,237 ms | 29,943 ms | 84,559 ms (84.6s!) | 74,494 s | **~41% of the 50.7h uptime** |
| ea11e68c | 6,503 | 14,459 ms | 28,069 ms | 42,418 ms | 42,930 s (+ its polling-group siblings → 87,682s total) | **81% combined with its polling-group siblings** |

*1fba378c's numbers reflect the map-coverage endpoint, not countries specifically, per that
agent's report — see §2.1's note on `/api/insights/map-coverage`.

This endpoint is polled continuously (roughly every 4–17 seconds on every instance) alongside a
tight group of siblings that are ALSO consistently slow and ALSO consistently polled at the same
cadence: `/api/database/coverage`, `/api/database/figures`, `/api/database/stats`,
`/api/library/overview`, `/api/insights/map-coverage`. The near-identical request counts across
this group on every single instance (e.g. `243c5a14`: all five at exactly 11,230/11,230/11,230/…)
confirm they're polled together by one UI surface — almost certainly the Library/Governments tab
staying open across the whole diagnostics-export window.

### 2.1 Precise fix specification

**Exact query and cost model.** `src/api/database.py:309-365` (`sources_by_country`):
```python
def _compute() -> dict:
    rows = db.query(Source.country, Source.enabled, Source.tags).all()   # line 328
    per: dict[str, dict] = {}
    for country, enabled, tags in rows:
        cc = (country or "").strip().lower() or "(none)"
        slot = per.setdefault(cc, {"sources": 0, "enabled": 0, "tags": Counter()})
        slot["sources"] += 1
        if enabled:
            slot["enabled"] += 1
        for t in (tags or "").split(","):
            t = t.strip()
            if t:
                slot["tags"][t] += 1
    countries = [...]   # per country: sources, enabled, top_tags.most_common(8)
    countries.sort(key=lambda c: (-c["sources"], c["code"]))
    present = {cc for cc in per if cc != "(none)"}
    missing = sorted(c for c in ISO_3166_1_ALPHA2 if c not in present)
    return {"countries": countries, "covered": len(present),
            "total_countries": len(ISO_3166_1_ALPHA2), "missing": missing,
            "missing_names": {c: country_display_name(c) for c in missing},
            "missing_count": len(missing)}

return _cached("countries", _compute, db)   # line 365
```
It scans only `sources` (line 328), no join to `articles`/`keyword_mentions`, with no LIMIT/WHERE
— it must visit every row. **Caching:** `_cached("countries", ...)` uses the shared
`SimpleCache(max_size=8, default_ttl=30)` (`database.py:36`), gated by `_db_change_probe`
(`database.py:42-50`):
```python
def _db_change_probe(db: Session) -> tuple:
    return (db.execute(text("PRAGMA data_version")).scalar(),
            db.execute(text("SELECT total_changes()")).scalar())
```
**`PRAGMA data_version` is DATABASE-WIDE** — it bumps on any commit from *any* connection to the
file (article ingest, keyword-mention writes, qualification-attempt logging, world-discovery
inserts, etc.), so on an actively-collecting install this changes essentially continuously and the
30s TTL cache almost never actually serves a hit.

**The query is a genuine bare table scan, not an index-covered one — verified empirically**
against the real `Source` schema/indexes (`src/database/models.py:378-475`, indexes at 465-475:
`idx_source_domain`, `idx_source_enabled`, `idx_source_priority`, `idx_source_reliability`,
`idx_source_language`, `idx_source_region`, `idx_source_country`, `idx_source_type`,
`idx_source_status`, `idx_source_last_crawled` — none composite, none covering `tags`) via
`EXPLAIN QUERY PLAN`:
```
SELECT sources.country, sources.enabled, sources.tags FROM sources
→ (2, 0, 0, 'SCAN sources')                         # bare scan, no USING INDEX

-- compare, same schema:
SELECT count(*) FROM sources
→ 'SCAN sources USING COVERING INDEX idx_source_last_crawled'   # healthy
SELECT country FROM sources
→ 'SCAN sources USING COVERING INDEX idx_source_country'         # healthy
```
`tags` (`String(500)`) isn't covered by any index, so SQLite must read every row's full base-table
page — a genuine bare `SCAN sources` (this project's own `src/monitoring/slowquery.py` diagnostic
convention classifies exactly this shape — `SCAN <table>` with no `USING` — as the only real
scaling smell). **This is the one query in the polled sibling set that is NOT a covering-index
scan** — the sibling COUNT/GROUP-BY-by-country-alone queries (below) *are*.

Combined with the universal WAL/checkpoint starvation (§1, which inflates the cost of every read
on an I/O-starved store) and a cache invalidated by nearly every write anywhere in the database,
this individually-moderate-cost scan re-runs constantly (`src/static/app.js:7399`'s `loadCoverage()`
fires it, via `Promise.all`, roughly every 16s — `app.js:7571-7572`) against an already-strained
store, producing exactly the fat-tail latencies reported.

**Sibling endpoints — quoted queries and health:**

| Endpoint | File:line | Query | Verdict |
|---|---|---|---|
| `/api/database/stats` | `database.py:105-186` | `COUNT(*)` per table + `Source.enabled`/`status` filters | `SCAN sources USING COVERING INDEX idx_source_last_crawled` — **healthy**, but shares the same DB-wide cache probe, so it also recomputes on nearly every poll. |
| `/api/database/coverage` | `database.py:267-306` | `country_counts_from_session` (`src/catalog/coverage.py:159-166`): `session.query(Source.country, func.count(Source.id)).group_by(Source.country)` | `SCAN sources USING COVERING INDEX idx_source_country` — **healthy, live, covering.** Not the bottleneck in isolation, but polled in the same `Promise.all` burst and shares the cache-thrash problem. |
| `/api/database/figures` | `database.py:191-249` | `COUNT(Article)`, `AVG(Article.word_count)` (idx-backed), `MIN(Article.created_at)`, and `COUNT(*) FROM keyword_mentions` (`database.py:220`, O(n)) | **Live**, but already has its own separate, coarser, time-based (not write-probed) cache: `_FIGURES_TTL_S = 60`, `_figures_cache` (`database.py:191-193,250-265`) — a materially better mitigation than `/countries`'s own. |
| `/api/library/overview` | `src/api/library.py:91-160+` | reuses `database_stats(db)` + small `_by_kind` GROUP BYs on `ArticleAnalysis.kind`/`AiKeyword.kind` | Not a per-country aggregation; own 30s write-probed cache, same DB-wide-probe defect but on unrelated data. |
| `/api/insights/map-coverage` | `src/api/insights.py:1196-1231` | `map_serve.map_coverage(db)`, falling back to `rm.source_country_counts(db)` = `src/analytics/queries.py:970-1035` | See below — already has a partial fix, gated on an optional dependency. |

`queries.source_country_counts` (the live fallback for map-coverage) is architecturally
*heavier* than `/countries`'s own query — a genuine `Source ⨝ Article` join:
```python
art_rows = (
    session.query(Source.country, func.count(Article.id),
                  func.avg(Article.sentiment_score), func.count(Article.sentiment_score))
    .join(Article, Article.source_id == Source.id)
    .group_by(Source.country).all()
)   # queries.py:987-994 — the codec column-order trap class
```

**Already-shipped precedents, exact code:**

*Precedent A — incremental write-time counter (`Keyword.mention_count`/`article_count`).*
`src/database/models.py:909-913`, indexed at `Index("idx_keyword_mention_count", ...)` (line 943);
maintained from the **single** `index_article` chokepoint (`src/analytics/store.py:210`) via
`_apply_keyword_counter_deltas` (`store.py:156-180`); served by `queries.top_terms`'s
corpus-wide branch (`queries.py:299-312`), an index-only scan (own comment: *"never the mention
join that dragged article pages through the SQLCipher codec"*).

*Precedent B — periodic full-rebuild counter, on the exact same table `sources`
(`Source.article_count`).* `src/analytics/store.py:1189-1220`, `reconcile_source_counters`:
recomputes exactly via one `GROUP BY source_id` scan (own docstring: *"CHEAP by design: sources
are few... no cursor/budget needed"*), triggered **unconditionally on every off-peak
idle-maintenance cycle** (`src/scheduler/maintenance.py:65-72`, throttled to `OO_MAINT_INTERVAL_S`
default 300s, mutually exclusive with a collect pass).

*Precedent C — the already-attempted-but-incomplete columnar version, `map_serve.py`.* Its own
docstring: *"the map country GROUP BY was the 12:14 field logs' #1 slow query — 748s total, ~150
s/call, max 211s"* (`map_serve.py:14-16`). Structure: module-level lock/state, a `_same_bind`
bind-awareness guard (`map_serve.py:219-228`), `served()` returns `None` on any miss/cold/error
(falls back live). **Gated on `columnar.duckdb_available()`** — an *optional* `[columnar]` extra
(`map_serve.py:92-100`) — so a core-only install (explicitly first-class-supported per
`database.py`'s own module docstring) never benefits from it, which is why map-coverage is fast on
some field machines and slow on others depending purely on whether `duckdb` happens to be
installed.

**Recommended fix: a periodically-refreshed maintained aggregate — a plain in-memory Python
dict, NOT a DuckDB rollup — refreshed unconditionally on the existing off-peak idle-maintenance
cadence.**

*Why not an incremental write-time counter (like Precedent A):* `Source` rows have no single write
chokepoint — at least 18 distinct, unrelated call sites construct/mutate a `Source` row
(`src/discovery/channels.py`, `src/discovery/cited_sources.py`, `src/api/source_management.py`,
`src/ai_layer/source_tags.py`, `src/api/governments.py`, `src/api/ingestion.py`,
`src/ingest/import_job.py`, `src/ingest/pdf_import.py`, `src/hazards/ingest.py`,
`src/law/catalog.py`, `src/law/corpus.py`, `src/stats/ingest.py`, `src/stats/subscriptions.py`,
`src/wiki/corpus.py`, `src/timemap/locextract.py`, plus boot catalog seeding). An incremental
hook risks a missed site causing silent, undetected drift. This project's own choice for the
closely-analogous `Source.article_count` counter (Precedent B) was periodic full-rebuild, even
though article writes *do* have a single chokepoint — because `Source` rows are few and cheap to
rescan wholesale. Same reasoning applies here.

*Why a plain dict, not DuckDB (unlike `map_serve.py`):* `map_serve.py` is dependency-gated and
therefore not a universal fix — a core-only install gets nothing from it, and `/api/database/
countries` must work on every install, including the weakest 2-core/3.5 GB field machines. The
data is tiny (at most ~249 countries × ≤8 top tags each, a few KB) — no scale justification for a
columnar engine.

**Design (mirrors `map_serve.py`'s structure, minus DuckDB, minus change-gating):**

1. Extract the current `_compute()` body (`database.py:327-363`) verbatim into a standalone
   function, e.g. `_live_sources_by_country(session)` in `src/catalog/coverage.py` (next to
   `country_counts_from_session`) or as a private helper reused by both `database.py` and the new
   rollup module — the single source of truth for both the live fallback and the rollup builder.
2. New module `src/analytics/source_country_rollup.py`, mirroring `map_serve.py`'s skeleton (lock,
   module-level `_STATE`, bind-awareness) but pure Python:
   ```python
   _LOCK = threading.Lock()
   _STATE: dict = {"payload": None, "bind": None, "built_at": None}

   def _same_bind(session, built_bind) -> bool:
       ...  # identical logic to map_serve.py:219-228

   def refresh(session: Session) -> None:
       """Unconditional full rebuild — called from run_idle_maintenance, mirroring
       reconcile_source_counters: sources are few, so no change-token gating is needed
       (unlike rollup_serve/map_serve's expensive DuckDB rebuilds)."""
       payload = _live_sources_by_country(session)
       with _LOCK:
           _STATE["payload"] = payload
           _STATE["bind"] = session.get_bind()
           _STATE["built_at"] = datetime.now(UTC)

   def served(session: Session) -> dict | None:
       """None => caller falls back to the live compute. Never wrong, only sometimes
       absent/stale-by-<=OO_MAINT_INTERVAL_S (disclosed via basis)."""
       with _LOCK:
           payload, built_bind, built_at = _STATE["payload"], _STATE["bind"], _STATE["built_at"]
       if payload is None or not _same_bind(session, built_bind):
           return None
       out = dict(payload)
       out["basis"] = {"source": "rollup", "as_of": built_at.isoformat(timespec="seconds"),
                        "refresh_interval_s": 300}
       return out
   ```
3. Wire `refresh(session)` into `run_idle_maintenance` (`src/scheduler/maintenance.py`), beside
   the existing `reconcile_source_counters` call at `maintenance.py:65-72`, in the same isolated
   try/except-and-degrade-to-`{"skipped": "error"}` pattern every other step there uses.
4. `sources_by_country` (`database.py:309-365`) becomes:
   ```python
   def _compute() -> dict:
       served = source_country_rollup.served(db)
       if served is not None:
           return served
       return _live_sources_by_country(db)   # unchanged existing body, extracted

   return _cached("countries", _compute, db)   # existing wrapper stays, harmless
   ```
5. No change needed to the DB-wide `PRAGMA data_version` probe — once the rollup is warm, the
   expensive bare scan no longer happens on the request path at all; cold-start (first ~≤300s
   after a restart, until the first idle-maintenance cycle) still falls through to the unchanged
   live path, never worse than today's baseline.

**Optional defense-in-depth (not required for correctness):** `database.py`'s three cached
endpoints have no statement deadline or bounded-concurrency guard, unlike `src/api/insights.py`'s
heavy endpoints, which use `_deadlined` (`insights.py:103-140`) — a TTL cache + `run_heavy`'s
single-flight/bounded-concurrency (`src/api/heavy.py`) + a `statement_deadline`, built exactly for
this "polled continuously, could pile into a death-spiral" scenario. Wrapping `/countries`,
`/coverage`, and `/stats` in the same pattern is recommended as a second, independent safety net
against the cold-start window and any future regression — separate, smaller change from the
rollup itself.

**Does the fix cover the siblings?** `/api/database/coverage`'s own query is already covering-index
healthy but can trivially be made to prefer the rollup too (the rollup's per-country dict is a
strict superset of `{country: sources}`) — cheap, optional, same PR. `/api/database/figures` and
`/api/library/overview` are **not** covered (different tables) — out of scope here, though
`figures`'s `n_mentions = COUNT(*) FROM keyword_mentions` (`database.py:220`) could trivially
become `select(func.sum(Keyword.mention_count))` — the maintained counter Precedent A already
keeps up to date — turning an O(n) scan into a free index-only aggregate; flagging as a low-risk
adjacent follow-up, not part of this ticket. `/api/insights/map-coverage`'s cold path is **not**
fixed by this change (it needs the `Source ⨝ Article` join fixed, not the source-only breakdown),
but note the article-count half of that join could now be served for free too since
`Source.article_count` is already a maintained counter (Precedent B):
`SELECT country, SUM(article_count) FROM sources GROUP BY country` replaces the
`queries.py:987-994` join entirely, independent of whether `duckdb` is installed — a natural,
low-risk follow-up, not built here.

**Honesty/no-fabrication compliance:** the rollup never reads `Article.content` or any other
large/uncovered article column — built purely from `sources`, the same table
`reconcile_source_counters` already scans wholesale off-peak. Moving the uncovered `tags` read off
the per-request hot path into a single off-peak scan is the general form of the codebase's own
documented lesson ("read small denormalisable facts via a covering index or a one-pass Python map,
never that join"). No composite score introduced — payload shape unchanged; the only addition is
a `basis` disclosure block, following the exact convention `map_serve.basis()`/
`rollup_serve.basis()` already use. Degrades loudly and safely by construction: any miss, cold
start, bind mismatch, or exception in `served()` returns `None` and the caller falls straight back
to the existing, unmodified live path.

**Tests to add:**

A. **Parity test**, new `tests/test_source_country_rollup.py`, modeled on
`tests/test_map_serve.py:145-165` and `tests/test_source_counter.py:33-64`:
```python
def test_served_payload_is_byte_identical_to_live(...):
    s = _session()
    _seed_sources_across_countries(s, n_sources=..., n_countries=..., mixed_enabled=True, varied_tags=True)
    live = _live_sources_by_country(s)
    source_country_rollup.refresh(s)
    served = source_country_rollup.served(s)
    served_no_basis = {k: v for k, v in served.items() if k != "basis"}
    assert served_no_basis == live
    assert served["basis"]["source"] == "rollup"
```
Seed a country with only disabled sources, a mixed enabled/disabled country, sources with no
country (`"(none)"` bucket), overlapping vs. disjoint tags, and >8 distinct tags in one country
(exercising `Counter.most_common(8)` truncation and ordering).

B. **Cold-start / bind-awareness tests**, mirroring `test_map_serve.py:137-143,168-180`:
```python
def test_cold_before_first_refresh_falls_back_to_live(...):
    assert source_country_rollup.served(s) is None

def test_bind_aware_never_answers_for_another_database(...):
    a = _new_session(); _seed(a); source_country_rollup.refresh(a)
    b = _new_session(); _seed(b, different_data=True)
    assert source_country_rollup.served(b) is None
    assert source_country_rollup.served(a) is not None
```

C. **Wiring test** in `tests/test_offpeak_maintenance.py`, mirroring the existing
`monkeypatch`-and-assert-called pattern at `test_offpeak_maintenance.py:23-38`:
```python
def test_run_idle_maintenance_refreshes_source_country_rollup(monkeypatch):
    calls = []
    monkeypatch.setattr("src.analytics.source_country_rollup.refresh",
                         lambda s: calls.append("country_rollup"))
    maint_mod.run_idle_maintenance()
    assert "country_rollup" in calls
```
Plus a "never breaks the rest of the cycle" test (a raising `refresh` still lets `cleanup`/
`incremental_vacuum`/`stat_snapshot` run), mirroring
`test_run_idle_maintenance_never_raises_on_a_failing_call` (`test_offpeak_maintenance.py:72-`).

D. **Endpoint-level parity + basis test**, mirroring `test_map_serve.py:183-`:
```python
def test_endpoint_serves_basis_and_matches_the_live_endpoint(tmp_path, ...):
    live = client.get("/api/database/countries").json()      # before refresh (cold)
    source_country_rollup.refresh(Sess())
    served = client.get("/api/database/countries").json()
    for k in ("countries", "covered", "total_countries", "missing", "missing_names", "missing_count"):
        assert served[k] == live[k]
    assert served["basis"]["source"] == "rollup"
```

E. **"No live scan when warm" structural test** (CI-safe, avoids flaky wall-clock assertions —
favor structural proof over timing in unit tests, per this repo's own convention):
```python
def test_no_sources_query_issued_when_rollup_is_warm(...):
    s = _session(); _seed(s, n_sources=5000)
    source_country_rollup.refresh(s)
    queries = []
    event.listen(s.get_bind(), "before_cursor_execute", lambda *a: queries.append(a[2]))
    result = source_country_rollup.served(s)
    assert result is not None
    assert not any("sources" in q.lower() for q in queries)
```
Plus a new case in `src/monitoring/benchmark.py`'s `_build_cases` (`benchmark.py:143-159`),
mirroring the existing `top_terms_grouped`/`supergroups` entries, so the maintainer can validate
on a real corpus the same way those two were validated:
```python
_Case(
    "sources_by_country",
    "Database tab per-country breakdown (rollup path)",
    lambda: source_country_rollup.served(session) or _live_sources_by_country(session),
    optimized=True,
    note="Reads the off-peak-refreshed in-memory rollup (mirrors reconcile_source_counters) "
         "instead of the bare SCAN sources forced by the uncovered tags column on every poll.",
)
```

## 3. Bottleneck class tracks hardware tier, with one clean exception

5 of 7 instances (all except the weakest) classify as **writer-bound** — ample CPU and RAM
headroom exists on every one of them (`mem_low_ticks: 0` on 4 of the 5), but the single-writer
SQLite gate is the binding constraint. The **one exception is `ea11e68c` (AMD 3020e, 2c/3.46GB,
the weakest and smallest-RAM machine of the 7)**, which classifies as **memory-bound**
(`mem_low_ticks: 53` and `44` across its two passes, `mem_low_min_permits: 1` — the governor's
own honest note: *"this machine's available RAM capped parallel collection at 1 worker(s) this
pass... never assume a bigger box will hit the same ceiling"*). This is a clean, sensible
hardware-tier signal: below some RAM threshold (`c1e1a30d` at 3.92 GB is writer-bound;
`ea11e68c` at 3.46 GB is memory-bound), the memory floor becomes binding before write-gate
contention has room to dominate — but `c1e1a30d`'s minimum available memory during its own
collection pass (751 MB) was ALSO tight, just not tight enough to trip the explicit floor gate in
the sampled window, and its own prior session ended `"unclean-end"` with RSS approaching the
machine's total RAM — a plausible (though not proven from these files alone) prior OOM kill.

No new fix is proposed for this section — it is diagnostic context for the WAL fix (§1) and the
8-machine experiment (§11), not a standalone defect.

## 4. A prior fix VALIDATED with real before/after field evidence — the duty-cycle work landed

`ea11e68c` is the exact machine type (AMD 3020e, 2-core, ~3.5GB RAM, over Tor) the project's own
CLAUDE.md ledger already analyzed once before, on 2026-07-23, finding 3–8 minute gaps between
collection passes caused by serial inter-pass housekeeping (the ledger's own "S4.1" fix target).
**This export measures the SAME machine type again and shows the fix worked**: reconstructing
pass boundaries from `scheduler.recent_runs` (30 runs across a ~2h20m window) gives an **average
inter-pass gap of 45.9 seconds** (min 5.0s, max 107.0s) — down roughly 4–10× from the previously
documented 3–8 minutes. This is a genuine, field-confirmed win, not a synthetic benchmark claim.

Two other 2026-07-23-documented characteristics of this exact hardware also reconfirm here: the
**~90% article-duplicate rate is unchanged** (supply-side saturation, not a code regression — e.g.
one recent run showed dup=605/entries=634, another dup=396/414), and the mem-low floor is still
present but now **oscillates between the floor (1 permit) and the ceiling (50 permits) rather than
sitting parked at a low median** — consistent with the separately-documented `rate_mode` default
flip to `"maximum"` (confirmed live on multiple instances via `scheduler.status.settings`), which
lets the governor chase the hardware ceiling until it hits a real limit instead of parking below
a fixed 500 KiB/s target.

**New, not in the 2026-07-23 baseline for this machine**: the WAL-bloat → giant-checkpoint →
memory-guard-trip cycle described in Finding 1 — a harder failure mode than the soft mem-low
back-off previously documented, worth folding into that machine-type's known-behavior record.
The §1 fix directly targets this new failure mode.

## 5. Bug A / Bug B cross-check — inconclusive on this batch, but with an important refinement

Neither of the two already-root-caused job bugs from the field-remarks brief (source-tags'
0/0-batches-then-crash; keyword-triage's silent pause-reads-as-done) could be **directly**
confirmed OR refuted by this batch, because **6 of the 7 instances have never run either job at
all** — `source-tags-run.json`/`keyword-triage-run.json` report `available: false` on
`0bfa36df`, `243c5a14`, `4663bbc5`, `6557d2cf`, `c1e1a30d`, and `ea11e68c`, in every case because
no working local LLM backend was reachable at export time.

**Only `1fba378c` (the 700k-article main DB) has real, live run data**, and it shows a THIRD,
previously-unconsidered failure mode: **neither job has crashed or paused — both are simply
running very slowly.** `keyword-triage-run.json`: `state: "in_progress"`, `batches_logged: 84`
after roughly 7 hours (≈2,100 of 6,914,218 keywords judged — ~0.03% coverage). `source-tags-run.json`:
`state: "in_progress"`, `detail_records_logged: 1012` against a 200-source scope, also after ~7
hours. Neither shows `state=="error"`, so the exact "paused-reads-as-done" collapse from the
field-remarks brief's root cause couldn't be directly observed here — but the sheer slowness on
this instance's otherwise-healthy hardware (6-core/15GB) is itself consistent with, and a
plausible trigger for, an eventual `LLMUnavailable`/`LLMError` given enough elapsed time; the
batch was simply still running at export time. The field-remarks brief's items 6-7 fix (retry-
with-backoff, uncaught `LLMError`, `/status` vs `/last` reconciliation) stands as written; this
export supplies no new precise-fix material for it, only corroborating context (the run is slow
enough that the failure mode it targets is plausible to eventually occur here too).

**A genuinely new, valuable finding surfaced instead**: `1fba378c`'s `perception-eval-live.json`
shows the active model (**`mistral:7b`** — the maintainer-ruled default) scored **precision 0.0526
/ recall 0.1667 / hallucination_rate 0.9474 (94.7%!)** on "who" extraction in a live 17-case eval
run against the real perception harness. `perception-extract-run.json` confirms the fail-safe
worked exactly as designed: all 700,242 gated articles were refused, zero who/where/when
candidates stored anywhere in this 700k-article corpus. This is real field evidence that
Mistral-7B — the maintainer's chosen default model — may not clear the perception-extraction
quality bar at all, at least for "who" extraction. **This is not a code bug and has no code fix —
it is a model-quality finding requiring a maintainer decision** (try a different default model for
this feature, accept the honest gap, or otherwise) — flag it to the maintainer, don't build
anything against it.

**One more relevant fact for context**: `ai.json`'s disclosed context-window gap (Ollama has no
RAM-derived `num_ctx` auto-tune, unlike vLLM's `compute_server_args` — confirmed present and
unaddressed on every instance that has `ai.json`) is a plausible contributing factor to
`LLMError`/context-overflow symptoms given source-tags' large embedded tag vocabulary
(`vocabulary_size: 202` on `1fba378c`) — but this batch doesn't contain a crashed run to confirm
it fired. This gap is already tracked as a known follow-up in CLAUDE.md's ledger (Session B,
2026-07-24 entry, "the Ollama `num_ctx` RAM-auto-tune gap") — no new fix spec needed here, just a
cross-reference for whoever picks it up.

## 6. Schema/migration drift — reproduced on 3 of the newer-schema instances

`schema-drift.json` on `4663bbc5`, `6557d2cf`, and `ea11e68c` (all three of the "newer schema"
group) independently shows the same two facts: **the database's own alembic stamp lags the
running code's migration head** (stamped at the older revision `95120f685050` while the code runs
at `4fc4be4dffef`), and **the `sources` table is missing its `last_crawled_at` index**
(`missing_indexes: ["last_crawled_at"]` — the COLUMN exists; only the index is missing). Not
cosmetic: on `6557d2cf`, the crawl-by-default feature is confirmed actively enabled
(`scheduler.status.settings.crawl_supplement: true, crawl_per_pass: 3`), meaning its
least-recently-crawled selection query is very likely running an unindexed sort over a 76,000+ row
`sources` table on hardware already shown to be write-gate/WAL constrained.

### 6.1 Precise fix specification

**Root cause, confirmed:** the migration and the boot self-heal for this exact column **diverge**
— the migration creates both the column and the index; the self-heal function most real installs
actually rely on creates only the column.

**The migration creates both** — `migrations/versions/4fc4be4dffef_source_last_crawled_at.py:
45-49`:
```python
def upgrade() -> None:
    if not _has_column(_SOURCE_TABLE, _COLUMN):
        op.add_column(_SOURCE_TABLE, sa.Column(_COLUMN, sa.DateTime(), nullable=True))
    if not _has_index(_SOURCE_TABLE, _INDEX):
        op.create_index(_INDEX, _SOURCE_TABLE, [_COLUMN])
```
(`_COLUMN = "last_crawled_at"`, `_INDEX = "idx_source_last_crawled"`, lines 30-32.) The
migration's own docstring (lines 9-11) states: *"The live store is never auto-migrated by alembic
(the boot self-heal `ensure_source_last_crawled_column` is the real upgrade path for it); this
migration keeps alembic-managed / staged-upgrade stores consistent."*

**The app never runs `alembic upgrade head` against the live store — this is intentional,
documented architecture, not a UX gap.** Confirmed by reading the full boot sequence in
`src/database/session.py:189-291`: it calls `stamp_if_unstamped(engine)` (stamps only,
`src/database/migrate.py:99-113`, `command.stamp`, never `command.upgrade`), then a long chain of
hand-written `ensure_*` self-heal functions applying raw SQL directly, then
`align_stamp_to_head(engine)` (stamp-only, `migrate.py:212-271`). The only place `command.upgrade`
is genuinely invoked against a real SQLite file is `upgrade_database_file()` (`migrate.py:77-96`),
explicitly restricted to "the staged-copy path of the backup/restore pipeline… never the live DB."
So the correct fix is completing the self-heal, not switching to `alembic upgrade`.

**The self-heal function exists but only handles the column** —
`src/database/maintenance.py:566-592`:
```python
_SOURCE_LAST_CRAWLED_COLUMN: dict[str, str] = {
    "last_crawled_at": "ALTER TABLE sources ADD COLUMN last_crawled_at DATETIME",
}

def ensure_source_last_crawled_column(engine: Engine) -> list[str]:
    """Self-heal ``sources.last_crawled_at`` on a store created before it existed."""
    if engine.url.get_backend_name() != "sqlite":
        return []
    added: list[str] = []
    with engine.begin() as conn:
        if not conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='sources'")
        ).fetchone():
            return []
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(sources)")).fetchall()}
        for name, ddl in _SOURCE_LAST_CRAWLED_COLUMN.items():
            if name not in cols:
                conn.execute(text(ddl))
                added.append(f"sources.{name}")
    if added:
        _LOG.info(f"added source last-crawled column(s): {', '.join(added)}")
    return added
```
It creates the column via `_SOURCE_LAST_CRAWLED_COLUMN` and never issues
`CREATE INDEX idx_source_last_crawled`. Correctly wired into boot at
`src/database/session.py:279-281`, so the wiring is fine — the function's *scope* is incomplete.

The canonical index-self-heal registry, `HOT_INDEXES` (`maintenance.py:41-92` — used for
`ix_mention_covering`, `ix_mention_date_keyword`, `ix_article_observed`,
`idx_article_source_sentiment`, `idx_article_quarantined`) also lacks this index, so
`ensure_hot_indexes()` (`maintenance.py:95-113`) never creates it either. This is a genuine
model/DB mismatch, not a deliberately-unmodeled expression index (unlike `ix_article_observed`,
which SQLAlchemy can't reflect) — the model declares it: `models.py:495`
`Index("idx_source_last_crawled", "last_crawled_at")` inside `Source.__table_args__` (column at
`models.py:469`).

**The alembic-stamp lag is a symptom, not a separate bug**: `align_stamp_to_head()`
(`migrate.py:212-271`) only advances the stamp when alembic's own `compare_metadata` drift
detector (`_schema_diffs_vs_head`, `migrate.py:182-209`) reports zero diffs against
`Base.metadata`. Because `Source.__table_args__` declares this index, `compare_metadata` correctly
sees the DB is missing it, returns a non-empty diff, and `align_stamp_to_head` correctly refuses to
advance the stamp (`{"action": "schema-behind", ...}`). **Fixing the index will also make the
stamp lag self-resolve on the next boot** — no separate fix needed for the stamp-lag symptom.

**Precise fix — extend `ensure_source_last_crawled_column` itself to also create the index**
(recommended over registering it in `HOT_INDEXES`, because `HOT_INDEXES` runs as one single
transaction at `session.py:238`, *before* `ensure_source_last_crawled_column` currently runs at
`session.py:281` — adding the index there without reordering would try `CREATE INDEX ... ON
sources (last_crawled_at)` before the column exists on any pre-2026-07-24 store, raising
`no such column` and rolling back the whole `ensure_hot_indexes` transaction including unrelated
indexes. Keeping it inside `ensure_source_last_crawled_column`'s own transaction, after the
column-add loop, sidesteps this ordering hazard with no change to `session.py`'s call order):

```python
def ensure_source_last_crawled_column(engine: Engine) -> list[str]:
    """Self-heal ``sources.last_crawled_at`` AND its covering index on a store created
    before either existed. The migration (4fc4be4dffef) creates the column and the
    index together; this self-heal must mirror that pairing exactly -- a store that
    got only the column would otherwise be left with a bare SCAN sources on the
    least-recently-crawled ORDER BY the §8 crawl-by-default rung depends on across a
    76k+-row table."""
    if engine.url.get_backend_name() != "sqlite":
        return []
    added: list[str] = []
    with engine.begin() as conn:
        if not conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='sources'")
        ).fetchone():
            return []
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(sources)")).fetchall()}
        for name, ddl in _SOURCE_LAST_CRAWLED_COLUMN.items():
            if name not in cols:
                conn.execute(text(ddl))
                added.append(f"sources.{name}")
        # Idempotent (IF NOT EXISTS) and unconditional so a store that already has the
        # column from a partial/earlier self-heal run (added is empty) still gets the
        # index repaired on this boot.
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_source_last_crawled "
                "ON sources (last_crawled_at)"
            )
        )
    if added:
        _LOG.info(f"added source last-crawled column(s): {', '.join(added)}")
    return added
```
No change needed to `src/database/session.py`, `src/database/models.py`, or the migration file.

*Alternative, not recommended as primary:* registering `idx_source_last_crawled` in
`HOT_INDEXES` is the more "canonical" location stylistically, but requires also moving the
`ensure_source_last_crawled_column(engine)` call from `session.py:281` to before
`ensure_hot_indexes(engine)` at `session.py:238`, mirroring the `idx_article_quarantined`
precedent's own comment ("BEFORE ensure_hot_indexes, since idx_article_quarantined needs the
column to exist") — a valid fix, but higher blast radius (touches boot ordering shared by 15+
other self-heal calls) for the same outcome.

**Test gap confirmed:** `tests/test_migrations.py:50-56` (`test_no_model_drift`) runs
`alembic upgrade head` on a *fresh* `tmp_path` store — since the migration itself correctly
creates the index, this test exercises the migration path (never broken) and is structurally
blind to the self-heal path (what most real installs use). It passes today and would still pass
if the self-heal bug were never fixed. `tests/test_crawl_supplement.py:351-374`
(`test_scheduler_wiring_and_setting`) is a pure source-string "wiring guard" (asserts literal
substrings appear in the file text) — proves the function exists and is called, never what it
*does*. **No test executes `ensure_source_last_crawled_column` against a real engine and inspects
the resulting schema for the index.**

**Proposed new test**, add to `tests/test_recursive_logs.py` (co-located with the `schema_drift`
tests — dogfoods the exact diagnostic that surfaced the bug) or `tests/test_crawl_supplement.py`:
```python
def test_source_last_crawled_self_heal_creates_column_and_index():
    """A store that predates C3 (column AND index both missing) OR a store that got
    only a partial fix (column present, index missing -- the exact field-diagnosed
    state) must both end up fully healed, and schema_drift() must report zero drift
    for sources.last_crawled_at afterward."""
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.orm import Session
    from src.database.maintenance import ensure_source_last_crawled_column
    from src.database.models import Base
    from src.monitoring.schema_drift import schema_drift

    # Case A: a store that never had the column (a genuinely old install).
    eng = create_engine("sqlite://", future=True)
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(text("DROP INDEX idx_source_last_crawled"))
        conn.execute(text("ALTER TABLE sources DROP COLUMN last_crawled_at"))
    ensure_source_last_crawled_column(eng)
    idx_names = {ix["name"] for ix in inspect(eng).get_indexes("sources")}
    assert "idx_source_last_crawled" in idx_names
    with Session(eng) as s:
        r = schema_drift(s)
    src_tbl = next((t for t in r["tables"] if t["table"] == "sources"), None)
    assert src_tbl is None or "last_crawled_at" not in src_tbl.get("missing_indexes", [])

    # Case B: the exact field-diagnosed state -- column present, index missing only.
    eng2 = create_engine("sqlite://", future=True)
    Base.metadata.create_all(eng2)
    with eng2.begin() as conn:
        conn.execute(text("DROP INDEX idx_source_last_crawled"))
    ensure_source_last_crawled_column(eng2)
    idx_names2 = {ix["name"] for ix in inspect(eng2).get_indexes("sources")}
    assert "idx_source_last_crawled" in idx_names2
    ensure_source_last_crawled_column(eng2)   # idempotent: never raises / never double-adds
```
This directly reproduces both the historical "never had it" case and the exact "column exists,
index missing" state the field export shows, and reuses `schema_drift()` (the diagnostic module
itself) as the assertion oracle so the test and the field symptom are the same measurement.

## 7. A power-profile diagnostic reports the wrong effective value

`243c5a14`'s `power-profile.json` reports the "optimized" profile's effective
`collect_parallelism` as **1** (`source: "profile:optimized"`), while the SAME instance's live
`debug-bundle.json → scheduler.status.settings.collect_parallelism` is actually **50**.

### 7.1 Precise fix specification

**Important nuance — half of this is already fixed on `main`, half is not.** The `collect_
parallelism` row in `PUBLISHED_KNOBS` *did* read `optimized=1` for roughly a month, and was found
and fixed in commit `4c20b23` ("C9: hardware-aware fetch ceilings"), 2026-07-24, an ancestor of the
current `HEAD` (verified: `git merge-base --is-ancestor 4c20b23 HEAD` → yes). Today's table
(`src/config/power_profiles.py:89-97`) reads:
```python
Knob("collect_parallelism", "", "collect_parallelism", "workers", "network",
     low=10, optimized=50, max=50, ...)
```
**So the specific "1 instead of 50" value cannot be reproduced against current `main`** — this
field export almost certainly came from an instance running an older commit than `4c20b23` (this
project's self-update is manual/git-pull-based; field VMs routinely lag `main`). Do not re-fix the
table value — it's already correct on `main`.

**However, the structural bug the maintainer is really pointing at is still live on `main` today,
independent of what number happens to be in the table.** `src/api/diagnostics.py:1399-1416` (the
`/power-profile` endpoint, which produces `power-profile.json` — also the bundle member at
`diagnostics.py:2830`):
```python
@router.get("/power-profile")
def power_profile(profile: str = Query("optimized"), download: bool = Query(False)) -> JSONResponse:
    from src.config.power_profiles import power_profile_report
    report = power_profile_report(active_profile=profile)   # no overrides!
    ...
```
Calls `power_profile_report(active_profile=profile)` with **no `overrides`**. `power_profile_
report` → `resolve_effective(active_profile, overrides)` (`power_profiles.py:155-188`,
`overrides = overrides or {}` at line 166) → for any knob **not** in `overrides`,
`value = _value_for(knob, profile)` (line 175) — a pure lookup into the static table.

The module's own docstring already names the exact category this breaks
(`power_profiles.py:25-27`): *"The three SETTING-backed knobs (`collect_parallelism`,
`llm_keep_alive`, `qualification_per_pass`) are applied via the settings-write path, not the read
site (the stored value is the user's explicit choice)."* — meaning, by design, **these three knobs
are never actually mutated by selecting a profile** (no code anywhere, on a profile switch, calls
`save_settings({"collect_parallelism": ...})`). So for these three knobs, the persisted
`SchedulerSettings`/`AppSettings` value is *always* what's genuinely in effect — the profile-table
number is only ever a suggested value, never an applied one — but the diagnostic presents it as
`"source": "profile:optimized"` with no distinction from a knob whose profile value *is* actually
live-applied (e.g. `sqlite_cache_mb`). Any time an operator has changed `collect_parallelism` away
from the current default of 50, or if `profile="low"`/`"max"` is queried, the diagnostic will
misreport the effective value and mislabel its source — **this is the persistent, currently-live
bug, with no dependency on which number happens to be in the table.**

Confirmed genuine gap, not just stale data: `test_collect_parallelism_optimized_matches_the_real_
scheduler_default` (`tests/test_power_profiles.py:138-151`) only checks `knob.optimized ==
SchedulerSettings().collect_parallelism` — the table value against a **freshly-instantiated
dataclass's compiled-in default**, never against a *persisted* value loaded via `load_settings()`.
It would not catch an operator override diverging from the table.

Live source-of-truth accessors exist and are already used elsewhere for exactly this purpose:
`src/scheduler/settings.py:265` `load_settings() -> SchedulerSettings` (already used the same way
at `src/api/scheduler.py:269,279`), `src/config/app_settings.py:166` `load_settings() ->
AppSettings`.

**Why the fix must sit at the endpoint layer, not inside `resolve_effective`/`power_profile_
report`:** both `SchedulerSettings.load_settings()` and `AppSettings.load_settings()` do real I/O
(an encrypted KV read via `kv_get_json`, which opens its own SQLCipher connection). `resolve_
effective` is explicitly documented as "PURE" (`power_profiles.py:155-156`) and is called directly
by `run_power_profile_selftest()` (`power_profiles.py:340-424`), whose docstring promises
*"Deterministic, no env/DB/network"* — its HTTP counterpart `GET /api/diagnostics/power-profile-
selftest` (`diagnostics.py:1419-1431`) also calls `power_profile_report("optimized")` internally.
Injecting a DB read into `power_profile_report`/`resolve_effective` would silently break that
determinism guarantee. **Keep those two functions exactly as they are.**

**Precise fix.** Add a small, defensive helper to `src/config/power_profiles.py` (near other
consumer-facing resolvers, e.g. after `fts_analysis_limit()` around line 289):
```python
def live_setting_overrides() -> dict[str, Any]:
    """The LIVE, PERSISTED value of every SETTING-backed knob (collect_parallelism,
    qualification_per_pass, llm_keep_alive). These knobs are applied via the
    settings-write path, not a profile-table read -- no code today rewrites the
    persisted setting when a profile is selected, so the persisted value is ALWAYS
    what is genuinely in effect. Callers that want an honest "what's actually
    configured" report (e.g. the /power-profile diagnostic) should pass this as
    resolve_effective's overrides. Read-only, best-effort: any settings-store error
    degrades to omitting that knob rather than raising."""
    out: dict[str, Any] = {}
    try:
        from src.scheduler.settings import load_settings as _load_scheduler_settings
        sched = _load_scheduler_settings()
        out["collect_parallelism"] = sched.collect_parallelism
        out["qualification_per_pass"] = sched.qualification_per_pass
    except Exception:  # noqa: BLE001 - a diagnostic must never break on a settings-read fault
        pass
    try:
        from src.config.app_settings import load_settings as _load_app_settings
        out["llm_keep_alive"] = _load_app_settings().llm_keep_alive
    except Exception:  # noqa: BLE001
        pass
    return out
```
Then edit **only** the HTTP endpoint at `src/api/diagnostics.py:1399-1416`:
```python
@router.get("/power-profile")
def power_profile(profile: str = Query("optimized"), download: bool = Query(False)) -> JSONResponse:
    """... The three SETTING-backed knobs (collect_parallelism, qualification_per_pass,
    llm_keep_alive) report their LIVE persisted value (source "override") rather than
    the profile-table suggestion, since nothing today rewrites the persisted setting on
    a profile switch. download=1 returns a dated attachment."""
    from src.config.power_profiles import live_setting_overrides, power_profile_report
    report = power_profile_report(active_profile=profile, overrides=live_setting_overrides())
    headers = {}
    if download:
        fname = f"oo-power-profile-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(report, headers=headers)
```
Do **not** change `power_profile_selftest()` (`diagnostics.py:1419-1431`) or
`run_power_profile_selftest()` — both must keep calling `resolve_effective`/`power_profile_report`
with no overrides, preserving the documented deterministic/no-DB contract.

This reuses the existing `source: "override"` semantics — `resolve_effective`'s own docstring
already frames an override as "the user's deliberate, reversible focus," which is exactly what a
persisted setting is for these three knobs.

**Test gap confirmed:** no test calls the `/power-profile` HTTP endpoint at all
(`tests/test_power_profiles.py` and `tests/test_power_profile_wiring.py` are the only two files
mentioning it; the latter covers only the five **env-var**-backed resolvers, deliberately
excluding the three setting-backed knobs — it cannot regress on this).

**Proposed new tests**, add to `tests/test_power_profiles.py` (unit-level, follow this project's
own settings-test pattern, e.g. `tests/test_scheduler_selection.py:94`, calling `save_settings`
directly — `kv_set_json`/`kv_get_json` self-manage their connection via `OO_DATA_DIR`):
```python
def test_setting_backed_knobs_report_the_live_persisted_value_not_the_profile_table(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.scheduler.settings import save_settings as save_scheduler_settings
    from src.config.app_settings import save_settings as save_app_settings
    from src.config.power_profiles import live_setting_overrides, power_profile_report

    save_scheduler_settings({"collect_parallelism": 7, "qualification_per_pass": 3})
    save_app_settings({"llm_keep_alive": "5m"})

    overrides = live_setting_overrides()
    assert overrides["collect_parallelism"] == 7
    assert overrides["qualification_per_pass"] == 3
    assert overrides["llm_keep_alive"] == "5m"

    for profile in ("low", "optimized", "max"):
        report = power_profile_report(active_profile=profile, overrides=overrides)
        eff = report["effective"]
        assert eff["collect_parallelism"]["value"] == 7
        assert eff["collect_parallelism"]["source"] == "override"
        assert eff["qualification_per_pass"]["value"] == 3
        assert eff["llm_keep_alive"]["value"] == "5m"
        assert eff["dump_concurrency"]["source"] == f"profile:{profile}"   # env-var knob unaffected


def test_power_profile_endpoint_matches_the_live_scheduler_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from fastapi.testclient import TestClient
    from src.scheduler.settings import save_settings as save_scheduler_settings
    from src.api.main import app

    save_scheduler_settings({"collect_parallelism": 33})
    client = TestClient(app)
    diag = client.get("/api/diagnostics/power-profile?profile=optimized").json()
    live = client.get("/api/scheduler/status").json()
    assert diag["effective"]["collect_parallelism"]["value"] == live["collect_parallelism"] == 33
```

## 8. A second unfiltered third-party logger — root-caused + fixed same day, live confirmation

CLAUDE.md's own lessons record that `htmldate.meta`'s `"impossible to clear cache"` WARNING-noise
was already found and filtered (2026-07-23) after it was found to be 85 of 93 "problems" logged in
one export. **This batch surfaced a second, still-unfiltered instance of exactly the same class**:
on `0bfa36df`, **175 of a 300-record error-log sample (58%)** are `trafilatura.metadata: error in
JSON metadata extraction: 'NoneType'/'list' object...` WARNING-level noise — a different logger
than the one already fixed. `6557d2cf` independently shows the same `trafilatura.metadata` pattern
(105+ occurrences) alongside a THIRD noise source: `GET /v1/models` returning 404 (the
vLLM-availability probe on GPU-less hardware) — **511–617 such requests per instance**, all
correctly-failing-as-designed but adding continuous low-value load and log noise.

**Live confirmation, same day, separate from the diagnostics exports:** the maintainer pasted a
fresh-install terminal log (a different app instance entirely, launched interactively — legal
banner, uvicorn startup, `/api/legal/consent` POST, an alembic stamp line) showing **25 repeated
`ERROR [htmldate.meta] impossible to clear cache for function: 'function' object has no attribute
'cache_clear'` lines printed to the console**, flagged explicitly as noise that "shouldn't be
there." This is the SAME message the 2026-07-23 fix already targeted — but printing to the
**console**, not just polluting the JSONL error-log counters the 2026-07-23 fix addressed. This
sharpens the fix below: the existing mechanism only stops the noise from muddying one specific
diagnostic file; it does nothing to stop it reaching the terminal.

### 8.1 Precise fix specification (investigated + specified directly, no delegated agent needed)

**Root cause of why the console still shows it despite the "already fixed" ledger entry:**
`src/monitoring/errorlog.py:79-90`:
```python
_HTMLDATE_NOISE_LOGGER = "htmldate.meta"
_HTMLDATE_NOISE_MESSAGE = "impossible to clear cache for function"

class _HtmldateCacheNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != _HTMLDATE_NOISE_LOGGER:
            return True
        try:
            return _HTMLDATE_NOISE_MESSAGE not in record.getMessage()
        except Exception:
            return True
```
`install()` (`errorlog.py:231-244`) attaches this filter **only to this app's own
`_JsonlErrorHandler`**:
```python
def install() -> None:
    global _installed
    root = logging.getLogger()
    if any(isinstance(h, _JsonlErrorHandler) for h in root.handlers):
        _installed = True
        return
    handler = _JsonlErrorHandler(level=logging.WARNING)
    handler.addFilter(_HtmldateCacheNoiseFilter())   # <-- filter is on the HANDLER
    root.addHandler(handler)
    _installed = True
    note_boot()
```
A `logging.Filter` attached to a **handler** only suppresses that record for that *one* handler —
it does nothing to stop the record from reaching every OTHER handler in the chain (a console
`StreamHandler`, uvicorn's own handlers, or Python's built-in `logging.lastResort` fallback). So
the record is correctly dropped from `app_errors.jsonl`'s counters (the original 2026-07-23 fix's
stated goal — "drowning out real signal" in the JSONL file) but is never stopped from being
printed anywhere else, which is exactly the newly-reported symptom. **Confirmed no `logging.
basicConfig()` call exists anywhere in `src/`** (repo-wide grep), and confirmed `src/utils/
logging_config.py`'s `setup_logging()` (used at 7 call sites, none named `htmldate`/`trafilatura`)
is not the source either (different format, different namespace) — the exact handler responsible
for the console line doesn't matter for the fix, because the correct fix intercepts the record
**before it reaches any handler at all**.

**Precise fix — move the filter from the handler to the logger itself, and extend it to cover
both known noise sources with one mechanism.** In Python's `logging` module, `Logger.handle()`
calls `self.filter(record)` (checking filters attached to the **logger the record was logged
through**) before `self.callHandlers(record)` (which walks the hierarchy invoking every handler on
every ancestor logger, including root). A filter rejected at the logger level means the record
never reaches `callHandlers()` at all — it is dropped before any handler, anywhere in the process,
including a future/unknown console handler, ever sees it. This is strictly more robust than a
handler-level filter and requires no knowledge of which handler is currently printing to console.

Edit `src/monitoring/errorlog.py:70-90`:
```python
# S5 item 1 (field-feedback 2026-07-23) + the 2026-07-26 hardware-diagnostics batch:
# htmldate.meta.reset_caches() (reached via trafilatura's own reset_caches(), which
# src/scheduler/hygiene.py calls at EVERY pass boundary) hits an AttributeError on
# charset_normalizer's functions in the installed version pin and logs it as an ERROR
# every single time -- measured 85 of 93 "problems" on one field session, and,
# independently, live-confirmed printing to the CONSOLE on a fresh install (25 repeated
# lines) despite the 2026-07-23 fix, because that fix only filtered this app's OWN
# JSONL handler, never the source logger -- so the noise still reached every OTHER
# handler on the chain (console, uvicorn's, Python's own last-resort stderr fallback).
# A second, structurally identical noise source was independently found the same day:
# trafilatura.metadata's "error in JSON metadata extraction" (58% of one field
# instance's 300-record error-log sample). Both are fixed with ONE mechanism, applied
# at the LOGGER level (not the handler level) so the record is dropped before it can
# reach ANY handler in the process -- never a blanket suppression of either logger:
# only this ONE known-benign message class per logger is dropped; any other message
# from either logger (e.g. a genuine import failure) still counts as a problem and
# still reaches the console.
_HTMLDATE_NOISE_LOGGER = "htmldate.meta"
_HTMLDATE_NOISE_MESSAGE = "impossible to clear cache for function"
_TRAFILATURA_NOISE_LOGGER = "trafilatura.metadata"
_TRAFILATURA_NOISE_MESSAGE = "error in JSON metadata extraction"
_THIRD_PARTY_NOISE_RULES: dict[str, str] = {
    _HTMLDATE_NOISE_LOGGER: _HTMLDATE_NOISE_MESSAGE,
    _TRAFILATURA_NOISE_LOGGER: _TRAFILATURA_NOISE_MESSAGE,
}


class _ThirdPartyCacheNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D102
        needle = _THIRD_PARTY_NOISE_RULES.get(record.name)
        if needle is None:
            return True
        try:
            return needle not in record.getMessage()
        except Exception:  # noqa: BLE001 - never let the filter itself break logging
            return True
```
And `install()` (`errorlog.py:231-244`):
```python
def install() -> None:
    """Attach the handler to the root logger (idempotent AND self-healing) and
    attach the third-party noise filter DIRECTLY to the noisy loggers themselves --
    not just to this app's own JSONL handler -- so the known-benign message classes
    never reach ANY handler (console included), while a genuinely different message
    from the same logger still does."""
    global _installed
    root = logging.getLogger()
    handler_present = any(isinstance(h, _JsonlErrorHandler) for h in root.handlers)
    if not handler_present:
        handler = _JsonlErrorHandler(level=logging.WARNING)
        root.addHandler(handler)
    for _name in _THIRD_PARTY_NOISE_RULES:
        _lg = logging.getLogger(_name)
        if not any(isinstance(f, _ThirdPartyCacheNoiseFilter) for f in _lg.filters):
            _lg.addFilter(_ThirdPartyCacheNoiseFilter())
    _installed = True
    if not handler_present:
        note_boot()
```
(Renaming `_HtmldateCacheNoiseFilter` → `_ThirdPartyCacheNoiseFilter` is a clean rename since it
now covers two loggers by table lookup, not one by hardcoded name — if the executing session
prefers a smaller diff, keep the old class name and just add the `trafilatura.metadata` rule to
the same `filter()` method's logic instead of introducing a dict; either shape works, the load-
bearing change is *where* the filter is attached, not its internal structure.)

This is a **low-risk, behavior-preserving-for-the-JSONL-channel, additive fix**: the existing
2026-07-23 test (`tests/test_errorlog_summary.py:141-165`,
`test_htmldate_cache_clear_noise_is_filtered_out`) calls `errorlog.install()` then
`logging.getLogger("htmldate.meta").error(...)` and asserts on `errorlog.recent_errors()`/
`errorlog.summary()` — since the record is now dropped one step earlier (at the logger instead of
the handler), the observable JSONL-channel behavior that test checks is unchanged and it should
continue to pass unmodified. The **new** behavior this fix adds is that the record now also never
reaches the console (or any other handler) — which the existing test does not, and cannot, check.

**Tests to add**, in `tests/test_errorlog_summary.py` (same file/conventions as the existing
htmldate tests, `test_errorlog_summary.py:141-178`):
```python
def test_htmldate_noise_never_reaches_any_other_handler_not_just_our_own(monkeypatch, tmp_path):
    """The 2026-07-23 fix only stopped this noise from muddying our OWN JSONL
    counters; a live terminal capture on 2026-07-26 showed it STILL printing to the
    console. The fix must drop the record at the LOGGER level so it never reaches
    ANY handler attached anywhere in the process -- proven here with a second,
    independent dummy handler standing in for "the console" (or any future handler),
    which must never see the noisy record but must still see a genuinely different
    one from the same logger."""
    _fresh(monkeypatch, tmp_path)
    errorlog.install()
    sink: list[str] = []
    probe = logging.Handler()
    probe.emit = lambda record: sink.append(record.getMessage())  # type: ignore[method-assign]
    logging.getLogger().addHandler(probe)
    try:
        noisy = logging.getLogger("htmldate.meta")
        noisy.error("impossible to clear cache for function: %s", "AttributeError('x')")
        noisy.error("impossible to import charset function name")  # a different message -- must pass
    finally:
        logging.getLogger().removeHandler(probe)
    assert not any("impossible to clear cache for function" in m for m in sink)
    assert any("impossible to import charset function name" in m for m in sink)


def test_trafilatura_metadata_noise_is_filtered_the_same_way(monkeypatch, tmp_path):
    """The 2026-07-26 hardware-diagnostics batch found a second, structurally
    identical noise source on a different logger -- 58% of one field instance's
    300-record error-log sample. Fixed with the SAME mechanism, one new table row."""
    _fresh(monkeypatch, tmp_path)
    errorlog.install()
    noisy = logging.getLogger("trafilatura.metadata")
    for _ in range(10):
        noisy.error("error in JSON metadata extraction: 'NoneType' object is not subscriptable")
    noisy.error("a genuinely different trafilatura.metadata problem")  # must still count

    recs = errorlog.recent_errors()
    problem_msgs = [r["message"] for r in recs if r.get("level") in errorlog._PROBLEM_LEVELS]
    assert not any("error in JSON metadata extraction" in m for m in problem_msgs)
    assert any("a genuinely different trafilatura.metadata problem" in m for m in problem_msgs)
```
The two existing tests (`test_htmldate_cache_clear_noise_is_filtered_out`,
`test_htmldate_noise_filter_leaves_other_loggers_untouched`, `test_errorlog_summary.py:141-178`)
should be re-run unmodified as a regression check that the JSONL-channel behavior is preserved by
the refactor.

**On the `/v1/models` 404 polling noise** (511–617 requests/instance on GPU-less hardware,
`6557d2cf`): this is a separate, smaller, lower-priority item — the probe is *correctly* failing
as designed (there is no vLLM to find), so it is a candidate for a lower-frequency backoff once
vLLM is confirmed absent, rather than a bug fix. No precise fix spec is provided here (out of scope
for this investigation round) — flagged for a future session to design a simple "back off the
health-probe interval once `vllm_available()` has been false for N consecutive checks" mechanism,
consistent with this project's existing backoff idioms (e.g. the capped per-feed RSS backoff).

## 9. Findings specific to the main production instance (`1fba378c`, 700,522 articles)

This instance is qualitatively different from the other 6 (which read as parallel test/staging
VMs) and is where the project's own still-open scale-gate concerns become directly visible:

- **~97.8 GB of accumulated stale pre-restore snapshots** — see §9.1, precise fix below.
  **Highest-priority single fix on this instance.**
- **Cold-boot unlock time is growing with corpus scale**: two measurements on this instance show
  17.7s → 29.7s across two boots — both far above the P0 `<2000ms` bar and far above the 540.8ms
  the 2026-07-18/20/21 P0-validation run measured on a smaller (474,556-article/22.2GB) snapshot
  of this same corpus. This is the closest real signal in the whole dataset to the still-open
  "K1: warm unlock at 100GB+" project gate, and it's trending the wrong direction. **No precise
  code fix is specified for this in this round** — it is closest in nature to a re-run of the
  existing `p0_validation.py` tool at this corpus's current scale (which the field-remarks brief
  item 8 already recommends keeping for exactly this re-entry point) plus a dedicated profiling
  pass, not a small isolated bug; flag for a dedicated future investigation, not a quick patch.
- **Severe keyword-counter drift, unverifiable at this scale**: `corpus-integrity.json` counts
  only 120,965 genuine orphan keywords, but `keyword-engine.json` reports 6,472,070 keywords
  (93.6% of the whole 6.9M-keyword table) showing a maintained `mention_count` counter of exactly
  zero — a ~6.35M-keyword gap between the counter and reality. The app's own drift-sampling check
  couldn't even complete (`counter_drift_error: "interrupted"`) — the true extent is currently
  unverifiable in-app at this scale. **No precise fix specified this round** — needs its own
  dedicated investigation (why is the counter zero for 93.6% of keywords, and why does the
  drift-sampling check itself fail to complete at this scale) before a fix can be scoped; flagging
  as a high-priority candidate for the *next* round of precise-fix delegation, not attempted here
  because it was outside this round's four-agent scope.
- **Two diagnostic members categorically cannot complete within their 300s deadline at this
  scale**: `keyword-log-digest.json` and `source-audit.json` both hit `outcome: "skipped-deadline"`
  on 6.9M keywords / 76,679 sources. The fixed 300s budget doesn't scale with corpus size; these
  may need a background-job form (mirroring the existing `all-job` pattern) rather than a
  synchronous GET. **No precise fix specified this round** — the shape (convert to a background
  job) is clear from the existing `all-job` precedent (`src/api/diagnostics.py`'s `/all-job`
  endpoints), but scoping which of the two members needs it and whether they should share one job
  or two needs its own small investigation; flagging as a follow-up, not blocking on it here.

### 9.1 Precise fix specification — stale pre-restore snapshot accumulation

**Summary verdict:** cleanup **does exist** but is purely event-driven (fires only as a
side-effect of a *later* restore) and purely count-based (keep the newest 3). There is no
time-driven backstop, and the pattern is completely outside the scope of the boot-time janitor. On
a production instance where 3 restores happened close together and then stopped, the count-based
policy correctly retained exactly 3 snapshots — and because no 4th restore has since occurred,
nothing will ever prune them again, for as long as the app runs. This is exactly the diagnosed
97.8 GB.

**Where the snapshot is created** — `src/backup/merge.py`, inside `run_restore()`'s commit path
only:
```python
# src/backup/merge.py:1804-1808
ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
snapshot = data_dir() / f"pre-restore-{ts}.db"
with timings.stage("pre_restore_snapshot"):
    snapshot_preserving(live_db_path(), snapshot)
report["pre_restore_snapshot"] = str(snapshot)
```
Runs only if `commit=True` and `verify_copy()` already passed — immediately before the atomic swap
(`merge.py:1838-1846`). Every commit surface funnels through this one function (`run_restore`):
`src/api/backup_v2.py:215` (`restore_commit`), `src/api/backup_v2.py:290` (`legacy_restore`),
`src/backup/volume_job.py:269` (volume restore job) — a fix here covers all of them.

**The existing count-based prune:**
```python
# src/backup/merge.py:58
_SNAPSHOT_KEEP = 3

# src/backup/merge.py:1532-1541
def _prune_snapshots(keep: int = _SNAPSHOT_KEEP) -> list[str]:
    snaps = sorted(data_dir().glob("pre-restore-*.db"), key=lambda p: p.name, reverse=True)
    removed = []
    for p in snaps[keep:]:
        try:
            p.unlink()
            removed.append(p.name)
        except OSError:  # pragma: no cover
            pass
    return removed
```
Called **only** at the tail of a *successful commit* (`merge.py:2001-2005`) — no scheduled/
periodic/boot-time invocation exists anywhere (confirmed by grep: the only call site is this one).
If 3 restores happen in a burst and then stop, `_SNAPSHOT_KEEP=3` correctly keeps all 3 forever,
since nothing else ever calls `_prune_snapshots()` again — exactly the diagnosed 97.8 GB.

**The boot-time janitor does not cover this pattern** — confirmed by direct comparison.
`cleanup_stale_staging()` (`src/api/main.py:138-146` → `src/backup/artifact.py:732-743` →
`src/backup/stream_backup.py:147-185`, `sweep_stale_backup_temps`) only matches
`_TEMP_DIR_PREFIXES = (".bak-build-", ".restore-")` and `_TEMP_FILE_SUFFIXES = (".oopart",
".reassembling")` — `pre-restore-<ts>.db` matches **neither**: it's a plain file, not a
`.bak-build-`/`.restore-` dir, and ends in `.db`, not `.oopart`/`.reassembling`. The crash-leftover
forensics detector (`src/monitoring/forensics.py:50`, `_STAGING_DIR_PREFIXES`) has the identical,
narrower scope — a `pre-restore-*.db` file is a plain `kind:"file"` entry that falls into
`other_bytes` in the totals, invisible as a distinct category (correctly, since these are not
crash leftovers, but the diagnostics have no dedicated lens on this file family at all today).

**This was the original, known, documented gap — only half-fixed.** The archived design record
(`docs/archive/design/DB_RELIABILITY_01_GAP_ANALYSIS.md:149-152`) named it explicitly: "Pre-restore
snapshots accumulate forever... never pruned, never surfaced in the UI." The planned fix had two
halves (`docs/archive/design/DB_RELIABILITY_02_DESIGN.md:145-149`): "keep the newest 3
`pre-restore-*.db`, surface them in Settings → Data & backup with dates and sizes." **Only the
count half shipped** — zero listing/download/delete endpoint exists for these files
(`src/api/backup_v2.py` grep confirms). Today they are simultaneously invisible to the user, only
pruned as a side effect of a *future* restore, and not time-decayed — exactly the combination that
produced the 97.8 GB finding.

**Retention policy — a combination, and the two knobs must be genuinely independent/additive:**

- **Count-based alone is unsafe as the sole trigger** (already correctly implemented — a fresh
  snapshot is always retained since it's always the newest).
- **Age is the missing piece.** Should mirror the *pattern* used elsewhere in this codebase
  (`sweep_stale_backup_temps(root, *, max_age_hours: float = 24.0)`), but **not the same 24h
  value** — `.bak-build-*`/`.restore-*`/`.oopart` are definite crash residue, worthless the moment
  found stale; `pre-restore-*.db` files are deliberately-kept, useful safety nets whose value
  decays with *operator review time*, not process lifetime. **Recommendation: default `168.0`
  hours (7 days)**, operator-tunable via a new env var, following the exact
  `_incremental_vacuum_hours()`/`_maint_interval_s()` idiom already used in this codebase
  (`float(os.getenv(NAME, default))`, `except ValueError: return default`). This is a judgment
  call, not a hard fact from the code — flagged explicitly so the maintainer can tune the one
  constant.
- **Structural double-guard against ever racing a still-running restore**, mirroring this
  codebase's own established pattern for exactly this hazard
  (`src/backup/stream_backup.py:116-140`, `active_staging`/`is_active_staging` — the same
  primitive `sweep_stale_backup_temps` itself uses, calling itself "protected twice over"): the
  ordinary REST commit path (`restore_commit`/`legacy_restore`) does **not** pause the scheduler
  (only the separate volume-restore job path does), so the scheduler's off-peak maintenance loop
  (`src/scheduler/runner.py:_run_off_peak_maintenance`, gated only on the collect-pass lock, not a
  restore lock) *can* run concurrently with an in-flight ordinary restore's long post-swap tail
  (reindex/quarantine/work-induced-tally). The fix must register the freshly-created snapshot as
  "active" for the *entire* remaining commit tail, so a new age sweep structurally cannot touch it
  while its own restore is still finishing, no matter what threshold is configured.

**Precise fix.**

1. New function, `src/backup/merge.py`, next to `_prune_snapshots` (add `_SNAPSHOT_MAX_AGE_HOURS_
   DEFAULT` near `_SNAPSHOT_KEEP` at line 58; needs `timedelta` added to the existing
   `from datetime import UTC, datetime` import at `merge.py:45` — `re`/`os` are already imported):
   ```python
   _SNAPSHOT_MAX_AGE_HOURS_DEFAULT = 168.0  # 7 days -- see justification above

   def _snapshot_max_age_hours() -> float:
       """OO_PRE_RESTORE_SNAPSHOT_MAX_AGE_HOURS -- same env-var idiom as
       _incremental_vacuum_hours()/_maint_interval_s()."""
       try:
           return float(os.getenv(
               "OO_PRE_RESTORE_SNAPSHOT_MAX_AGE_HOURS", str(_SNAPSHOT_MAX_AGE_HOURS_DEFAULT)
           ))
       except ValueError:
           return _SNAPSHOT_MAX_AGE_HOURS_DEFAULT

   _SNAPSHOT_TS_RE = re.compile(r"^pre-restore-(\d{8}T\d{6}Z)\.db$")

   def prune_pre_restore_snapshots_by_age(max_age_hours: float | None = None) -> list[str]:
       """Remove pre-restore-<ts>.db safety-net snapshots older than max_age_hours.
       Complements _prune_snapshots()'s count-based policy, which only fires as a side
       effect of a LATER restore -- this is the time-driven backstop for the case
       where no further restore ever happens. Age is read from the file's OWN
       embedded timestamp, never filesystem mtime. A snapshot currently registered
       via src.backup.stream_backup.active_staging (an in-flight restore's own,
       still-running commit) is never touched regardless of its age."""
       from src.backup.stream_backup import is_active_staging

       hours = max_age_hours if max_age_hours is not None else _snapshot_max_age_hours()
       cutoff = datetime.now(UTC) - timedelta(hours=hours)
       removed: list[str] = []
       for p in data_dir().glob("pre-restore-*.db"):
           m = _SNAPSHOT_TS_RE.match(p.name)
           if not m:
               continue  # unrecognized shape -- never guess, never touch
           try:
               created = datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
           except ValueError:
               continue
           if created >= cutoff:
               continue
           if is_active_staging(p):
               continue  # an in-flight restore's own snapshot -- never touched
           try:
               p.unlink()
               removed.append(p.name)
           except OSError:  # pragma: no cover
               pass
       return removed
   ```

2. Register the just-created snapshot as "active" for the whole commit tail — two surgical edits
   to `run_restore()` in `merge.py`, no re-indentation of the intervening ~200 lines needed, via
   `contextlib.ExitStack`. At snapshot creation (`merge.py:1804-1808`), right after the existing 4
   lines:
   ```python
   from contextlib import ExitStack
   from src.backup.stream_backup import active_staging
   _snapshot_guard = ExitStack()
   _snapshot_guard.enter_context(active_staging(snapshot))
   ```
   At the existing prune stage (`merge.py:2001-2005`), add a `finally`:
   ```python
   with timings.stage("prune_snapshots"):
       try:
           report["pruned_snapshots"] = _prune_snapshots()
       except Exception:  # noqa: BLE001 - never undo a committed, additive restore
           _LOG.warning("post-restore snapshot pruning failed", exc_info=True)
       finally:
           _snapshot_guard.close()  # release the active-staging guard either way
   ```
   There is no early `return` anywhere between these two points in the commit path (every
   intervening step is already independently try/except-guarded with "never undo a committed,
   additive restore"), so control flow always reaches `prune_snapshots`.

3. Wire the age sweep into the **recurring** off-peak maintenance pass — not just the boot-time
   janitor, since a long-lived instance like the diagnosed one may not restart for weeks. Extend
   `run_idle_maintenance` in `src/scheduler/maintenance.py`, as a new step **before** the existing
   `with session_scope() as session:` block (a filesystem sweep needs no DB session), matching the
   file's own house pattern:
   ```python
   try:
       from src.backup.merge import prune_pre_restore_snapshots_by_age
       out["pre_restore_snapshot_sweep"] = {"removed": prune_pre_restore_snapshots_by_age()}
   except Exception:  # noqa: BLE001 - a background safety net must never break
       _LOG.warning("off-peak pre-restore snapshot sweep failed", exc_info=True)
       out["pre_restore_snapshot_sweep"] = {"skipped": "error"}
   if stop():
       out["reconcile"] = {"skipped": "stopping"}
       return out
   ```

4. Optional, recommended, not required: also run once at boot, beside `cleanup_stale_staging()`
   in `_run_startup_upkeep` (`src/api/main.py:138-146`), for instances that restart occasionally
   but may not accumulate much scheduler idle time before the next restart:
   ```python
   try:
       from src.backup.merge import prune_pre_restore_snapshots_by_age
       _removed = prune_pre_restore_snapshots_by_age()
       if _removed:
           logger.info(f"pruned {len(_removed)} aged pre-restore snapshot(s)")
   except Exception:  # noqa: BLE001 - the janitor must never block startup
       logger.warning("pre-restore snapshot age sweep failed", exc_info=True)
   ```

**Justification against the data-safety non-negotiables:** a restore never deletes its own
snapshot (the count-based policy is untouched, unconditional, and still runs right after every
commit). The age threshold is generous (7 days default, operator-tunable) relative to any
realistic review window, and is explicitly flagged as a judgment call. The structural double-guard
makes it *impossible*, not merely unlikely, for the sweep to remove a snapshot whose owning
`run_restore()` call has not yet finished its commit tail, regardless of how aggressively the
threshold is configured. Only files matching the exact self-generated `pre-restore-<ISO8601Z>.db`
shape are ever considered. Nothing about `_prune_snapshots()`'s existing behavior, the atomic
swap, or any other commit stage is modified — purely additive.

**Tests to add**, in `tests/test_restore_timing_instrumentation.py` (reuses the existing `client`,
`_build_backup`, `_commit` fixtures already proven against real `run_restore` calls) plus a new
`tests/test_pre_restore_snapshot_sweep.py` (pure filesystem unit tests, no app boot needed —
`data_dir()` is already process-wide isolated per `tests/conftest.py:36`):

1. **Count-based prune still holds beyond `_SNAPSHOT_KEEP`** (codifies existing, currently-untested
   behavior at n>3):
   ```python
   def test_repeated_commits_prune_down_to_the_newest_keep_n(client, monkeypatch):
       import src.backup.merge as merge_mod
       from src.paths import data_dir
       blob = _build_backup()
       for _ in range(merge_mod._SNAPSHOT_KEEP + 1):
           resp = _commit(client, blob)
           assert resp.status_code == 200
       snaps = sorted(data_dir().glob("pre-restore-*.db"))
       assert len(snaps) == merge_mod._SNAPSHOT_KEEP
   ```
2. **A successful commit's own snapshot is retained, not immediately deleted:**
   ```python
   def test_a_committed_restore_never_deletes_its_own_fresh_snapshot(client):
       resp = _commit(client, _build_backup())
       report = resp.json()
       from pathlib import Path
       assert Path(report["pre_restore_snapshot"]).exists()
       assert report["pruned_snapshots"] == []
   ```
3. **The required negative case — an OLD-but-active (in-flight) snapshot is never removed
   regardless of threshold**, directly exercising `is_active_staging()`, new
   `tests/test_pre_restore_snapshot_sweep.py`:
   ```python
   from datetime import UTC, datetime, timedelta
   from src.backup.merge import prune_pre_restore_snapshots_by_age
   from src.backup.stream_backup import active_staging
   from src.paths import data_dir

   def _make_snapshot(age_hours: float):
       ts = (datetime.now(UTC) - timedelta(hours=age_hours)).strftime("%Y%m%dT%H%M%SZ")
       p = data_dir() / f"pre-restore-{ts}.db"
       p.write_bytes(b"fake corpus bytes")
       return p

   def test_an_active_in_progress_restores_own_snapshot_is_never_swept_even_far_past_the_age_cutoff():
       stale_but_active = _make_snapshot(age_hours=24 * 10)  # 10 days old
       with active_staging(stale_but_active):
           removed = prune_pre_restore_snapshots_by_age(max_age_hours=1)  # aggressive threshold
           assert stale_but_active.name not in removed
           assert stale_but_active.exists()
       removed_after = prune_pre_restore_snapshots_by_age(max_age_hours=1)
       assert stale_but_active.name in removed_after
       assert not stale_but_active.exists()
   ```
4. **The age sweep only removes files past the threshold, leaves recent/unrecognized ones alone:**
   ```python
   def test_age_sweep_only_removes_snapshots_past_the_threshold_and_ignores_unrecognized_names():
       old = _make_snapshot(age_hours=200)      # past a 168h default
       borderline = _make_snapshot(age_hours=1) # well within the window
       garbage = data_dir() / "pre-restore-not-a-real-timestamp.db"
       garbage.write_bytes(b"junk")
       removed = prune_pre_restore_snapshots_by_age(max_age_hours=168)
       assert old.name in removed
       assert not old.exists()
       assert borderline.exists()
       assert garbage.exists()
   ```
5. **Wiring test** (closes the "shipped the function but forgot to wire it" gap this project has
   hit before):
   ```python
   def test_run_idle_maintenance_wires_the_pre_restore_snapshot_sweep(monkeypatch):
       from src.scheduler import maintenance as maint_mod
       called = {}
       def _fake_sweep(*a, **kw):
           called["ran"] = True
           return ["pre-restore-fake.db"]
       monkeypatch.setattr("src.backup.merge.prune_pre_restore_snapshots_by_age", _fake_sweep)
       out = maint_mod.run_idle_maintenance()
       assert called.get("ran") is True
       assert out["pre_restore_snapshot_sweep"]["removed"] == ["pre-restore-fake.db"]
   ```

No changes needed to `src/backup/stream_backup.py`, `src/monitoring/forensics.py`, or
`folder_backup.py` for the cleanup mechanism itself — though the `data_dir_inventory`/
`suspect_staging` observability gap and the never-built Settings UI listing from the original
design are worth flagging as separate, smaller follow-ups, not required for this fix.

---

## 10. UNCHANGED context — items with no precise fix produced this round

Two items from the earlier pass remain informational only, deliberately not investigated further
in this round because they are maintainer decisions or larger dedicated investigations, not
small, precisely-specifiable code fixes:

- **§5's Mistral-7B 94.7% hallucination-rate finding** — a model-quality signal, not a code bug.
  No fix to specify; surface to the maintainer as a decision point.
- **§9's cold-boot-unlock growth and keyword-counter-drift findings on `1fba378c`** — both need
  their own dedicated investigation before a fix can be scoped (see §9's bullets above for exactly
  what's still unknown about each).

---

## 11. NEW — the 8-machine parallel-instance confirming experiment (2026-07-26, same day)

**What the maintainer ran and why:** independent of the diagnostics-export analysis above, the
maintainer installed the current build of the app on **8 separate machines simultaneously**,
running them in parallel purely to test a specific hypothesis, in the maintainer's own words:
*"in order to confirm my intuition that having multiple instances of OOS downloads more articles
than having only one, thus explaining that the current limitation is neither TOR related bandwidth
limitation nor hard disk / ram / computation limitations, and that it's only related to the
software."*

**Why this is strong corroborating evidence for the findings above, not a separate investigation
thread.** This experiment is a controlled test of exactly the causal story §1–§3 and §11 of the
field-remarks brief (item 9) already build: if per-instance throughput were capped by something
*external* to the app (Tor exit-relay bandwidth shared across the whole Tor network, or a single
machine's disk/RAM/CPU ceiling), then running 8 instances in parallel — each independently
Tor-circuited, each on its own separate hardware — would show **aggregate** throughput roughly
flat or only mildly improved over one instance, because the bottleneck would sit outside any one
instance's control. If, instead, throughput scales roughly linearly (or even just clearly
super-additively) with instance count, that is direct evidence the ceiling is **inside the
software of a single instance** — i.e. exactly the class of finding this doc has been building all
along: a single-writer SQLite gate contended by a long-lived reader (§1), a single-connection
per-instance write-serialization bottleneck, and per-instance polling/aggregation overhead (§2) —
none of which would be relieved by more instances if the bottleneck were truly Tor-bandwidth or
single-machine hardware, but ALL of which are trivially relieved by running N separate,
independent instances, since each gets its own fresh SQLite writer gate, its own fresh WAL, and
its own fresh Tor circuit pool.

**What this doc cannot state as fact:** the actual aggregate-vs-single-instance article counts from
this 8-machine run were not included in what was shared this turn — only the experiment's design
and stated purpose. **No specific throughput number from this experiment should be fabricated or
assumed here.** If/when the maintainer shares the actual per-instance article counts from this
run, they should be added to this section as the direct empirical confirmation (or refutation) of
the hypothesis, and cross-referenced against §1's WAL-starvation fix and §2's countries-endpoint
fix as the two most likely single-instance software ceilings this experiment would be probing.

**How this connects to the still-open item 9 from the field-remarks brief** (73,079 discovered
candidates never entering "awaiting qualification," and the qualification job silently
trial-fetching disabled candidates and discarding the verdict): if the maintainer's intuition is
confirmed (software-bound, not Tor/hardware-bound), the highest-leverage next step for raising
*per-instance* throughput is closing exactly the gaps this doc's §1/§2 fixes target — a
WAL-starved single-writer gate and a per-request bare-scan endpoint are both squarely
"software-side, single-instance" bottlenecks of precisely the shape this experiment is designed to
implicate. **Recommend building §1 and §2 first, on the theory that they are the most likely
concrete software mechanisms behind whatever ceiling this experiment measured**, then re-running a
smaller version of the same multi-instance experiment (2-3 machines, before/after the fix) as the
direct validation that the fix actually raised the per-instance ceiling — reusing this same
"parallel instances, compare aggregate throughput" methodology as a lightweight before/after
benchmark, rather than inventing a new measurement approach.

---

## Actionable recommendations, prioritized

Each item below now names the exact fix location and the exact test file(s) to add — this is the
executable punch list for the autonomous session, cross-referenced to the precise fix
specifications above.

1. **Fix WAL/checkpoint starvation (§1.1)** — restructure `run_all`'s producer loop
   (`src/briefing/registry.py:41-87`) and `warm_cache`'s five steps (`src/api/insights.py:
   1362-1419`) to commit/release the transaction between steps; add periodic commits to
   `build_keyword_daily`'s streaming loop (`src/analytics/columnar.py:761-774`). Optionally add a
   `WalGuard` watchdog modeled on `src/scheduler/memguard.py`. New test files:
   `tests/test_wal_reader_starvation.py`, extensions to `tests/test_wal_checkpoint.py`/
   `tests/test_wal_ceiling.py`, an extension to `columnar.py`'s `keyword_daily_parity` probe. This
   is universal (all 7 instances) and plausibly reduces or eliminates several of the symptoms
   below as a side effect — **do this first.**
2. **Fix `/api/database/countries` and its polling-sibling group (§2.1)** — extract
   `_live_sources_by_country` from `src/api/database.py:327-363`, add
   `src/analytics/source_country_rollup.py` (a plain in-memory dict, refreshed off-peak, mirroring
   `reconcile_source_counters`), wire into `run_idle_maintenance`
   (`src/scheduler/maintenance.py`). New test file `tests/test_source_country_rollup.py` plus
   wiring tests in `tests/test_offpeak_maintenance.py`. Sole cause of the KPI board's only
   consistently-red metric across every instance measured.
3. **Fix the `sources.last_crawled_at` missing-index self-heal (§6.1)** — one function edit,
   `src/database/maintenance.py:575-592` (`ensure_source_last_crawled_column`), add
   `CREATE INDEX IF NOT EXISTS idx_source_last_crawled ...` inside the existing transaction after
   the column-add loop. New test in `tests/test_recursive_logs.py` or
   `tests/test_crawl_supplement.py`. Small, isolated, directly relevant to the actively-enabled
   crawl-by-default feature.
4. **Filter the `htmldate.meta`/`trafilatura.metadata` console+log noise (§8.1)** — move the
   filter from handler-level to logger-level in `src/monitoring/errorlog.py` (`install()`,
   lines 231-244), extend the noise-rule table to cover both loggers with one mechanism. Two new
   tests in `tests/test_errorlog_summary.py`. Small, low-risk, mechanical, with a live terminal-log
   confirmation the noise is currently reaching the console.
5. **Clean up stale pre-restore snapshots on the main instance, and add a recurring age-based
   sweep (§9.1)** — new `prune_pre_restore_snapshots_by_age()` in `src/backup/merge.py`, an
   `ExitStack`-managed `active_staging()` guard around the existing snapshot lifetime, wired into
   `run_idle_maintenance` (`src/scheduler/maintenance.py`) and optionally `_run_startup_upkeep`
   (`src/api/main.py:138-146`). New test file `tests/test_pre_restore_snapshot_sweep.py` plus
   additions to `tests/test_restore_timing_instrumentation.py`. The single most urgent disk-safety
   item found in this whole batch (97.8 GB on one instance).
6. **Reconcile the power-profile diagnostic's reported `collect_parallelism` against the live
   scheduler setting (§7.1)** — add `live_setting_overrides()` to
   `src/config/power_profiles.py`, pass it as `overrides` from the HTTP endpoint only
   (`src/api/diagnostics.py:1399-1416`), never from the pure `resolve_effective`/selftest path.
   Two new tests in `tests/test_power_profiles.py`. Note: the specific "1 instead of 50" value
   already self-resolved in commit `4c20b23` (2026-07-24) — this fix addresses the structural
   "reads static table, ignores live setting" bug that persists for any operator override or any
   non-`optimized` profile query.
7. **Cross-reference the 8-machine confirming experiment (§11) against items 1 and 2 above** —
   once the maintainer shares the actual per-instance throughput numbers from that run, use them
   to validate (or redirect) the priority ordering of fixes 1–2; consider re-running a smaller
   2-3-machine version of the same experiment before/after those fixes land, as the direct
   before/after validation.
8. **Flag, don't build, the two remaining `1fba378c`-specific findings (§9, §10)** —
   cold-boot-unlock growth and keyword-counter drift both need their own dedicated investigation
   before a fix can be scoped; the Mistral-7B hallucination-rate finding (§5) needs a maintainer
   decision, not code.
9. **Consider whether the 300s-per-member diagnostics deadline should scale with corpus size**
   (§9) — two members already can't complete at ~700k articles / 6.9M keywords; shape is clear
   (background-job form, mirroring the existing `all-job` pattern) but scoping needs its own small
   investigation.
