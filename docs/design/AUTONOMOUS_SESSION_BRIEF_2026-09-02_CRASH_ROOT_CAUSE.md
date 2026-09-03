# Autonomous session brief — the systematic crashes (2026-09-02)

**You are the executing session.** Four field sessions across three machines ended in an unclean
stop; the maintainer had to restart or reinstall after each. This brief is the operating manual for
fixing that. It is written to be executed at maximum effort with subagent fan-out, in draft PRs,
against `main` @ `6c3fa25` (app 0.3.0).

**What produced it.** One all-diagnostics bundle (machine C) + four session-forensics files were
analysed by seven distinct-lens investigators over the raw data and the tree, then every finding was
put through adversarial refutation on three axes (does the CODE do this / does the DATA support it,
or does a simpler explanation / is the FIX+TEST sound and non-vacuous). 60 findings were judged:
**6 killed, 54 survive** (53 with corrections applied below, 1 clean). Every load-bearing claim was
then hand-re-verified against the tree by the authoring session. Where a claim is inferred rather
than measured, it says so — treat those as hypotheses, not as facts to build on.

**Read before you start:** §1 (what is actually happening), §2 (what was refuted — do not
resurrect it), §3 (the maintainer's rulings — these are decisions, not suggestions), then execute
§5 in order. §8 is what only the maintainer can supply.

---

## 0. Working mode (read every session, non-negotiable)

- **Draft-PR-only. Nothing auto-merges.** One draft PR per slice onto `main`, small and additive.
  Branch prefix `claude/oos-crash-*`. The maintainer reviews and merges.
- **Staleness guard FIRST, every slice.** Line/file anchors here were verified against `main` @
  `6c3fa25`; the engine moves weekly. Re-derive every anchor with `grep`/read before editing. If a
  slice turns out to be already shipped, VERIFY-AND-MARK — do not rebuild it (the 06-audit lesson).
- **Skeptics-before-push with the mandatory NEGATIVE-SPACE lens** on every slice marked ⚠:
  generate should-be-empty / should-never-happen inputs and assert them, not only the happy path.
  Reproduce a claimed defect live before trusting a fix, and reproduce the fix's own failure mode.
- **Every fix ships with a MUTATION that reddens its test by name.** A mutation that reddens
  nothing is a finding, not a pass. Record the mutation matrix in the PR body.
- **House gates, every slice, all green before push:**
  - `ruff check --select=F,B --extend-ignore=B008 src/ tests/`
  - `python -m mypy src/` → **exit 0** (the ratchet is gone; the pass condition is zero, and the
    tell of an aborted run is the missing `Success: no issues found in N source files` line —
    N is ~482. Use the pyproject-pinned `mypy==2.3.0` in the project venv, never the ambient one.)
  - `bandit==1.9.4 -r src/ -ll -q` → exit 0. Redirect to a file and read `$?` on its own line —
    `cmd | tail` reports `tail`'s status and always looks green.
  - `python scripts/i18n_report.py --min 100`, then **separately** `--max-untranslatable 561` and
    `--max-unkeyed-t-calls 298`. Gate 1 passing is NO evidence about gate 2 — run each command
    verbatim and read its own output. Any new user-facing string in `index.html` needs gate 2 run.
  - `alembic check` + `alembic upgrade head` when a column/index is added (random 12-hex revision
    id, `grep` the versions dir to confirm it is free, real head from `python -m alembic heads`).
  - Full `python -m pytest -q` after each push-ready slice, in a py3.13 venv with `pip install -e .`
    (TMPDIR inside the repo). A single-file run misses cross-test pollution.
- **Baseline diff, done honestly.** Two worktrees, absolute paths, NO persisting `cd`;
  `--continue-on-collection-errors -rs`; print BOTH totals lines; assert (a) the head run's cwd is
  the head worktree, (b) `passed(head) − passed(base)` equals the number of tests this PR adds,
  (c) the failure-name diff is empty AND the skip-name diff is unchanged. Fetch `origin/main`
  immediately before creating the base worktree and echo the SHA it resolved to.
- **The non-negotiables outrank every fix here.** Airplane mode stays a socket-level guarantee; no
  fabricated numbers, scores or security; caveats visible; degrade loudly; never delete user data;
  **no auto-restart** (the standing "honesty first" ruling — a crash screen tells the truth, it does
  not silently relaunch).
- Frontend is BROWSER-UNVERIFIED in the sandbox unless you drive Chromium (it IS available at
  `/opt/pw-browsers/…`; `python3.13` exists; a venv + `pip install -e ".[analysis]" playwright`
  works). Prefer driving it. If you do not, ship conservative + flagged with `node --check` and an
  invariant guard, and say "browser-unverified, needs click-through".

---

## 1. What is actually happening

### 1.1 The four sessions

| | machine | shape | corpus | ended |
|---|---|---|---|---|
| S1 | A (Lenovo Yoga) | 6 cores, ext4, expedition armed 9 days | 89,478 articles, 2.7 GB DB | unclean |
| S2 | C | **2 cores / 3,296 MB RAM / 7.25 GiB swap**, SSD | 117,510 articles, 4.4 GB DB, 9.31 M mentions | unclean, in the post-pass tail |
| S3 | C | same | same | unclean, ≤18 min after a 60-minute diagnostics bundle |
| S4 | B | btrfs | **7.1 GB DB** + 6.8 GB wiki dumps | unclean |

Only C produced a bundle. A's forensics says its own 66/66 bundle completed — **that zip is on A's
disk and was never uploaded** (§8).

### 1.2 The crash kind is NOT determinable from the app's data — and one instrument lies

All four sessions report `unclean-end` **and** `WAL before open: absent (0 B)`, and the forensics
text explains the second as *"a clean shutdown checkpoints and removes it"*. That explanation is an
**artifact of the measurement order**:

`unlock()` verifies the passphrase with `conn = connect(p, key=…); conn.close()`
(`src/api/unlock.py:341-342`) **before** `_finish_unlock` builds `_forensic_timer` (`:228`), whose
`__init__` calls `wal_state_before_open()` (`:278-280` → `forensics.py:280`, which returns `absent`
only on `FileNotFoundError`). In a process that booted locked, that verify connection is the **last**
connection to the file, and SQLite checkpoints and unlinks the `-wal` on last close. So on an
encrypted store the probe reads `absent` **whatever** happened. Reproduced with stdlib sqlite3: a
crashed store with an 840 KB `-wal` → one `connect()`/`close()` → the file is gone.

Consequences, all of which must be fixed together:
- The only field that appeared to say "the previous shutdown was clean" says nothing at all.
- The same false inference is asserted in `forensics.py:311-315`, `p0_validation.py:582-586` and
  the P0 runbook §8.
- A **wrong-passphrase attempt** also deletes the WAL, so reordering *inside* `unlock()` is not
  sufficient — the load-bearing read is at **boot**, before any connection can exist.
- S3's unlock spent **24.7 s outside the timed phases** (30,309.6 ms total vs 5,631.3 ms
  `synchronous_total`) — i.e. inside that verify connect/close, recovering and checkpointing
  whatever WAL the dead session left. That cost is currently attributed to nothing.

**Therefore: the app cannot today tell an OOM-kill from a machine freeze from a closed terminal
from a native fatal.** Phase 0 exists to fix that, and it is the reason the maintainer ruled the
host kernel-log read in (§3).

### 1.3 Machine C is swap-thrashing, not OOM-killing

Across all 200 collector ring samples, **app RSS + available RAM is conserved at 1,830–1,940 MB**
(e.g. 1,874 at 09:36:19; 1,917 at 09:37:33; 1,835 on a fresh process at 11:00:13). The app's memory
comes straight out of the machine's. With 7.25 GiB of swap configured, the kernel has no reason to
OOM-kill at 1.35–1.8 GB RSS; it swaps — **the app and the desktop together**. The signature:

- 09:36:19 → 09:37:35: RSS falls **1,649.3 → 1,197.7 MB in 75 s** while `py_alloc_blocks` **rises**
  37,598,459 → 37,751,597 (Python objects are not being freed) with `cpu_sys_pct` 23–42 %.
- `hygiene.freed_mb` over 30 passes: median 131.4, **min −83.0** (RSS *rose* after `gc.collect()` +
  `malloc_trim` — the swap-in signature); `gc_collected` is 0 on 13 of 30 passes.
- 79 `MEMORY GUARD ENGAGED` / 79 `released` records, 59 of them on one day.
- `mem_avail` reached **69 MB**.

This is why the **computer** freezes rather than the app dying, and why every "recovery" the guard
reports is the kernel paging the idle app out, not the app releasing anything.

**Swap is never sampled anywhere** (`grep swap src/monitoring/collect_perf.py src/scheduler/memguard.py`
→ nothing), so the above is inferred from the conservation identity + flat allocation count + high
system CPU. Sampling it is part of Phase 1 and turns the inference into a measurement.

### 1.4 The resident floor is set by RAM-blind constants

Idle RSS on the 3.3 GB box: **1,047–1,170 MB**. It is composed of:

- `session.py:75-76` — QueuePool `pool_size=8`, `max_overflow=64`, read at module import.
- `session.py:121-123` — `PRAGMA cache_size=-{cache_mb*1024}` with `cache_mb=64` **per connection**;
  the file's own comment says "the worst case is ~cache_mb × (pool_size + max_overflow)".
- `rollup_serve.serve_enabled()` (`rollup_serve.py:98-110`) and `map_serve` turn themselves **on
  whenever `duckdb` is importable** — "no flag to flip" — and `columnar._offline_config` sets
  **neither `memory_limit` nor `threads`**, so DuckDB uses its documented default (80 % of RAM).
- `main.py:239-250` kicks `_warm_insights_cache` at boot, which triggers the rollup build: a
  streamed scan of all 9.31 M mentions into an in-memory DuckDB.

None of these scale with the machine. On a 16 GB box nobody notices; on 3.3 GB it is a third of RAM
before any work happens.

### 1.5 Three defects that are confirmed and NOT machine-C-specific

