# Field instance slowness at 1.3 M articles: analysis of the 2026-09-11 bundle and the 2026-09-21 forensics

**Status: ANALYSIS ONLY. Nothing here is built.** Maintainer report that prompted it
(2026-09-21): *"my running instances were each very slow despite having been launched for the
first time in entirely new VMs with the latest repo"*, following the earlier report that
indexing an imported 1.3 M-article database *"would take months or years"*.

Every figure carries its provenance: **[MEASURED]** is a number read out of the bundle or the
forensics file, with the member named; **[CODE-READ]** is a fact verified in the working tree at
`68b295b` (main, 2026-09-21) with the file named; **[ARITHMETIC]** is a shown calculation over
measured inputs; **[HYPOTHESIS]** is a causal claim the evidence supports but does not prove, with
the experiment that would settle it. Nothing below quotes a speed-up multiplier that was not
measured on this instance.

---

## 0. The answer in one page

The instance is not slow at one thing. It is slow at everything that writes, and everything that
reads waits behind the writes. Six links, each measured:

1. **Every stored or re-indexed article is a random-write storm** across ~20 B-trees plus the
   FTS5 index, on a 27.7 GB encrypted store, through an **8 MB page cache**, on a VM with
   **~2.2 GB of free RAM**. The store is seven times the RAM. Nearly every page touched is a
   16 KB read plus a decrypt, and later an encrypt plus a write.
2. **The single write gate is held for minutes at a time.** The collector's batched flush holds
   it across the article insert (which fires the FTS insert trigger), the per-article keyword
   index, the link rows and the commit. Measured: busy 79 % of the sampled uptime, one hold of
   **1,329 s**, four threads permanently queued, longest wait **1,840 s**.
3. **The queued collector threads each hold a pooled connection**, and on this RAM tier the pool
   is **8 connections**. Every API request that needs a connection waits the full **30 s pool
   timeout** and returns **500**. Measured: 153 stalls at exactly 30.0 s on the task-manager
   poll, 160 of its 332 calls failed, and three members of the diagnostics bundle itself died
   on the same timeout.
4. **The collection governor reads that saturation and cuts fetch permits to 1** (200 of 200
   samples). Collection collapsed to **267 to 508 stored articles per 6 to 11-hour pass**, about
   **45 per hour**, with fetch failures outnumbering stores five to one.
5. **The VM is over its memory.** The session before the bundle peaked at **4,158 MB RSS on a
   4,029 MB VM** with swap 100 % used and ended uncleanly. The diagnostics bundle's keyword-log
   digest alone raised RSS by **3.4 GB**.
6. **Corpus-sized work sits on polled and per-import paths** at 11 M keywords, 9.86 M of which
   are orphans the merge carried in without their mentions: a 17 s counter-freshness probe on
   the Insights top path, an 84 s super-group total, and **2 h 25 min of corpus-wide stages for
   a 77 MB import** whose merge step took 7 s.

**Why the latest repo in a fresh VM did not help.** Every September throughput change is on
the CPU side of ingest (date extraction 10×, keyword extraction 2×, the governor's self-throttles,
the stacked-poll fix). They were measured on a plaintext 4-core sandbox where the collector is
CPU-bound, and the audit that produced them says so. This instance is **write-bound**: the
governor's own samples say `writer-saturated` in every one of 200 readings. A faster extractor
on a write-bound machine changes nothing visible, and a fresh VM does not change the ratio of
corpus to RAM, which is the variable that matters. The corpus came with the instance.

**Why the drain would take months.** The re-index of the 1,282,083 imported articles runs in
its worst configuration: one commit per article, no phase instrumentation, and the same
per-article write pattern as ingest. The one rate that can be bounded from the forensics is
**~870 articles per hour**, which is **61 days** for the backlog if it had the machine to itself.

**What changes the order of magnitude** is not any of the constant-factor fixes but a bulk
build: extract in parallel, sort, load in key order with the secondary indexes dropped, rebuild
them sequentially. That is how the merge already builds the FTS index (23.7× measured on its
insert step) and how every large indexer works. The rest of this report is the evidence, the
findings that were not previously recorded, and the ordered plan.

---

## 1. Sources and their limits

| Source | Generated | What it covers |
|---|---|---|
| `oo-all-diagnostics.001of001.zip` (72 members) | 2026-09-11 15:48 to 16:25 UTC | the running instance while collecting, with the bundle owning the machine |
| `oo-session-forensics-20260921-1200.txt` | 2026-09-21 12:00 UTC | the same instance ten days later, collection off, the drain running |
| `articles.csv` (200 rows) | operator export | a sample of the Articles tab; consistent with the corpus shape below and not otherwise used |
| the working tree at `68b295b` | 2026-09-21 | the code every [CODE-READ] cites |

**What was not available, and therefore not claimed:**

- A bundle from any of the other instances. Everything here is evidence at 1.3 M articles on
  one 6-vCPU Qubes VM; section 6 says what transfers and what does not.
- The drain's own rate. Its progress counter restarts per run and it writes no run journal, so
  the 870 per hour above is a bound derived from the boot time and the counter, not a reading.
- Per-table storage: `dbstat` is not compiled into the bundled sqlcipher3, so the size of the
  FTS index, the mention indexes and the freelist composition are unknown.
- The journals of the imports that brought the 1.28 M articles (`data/run_logs/`, 58 files, not
  in the bundle). The one import journal present is for a 77 MB backup and is used as such.
- Per-statement timings inside the collector's gate window. The slow-statement recorder shows
  three SAVEPOINT statements at 8 to 11 minutes and no INSERT above its 500 ms threshold, which
  is itself a finding (F5).

---

## 2. The instance

| Property | Value | Provenance |
|---|---|---|
| Host | Qubes AppVM on an Intel i7-1065G7 at 1.3 GHz, 6 vCPUs | [MEASURED] `manifest.json` hardware |
| RAM as seen by the app | 4,029 MB at the bundle's boot; 4,421 MB during the 09-06 import; 7,255 MB during the 09-09 export; 5,407 MB on 09-21 | [MEASURED] hardware blocks of each run; Qubes balloons the VM |
| Free RAM while collecting | 2,123 to 2,328 MB | [MEASURED] `collect_perf`, 200 samples |
| Swap | 1 GB, 730 MB to 1,024 MB used | [MEASURED] beats, forensics |
| Disk | NVMe, 100+ GB free | [MEASURED] hardware |
| RAM tier chosen by the app | **small** (pool 6 + 2 overflow, page cache **8 MB** per connection) at the bundle's boot | [CODE-READ] `src/config/memory_budget.py` `_SMALL`; [MEASURED] the pool errors say `size 6 overflow 2` |
| Collector workers | configured 50, floor-capped to **8** below the 4 GB floor, 5 active, **1 permit** | [MEASURED] `scheduler.status.concurrency`, `collect_perf` |
| Store | **27.7 GB**, 16 KB pages, 1,691,420 pages, 135,588 free pages (2.2 GB), `auto_vacuum=incremental`, WAL 48 MB | [MEASURED] `storage-composition.json` |
| Articles | 1,341,206 | [MEASURED] manifest |
| Keywords | 11,003,857, of which **9,863,504 have zero mentions** | [MEASURED] `keyword-engine.json`, `corpus-integrity` |
| Mention rows | 4,702,193 | [MEASURED] manifest |
| Articles with any keyword | 61,012 | [MEASURED] `keyword-growth.json` totals |
| Re-index backlog | **1,282,083** articles across the import batches; 3,190 done in the run current on 09-21 | [MEASURED] forensics 09-21 |
| Article size | median 398 words, mean 615; 5,694 bytes mean in the merge's sample | [MEASURED] `article-length.json`, `merge-diag.json` |
| Store density | 20.7 KB per article all-in, with 95 % of articles unindexed | [ARITHMETIC] 27.7 GB / 1.34 M |

Two derived facts frame everything after. The mention rows belong to the ~51,000 articles the
instance held before the imports, about **92 per article** [ARITHMETIC]. So the backlog implies
roughly **118 M mention rows** still to write, each into eleven B-trees [CODE-READ: ten secondary
indexes on `keyword_mentions`, `src/database/models.py`]. And the page cache is **0.03 %** of the
file [ARITHMETIC: 8 MB / 27.7 GB]; the OS page cache, at ~2 GB free, covers at most 8 %.

---

## 3. What is slow, measured

### 3.1 The UI

From `request-latency.json` (a bounded recent-window reservoir) and `stall-forensics.json`:

| Route | n | p50 | p95 | Failures | Note |
|---|---:|---:|---:|---|---|
| `GET /api/scheduler/activity` (task-manager poll) | 332 | 15,436 ms | 30,135 ms | **160 × 500** | 153 stalls at exactly 30.0 s |
| `GET /api/insights/latest` | 1 | 60,675 ms | | 503 | deadline |
| `GET /api/briefing` | 3 | 3,426 ms | 60,114 ms | | |
| `GET /api/insights/trending-windows` | 7 | 5,019 ms | 60,076 ms | 429 ×5, 503, 500 | busy / deadline |
| `GET /api/signals/flood`, `/bury` | 3 | | 60,009 ms | 500 ×2 | two pool waits back to back |
| `GET /api/database/stats` | 342 | 6 ms | 25 ms | | p99 3,589 ms, max 8,461 ms |
| `GET /api/system/vitals` | 331 | 9 ms | 102 ms | | p99 853 ms |