**(a) `statement_deadline` poisons the connection pool.** `maintenance.py:1137` arms the session's
current pooled DBAPI connection with `set_progress_handler(_check, 20_000)` (`:1181`); `_check`
(`:1149-1150`) is a pure clock test that returns 1 for the rest of the block once the limit has
elapsed, **on whatever thread runs the statement**. A `session.commit()` inside the block returns
that still-armed connection to the QueuePool (nothing clears the handler; `session.py:93` registers
only a `connect` listener). Any other thread that draws it has its next ≥20,000-opcode statement
killed with `OperationalError: interrupted`. **Reproduced** (SQLAlchemy 2.0.52, real QueuePool):
after the commit `pool.checkedin()==1`; 3/3 victim threads interrupted; a short statement on the
same connection succeeds (the 20k-opcode granularity). Production compositions that commit inside a
deadlined block: diagnostics members under `statement_deadline(db, 300)` (`diagnostics.py:4310`)
calling `run_all_bounded`, whose `_release_transaction` commits between producers
(`registry.py:533` → `:107`) and whose WAL guard commits every 30 s (`:271`, `:344`).
Field evidence: **81 `interrupted` records** — 37 × unhandled error on `GET /api/scheduler/activity`,
14 briefing producers, 25 producer scans, 2 insights warm, 2 alert-layer, 1 corpus_tier — in two
bursts whose shape matches the `get_briefing(force=True) → refresh_briefing → run_all → warm_cache
→ corpus_tier` chain that the home-cards member runs.
**It cannot kill the process** — it produces 500s, 503s, a degraded boot briefing and hours of
wasted work. Do not sell it as the crash cause.

**(b) `database is locked` at the pass tail is `SQLITE_BUSY_SNAPSHOT`.** `run_discovery` opens
`session.begin_nested()` (`channels.py:429`) — SQLite treats a SAVEPOINT outside a transaction as
`BEGIN DEFERRED` — then the channels READ (`channels.py:190`, a full `article_links` scan), pinning
a snapshot. The housekeeping lane was kicked one step earlier (`runner.py:1885`) and its steps commit
through the gate; the briefing thread commits between producers. When discovery's `flush()` promotes
the read txn to a write txn, SQLite returns `SQLITE_BUSY_SNAPSHOT` **and the busy handler is not
invoked** (it is only consulted when no read transaction is open) — so the 30 s `busy_timeout` never
applies and the error is instant. SQLAlchemy then issues `ROLLBACK TO SAVEPOINT` **without RELEASE**,
so the stale outer transaction survives, the next tail writer fails identically 19 s later, and
`session_scope`'s final commit raises `PendingRollbackError` — a 4-hour pass recorded `ok:false`.
Reproduced with stdlib sqlite3 3.45.1 (fails in 0.000 s with `busy_timeout=30000`; the no-concurrent-
commit control succeeds). **This race was created by moving the ride-alongs onto a concurrent lane
thread (2026-07-24 S-B/C1).** Field: 5 `source discovery failed; rolled back its savepoint` records,
`locked_errors_total` 82, two whole passes lost.

**(c) WAL starvation.** The WAL reached **9,104,044,464 bytes on a 4.4 GB database**. 27 of 30
pass-boundary checkpoints returned `busy=1` after burning exactly their 5 s budget
(`duration_ms` 5,008–5,203) with `wal_bytes_before == wal_bytes_after`, and `checkpointed_frames`
was **identical across passes hours apart** (130,650 at 17:03, 19:17 and 20:04 — a single read
snapshot pinned the read-mark for ≥3 h). `checkpoint_wal` runs `PRAGMA wal_checkpoint(TRUNCATE)`
inside `write_lock()` (`hygiene.py:208-212`), so each boundary spent ~5 s of **exclusive gate time**
truncating nothing. When the reader finally went away the reset took 376 ms. The pinner cannot be
named from the data — the write gate records waits but **no holder**, and nothing records pool
checkout age. That is why Phase 2 ships an instrument, not a guess.

### 1.6 The request storm

Measured on C, in one 35.5-minute window with 1,777 API requests (~50/min):

- `GET /api/signals/alerts`: **p50 530,534 ms, max 558,766 ms, 2 requests, both 200.** A cold
  `poll_cache` runs the whole-table convergence scan **on the request thread**, with no
  single-flight, no admission cap and no deadline (`poll_cache.py:187-204`; the handler at
  `signals.py:140-163` calls `get_alerts` directly, unlike its siblings which use `guarded_read`).
  Two concurrent cold calls because opening Home fires `loadHomeAlerts()` un-awaited **and** starts
  the live poller whose first tick fires it again.
- `GET /api/database/stats`: p50 28.2 ms, **p95 14,412 ms**, 12 of 53 stalls. Its 30 s cache is a
  *verified* cache keyed on `PRAGMA data_version` + `total_changes()` (`database.py:41-61`), so under
  continuous collection **every commit invalidates it** and the poll re-runs six `COUNT(*)` scans.
  `GET /api/database/figures` runs `SELECT count(*) FROM keyword_mentions` over 9.31 M rows —
  **43,095 ms measured, 97.8 % of that request**.
- `GET /api/insights/trending-windows`: **{429: 5, 503: 1}**, max 69,455 ms. The boot warm stores
  the key with `tl=None` (`insights.py:1461-1468`) while Home **always** sends `&target_lang=en`
  (`app-home.js:484` + `app-corpus.js:730`), and `_tlang('en')` returns `'en'` — so the warmed entry
  **can never be a hit, in any UI language**. Every 120 s TTL expiry is a cold whole-corpus scan on
  a poll thread.
- The UI never backs off: fixed 15 s / 6 s / 5 s timers, 429 retried 4×, 503 swallowed, next tick
  on schedule. `frontend_kind_breakdown {fetch-5xx: 205}`, `{503: 174, 429: 9}`.
- The biggest stalls are **process-wide freezes**, not handlers on the loop: 41,497 ms of loop lag
  with six *trivial* requests in flight (`/api/scheduler/status` is a pure in-memory dict read and
  took 41.7 s), and **22,138 ms of lag with NOTHING in flight**. A handler cannot block a loop it is
  not running on. Candidates, in order: memory pressure/swap; gen-2 GC over millions of live objects;
  `_lock_gate` (`main.py:602-616`) doing a file `stat`+16-byte read of the 4.4 GB DB on **every**
  request; `async def list_sources` materialising 68,409 rows on the loop (12.6 s measured).

### 1.7 Where S2 actually died

The pass-end summary was written at **09:42:04.340** (pass `03:20:44`, 22,879.8 s); **no scheduler
run record was ever appended** for that pass; the error log has nothing between 09:37:20 and the S3
boot at 10:53:47. So S2 died — or hung — inside `_do_run`'s tail: lane kick (`runner.py:1885`) →
discovery (`:1904`) → source enrichment (`:1961`) → `_refresh_briefing_async` (`:1981`) →
`run_pass_hygiene` (`:1642`, the TRUNCATE checkpoint under the gate) → `record_run` (`:1649`).
That window runs three whole-corpus consumers concurrently on two cores, plus a multi-GB checkpoint,
on a box that had just spent 65 minutes with the memory guard engaged at ~220 MB available. **And
`WriterGate.acquire()` has no timeout** (`writer.py:105-125`) — a checkpoint that queues behind a
stuck holder waits forever, which from the outside is indistinguishable from a dead process.

S3 died within 18 minutes of a 60-minute diagnostics bundle that ran **concurrently with a
collection pass, the housekeeping lane and the rollup build**.

### 1.8 THE MEASURED HEADLINE — 50 workers each hold a pooled connection across a Tor fetch

**This section supersedes the earlier ranking. It rests on machines A and B, whose bundles arrived
after the first pass and which are NOT small machines.**

All three machines run the shipped defaults: `collect_parallelism=50`, `rate_mode=maximum`,
`qualification_per_pass=5`, `continuous=true`, `interval_minutes=60`.

`_worker` (`src/scheduler/runner.py:904-925`) takes a governor permit, then opens
`session_scope()`, then calls `_process_source` → `ingest_source(session, source, fetcher=…)`
(`:597-619`) — so **the RSS fetch and every article fetch happen with a pooled SQLCipher connection
checked out**, each carrying `PRAGMA cache_size=-65536` (64 MiB). The pool allows 8 + 64 = 72.
The governor's `_AdjustableSemaphore.set_permits` states its own semantics plainly
(`src/scheduler/bandwidth.py:52-56`): *"holders in excess simply finish their one unit of work and
release — never preempted"* — and one unit of work is a whole source over Tor.

**Measured on machine B (7,858 MiB RAM, 8 logical cores, 198,374 articles, 15.6 M mentions),
2026-08-16, one pass:**

| time | RSS | available | permits | active_workers | guard |
|---|---|---|---|---|---|
| 04:44:28 | 6,211 MB | 590 MB | 50 | 50 | false |
| 04:44:33 | 6,510 MB | 250 MB | 12 | 50 | false |
| 04:44:38 | 6,588 MB | 199 MB | 3 | **50** | **true** |
| 04:44:45 | 6,717 MB | 135 MB | 1 | **50** | true |
| 05:19:51 | 6,732 MB | **94 MB** | 1 | **50** | true |
| 07:20:21 | **6,767 MB** | 105 MB | 1 | **50** | true |

The governor did exactly what it was built to do — permits 50 → 25 → 12 → 6 → 3 → 1 — and **RSS did
not move for the next two and a half hours**, because `active_workers` (which is
`governor.active`, i.e. workers currently *holding a permit and a session*,
`collect_perf.py:398`) stayed at 50. Throttling new work cannot reclaim what 50 in-flight workers
are already holding. 50 × 64 MiB of page cache alone is 3.2 GB.

**This is the mechanism behind every memory symptom in this report**, and it is not a small-machine
problem: B has 7.9 GB of RAM and still reached 94 MB available. On C the same code with the same
defaults simply hits the wall sooner. It also explains why the memory guard's pause "frees nothing"
(S1.2): there is nothing for it to free while the workers hold it.

### 1.9 Cross-machine: what the three bundles agree on