The event-loop watchdog recorded lag up to **3,261 ms** and, at 13:56:48, **five concurrent**
`/api/scheduler/activity` requests aged 0.9 s to 25 s. The frontend error log holds **732**
`fetch-5xx` entries, 499 of them on that route. The snappy bar (p95 < 500 ms) is failed by the
one route with a real sample and breached by thirteen thin-sample routes.

The 30.0 s is not a coincidence. It is `pool_timeout` [CODE-READ: `src/database/session.py:97`,
`OO_DB_POOL_TIMEOUT` default 30]. The bundle's own members failed with the exact message:
`QueuePool limit of size 6 overflow 2 reached, connection timed out, timeout 30.00`
(`performance.json`, `schema-drift.json`, and the store and corpus blocks of `benchmark.json`).

### 3.2 The write gate

From `write-gate.json` and `soak-window.json`, process-cumulative over 2,330 s of uptime:

| Counter | Value |
|---|---:|
| grants / contended | 7 / 6 |
| total held | 1,849 s (busy share **79 %**) |
| longest single hold | **1,329 s**, holder `oo-collect_3` |
| hold in flight at the reading | 342 s, holder `oo-collect_0` |
| waiters at every sample | 4 (185 samples) or 3 (15 samples) |
| longest wait | **1,840 s** |
| total wait, summed across waiters | 3,165 s |

The pool listing at the same instant showed **all 8 connections checked out**: five collector
threads, the scheduler thread, the diagnostics job and one API worker.

### 3.3 Collection

From `scheduler.recent_runs` and `collect_perf` (200 samples over five minutes):

| Pass | Mode | Duration | Sources | Pages | Stored | Failed fetches | Errors | Robots unavailable |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-09-09 02:22 | crawl | 21,412 s (5.9 h) | 174 | 330 | **267** | 1,328 | 925 | 326 |
| 2026-09-08 15:24 | crawl | 38,164 s (10.6 h) | 9 | 627 | **508** | 65 | 3 | 0 |
| 2026-09-07 10:47 | crawl | 39,003 s (10.8 h) | 9 | 575 | **471** | 162 | | 0 |

Every one of the 200 governor samples reads `adjust_reason: writer-saturated`, `permits: 1`,
`download_rate_kbps: 0.0`, `inflight_fetches: 0`. The pass discovery phase reached **1,590,907 ms**
(26.5 minutes). Round-robin covers 2,670 sources; at 9 sources per 10.6-hour pass a full cycle is
**~131 days** [ARITHMETIC]; at 174 per 5.9 h it is ~3.8 days. The two passes differ by what the
crawl supplement chose, and neither is a rate a collector should run at.

Per stored article the write gate cost is bounded from the same data: 1,849 s held over 7 grants
is 264 s per grant, and a collector batch is at most 8 articles [CODE-READ: `OO_COLLECT_COMMIT_BATCH`
default 8, `src/ingest/batch.py`], so **at least 33 s of exclusive write time per stored article**
[ARITHMETIC], against 80 s of wall time per stored article in the 09-09 pass.

### 3.4 The import (the one journal available)

`imp-20260906T213621Z-ad2a86`, a **77 MB** backup, `owns_the_machine: true`, 6 workers,
commit batch 200, cache 256 MB. Total **8,710 s (2 h 25 min)**:

| Stage | Seconds | What it does | Scales with |
|---|---:|---|---|
| `pre_restore_snapshot` | 2,362 | a full copy of the 27.7 GB corpus | corpus |
| `corpus_epoch_bump` | 1,895 | bump the epoch, then `reconcile_source_counters` over 86,470 sources | corpus |
| `snapshot_working_copy` | 1,816 | a second full copy | corpus |
| `verify` | 1,118 | `quick_check` 814 s + `foreign_key_check` 303 s over the whole file | corpus |
| `keyword_counter_reconcile` | 761 | corpus-wide counter pass | corpus |
| `event_mirror_refresh` | 699 | side-file mirror rebuild | corpus |
| `merge` (all 20 steps) | **7.4** | the actual import | import |

The stage-4 re-index was deferred to the drain, as designed. The two safety copies left **55 GB**
of `pre-restore-*.db` files in the data folder at the time of the bundle.