| | **A** (Qubes, i7-1065G7) | **B** (Parrot, i5-8250U) | **C** |
|---|---|---|---|
| cores (phys/logical) | 4 / 4 | 4 / 8 | 2 / 2 |
| RAM | **3,924 MiB** | 7,858 MiB | 3,296 MiB |
| swap | **1,024 MiB** | 9,012 MiB | 7,250 MiB |
| corpus | 94,496 art / 3.69 M mentions | 198,374 art / **15.6 M mentions** | 117,510 art / 9.31 M |
| DB / WAL at export | 2.7 GB / 64 MB | 6.9 GB / **637 MB** | 4.4 GB / 28 MB |
| RSS min–max (ring) | **1,729–2,112 MB** | 1,279–**6,767 MB** | 1,123–1,659 MB |
| available min | 1,239 MB | **94 MB** | 225 MB (69 MB in a pass summary) |
| RSS + available | 3,219–3,381 | 5,274–6,872 | 1,757–1,954 |
| permits observed | **pinned at 1** | 1–50 | pinned at 1 |
| gate peak waiters / max wait | 0 / 0 s | **50 / 2,818 s** | 43 / 6,236 s |
| gate total wait | 0 | **2,912,758 s** | 474,771 s |
| `database is locked` in the 300-error ring | **118** | 26 | 5 |
| `locked_errors_total` | **234** | 144 | 82 |
| `interrupted` | 0 | 0 | 81 |
| checkpoints busy | 0 / 19 | 9 / 26 | **26 / 30** |
| last unlock | 345 ms | **90,111 ms** | 162,549 ms (S2) |
| `/api/signals/alerts` p50 | — | **124,953 ms** (n=4) | **530,534 ms** (n=2) |
| trending-windows | 47 × 429, p95 16.8 s | 429×5 + 503×3, max 60 s | 429×5 + 503×1, max 69 s |
| filesystem | ext4 | btrfs | — |

**What this settles:**

1. **The RSS + available conservation identity holds on all three** (3.2–3.4 GB on A, 5.3–6.9 GB on
   B, 1.8–1.9 GB on C). The app's memory is the machine's memory. This is now measured three times,
   not inferred once.
2. **`SQLITE_BUSY_SNAPSHOT` (S2.4) is the most frequent error on every machine** — and it is far
   worse on A (118 of 300 ring records; 234 lifetime) than on C (5; 82). Every one carries the
   identical `src.discovery.channels` → `sqlcipher3.dbapi2.OperationalError: database is locked`
   traceback. **Promote it: it is the highest-frequency confirmed defect in the fleet.**
3. **The alerts cold-compute (S3.1) is not C-specific**: B, with 8 logical cores and 7.9 GB, took
   **142.8 seconds** on one of four requests. It scales with corpus size, not with machine size.
4. **The trending-windows warm-key mismatch (S3.3) is confirmed on all three** — A logged 47 × 429
   on that route in a 300-record ring.
5. **The learned ceiling never relaxing (S1.4) is confirmed on A**: permits pinned at 1 while
   **1,239 MB was available** and the guard was not engaged. A is running one worker for no
   current reason.
6. **A is the machine closest to a true OOM kill**: 3,924 MiB of RAM, only **1,024 MiB of swap**,
   and an RSS floor of 1.7–2.1 GB. C's 7.25 GiB of swap is what turns its equivalent pressure into
   a freeze instead of a kill. **Do not generalise "it thrashes rather than OOMs" to A.**
7. **The `interrupted` storm is C-only in these windows** — consistent with the mechanism (it needs
   a deadlined block that overruns), not with it being universal. Keep it at its measured rank.
8. **B's WAL (637 MB) and 9/26 busy checkpoints** confirm the starvation pattern at a second site;
   A's WAL is healthy (0/19 busy, 13–67 MB), so the pin is not universal — it is a *reader-shape*
   problem that bites where a long reader exists.
9. **B's 90-second unlock** and C's 162-second unlock make the one-time hot-index build (S4.x /
   `unlock-162s-onetime-hot-index-build`) a real, repeating field cost worth reporting honestly in
   the unlock phase list, not a curiosity.
10. **The rollup build finished on A** (1,582,054 rows, in memory) and was **still building on both
    B and C at export** — so the in-memory columnar build is a live, unbounded cost on exactly the
    two machines with the biggest corpora.

**Deleted claim:** the earlier note that machine A has "6 cores" came from a human label in an
expedition event (*"12 hours run on Lenovo Yoga 6 core"*). The hardware probe says **4 physical /
4 logical**. Trust the probe.

---

## 2. Refuted — do NOT resurrect these without new evidence

| id | why it was killed |
|---|---|
| `crash-kind-sentinel-contradiction` | "unclean-end + WAL absent is a contradiction a kill cannot produce" is wrong: the WAL is deleted by the *next* boot's own verify connection, so the pairing carries no information about how the previous session died. (The instrument defect is real — see §1.2 — the *contradiction* reading is not.) |
| `expedition-estimate-omits-mentions` | The claimed mechanism ("the scan's dict size tracks mentions, not articles") does not hold in the code; the per-article constant matches the measured ~1.15 KB/article. Refuted on all three axes. |
| `unlock-on-the-event-loop` | The unlock route is a plain `def`, not `async def`; the 30.3 s is real but the mechanism, fix and tests were wrong. |
| `diagnostics-bundle-retains-351mb` | The +351 MB is `ru_maxrss` (a process high-water mark), not retained RSS — reframe as "the member's transient peak was ≥351 MB above the prior high-water mark", which is still a real contributor on a box with 225–714 MB available. |
| `mem-floor-absolute-locks-one-worker` | The arithmetic is wrong (a 15 %-of-RAM floor changes nothing on this box) and the proposed test fails under its own fix. **The relax half survives** and is S1.4. |
| `a-expedition-digest-stale-refresh` | Refuted on the data. |

---

## 3. The maintainer's rulings (2026-09-02) — decisions, not suggestions

1. **Below ~4 GB RAM: reduce AND decline.** Auto-apply a small-RAM budget (≈2 pooled connections,
   ≈16 MiB page cache, no in-memory columnar rollup) **and** decline the whole-corpus background
   scans by default, each refusal stated with the real numbers, a visible translated caveat, and an
   override. Collection keeps running. **Never a hard block** — the AI hardware gate is the
   precedent (it already refuses on this exact box and says why).
2. **Self-cap AND document the hard ceiling.** The app caps its own resident budget and actually
   RELEASES memory when paused, accepting slower collection on small machines; the manual documents
   the operator's real ceiling (a cgroup `MemoryMax`), which converts a desktop freeze into a clean
   app restart with the corpus intact.
3. **Read the host kernel log at boot — always, local-only.** Best-effort `journalctl -k` on a
   background thread with a timeout, storing only lines naming this app's own process. Zero network,
   read-only, shared only on export.
4. **The diagnostics bundle pauses collection while it runs** (the existing exclusive-hold
   mechanism) and still runs **every** member — the bundle is the maintainer's only evidence channel.
5. **Bound the gate AND serialise the pass tail** — both.
6. **The `database is locked` fix is targeted**: fix the two failing call sites; do not change the
   engine's transaction mode in this batch (record it as a separate reviewed slice).
7. **Both ends under load**: the server publishes an honest load reading and the UI backs off with
   one honest banner, recovering automatically.
8. **Collect files AND host checks from machines A and B** (§8).

---

## 4. Ranked root causes (after A and B)

| # | id | confidence | kills the process? | measured on |
|---|---|---|---|---|
| 1 | **Workers hold a pooled 64 MiB-cache connection across the fetch; the governor cannot preempt them** (§1.8) | **confirmed, measured** | plausible proximate cause — B reached 6,767 MB RSS / 94 MB available and held it 2.5 h | B (directly), A + C (same defaults, same shape) |
| 2 | Resident budget unscaled to RAM (§1.4) — pool 8+64 × 64 MiB, auto-on in-memory rollups, no DuckDB limits | confirmed | sets the floor #1 overruns | all three |
| 3 | **`SQLITE_BUSY_SNAPSHOT` at the pass tail** (§1.5b) — **the most frequent error in the fleet** | confirmed, reproduced | no — loses passes, poisons the session | A 234 · B 144 · C 82 |
| 4 | The guard pauses but releases nothing; swap never sampled (§1.3) | confirmed mechanism | contributor | C, and by construction #1's consequence on B |
| 5 | Pass-tail concurrency + unbounded gate acquire (§1.7) | likely | plausible proximate cause of C-S2 | C (window), all (code) |
| 6 | Request storm: alerts / stats / trending / no backoff (§1.6) | confirmed | contributor | **B 142.8 s alerts**, C 558.8 s, A 47×429 |
| 7 | WAL reader-pin starvation (§1.5c) | confirmed where a long reader exists | contributor | C 26/30 busy, B 9/26; A clean |
| 8 | Whole-corpus qualification scan per batch (§5) | confirmed | contributor | all three (`qualification_per_pass=5`) |
| 9 | `statement_deadline` pool poison (§1.5a) | confirmed, reproduced | no — 500s/503s, degraded briefing | C only in these windows |
| 10 | Learned ceiling can never relax (S1.4) | confirmed | not a cause — a permanent throughput loss | **A: 1 permit with 1,239 MB free** |
| 11 | Crash-kind blindness (§1.2) | confirmed | not a cause — the reason we cannot name one | all three |

**Honest statement of what is still NOT established:** no artifact names the proximate cause of any
of the four deaths. #1 is the strongest candidate because it is the only mechanism measured driving
a machine to 94 MB of available RAM and holding it there — but B survived that episode, so "it
reaches the wall" is not the same as "it is what killed the process". An OOM-kill, a host reset, a
`SIGHUP` from a closed terminal and a native fatal still leave the identical app-side record until
Phase 0 ships. **A is the machine most likely to be genuinely OOM-killed** (3.9 GB RAM, 1 GB swap);
C's 7.25 GiB of swap is what converts the same pressure into a desktop freeze. Do not write a crash
cause into any user-facing string yet.

---

## 5. The slices

Ordered. Phase 0 first because it is small, changes no behaviour, and without it the next crash is
again unclassifiable — every later phase's acceptance number is read through these instruments.
Each slice: **goal → anchors → what to build → test + the mutation that must redden it → risk**.
⚠ marks a slice that requires the skeptic pass with the negative-space lens.