### 3.5 The re-index drain

On 2026-09-21 the job read `running [3190/1282083] import 1 (48368 article(s))` with the app booted
at 08:21 and the forensics taken at 12:00. If the job auto-resumed at boot, which the current code
does [CODE-READ: `src/api/main.py:133`], that is **~870 articles per hour** and **61 days** for the
backlog [ARITHMETIC]. If the job was started later the rate is higher; the status endpoint read
twice an hour apart is the only exact reading. The counter shown restarts at zero on every run
(F11), so the 3,190 says nothing about earlier runs.

The drain's configuration is fixed by the caller [CODE-READ: `_reindex_resume_worker`,
`src/api/backup_v2.py`, passes neither `commit_batch` nor `workers` nor `stats`]: **one commit per
article**, 5 pool workers, and the code branch of `reindex_articles` whose apply-phase split is
never recorded. The import path, for the same work, uses 200 and all cores.

### 3.6 Memory and the unclean end

From the bundle's `session-forensics.txt`: the previous session (2026-09-10 19:56 to 2026-09-11
07:55) ended **unclean** with **peak RSS 4,158 MB** against a 4,029 MB VM, **minimum available
1,731 MB**, **peak swap 1,024 MB** (all of it), last phase `collecting`. The app's own wording:
consistent with an external OOM kill, not provable from inside the VM. The 09-21 forensics show
the next previous session ended by **SIGHUP** after 78 s with a **135 MB WAL** to replay.

Inside the bundle run: `keyword-log-digest.json` raised RSS by **3.4 GB** (peak rise), the
benchmark by 483 MB, the keyword-engine report by 315 MB. The pass hygiene step freed 1.5 GB after
a pass that had grown the process to 4,097 MB.

### 3.7 The diagnostics run itself

37.5 minutes, collection paused. The seven slowest members are all corpus scans:
bulletin-weekly 333 s, benchmark 305 s (partial, six cases interrupted by the deadline), source-audit
298 s, leads-quality 285 s, article-length 194 s, non-article-scan 105 s, criteria-calibration 101 s.
Three members produced nothing because the pool was exhausted (3.1). Release gate row C requires a
bundle from this instance *"with every member non-zero"*; this bundle does not qualify, for the
reason in link 3 of the chain.

---

## 4. The causal chain

### 4.1 Per-article write cost on a store seven times the RAM

What one article's apply does, from `index_article` and its callers [CODE-READ:
`src/analytics/store.py`, `src/timemap/whostore.py`, `src/timemap/datestore.py`]:

- ~92 rows into `keyword_mentions`, each maintained in the primary key plus **ten** secondary
  indexes;
- one ORM query per kept term against an 11 M-row keywords index, then an ORM UPDATE per keyword
  touched for the two counters, each UPDATE also relocating the keyword's entry in the
  mention-count index;
- delete-then-insert into the three when/where/who tables, seven more indexes;
- an UPDATE of the article row for the stamp, sentiment and top keyword, which rewrites the whole
  record and fires the FTS update trigger (F2);
- the commit.

With an 8 MB SQLite cache and ~2 GB of OS cache against 27.7 GB, the upper B-tree levels stay
warm and almost nothing else does. Each dirtied 16 KB page is decrypted on read and encrypted on
write, once into the WAL and once at checkpoint. The magnitude on this box is **unmeasured**: the
instrumentation that would give it (`apply_index_s`, `apply_commit_s`) is dead in the branch the
drain runs, and `dbstat` is absent. What is measured is the consequence, 3.2 and 3.3.

### 4.2 The gate is held across the whole batch, FTS trigger included

[CODE-READ: `src/ingest/batch.py:292-330`] `_flush_batched` stages up to 8 articles, runs the
DB-free extraction outside the gate (the C16 change), then `session.flush()` opens the one gate
window: the article INSERTs fire `article_fts_ai` (FTS5 tokenises each body and does its merge
work inside the trigger; the merge path suspends this trigger for exactly that reason,
`src/backup/merge.py:806`), then `_index_one` applies the keyword index per article, then the
links, then `commit()`. Everything in 4.1 happens with the gate held. The 1,329 s hold is one
such window.

### 4.3 The pool starves behind the gate

[CODE-READ: `src/database/writer.py:573-600`] a collector thread acquires the gate inside
`before_flush`, on a session that already holds a pooled connection. Four threads queued on the
gate therefore hold four of the eight connections; the holder has a fifth; the scheduler thread
and any background job take more. An API handler declared with `Depends(get_db)` then waits
`pool_timeout` and fails. `GET /api/scheduler/activity` is such a handler [CODE-READ:
`src/api/scheduler.py:251`], and its p50 of 15 s is the queue, not its query.