### Phase 0 — the truth layer

#### S0.1 — the WAL probe is measured before anything can touch the file ⚠
**Goal:** `wal_state_before_open` stops being an artifact, and the three places that infer a clean
shutdown from it stop lying.
**Anchors:** `src/api/unlock.py:341-342` (verify connect/close), `:228` (`_forensic_timer`),
`:278-280`; `src/monitoring/forensics.py:280-318` (`absent` on `FileNotFoundError`) and `:311-315`
(the reason text); `src/api/main.py:314` (`record_session_start`); `src/monitoring/p0_validation.py:582-586`.
**Build:** (a) read `wal_state_before_open()` in the lifespan startup right after
`record_session_start()` and persist it into the sentinel as `wal_at_boot` — this is the
load-bearing read, because **a wrong-passphrase attempt also deletes the WAL**, so fixing only the
order inside `unlock()` leaves every retry blind; (b) in `unlock()` take the reading at the top and
pass it into `_finish_unlock(wal_state=…)` (note `create_db` also calls `_finish_unlock`, and a
fresh store legitimately has no WAL); (c) time the verify step as its own phase — call it
*"passphrase verify + WAL recovery + checkpoint-on-close"*, because the 24.7 s includes wal-index
recovery and the page-size probe, not only the checkpoint; (d) rewrite the reason text, the
`p0_validation` sentence and the P0 runbook §8 claim: **present at boot** ⇒ the last SQLite
connection was never cleanly closed (which includes a clean lifespan teardown that still had a
connection checked out); **absent** ⇒ nothing can be concluded.
**Test:** `tests/test_forensics_wal_at_boot.py`. The portable mechanism pin is a plaintext WAL store
written by a subprocess that `os._exit()`s → assert `-wal` exists → drive the boot read → `present`
with bytes > 0. The route-level twin needs `sqlcipher3` (`unlock.py:330` returns 409 unless
`is_encrypted_file`) — `pytest.importorskip('sqlcipher3')`, and run with `-rs` so a skip is never
read as a pass. Add a **call-ORDER** monkeypatch test (cheap, always runs): record the order of
`wal_state_before_open` vs `connect` and assert the probe comes first.
**Mutation:** restore today's order → the assertion reads `absent`.
**Negative twin:** after a genuinely clean close the boot read still says `absent` — the fix must
not manufacture a `present`.
**Risk:** low. No behaviour change beyond measurement order.

#### S0.2 — shutdown states, the terminating signal, and SIGHUP ⚠
**Goal:** a deliberate stop can never be rendered as a crash, and a death *during* teardown is
distinguishable from a death before it.
**Anchors:** `src/api/main.py:352-366` (teardown: `get_scheduler().stop()` → `dispose_engine()` →
`record_clean_shutdown()`), `:2532` (`uvicorn.run` with no `timeout_graceful_shutdown`);
`scripts/launch.sh:78,83,86,97`; `install.sh:608-610,694-696` (`Terminal=true`).
**Build:** (a) stamp `state:'shutting-down'` + `shutdown_reason` **first** in the teardown, then
`dispose_done` after `dispose_engine()`, then `clean`; (b) extract a real
`install_signal_handlers()` in `main.py` that registers **SIGHUP** onto the same graceful path as
SIGTERM and records which signal initiated the stop, and call it before `uvicorn.run`; (c) pass a
`timeout_graceful_shutdown` (e.g. 30 s) so a logout SIGTERM during a 9-minute request cannot leave
the app waiting until logind SIGKILLs it; (d) `launch.sh`: add `HUP` to the trap and keep the
existing `wait "$SERVER"`.
**Correction applied:** Ctrl-C (SIGINT) and the in-app power button ARE clean today. Only the
**advertised** stop path — closing the terminal window, or a desktop logout — is SIGHUP, and
uvicorn handles only SIGINT/SIGTERM, so the process dies with `SIG_DFL` before the lifespan runs.
**Test:** a pty test that imports and calls the REAL `install_signal_handlers()` (a stub that
"mirrors main()" would pass whether or not `main.py` changed — that is the vacuity trap), plus an
AST guard that `main()` calls it before `uvicorn.run`.
**Mutation:** drop the SIGHUP registration → the sentinel stays `running`.
**Risk:** medium — signal handling. Verify the in-app shutdown button and Ctrl-C both still end
`clean` (negative twin).

#### S0.3 — the host kernel-log reader (RULED: always, local-only) ⚠
**Goal:** the next crash names its own kind.
**Build:** at boot, after `record_session_start()`, **on a background thread** (never on the
lifespan critical path — a hung `journalctl` must not delay a boot), run `journalctl -k -b -1` and
`journalctl -k -b 0 --since <previous started_at>` with a ~5 s timeout, falling back to a
`/var/log/kern.log` tail. Grep for `oom-kill` / `Killed process` / `segfault` / `traps:` naming the
previous pid or `comm` (**truncated to 15 chars: `open-omniscien`**). Store the matched lines plus
an availability reason into the sentinel's previous-session block.
**Honesty rules that decide the verdict vocabulary:** an empty result is `no-kernel-evidence`,
never `clean`; a missing binary is `no-journalctl`; a volatile journal (`Storage=volatile`, no
`/var/log/journal`) or missing `adm`/`systemd-journal` group membership is `permission-denied` /
`no-journal` — say which. Render: `unclean-end · kernel OOM-killed (<line>)` /
`· host reset (previous boot log ends without shutdown)` / `· stopped by SIGHUP (window closed)` /
`· no host evidence available (<reason>)`.
**Test:** monkeypatch `subprocess.run` with canned outputs — OOM line → `oom-kill` with the verbatim
line; segfault → `native-fatal`; `FileNotFoundError` → `no-journalctl`; non-zero rc → `no-journal`;
**empty output → `no-kernel-evidence`**.
**Mutation:** make the reader return `clean` on empty output → the last case must fail.
**Risk:** low. Read-only, zero network, opt-out via env for the paranoid.

#### S0.4 — the previous session's own numbers
**Goal:** `previous_session_report` stops attaching the CURRENT session's last collector sample to
the CRASHED session's verdict (`forensics.py:351`), which is how an OOM was "inferred" from numbers
belonging to the wrong process.
**Build:** a tiny per-session high-water sidecar (atomic replace, no fsync, ≤ every 30 s) carrying
`rss_max`, `avail_min`, `swap_used_max`, `last_ts`, `phase`; snapshot it into the sentinel at boot.
**It must OMIT a field it cannot measure, never write 0** (the `.get(key, 0)` lesson).
`render_text` (`forensics.py:571`) does not print `last_collector_sample` at all today — add it, or
the fix is invisible in the .txt the maintainer sends.
**Mutation:** write 0 for an unreadable field → the omission test reddens.

#### S0.5 — the pass-tail phase journal
**Goal:** a death in the tail names its step (§1.7).
**Build:** bounded `phase_begin`/`phase_end` records (lane-kick, discovery, enrichment,
briefing-refresh, `hygiene:checkpoint`, `hygiene:trim`, `record_run`) with rss/avail/swap, in a
sidecar — **not** as extra rows in `scheduler_runs.jsonl`, whose `recent_runs()` reader
(`runlog.py:44-60`) would surface them as phantom runs in the task manager, bundle and forensics.
Cap/rotate it (the 2026-08-06 untrimmed-stream lesson). **A `begin` without an `end` must stay
unmarked** — the absence IS the evidence; never write a terminal marker to mean "handled".
**Test:** monkeypatch the INNER step (`checkpoint_wal`) to raise — `run_pass_hygiene` swallows
everything (`hygiene.py:244-256`), so patching it proves nothing — and assert the report says
*died during: hygiene:checkpoint*.

### Phase 1 — stop the bleeding (ruling 1 + 2)

#### S1.0 — a worker must not hold a DB connection across a network fetch ⚠ **[do this first]**
**Goal:** cut the collector's resident ceiling from `workers × 64 MiB` to something bounded, and
make the governor's back-off able to reclaim memory instead of only slowing new work.
**This is the measured headline of §1.8** — build it before anything else in this phase.
**Anchors:** `src/scheduler/runner.py:904-925` (`_worker`: `governor.acquire()` → `session_scope()`
→ `_process_source`), `:597-619` (`_process_source` → `ingest_source(session, source, fetcher=…)`,
i.e. the fetch runs inside the session), `:930-931` (`ThreadPoolExecutor(max_workers=w_max)`);
`src/scheduler/bandwidth.py:52-56` (`set_permits` never preempts holders), `:87` (`active`);
`src/database/session.py:75-76,121-123`; `src/monitoring/collect_perf.py:398`.
**Build — restructure the worker into fetch-then-store:**
1. Do the network work **outside** any session: fetch the feed and the article bodies into memory
   (or a small bounded staging structure), then open `session_scope()` only for the store phase.
   `ingest_source` will need a seam — a fetch step returning what it fetched, and a store step
   taking it — mirroring the existing stage-then-gate shape used elsewhere in the codebase for the
   write gate.
2. If (1) is too large for one slice, ship the **bounded interim**: a second semaphore that caps
   the number of workers holding a *session* (not a permit) at a small number derived from the
   memory budget (S1.1), so the fetch fan-out stays 50 while the DB fan-in is ≤ N.
3. Either way: make the per-connection `cache_size` a function of that cap, not a constant —
   `workers × cache_mb` is the number that must fit, and today nothing computes it.