The stacked-poll fix of 2026-09-11 (`a4d2c48`) removes the client's amplification, which the
bundle still shows. It does not change the arithmetic: a small-tier pool of 8 against 5 to 8
collector threads leaves at most three connections for everything else while the gate is slow,
and it is always slow here.

### 4.4 The governor cuts permits to 1 because the writer is saturated

[CODE-READ: `src/monitoring/collect_perf.py`, `writer_saturated` from the waiter count]. The
governor is doing what it was built to do: the writer is saturated. The consequence is a serialised
collector over Tor, where a single crawl-mode source with a 7 to 15 s crawl delay and 100 pages
takes half an hour on its own, and where the fetch failure rate in the 09-09 pass was **five
failed fetches per stored article**. Two mechanisms are stacked here, the write side and the
transport, and only the first is this report's subject; the second is visible in the tallies and
belongs to the collect-throughput track.

### 4.5 Memory

The RAM tier logic chooses the small tier on a 4 GB VM and declines the whole-corpus scans by
default; that half works. The other half, the process itself, still peaked at 4,158 MB with the
corpus this size, and the diagnostics bundle's largest member needs 3.4 GB. On this VM the app is
therefore intermittently swapping, and a swapping process makes every measurement above worse
than the mechanisms alone predict (F5 may be one symptom).

### 4.6 Corpus-sized work on hot paths at 11 M keywords

- `counter_envelope` [CODE-READ: `src/analytics/store.py:1934`] runs `min(last_reconciled_at)`
  over every keyword with mentions on the Insights top path; measured **17 s, three times**
  in the slow-query log. The scan is index-assisted on `mention_count` but reads 1.1 M rows for
  the timestamp.
- The super-group totals case measured **84 s** in the benchmark; the 11 M keywords include
  9.86 M orphans, so every member resolution and every count walks a table ten times its live
  size.
- Import post-stages (3.4) run per import and scale with the corpus; `reconcile_source_counters`
  inside the epoch bump is described in its own comment as "cheap; sources are few" and takes
  32 minutes at 86,470 sources.
- A read transaction on an API worker thread was **62,500 s** old at the pass-end checkpoint
  (`busy: 1`, `oldest_thread: AnyIO worker thread`), which prevents TRUNCATE checkpoints from
  completing and keeps the WAL at its high-water mark (F4).

---

## 5. Why the latest repo in a fresh VM changed nothing visible

September's changes on or near the ingest path, from `git log` on main:

| Commit | Date | What it changed | Side |
|---|---|---|---|
| `382d0f3` P1 + P2 | 09-10 | date extraction ~10×, keyword extraction ~2× per article | CPU |
| P4 + P6 | 09-10/11 | governor self-throttles removed, loop-lag back-off measured | control |
| `a4d2c48` A4 + A5 | 09-11 | client polls no longer stack; sorted COUNT | client, read |
| `7949dec` | 09-11 | bulk-write hole in the single-writer gate closed | correctness |
| `5bcc91f` | 09-17 | lemmatise at extraction; a per-mention language column | CPU up, row wider |
| `8771829` Q204/Q205 | 09-16 | import lifecycle page; the drain auto-resumes at boot | UX |

None of them reduces the number of pages an article write dirties, the width of the gate window,
the pool size on the small tier, or the corpus-sized stages. The 2026-09-10 audit's verdict,
*"the collector is CPU-bound, not download-bound"*, was measured on a plaintext store with a small
corpus and carries that caveat in its own text; on this instance the governor's verdict is
`writer-saturated` in 200 of 200 samples. A verdict measured in one regime does not transfer to
the other, and the fixes that follow from it do not either. The lemmatisation change adds CPU per
article and bytes per mention row, which is neutral to slightly negative in a write-bound regime;
its magnitude here is unmeasured.

A fresh VM removes stale state. It does not change the corpus-to-RAM ratio, the tier the app
picks at 4 GB, or the fact that the 1.28 M imported articles arrived without their derived rows
and must be written from scratch.

---

## 6. What transfers to the other instances

No bundle from another instance was available, so this section states mechanisms, not
measurements.

- **The corpus-to-RAM ratio is the variable.** An instance whose store fits in RAM will not show
  4.1 at this severity. The 48 K and 27 K-article instances named in the run list are ~1 GB
  stores and should not; if they are also "very slow", the cause is elsewhere and one bundle from
  the smallest slow instance would name it.