**Test:** `tests/test_collect_worker_holds_no_session_across_fetch.py` — a fake fetcher that blocks
on an event while N workers are dispatched; assert `engine.pool.checkedout()` stays ≤ the cap while
all N are inside their fetch (today it reaches N). A second test asserts the store phase still
commits per source and the tally is unchanged (byte-identical outcome).
**Mutation:** restore the fetch inside `session_scope()` → `checkedout()` reaches N and the test
reddens by name.
**Field twin (the acceptance number, operator-run):** on B, a pass with the same
`collect_parallelism=50` must not reach 6.7 GB RSS; report `rss_max` and `mem_avail_min` from the
collect_perf ring before/after. **Do not claim a multiplier without that run.**
**Risk:** high — this is the collector's hot path. Full skeptic matrix, data-safety lens included:
the store phase must keep the existing per-source commit semantics and the batched-commit
no-loss fallback (`ingest.batch` — B's ring shows it firing 8 times, so it is live and load-bearing).


#### S1.1 — a RAM-aware resident budget ⚠
**Goal:** the app's floor scales with the machine.
**Anchors:** `src/database/session.py:75-76` (pool 8+64), `:121-123` (64 MiB per connection);
`src/analytics/rollup_serve.py:98-110` and `map_serve.py:85-99` (auto-on when duckdb imports);
`src/analytics/columnar.py:117-126` (`_offline_config` sets neither `memory_limit` nor `threads`);
`src/api/main.py:239-250` (boot warm); `src/config/power_profiles.py:84` (`PUBLISHED_KNOBS`),
`:230` (`sqlite_cache_mb`).
**Build:** `src/config/memory_budget.py` — resolve once at boot from total RAM (+ available, + own
RSS), publish it in the perf/diagnostics payloads, and wire it **through the existing
power-profile knob table** so it stays visible and overridable:
- total < 4 GB → `OO_DB_POOL_SIZE` 2, `OO_DB_MAX_OVERFLOW` 6, `sqlite_cache_mb` 8–16,
  `rollup_serve`/`map_serve` `serve_enabled()` **False**, boot warm limited to the cheap views.
- 4–8 GB → pool 4, cache 16, in-memory DuckDB allowed.
- **Always** set `memory_limit` and `threads` in `_offline_config` — never leave DuckDB's
  80 %-of-RAM default on a laptop, at any size.
**Ruling-3 constraint (power profiles are user-activated, suggest-never-silently-switch):** this is
a hardware-aware **default for the knob values**, with a visible statement of what was chosen and
why — it is NOT an automatic profile switch. Both readings must be true of the shipped text.
**Expected effect on C** (arithmetic, to be measured not asserted): resident 1.1 GB → ~0.6–0.7 GB,
so with RSS+avail ≈ 1.88 GB conserved, available rises to ~1.2 GB — above the 512 MB mem-low floor,
ending the 1-worker lock-in.
**Test:** `tests/test_memory_budget.py` with `psutil.virtual_memory` monkeypatched to 3.3 GB →
pool 2, cache ≤16, `serve_enabled()` False, `_offline_config()` carries `memory_limit`+`threads`;
at 16 GB the values are unchanged. Behavioural twin: read back `PRAGMA cache_size` on a fresh
engine — the connect-event must actually apply the resolved value.
**Mutation:** delete the RAM gate → `serve_enabled()` returns True on the 3.3 GB fixture.
**Risk:** medium — it changes pool sizing process-wide. `pool_size`/`max_overflow` are read at
module import (`session.py:90`), so the resolver must run before the engine is built, or be applied
by rebuilding it; check that path explicitly.

#### S1.2 — the memory guard must actually release, and must see swap ⚠
**Goal:** a pause frees something real, and the guard stops mistaking a swap-out for a recovery.
**Anchors:** `src/scheduler/memguard.py:104-113` (rss 85 % / avail 256 MB; resume needs
`rss ≤ 75 %` AND `avail ≥ 512 MB`), `:162-189`; `src/scheduler/runner.py:1569-1603` (paused loop),
`:59-65` (30 s reclaim); `src/scheduler/hygiene.py:75-126` (`release_pass_state`: trafilatura
`reset_caches` + `gc.collect` + `malloc_trim` — nothing else); `src/monitoring/collect_perf.py:45`
(`_DEFAULT_MEM_FLOOR_MB = 512.0`), `:104-117` (`_vitals`, no swap).
**Build:**
1. **Sample swap** — `psutil.swap_memory().used` and `/proc/self/status` `VmSwap` per tick, in
   `collect_perf` and in the guard's readings. Publish them (omit with a reason when unreadable,
   never 0). This turns §1.3's inference into a measurement; do it **before** gating on it.
2. **A real release ladder on engage**, measuring RSS after each step and publishing per-step
   `freed_mb`: dispose the pool's IDLE connections (drops their page caches; checked-out ones close
   on return) → `PRAGMA shrink_memory` on a short-lived connection → close the rollup/map serve
   connections and mark them pending (the serve already falls back to live queries by design) →
   clear the insights read cache → `malloc_trim`. **Skip `gc.collect()` when `VmSwap > 0`** — on a
   swapping box it walks the heap and faults it back in (measured: one pass RSS *rose* 1668 → 1751).