- **The small tier applies to every VM under 4 GB**, corpus size regardless: 8 connections, 8 MB
  cache, workers capped at 8, big scans declined. On such a VM the pool-versus-workers
  interaction (4.3) exists at any corpus size; it only becomes visible when the gate is slow.
- **The transport failures are per instance.** The 09-09 pass's 1,328 failed fetches, 925 errors
  and 326 unavailable robots files are Tor-side facts and would make any instance's passes long.
- **The import's fixed costs scale with the receiving corpus**, so a small instance importing a
  small backup pays little; this instance pays 2.4 h per import regardless of the import.

---

## 7. Findings not previously recorded

Each with its evidence and confidence. F-numbers are this report's.

**F1. On the small and medium tiers the connection pool is not larger than the collector, so a
slow gate starves the API.** [MEASURED 3.1, 3.2; CODE-READ `memory_budget.py`, `machine_floor.py`
`FLOOR_MAX_WORKERS = 8`]. Certain. The invariant that is missing: the collector may never hold
every connection; pool size must exceed the worker cap by a margin, or the worker cap must be
derived from the pool.

**F2. The FTS update trigger fires on every re-index pass, not once per article.** [CODE-READ
`src/database/fts.py:271`, trigger `AFTER UPDATE ON articles` without a column list;
`store.py` stamps `keyword_indexed_at` unconditionally since PRH-01, 2026-09-07]. The 2026-08-03
analysis measured this trigger at 3.3 to 4.6 ms per article in memory and recorded it as one-time.
It is now per pass, on a 1.34 M-document index whose row count cannot be counted within the
integrity deadline, and its cost here is unmeasured. Hypothesis for the drain's dominant apply
cost; settled by draining 500 articles with the trigger scoped to `title, content` versus not.

**F3. The backlog drain runs with commit-per-article and no instrumentation.** [CODE-READ
3.5]. Certain. The exclusive import path uses batch 200 and all cores for identical work.

**F4. A read transaction on an API worker thread was open for 17 hours.** [MEASURED
`recent_runs[0].hygiene.wal_checkpoint.readers`, `oldest_age_s: 62500`; the 200 collect_perf
samples show the oldest reader aging 1,220 to 1,520 s across five minutes]. A leaked session or a
streaming response holding one. It blocks TRUNCATE checkpoints (`busy: 1`) and pins the WAL.
Which handler is unknown; the pool listing names the thread class only.

**F5. Three SAVEPOINT statements were timed at 510, 660 and 664 s.** [MEASURED `slow-queries.json`;
the stall forensics attach `SAVEPOINT sa_savepoint_14` to the 30 s stalls]. A SAVEPOINT does no I/O.
Either the recorder attributes a neighbour's time to it, or the process was suspended (4.5). No
INSERT appears above the 500 ms threshold, so the collector's real per-article statement costs
are not in the log at all. Unexplained; worth a dedicated look because it sits exactly where the
per-article write cost should show.

**F6. The corpus-epoch bump costs 32 minutes per import** because it runs
`reconcile_source_counters` over all sources [MEASURED 3.4; CODE-READ `merge.py:5842-5860`].
Certain. The comment beside it says sources are few; there are 86,470.

**F7. The counter-freshness probe scans 1.1 M keyword rows on a hot path** [MEASURED 17 s × 3;
CODE-READ `store.py:1934`]. Certain. A maintained watermark row, or an index on
`(mention_count, last_reconciled_at)`, removes the scan.

**F8. 9.86 M of 11 M keywords are orphans** because the merge carries keyword rows without their
mentions under the 2026-07-29 option (a) ruling [MEASURED; CODE-READ merge steps]. Certain. Every
lookup, count and scan over `keywords` is ten times its live size until the drain reattaches them
or the prune removes them. The prune reclaims ~80,000 per 30 s budgeted pass.

**F9. The release-gate row C bundle cannot complete on this configuration**: three members died
on the pool timeout [MEASURED 3.7]. Certain. Row C's closing condition requires every member
non-zero.

**F10. The 2026-09-09 pass ran 5.9 hours against a 60-minute pass budget with no recycle
recorded** (`recycled: null`, where the two previous passes recorded `budget`) [MEASURED
`recent_runs`]. Unexplained; may be a crawl-mode source that cannot be interrupted mid-source.
To check, not asserted.

**F11. The drain's progress counter restarts at zero per run** [CODE-READ `_reindex_resume_worker`,
`ctx.set_progress(done=_base + done)` where the per-batch resume skips already-done ids before
counting]. Certain, cosmetic, and misleading: the task manager shows 3,190 of 1,282,083 whatever
earlier runs achieved.

**F12. The diagnostics bundle's keyword-log digest needs 3.4 GB of RSS** [MEASURED manifest
`rss_peak_rise_kb`]. On a 4 GB VM this member alone forces swapping. The S1.3 rule declines
whole-corpus scans below the floor; this member is not covered by it.

---

## 8. What the bundle could not tell, and how to get it

| Question | How to answer it | Cost |
|---|---|---|
| Where the drain's per-article time goes | pass a `stats` dict from the resume worker and publish the split in its status; run the drain with commit batch 200 so the split is populated | one small change |
| Whether the FTS trigger dominates | 500 articles each way, trigger scoped versus not, same batch | one A/B run |
| Bytes written per article | WAL growth divided by articles from the run-journal beats | already recorded for imports; the drain has no journal |
| Which handler holds the 17-hour reader | log the request path at checkout when a reader exceeds an age threshold | one probe |
| What the SAVEPOINT timings are | record statement timings with the gate acquisition excluded, or mark the gate wait separately | one probe |
| Whether the other instances share the cause | one all-diagnostics bundle from the smallest slow instance | operator |
| The exact drain rate | `GET /api/backup/reindex-backlog/resume/status` twice, an hour apart | operator |
| The big imports' stage timings | `data/run_logs/imp-20260903T095705Z-*.jsonl` and the 09-04 files | operator |

---

## 9. The plan, in order

### 9.1 Operator, on this instance, before any code changes

1. Give the VM at least 8 GB at boot so the app picks the large tier (64 MB cache, pool 8 + 64),
   and as much more as the host can spare: the OS page cache is what makes random writes on a
   27.7 GB store survivable.
2. Run the drain alone: collection off, the Insights tab closed (its auto top-up is a second
   serial drain), no diagnostics bundle (it claims the machine and stops the drain), no
   "Clean up keywords" (a third, whole-corpus drain).
3. Launch with `OO_REINDEX_COMMIT_BATCH=200` and, once the VM has 8 GB or more,
   `OO_SQLITE_CACHE_MB=64`. Leave the worker count alone. Shut down with the in-app button so the
   WAL is checkpointed rather than replayed at the next boot.
4. Read the resume status endpoint twice an hour apart and keep the readings.
5. Send one bundle from the smallest slow instance and the big-import journals.

### 9.2 Engineering, one PR each, measured on this instance before the next

1. **The drain runs like the import, and says what it spends.** Exclusive settings whenever the
   collector is idle; `stats` published in the job status; the epoch bumped once per run; the FTS
   update trigger scoped to `title, content` with a boot self-heal. Small; the A/B in section 8
   rides on it. (F2, F3)
2. **The pool can never be exhausted by the collector.** Pool size derived from the worker cap
   with a margin on every tier, or the worker cap derived from the pool; the diagnostics bundle
   uses its own connection budget; members over a RAM threshold decline on small machines. (F1, F9, F12)
3. **Corpus-sized work off the hot and per-import paths.** The counter watermark (F7); source
   counters scoped to touched sources (F6); the long-reader probe (F4); the SAVEPOINT attribution
   (F5); the cumulative drain counter (F11).
4. **The constant factors in apply.** Batched keyword lookups per article; counters as one
   statement or deferred during an exclusive drain with the estimated envelope; the article-row
   rewrite taken off the pass.
5. **The bulk-build mode.** Extract to sorted runs, resolve the dictionary once, drop the ten
   secondary mention indexes and the seven when/where/who indexes, load in key order, rebuild the
   indexes sequentially, counters by one GROUP BY, FTS untouched. Used by the drain and by full
   re-indexes when the machine is exclusive. This is the step that changes the order of magnitude
   on this class of machine.
6. **The import's fixed costs.** Snapshot once per run is already there; quick_check, the keyword
   reconcile and the event mirror scoped or deferred; the working copy kept. Attended.
7. **Design for 0.5.** The segmented derived index for the 1 TB target, and carrying mention rows
   from same-engine backups instead of re-extracting them. *(2026-09-24: the carry BUILT as `R24`;
   the index DESIGNED in `docs/design/SEGMENTED_DERIVED_INDEX_2026-09-24.md`, adoption `D47`.)*

### 9.3 Rulings — DECIDED 2026-09-22, every default accepted