3. **Resume on OUR RSS falling**, not on `available` rising — a swap-out fakes the second.
**Test:** `tests/test_memguard_release.py` — seed an engine with warm pooled connections + a fake
rollup connection, call the new `release_residents()`, assert `pool.checkedin()==0`, the rollup is
marked not-built, and the record lists each step's `freed_mb` (None when psutil is absent, never 0).
Swap test: readings where RSS stays 1600 while `avail` alternates 200/600 and `VmSwap` rises → the
guard must stay ENGAGED.
**Mutation:** remove the dispose step → `checkedin()` stays > 0; drop the VmSwap term → the guard
flaps engage/release (today's behaviour).
**Field replay (anti-vacuity):** copy the 200 real ring samples into
`tests/fixtures/collect_perf_machine_c.jsonl`, feed them to `observe` in order, and assert the
CURRENT policy produces ≥1 engage cycle (it must — the field data has 18 engaged samples) before
asserting the new policy's smaller number. A policy change without this replay is unmeasured.
**Risk:** medium-high — disposing pool connections under load. The dispose must be idle-only.

#### S1.3 — below the floor, decline the whole-corpus background scans (ruling 1) ⚠
**Goal:** the app stops doing, by default, the thing that pushes a small box over.
**Anchors:** `src/catalog/qualification.py:393` (`per_source_metrics` per batch),
`src/catalog/qualify_job.py:142-152`, `src/scheduler/runner.py:1116-1117,1232-1243` (the ride-along),
`src/analytics/source_quality.py:210-240`; the precedent gate is `src/llm/backend.py`
(`inference_capability`, which already refuses on this box and states the numbers).
**Build:** a `machine_floor()` verdict (total RAM < 4 GB, or measured available-at-boot < 1 GB)
that (a) applies S1.1's budget, (b) **declines bulk qualification and any whole-corpus scan** with
an honest `{skipped: 'memory', available_mb, need_mb}` — `need` = 64 MiB cache + ~1.2 KB × articles
+ 100 MB, measured not guessed, (c) caps `collect_parallelism`, (d) shows a **visible translated
caveat** in Settings and beside the collection state. **Never a hard block:** the override exists,
is disclosed, and the verdict reports `overridden: true` when used.
**Say the cost out loud:** on machine C the estimate is ~305 MB against 225–714 MB available, so
qualification may effectively never run there by default. That is the honest consequence of the
ruling and must be stated in the caveat, not hidden.
**Test:** `tests/test_machine_floor.py` — 3.3 GB → `below` True with the three numbers in the
reason; 8 GB → False; override → `below` True AND `overridden` True (both directions). Source guard:
no code path calls `resource.setrlimit(RLIMIT_AS)` — DuckDB and numpy reserve virtual space far
above RSS, so an address-space cap is a false ceiling that raises `MemoryError` in unrelated code.

#### S1.4 — the learned ceiling must be able to relax
**Goal:** a box that brushes the mem-low floor once is not pinned at one worker forever.
**Anchors:** `src/scheduler/capacity.py:127-160` (`record_pass`: any `mem_low_ticks > 0` pins the
floor at `mem_low_min_permits`), `:219` (`learned_ceiling`).
**Corrected claim** (the original finding's arithmetic was refuted): the defect is not the absolute
floor value — it is that **the ceiling can never relax**. On C, 499 mem-low ticks out of 11,799
samples pinned it at 1.
**Build:** relax the ceiling (×2, bounded by `w_max`) after a pass with **no** memory-guard engage
(or with mem-low ticks below a small share of samples); keep pinning on a pass that did engage.
**Test:** `record_pass` with ticks > 0 and no engage → the ceiling doubles.
**Mutation:** today's code → it stays 1.

#### S1.5 — document the operator's real hard ceiling (ruling 2)
**Goal:** the manual states the one mechanism that genuinely bounds the app.
**Build:** a USER_MANUAL section: running the app under `systemd-run --user -p MemoryMax=…`
converts a desktop freeze into a clean app restart — **and states the cost honestly**: the app may
be killed; the corpus is safe because the WAL is replayed at the next unlock. Say plainly that a
self-imposed RSS ceiling is not enforceable on Linux (`RLIMIT_RSS` is ignored) and that this is why
the cgroup, not a code constant, is the real ceiling.

### Phase 2 — the confirmed correctness defects

#### S2.1 — `statement_deadline` must never leave an armed connection in the pool ⚠
**Goal:** a deadlined block can no longer interrupt other threads' statements.
**Anchors:** `src/database/maintenance.py:1137,1149-1150,1167-1182,1195-1200`;
`src/database/session.py:75-77,93`.
**Build — four edits, all four needed:**
1. `session.py`: an engine-level **`reset`** listener that calls
   `dbapi_connection.set_progress_handler(None, 0)` when the attribute exists. SQLAlchemy 2.0 fires
   `reset` on every checkin before rollback-on-return, and also for the NullPool read-snapshot
   engines before close — a connection can never re-enter the pool armed. *(Verify the event name
   against the installed SQLAlchemy before relying on it; `checkin` is the alternative.)*
2. `_rearm` (`:1174`) must re-arm **unconditionally** on `after_begin` — drop the
   `any(new_raw is a for a in armed)` skip. Measured: with the reset listener alone, the armer's own
   post-commit statement becomes unbounded, silently breaking the deadline's positive half.
3. The `finally` disarms **only the connection the session still holds**, never the historical
   `armed` list — a foreign disarm strips another session's live deadline (reproduced: X's exit
   erased Y's handler and Y's runaway query completed).
4. Belt: capture `owner = threading.get_ident()` at entry; `_check` returns 0 when the current
   thread is not the owner. Even an escaped connection cannot then interrupt another thread. Cost:
   one `get_ident` per 20,000 opcodes.
**Do NOT** "fix" it by moving the listener to the engine — the code comment at `:1160-1166` is right
that an engine-level `after_begin` would arm other sessions.
**Test:** new `tests/test_statement_deadline_pool.py`, plain sqlite3, three tests + one
sqlcipher3-gated copy (the field error class is `sqlcipher3.dbapi2.OperationalError` and the
translation at `:1188` matches on the string `interrupt`):
- **T1 cross-thread:** `QueuePool(pool_size=1, max_overflow=0)`; thread A commits inside a 0.3 s
  deadline then sleeps past it; thread B runs a ≥20k-opcode recursive CTE → must succeed.
  **Anti-vacuity:** record `id(dbapi_connection)` at A's arm and at B's checkout via a `checkout`
  listener and assert they are the SAME object — with `pool_size > 1` B may get a fresh connection
  and the test passes for free.
- **T1b negative twin (mandatory):** after its commit, A's OWN long statement inside the block must
  still raise `StatementTimeout`.
- **T2 granularity:** a short statement on the poisoned connection succeeds even on the OLD code —
  this pins the 20k-opcode boundary so the suite cannot pass through a statement that never reaches
  the handler.
- **T3 integration:** `run_all_bounded` with two stub producers under a wrapped deadline exactly as
  `diagnostics.py:4310` does, while another thread runs the CTE → must complete.
**Mutation:** revert edit 1 → T1 reddens; keep edit 1 but restore the re-arm skip → T1b reddens.
**Risk:** low-medium. Scale is irrelevant here — the property is per-connection state.

#### S2.2 — an expired deadline must STOP the loop, and the member must keep its payload ⚠
**Goal:** end the "member runs 400 s under a 300 s deadline, every statement failing instantly"
state, which is both the wasted wall and the poison window.
**Anchors:** `src/api/diagnostics.py:4310-4330` (the member wrapper and its outcome vocabulary),
`src/briefing/registry.py:463-490,518-521`; `src/api/heavy.py:230`; `src/monitoring/benchmark.py:108`.
**Build:** give `statement_deadline` a queryable expiry (a small handle, or
`deadline_expired(session)`); `run_all_bounded` treats an expired deadline exactly like its own
budget (break, `truncated=True`); home-cards, card-audit, benchmark, performance and
corpus-integrity check it between items.
**Correction that matters:** do **not** record `skipped-deadline` for an overrunning member — that
path writes only a marker (`diagnostics.py:4318-4324`) and would **discard** home-cards' 10 cards
and card-audit's 14 diagnoses. Add a **`partial-deadline`** outcome that keeps the payload and says
it is partial.
**Test:** drive `_write_all_diagnostics_zip` with a member looping 5 items each issuing a
≥20k-opcode statement under a 0.2 s member deadline → at most ONE item raises, outcome
`partial-deadline`, the payload is present, wall < 1 s.
**Mutation:** current code → items 2-5 each raise and the outcome is `ok`.

#### S2.3 — a diagnostic must not rewrite the surface it diagnoses
**Goal:** the home-cards member stops replacing the live Home feed with its own truncated result.
**Anchors:** `src/briefing/card_diagnostics.py:48` (`get_briefing(force=True)`);
`src/briefing/service.py:243-283` (writes `briefing_cache.json` unconditionally at `:272-273`).
**Build:** compute over `run_all_bounded(...)` directly (or read the existing cache); never call
`get_briefing(force=True)` from a diagnostic. Additionally `refresh_briefing` must refuse to replace
a non-empty cache with an empty set **when a deadline expired** — gate it strictly on the S2.2
expiry handle, because an unconditional "never replace non-empty with empty" would freeze a stale
feed on a corpus that genuinely yields zero cards.
**Test:** seed a 3-card cache, run the member with an already-expired deadline → the file is
byte-identical afterwards. **Mutation:** current code → rewritten.

#### S2.4 — the `BUSY_SNAPSHOT` pass failures (ruling 6: targeted) ⚠
**Goal:** discovery and enrichment stop losing passes.
**Anchors:** `src/discovery/channels.py:190,429-438`; `src/analytics/source_topics.py:119-133`;
`src/scheduler/runner.py:1892,1902-1906,1958-1966`; `src/database/session.py:340-352`.
**Correction that changes the fix:** rolling back *before* `begin_nested()` does **not** work — the
read snapshot is taken by the channel's reads **inside** the savepoint, so the identical window
remains. The sound shapes are: hold `write_lock()` from **before the scan through the flush** (every
in-process commit is gated, so none can land between snapshot and write), **or** materialise the
candidates outside any transaction, then `session.rollback()` → `with write_lock(): begin_nested();
add; flush()`. Same shape for `apply_source_topics`, whose own `write_lock` is currently taken
**after** its reads.
**Also:** give each pass-tail ride-along its own short `session_scope()` so one failure can never
mark a 4-hour pass `ok:false`, and route these writes through `run_write_with_retry` (which rolls
back between attempts) rather than letting a flush poison the pass session.
**Test:** `tests/test_discovery_busy_snapshot.py` on a real temp WAL store — monkeypatch the channel
to, mid-scan, commit an unrelated row from a second session/thread (the lane's markets commit), then
run `run_discovery` → `created > 0`, no rollback, and a subsequent `apply_source_topics` +
`session.commit()` must not raise `PendingRollbackError`.
**Mutation:** remove the gate-around-read-then-write → `OperationalError: database is locked` +
`PendingRollbackError`, the exact field signature.
**Negative space:** with NO concurrent commit the unchanged path must still create candidates — the
fix must not disable discovery.
**Out of scope (record it):** the engine-level `BEGIN IMMEDIATE` recipe. It is strictly stronger and
strictly riskier — it changes locking for every read path — and is its own measured slice.

#### S2.5 — bound the gate, serialise the tail (ruling 5) ⚠
**Goal:** the pass tail can no longer hang forever, and stops running three whole-corpus consumers
at once on two cores.
**Anchors:** `src/database/writer.py:105-125` (`acquire()` waits on a Condition with **no timeout**);
`src/scheduler/hygiene.py:203-215,244-252`; `src/scheduler/runner.py:1885,1902,1961,1981,1642,1649`.
**Build:** (a) an optional timeout on `WriterGate.acquire()`, and a bounded acquire for
`checkpoint_wal` that records `wal_checkpoint={'skipped':'gate busy', …}` and moves on, so
`record_run` is always reached; (b) serialise the tail — do not kick `_refresh_briefing_async` while
the lane's qualification scan is running; run the three consumers in sequence.
**Test:** hold the gate from another thread, call `run_pass_hygiene()` → it returns within the bound
with the skip recorded, and `record_run` is still reached.
**Mutation:** revert to the unbounded acquire → the test's join times out and no run record appears.
**Risk:** medium — changes pass-tail scheduling. Watch for a regression in per-pass wall time and
report it.

#### S2.6 — name the holder (instrument, not a guess) ⚠
**Goal:** the next 6,236-second gate wait and the next 3-hour WAL pin have a name.
**Anchors:** `src/database/writer.py:99-103,117-125,153-164` (waits recorded, holder not);
`src/scheduler/hygiene.py:153-161,209-215`.
**Build:** (a) `WriterGate` records `holder` (thread name), `held_since`, `max_hold_s` +
`max_hold_holder`, published in `stats()` and in every `collect_perf` sample; a daemon monitor logs
a WARNING with the holder when a hold exceeds a threshold. **Do not capture a stack on every
acquire** — that is a hot path (the 2026-08-06 instrumentation-cost lesson); capture on demand, in
the watchdog only. (b) an engine `checkout`/`checkin` listener recording per-connection
`{thread, checkout_at}`, surfaced as a diagnostics member — that is what names a WAL pinner.
(c) Add FIFO handoff so `max_wait_s` measures holds rather than starvation (today `acquire()` grants
to any thread that finds the gate free, so a looping re-acquirer can starve a waiter indefinitely —
the 6,236 s figure may be starvation, not a single hold).
**Test:** a named thread holds the lock 0.3 s → `stats()` reports that name and `held_for_s`; after
release, `holder` is None and `max_hold_holder` is retained. Pool twin: a checked-out connection is
listed with its age; **a returned connection must NOT be listed** (an over-eager instrument that
names innocent threads is the negative twin). Register both in conftest's autouse reset list or they
leak across tests.
**Mutation:** drop the owner-name recording → the first assertion fails by name.

### Phase 3 — the request storm (ruling 7)

#### S3.1 — `/api/signals/alerts` must never compute on the request thread ⚠
**Anchors:** `src/analytics/poll_cache.py:171-204`; `src/api/signals.py:140-163` (the only sibling
not using `guarded_read`); `src/analytics/convergence.py:294-301,171-191,486-508`;
`src/static/app-home.js:263-271` + `app-shell.js:134` (the double fire).
**Build:** (a) on a cold/mismatched cache for the **polled default params**, kick the background
refresh and return an honest `{cached:false, building:true, as_of:null}` payload the strip renders
as "computing…" — the briefing service already does exactly this; (b) any remaining live compute
goes through `guarded_read` (cap + single-flight + deadline); (c) fix the frontend double-fire so
opening Home issues **one** request, not two.
**Correction:** an SQL-level lookback pre-filter inside `find_convergences` would change
`scanned_places`, `place_total_mentions` and `baseline_share` — the ordering denominator is the
place's **all-time** mentions. Either keep the all-time denominators via a separate cheap aggregate
or disclose that the totals changed (the 2026-07-18 never-capped-figures ruling). Do not silently
narrow a published denominator.
**Test:** two threads on an empty cache → `_compute` called **once**, the second gets the shared
result or a `building` payload in <50 ms. Endpoint: with a stubbed 2 s compute, the request returns
in <200 ms with `building:true`. Frontend: a node harness extracting the real `loadHome`/`startLive`
asserts exactly **one** fetch to `/api/signals/alerts` after `showTab('home')` (today: two).

#### S3.2 — stop running `COUNT(*)` over hot tables on a poll ⚠
**Anchors:** `src/api/database.py:41-61` (the verified cache), `:68-75`, `:105-197`, `:200-215`
(`/figures`, the 43 s `keyword_mentions` count); `src/api/library.py:98-126`;
`src/static/app-home.js:673`, `app-library.js:977,251-252`.
**Build (cheapest honest step first):** serve-stale + **one** background recompute (the poll_cache
pattern), so a poll never pays a 10–25 s scan. Then move `/figures` off the whole-table count. A
maintained counter is the durable answer **but it must carry the honesty envelope**
(`{value, basis: exact|estimated, as_of}`) and a reconcile in the idle lane — the repo already
records keyword-counter drift, so an articles/links counter without a reconcile would be a
fabricated exact.
**Second miss cause to fix:** the probe uses the **per-connection** `total_changes()`, so a pooled
server misses the cache whenever a different connection serves the next poll (verify with a
two-connection repro: `data_version` differs across connections).
**Test:** after one inserted article, `GET /api/database/stats` issues **zero** `SELECT count(*)`
statements (capture via `before_cursor_execute`) and still reports the new count.
**Mutation:** re-enable the COUNT path → the statement capture is non-empty.

#### S3.3 — warm the key the UI actually requests
**Anchors:** `src/api/insights.py:1447-1468` (warms `tl=None`), `:928-936` (`_tlang('en') → 'en'`),
`:1064-1068`, `:56` (TTL 120 s); `src/static/app-home.js:484`; `src/static/app-corpus.js:730`.
**Build:** warm under the key Home sends (read the operator's `ui_lang` and warm `tl=<lang>` **and**
`tl=None`), or decouple the translation annotation from the aggregation cache so one entry serves
every language — the comment at `:1449-1450` already names this. Add a **stale tier**: `_cached`
returns `cached:true` only while the TTL is alive, so an expired key currently vanishes; serve the
stale value with `as_of` and refresh in the background.
**Test:** call `warm_cache`, then `GET` the exact URL `app-home.js` builds (parse it out of the real
file so drift reddens CI) → `cached: true`. **Today it is `cached: false`** — the test is
non-vacuous on the current tree.

#### S3.4 — both ends under load (ruling 7) ⚠
**Build:** (a) `/api/scheduler/status` (already polled) publishes
`server_load: {loop_lag_ms, heavy_in_flight, mem_guard_engaged}`; (b) the client tracks a rolling
latency + the last 429/503 and multiplies every poll interval by up to 8×, with **one** honest
banner naming the new cadence, resetting on recovery; (c) a polled call retries a 429 **once**, not
four times (mark polled calls so `api()` does not spend 5 attempts on a background refresh);
(d) a stale-served payload carries its real `as_of` and the strip says "as of HH:MM (server busy)".
**Refuter corrections:** do NOT add a queueing semaphore in `get_db` (it recreates pool-timeout
hangs for writes and diagnostics) — if you cap, scope it to polled GETs and fast-fail 429. And the
cache-size knob must ship as a hardware-aware **default with a visible suggestion**, never an
automatic power-profile switch.
**Test (node harness on the real files, fake timers):** after two 503s the next Home tick is
scheduled at ≥2× the base interval and the banner text is set. **Mutation:** current code schedules
at exactly 15,000 ms.

#### S3.5 — the rollup build must not full-scan per batch
**Anchors:** `src/analytics/columnar.py:832` (`SELECT MAX(created_at)` — **no index on
`keyword_mentions.created_at`**, `models.py:1855-1860`), `:843-857` (the `COALESCE(created_at), id`
keyset = a near-full scan per 50 k batch; measured 109–194 s each, 187 batches for 9.31 M rows);
`src/analytics/rollup_serve.py:101-110,268-272`.
**Build:** key the batch loop on the indexed PK (`id`), capturing `MAX(id)` **once** and bounding
`id <= that` so a concurrent delete-then-reinsert cannot land inside the scan (preserve the
scan-boundary invariant); or add a `created_at` index by migration. Gate the auto-on build on the
memory verdict — and read the memguard's own readings rather than fabricating a memory number;
record `skipped: mem-low` in `columnar.json`.
**Test:** capture the statements the REAL build emits and EXPLAIN those (not a hand-written
lookalike) — assert `SEARCH … USING INTEGER PRIMARY KEY` and **no bare `SCAN keyword_mentions`**.

#### S3.6 — take the file I/O off the loop
**Anchors:** `src/api/main.py:602-616` (`_lock_gate` → `app_is_locked` → `locked_state` →
`is_encrypted_file`, a `stat` + 16-byte read of the 4.4 GB DB on **every** request);
`src/api/main.py:2189-2205` (`async def list_sources`, 68,409 rows on the loop, 12.6 s measured).
**Build:** cache the lock state in a process flag, invalidated on **every** path that changes the
store (set_passphrase, create, encrypt/decrypt conversion, panic-wipe — enumerate them, do not rely
on the flag alone). Convert DB-touching `async def` handlers to plain `def`: the real count is
**56** (`main.py` 1, `commodity` 1, `source_management` 50, `source_io` 1, `ingestion` 3) — start
with the polled ones. **Before converting, grep the TEST tree for literal `async def <name>(`
anchors** (the recorded stale-anchor lesson).
**Test:** an AST guard listing `async def` handlers with `Depends(get_db)`; a middleware test that
an unlocked app never calls `is_encrypted_file`.

### Phase 4 — WAL

#### S4.1 — reader-aware checkpoint ⚠
**Build:** `PRAGMA wal_checkpoint(PASSIVE)` **first** (never blocks, never waits, backfills up to
the oldest reader mark), then attempt TRUNCATE only when nothing is pinned (`log_frames ==
checkpointed_frames` after the passive step) with a busy timeout of 0–500 ms. A pinned reader then
costs the gate milliseconds instead of 5 s per boundary. Keep `busy`/frames in the record and add
the oldest-reader age from S2.6.
**Test:** a reader with an unexhausted cursor pins the WAL; `checkpoint_wal(force=True)` → the gate
is held < 500 ms, the record shows `busy=1` **with `checkpointed_frames > 0`** (a passive backfill
happened); after the reader closes, the next call is `busy=0` and the WAL is 0 bytes.
**Mutation:** revert to TRUNCATE-only → the ≥5 s hold assertion fails.
**Keep MEASURE-FIRST:** `wal_autocheckpoint=0` + a writer-side PASSIVE tick is a hypothesis, not a
fix — with pass lengths of 1–6 h, a boundary-only tick would remove the only growth bound *during*
a pass.

#### S4.2 — bound the streaming readers
**Anchors:** `src/analytics/store.py:1477` (`yield_per(20000)` over all 9.3 M mentions, unbudgeted);
`src/api/diagnostics.py:2084`; `src/verification/fixity.py:106`; `src/database/read_snapshot.py:93-100`.
**Build:** wrap each in the registry `_WalGuardResult` shape or keyset pagination with a
close+commit between chunks. **Do not** put a hard max age on `read_snapshot` sessions — it would
abort a legitimate streamed export mid-response; re-arm per chunk or bound by rows instead.

#### S4.3 — WAL bytes in every collector sample
The hourly WAL gauge only records inside idle maintenance, which the scheduler **skips whenever the
memory guard is engaged** — so it is blind exactly on the machine that starves. Record WAL bytes
(and the oldest-reader age when known) in every `collect_perf` sample.

### Phase 5 — the qualification scan

#### S5.1 — hoist the cohort baseline out of the batch loop ⚠
**Anchors:** `src/catalog/qualification.py:393`; `src/analytics/source_audit.py:139,150-186,209-236`;
`src/analytics/source_quality.py:210-240`. Measured with tracemalloc at 117,510 articles: agg dict
17.1 MiB + `ArticleStat` list 75.0 MiB (669 B each) + per-source dicts 39.7 MiB ≈ **131.8 MiB of
Python per call**, plus the 64 MiB connection cache ≈ ~200 MB transient — **once per batch of 20**,
from both the bulk job and the per-pass ride-along.
**Build:** compute `per_source_metrics` + baselines **once per run/pass** (cache keyed on the corpus
epoch + max article id, the `change_token` shape), then judge each batch's candidates against those
frozen baselines with metrics scoped by `source_id IN (…)`. Stream `collect_article_stats` into
per-source/per-language accumulators instead of materialising 117 k objects.
**This changes verdict semantics** (a batch is judged against a baseline up to a run old): **bump
the criteria version and disclose the staleness in the stamp.** The 2026-08-12 ledger entry deferred
exactly this as data-safety-adjacent — do not ship it silently.
**Test:** statement counter over a fixture needing ≥3 batches → the whole-corpus GROUP BY runs
**once per run** (today ≥3). **Verdict-parity twin:** a cohort of ≥8 same-language sources with REAL
spread, including one that must be disqualified and one that must qualify — old path vs new path on
copies of the same DB must stamp identical statuses and identical `flag_criteria` reasons.
**Anti-vacuity:** assert at least one source is disqualified in BOTH runs (a fixture where nothing
fails passes for free — a zero-spread cohort makes p90 = 0 and hides any baseline change).

#### S5.2 — the guard must be able to interrupt the scan it guards
The memory guard polls only **between** batches (`qualify_job.py:142`) and between sources
(`runner.py:981`); the whole-corpus scan runs unguarded inside a batch. Give
`collect_article_stats` a cooperative pressure/`should_stop` callback consulted every N rows of
**both** loops, raising a typed `ScanPaused` the job records as `paused: memory` — **without
stamping any verdict**. Negative twin: healthy readings leave the stamped verdicts byte-identical.

### Phase 6 — the diagnostics bundle (ruling 4)

#### S6.1 — the bundle takes the exclusive hold
**Build:** the bundle acquires the existing exclusive hold (`runner.hold_exclusive()`,
`runner.py:1496-1513`) for its duration so it never competes with a pass, the lane and the rollup
build. **Every entry point that starts equivalent work must check the hold** (the 2026-07-24
lesson — a pause that only stops the primary loop is honest-sounding and incomplete). Release in a
`finally`. **All members still run** — nothing is skipped (ruling 4).
**Test:** with the bundle running, a manual run-now must not start a pass.

#### S6.2 — measure a member's cost honestly
`rss_delta_kb` is computed from `ru_maxrss`, a process **high-water mark** that never falls — which
is why every member after the first big one reports 0. Record real RSS (psutil / `VmRSS`)
before/after each member and keep the high-water rise as a separate, differently-named field; run
`hygiene._malloc_trim` (reuse it, don't write a second one) between heavy members and record
`freed_mb` after the release, so a retained delta is a real finding rather than allocator noise.

---

## 6. Sequencing

**Phase 0 first** — it is small, changes no behaviour, and every later acceptance number is read
through these instruments. Then **S1.0** (the measured headline), then the rest of Phase 1, then
Phase 2 in order (S2.4 is the most frequent fleet-wide error and can ship early — it is independent
of the memory work), then Phase 3, then 4/5/6.

A defensible PR order that keeps each diff small and each risk isolated:

```
PR-1  S0.1 + S0.4          the WAL probe + the previous session's own numbers
PR-2  S0.2 + S0.5          shutdown states / SIGHUP + the pass-tail phase journal
PR-3  S0.3                 the host kernel-log reader
PR-4  S2.4                 BUSY_SNAPSHOT (highest-frequency defect; independent)
PR-5  S1.0                 fetch-then-store  ⚠ the big one, full skeptic matrix
PR-6  S1.1 + S1.4          the RAM-aware budget + the ceiling relax
PR-7  S1.2 + S1.3 + S1.5   release ladder + swap + the floor verdict + the manual
PR-8  S2.1 + S2.2 + S2.3   the deadline family (one coherent change)
PR-9  S2.5 + S2.6          bounded gate + holder attribution
PR-10 S3.1 + S3.3 + S3.6   alerts + the warm key + the loop I/O
PR-11 S3.2 + S3.4          stats/figures + both-ends-under-load
PR-12 S3.5 + S4.1 + S4.2 + S4.3   rollup keyset + reader-aware checkpoint + WAL visibility
PR-13 S5.1 + S5.2          the qualification scan (criteria version bump — needs its own review)
PR-14 S6.1 + S6.2          the bundle's exclusive hold + honest member accounting
```

Nothing in Phase 0 depends on anything else. S1.0 does not depend on S1.1, but shipping S1.1 first
makes S1.0's cap derivable from a real budget rather than a constant.

---

## 7. Verification contract

**Per slice, in the PR body, as a table with no blank cells except the operator column:**

| fix | suite test | the mutation that reddens it, by name | operator artifact that carries the number |
|---|---|---|---|

**Rules that decide whether a green run means anything here:**

- **The mutation matrix is the evidence.** Revert each mechanism the fix ships *separately*; a
  fix with two mechanisms needs two mutations (reverting one of two proves nothing — the recorded
  WAL-guard lesson).
- **Anti-vacuity before assertion.** For S2.1, assert the two threads really shared one DBAPI
  object; for S5.1, assert at least one source is disqualified in BOTH runs; for S1.2, assert the
  unpatched guard produces ≥1 engage cycle on the field-replay fixture. A guard that cannot fail is
  a finding.
- **Negative-space twin on every ⚠ slice.** Name it explicitly: the fix must not turn a working case
  into a refusal. S1.3's twin is "an 8 GB machine is unaffected"; S2.4's is "with no concurrent
  commit, discovery still creates candidates"; S3.1's is "a non-default param still computes".
- **Environment split, stated honestly.** This sandbox has py3.13, Chromium, and `sqlcipher3`
  installs from wheels; it does **not** have a 3.3 GB box, a GB-scale WAL, or the field corpora.
  Mechanism tests (thread identity, statement counts, call order, per-connection state, pool
  checkouts) belong in the suite. Numbers (RSS, wall time, engage cycles per day, WAL max) are
  **operator artifacts** — write `not-measurable-here`, never a fabricated pass.
- **Skips are visible.** Run with `-rs`; a `pytest.importorskip('sqlcipher3')` guard that silently
  skips must never be read as green.
- **Baseline diff** per §0, including the pass-count delta check.

**Acceptance for the batch, on the maintainer's own machines (not a verdict — numbers):**

| metric | today | source |
|---|---|---|
| B pass `rss_max` / `mem_avail_min` | 6,767 MB / 94 MB | collect_perf ring |
| A `locked_errors_total` | 234 | error log |
| C memguard engage cycles/day | ~79 | error log |
| C `interrupted` on `/api/scheduler/activity` | 37 | error log |
| C `hygiene.wal_checkpoint.busy` share | 26/30 | scheduler runs |
| B `/api/signals/alerts` p50 | 124,953 ms | request-latency |
| A permits with >1 GB available | 1 | collect_perf ring |
| bundle `benchmark.json` cases `interrupted` | 14/15 (C) | bundle |

---

## 8. Operator steps — only the maintainer can produce these

**Ruling 8 was: files AND host checks, on both A and B.** A and B's bundles have since arrived and
are folded in (§1.8–1.9), so what remains is the host-side half, plus the one thing no bundle can
carry.

**Per machine, as soon as possible (a boot rotation destroys the -1 journal):**

```
journalctl --list-boots
journalctl -k -b -1 --no-pager | grep -iE 'oom|out of memory|killed process|segfault|hung_task|traps:'
journalctl -k -b  0 --no-pager | grep -iE 'oom|killed process|segfault'      # an OOM does NOT reboot
journalctl -b -1 -n 80 --no-pager      # does it end at "Reached target Shutdown", or mid-sentence?
last -x -n 20                          # a reboot with no preceding shutdown = a host reset
coredumpctl list 2>/dev/null | tail
free -m ; swapon --show ; nproc ; cat /proc/pressure/memory 2>/dev/null
grep -E 'Storage' /etc/systemd/journald.conf ; ls -d /var/log/journal 2>/dev/null
id | grep -oE 'adm|systemd-journal'     # without membership, other boots' kernel lines are hidden
```

If the journal is volatile or the group membership is missing, `-b -1` returns nothing — that is
`no-journal`, **not** "no crash". Say which.

**Before the NEXT unlock on any machine that has crashed:**

```
ls -l <data>/open_omniscience.db-wal
```

The file is intact until the passphrase is submitted, and the current probe destroys it (§1.2).
This is the only honest WAL-at-crash measurement available until S0.1 ships.

**Questions only you can answer:**

1. How is the app started and stopped in practice — desktop icon (terminal window), `launch.sh` in
   a terminal, `open-omniscience` directly, autostart? Was the launcher window still open when you
   found the machine?
2. Was the app process **alive but frozen** (`ps -C open-omniscience`) or **gone**?
3. Was the machine itself frozen (mouse dead, no tty) or only the app?
4. Was a browser tab open on Home during the runs, and roughly how many tabs? (The Home poll chain
   drives the heaviest endpoints; B logged 21.9 briefing requests/minute.)
5. Was `install.sh` re-run between any two crashed sessions?
6. Is `OO_AUTOSTART` in use anywhere — could two instances have been launched?

**After the batch ships, the field twins:**

- One pass on **B** at the same settings: `rss_max` and `mem_avail_min` from the collect_perf ring.
- One 72 h soak on **C** with the Home tab open: engage cycles/day, `wal_history` max, the
  `busy` share, `/api/database/stats` p95, and `0` `interrupted` on `/api/scheduler/activity`.
- One bundle from **A**: `locked_errors_total` should fall from 234 toward 0.
- A P0-style validation run — read its collector check as **not-measurable** unless ≥1 full pass
  ran, and note that the run itself contaminates the collect_perf window.

---

## 9. Scope fences

**Do not, in this batch:**

- Change the engine's transaction mode / adopt `BEGIN IMMEDIATE` globally (ruling 6 — record it as
  its own reviewed, measured slice).
- Add any form of auto-restart or watchdog relaunch (the standing "honesty first" ruling).
- Call `resource.setrlimit(RLIMIT_AS)` — DuckDB and numpy reserve virtual space far above RSS; it
  is a false ceiling that raises `MemoryError` in unrelated code. The cgroup is the real one (S1.5).
- Turn the hardware verdict into a hard block, or switch the power profile automatically (ruling 1
  + the 2026-07-12 power-profiles ruling: hardware-aware **defaults** with a visible statement, yes;
  a silent profile switch, no).
- Skip `performance.json` / `benchmark.json` on a small box — they are the maintainer's evidence
  channel (ruling 4).
- Touch per-host politeness, robots fail-closed, the honest UA, the airplane socket guard, or the
  transport (no downgrade, ever). If a slice would touch any of these, you have the wrong shape.
- Narrow a published denominator to make a scan cheaper without disclosing it (S3.1's convergence
  totals — the never-capped-figures ruling).
- Delete or quarantine any user data as part of a memory fix.

**Deliberately deferred, recorded so they are not rediscovered as new:**

- The engine-level `BEGIN IMMEDIATE` recipe (above).
- `wal_autocheckpoint=0` + a writer-side PASSIVE tick — measure first; with 1–6 h passes a
  boundary-only tick would remove the only in-pass growth bound.
- The btrfs `chattr +C` (nodatacow) recommendation for machine B — document it, do not automate it.
- Machine B's 6.8 GB of wiki dumps are **inert** at boot and per pass (verified: nothing in
  `_run_startup_upkeep` or `run_once` imports `src.wiki.dumps`/`dump_index`/`dumpread`; the
  scheduler imports only `track_watched`). B's extra exposure is its 6.9 GB DB and 15.6 M mentions,
  not the dumps. Add a source guard so a future boot-time dump scan cannot land silently.

---

## 10. What this batch does not fix

Stated plainly so no one reads more into it than it earns:

- It does not prove what killed any of the four sessions. Phase 0 makes the **next** one
  answerable; it cannot recover the four that are gone.
- It does not make a 3.3 GB machine fast. Ruling 1 makes it **honest and stable** — collection
  continues, the heavy background scans decline with their numbers stated, and the machine stays
  usable. That is a deliberate trade, and the caveat must say so.
- It does not address throughput. Several fixes here (S1.0's session cap, S1.3's refusals, S2.5's
  serialised tail) will make some passes *slower* on some machines. Report that honestly in the
  before/after rather than hiding it — the 2026-07-24 throughput brief is where speed is bought
  back, and it should be re-measured after this batch lands, not before.