The maintainer answered this section on 2026-09-22: "I agree with all your 7 rulings
defaults. Mark them as decided." Each is now recorded in
[`docs/ledger/RULINGS_INDEX.md`](../ledger/RULINGS_INDEX.md) under the id in the last
column, with the round's own entry in
[`docs/ledger/OPEN_QUEUE.md`](../ledger/OPEN_QUEUE.md). **Decided is not built:** the
`state` column says which of the §9.2 PRs carries each. **Swept 2026-09-24 (PR 7):** every ruling now has one, R3 only in part; `docs/ledger/RULINGS_INDEX.md` is the authoritative state, and this column had said "unbuilt" for six rulings already built.

| # | ruling, as decided at its default | index | state |
|---|---|---|---|
| R1 | the drain may use the exclusive settings whenever the collector is idle | R21 | **BUILT** — PR 1 (#1164) |
| R2 | counters deferred and reconciled at the end of an exclusive drain, disclosed as estimated meanwhile | R22 | **BUILT** — PR 4 (#1168) |
| R3 | bulk build on the live store, with surfaces disclosing "rebuilding, N of M" | R23 | **PARTLY BUILT** — PR 5 (#1169): the window, its boot heal and the disclosure; no caller yet (`D46`, which the segmented design dissolves — `D47`) |
| R4 | same-engine backups carry their mention rows in sorted bulk instead of re-extraction; revisits the 2026-07-29 option (a) | R24 | **BUILT** — PR 7 (#1171), per ARTICLE and per INPUTS rather than per backup (see `RULINGS_INDEX.md`) |
| R5 | all four import stages may be scoped to the batch: quick_check, keyword counter reconcile, event-mirror refresh, source counters | R25 | **BUILT** — PR 3 (#1167) + PR 6 (#1170); three of the four stages were already delivered, and a lone import's `quick_check` stays a data-safety question |
| R6 | raise the pool rather than lower the worker cap on the small and medium tiers (8 MB × 4 more connections is 32 MB) | R26 | **BUILT** — PR 2 (#1166) |
| R7 | diagnostics members that need more than half the machine's RAM decline below the floor, like the whole-corpus scans already do | R27 | **BUILT** — PR 2 (#1166) |

**What PR 1 changed, and what is still unmeasured.** It carries R21 plus the three items
of §9.2 item 1 that needed no ruling: the drain publishes the load/precompute/apply split
it had always computed and no caller asked for, the corpus epoch is bumped once per run
instead of once per batch, and the FTS update trigger is scoped to `title, content` with a
boot self-heal for stores that already carry the unscoped one. **No speed-up figure is
claimed for any of the four.** Each removes a cost that this report measured or read in
the code; what they are worth together on a 27.7 GB encrypted corpus is what §8's A/B
exists to find out, and that has to run on the operator's instance — a sandbox where the
collector is CPU-bound would produce a number that transfers to nothing. The worker count
is deliberately untouched (§9.1 step 3), so the A/B measures one change at a time.

---

## Appendix A. The 1 TB projection

At this corpus's density, 20.7 KB per article with 95 % of articles unindexed, 1 TB holds ~48 M
articles; fully indexed at 92 mentions per article the derived rows roughly double the density,
so 1 TB holds ~20 to 25 M fully indexed articles [ARITHMETIC]. At 870 articles per hour the drain
alone is 2.6 to 6 years, and the rate falls as the B-trees grow. Every corpus-sized stage in
section 3.4 also scales with it: two 1 TB copies per import, a quick_check over 1 TB, a per-source
count over every source. The per-article design cannot reach that scale; the bulk build in 9.2
step 5 and the import changes in step 6 are what can.

## Appendix B. Slow statements at 11 M keywords (top of `slow-queries.json`, total ms)

| Statement | Count | Total ms |
|---|---:|---:|
| `SAVEPOINT sa_savepoint_23` | 1 | 664,207 |
| `SAVEPOINT sa_savepoint_5` | 1 | 660,456 |
| `SAVEPOINT sa_savepoint_14` | 1 | 510,360 |
| `SELECT min(keywords.last_reconciled_at) ... WHERE mention_count > ?` | 3 | 50,781 |
| source-type article counts since a date (JOIN sources, articles) | 1 | 48,472 |
| keywords LEFT JOIN keyword_mentions GROUP BY keywords.id ORDER BY sum | 1 | 32,073 |
| dangling-mention count (NOT EXISTS keyword) | 1 | 29,395 |
| `count(keywords.id) WHERE article_count = ?` | 1 | 22,137 |
| entity keywords by article_count, paged | 1 | 20,689 |
| `count(*) FROM keywords` | 3 | 13,100 |
| `count(*) FROM article_links` | 4 | 12,852 |
| dangling-mention count (NOT EXISTS article) | 1 | 11,589 |
| orphan keyword count | 1 | 8,606 |
