# Field diagnostics, first batch: six machines, analysis and plan

**Status: analysis; the fixes it plans are in two PRs opened with it.** Written 2026-09-24 from
the six all-diagnostics bundles, three release-run reports and three forensics notes the
maintainer uploaded, read against `main` at `c8445c62` (PR #1170). The raw bundles are not
committed: they carry local paths and machine details, and every figure used is quoted here with
the member it came from. The maintainer's answers to §6 are recorded under each question.

Provenance tags follow `docs/audit/15`: **[MEASURED]** is read from a named file,
**[ARITHMETIC]** is a shown calculation on measured inputs, **[CODE-READ]** is verified in code
(with the commit), **[HYPOTHESIS]** is plausible but unproven, with what would settle it.

## 0. The answer in one page

**None of the six machines ran the indexing fixes.** All six ran commit `68b295b` (main just
after PR #1162), so none of PRs #1164–#1170 were on them. Updating them is the first step, and
most of the pool timeouts below should stop with it.

**The slowness mechanism audit 15 found on the 1.3 M-article instance is the normal state of a
4 GB machine at 140k to 290k articles.** The single write gate was busy 93 to 99 % of the time
on every machine that was collecting. Individual INSERTs ran up to 295 seconds, and that is
execution time, not lock waiting. On every machine a pooled connection taken at the UNLOCK is
never returned, which pins the WAL; Lenn's WAL reached 8.1 GB, larger than its database.

**The 0.4 release runs produced two good 72-hour soaks, and reports that cannot close a row.**
Asus and the NUC soaked for 72 hours with flat memory, which is the substance of row B, and
measured rows I, J and K. But my release-run code misreads row C, lost the NUC's row B, D and E
evidence to one pool timeout, and labels rows "measured" or "skipped" when their evidence
errored. My chronology mis-measures when the clock jumps (the NUC's was 12 hours fast), counts
app uptime rather than collection, and cannot see the crash just before it. Row 5 is a
multi-day whole-corpus re-index placed before the soak. It held all three Qubes VMs for 50 to 61
hours, so their soaks never started, and two of them then ran out of memory. Lenn's collector was
stranded for five days by a scheduler defect after a cancelled backup.

**Several surfaces report something untrue, outside the write path:**

- **Source qualification.** It never runs below the memory floor, which is all six machines, yet
  the job reports "done".
- **Fixity audit.** It flags 22 to 29 % of the sample as corrupted when none of it is.
- **Integrity sweep.** It reports "no drift" after checking nothing.
- **Custody log.** Entries are skipped silently whenever the pool times out.
- **Weekly bulletin.** Its cards section came back empty on all six.
- **Home cards.** Some open onto an empty search.

**Memory is at the edge.** Four of the six machines ended a session uncleanly in the last week,
and on three of them (Asus and two Qubes VMs) swap was completely full at the end.

**What to do** (§5):

- **You, now.** Update all six machines, restart Lenn's collection, cancel the Qubes row-5 runs,
  fix the NUC's clock, and measure Asus's drain. Swap stays at its 1 GB default (FD02, answered),
  so the fixes have to hold on 4 GB of RAM with 1 GB of swap.
- **Me.** Two fix PRs: the release run and chronology, and the non-write-path defects.
- **The indexing session.** A hand-off note with ten measured inputs.
- **Your answers.** Four questions (§6).

**How this was produced.** Six Sonnet analysts each read one dimension across all six bundles,
and six Sonnet verifiers then re-checked every medium-or-higher finding against the raw files
and current `main`: 12 agents, no errors, about 75 minutes. No finding was refuted; the
corrections are applied below. Every load-bearing claim was then checked by hand, which
corrected three agent claims: Asus's backlog comes from the 2026-09-03 imports, not the release
run; row 5 was slow, not hung; and the holiday feeds now return HTTP 404. Figures are tagged
as in audit 15.

## 1. The machines, and what code they ran

| Machine | CPU | Threads | RAM (GiB) | Swap (GiB) | Articles | Keywords | Mentions | Store (GiB) | Bundle started (local) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| Asus | Pentium Silver N5030 | 4 | 3.65 | 8.0 | 289,027 | 1.50 M | 8.46 M | 6.77 | 2026-09-24 13:42 |
| Lenn | AMD 3020e | 2 | 3.22 | 7.1 | 192,710 | 2.34 M | 15.19 M | 7.36 | 2026-09-24 14:07 |
| NUC | Core i3-5010U | 4 | 3.71 | 8.2 | 149,334 | 2.49 M | 11.54 M | 5.88 | 2026-09-21 19:25 |
| Qubes-A | i7-13620H host, VM | 2 | 3.83 | 1.0 | 147,985 | 2.33 M | 11.56 M | 6.04 | 2026-09-21 19:24 |
| Qubes-B | same host, VM | 2 | 3.83 | 1.0 | 141,282 | 2.18 M | 11.09 M | 5.74 | 2026-09-21 19:24 |
| Qubes-C | same host, VM | 2 | 3.83 | 1.0 | 149,489 | 2.34 M | 11.68 M | 6.05 | 2026-09-21 19:24 |

**All six ran commit `68b295b`, main right after PR #1162, and none of PRs #1164–#1170.**
[MEASURED + CODE-READ] Every bundle carries `chronology.json`, which PR #1162 added. No manifest
carries the `profile` block PR #1165 added. Asus and Lenn have run one process since 2026-09-19
04:36Z and 04:18Z, and the Qubes and NUC bundles predate PR #1164's merge. No bundle records the
commit it ran, which is why this had to be inferred (see §4).

**All six are on the SMALL memory tier and below the 4 GiB machine floor, on `main` too.**
[CODE-READ `src/config/memory_budget.py`] The floor compares a nominal size with a 3 % tolerance;
3.83 GiB is 4.2 % short of 4 GiB, so even the Qubes VMs provisioned as "4 GB" count as below it.

**The store is 1.5 to 2.3 times the RAM** [ARITHMETIC]: Asus 1.85, Lenn 2.29, NUC 1.59, Qubes
1.50–1.58. The audited 1.3 M-article instance was 7 times. So these machines sit in a milder
version of the same regime, and §3.2 shows that the mechanism is already fully present.

## 2. The release runs (all "release-scale", started 2026-09-19 early morning)

| Machine | Row 5 ticked | Outcome | Row 5 | P0 trio | Fresh restore | Soak | Collect | Bundle |
|---|---|---|---|---|---|---|---|---|
| Asus | yes | **done** | error after 7 h 07 min (pool timeout) | measured: backup, verify, restore pass; **unlock fail** 5,356 ms | measured, 40 min | **72.0 h**, 73 heartbeats, none dropped | measured | measured, 37 min |
| Lenn | yes | **cancelled** at 21 min | error after 2.5 min (pool timeout) | cancelled after 18 min | not run | skipped | cancelled | cancelled |
| NUC | no | **done** | skipped | measured: all five pass (unlock 1,763 ms) | measured, 32 min | **72.0 h**, 73 heartbeats, none dropped | **error** (pool timeout) | measured, 41 min |
| Qubes-A | yes | in flight | **still in row 5 after 61 h** at bundle time | not reached | not reached | not reached | | |
| Qubes-B | yes | interrupted | 50 h in row 5, then an unclean end (09-21 07:00Z) | not reached | | | | |
| Qubes-C | yes | interrupted | 58 h in row 5, then an unclean end (09-21 15:17Z) | not reached | | | | |

[MEASURED: the three release-run finals; for the Qubes, `chronology.json` `release_run` + `sessions`.]

**What the board got.** Two 72-hour soaks completed, and on both the substance of row B holds.
RSS stayed flat [MEASURED heartbeats]: Asus daily medians 1,349 / 1,307 / 1,323 MB (max 1,623);
NUC 1,540 / 1,474 / 1,553 MB (max 2,141); the memory guard never engaged. Rows I, J and K are
measured on both: a committed restore at corpus scale (Asus 2,436 s, NUC 1,922 s), a verified
dated backup, and a zero-duplicate scan on the restored corpus.

**What the board did not get, and why:**

- **Row C cannot close from these reports.** `coverage_complete` is null on both, so
  `bar_satisfied_by_this_bundle` is false even though both bundles' manifests read
  `complete: true`. The release run reads the coverage block from the wrong member (RR-1, §3.3).
- **The NUC lost its row B, D and E readings after a full 72-hour soak.** The collect phase
  died on one 30-second pool timeout and took every block with it (RR-2). The report still
  labels row B "measured", with `reaches_bar: null`, and calls row D "skipped" (RR-3).
- **Rows A and E cannot test their clause on this fleet.** "A previously-disqualified source is
  still disqualified afterwards" needs judged sources. The NUC has judged none of its 55,377
  (`with_judging_attempt: 0`), and Asus 657 of 86,411, because source qualification never runs
  below the memory floor (QUAL-1, §3.4).
- **Row G (row 5) failed wherever it was ticked.** It is a quarantine pass followed by a
  whole-corpus keyword re-index, placed before the soak (RR-6). On the three Qubes VMs it ran
  50 to 61 hours without finishing, so their soaks never started; two of the three VMs then
  ended uncleanly with their 1 GB swap exhausted.
- **Row P** is not measurable (the Wikipedia lane had no rows), **row T** has the Hugging Face
  sha but no Ollama digest (Ollama was not running), and **row Q** reached
  gesetze-im-internet.de and legislation.gov.uk but never eur-lex, whose robots.txt answer is
  treated as unavailable and fail-closed on both machines.
- **P0.4 unlock fails on Asus (5,356 ms) and Lenn (6,581 ms)**, both after an unclean previous
  session, with `init_db` alone at 4.2 and 4.1 s. The NUC passes at 1,763 ms after a clean
  restart, with only 713 ms in `init_db`. WAL replay does not explain the gap: the NUC opened
  with the largest WAL of the three (66 MB, against 42.5 and 23.2 MB). A cold page cache after a
  reboot is the likelier difference [HYPOTHESIS], and the kit does not record whether the machine
  had just booted, so the "cold boot" its bar names is assumed rather than known (§4).

## 3. Findings, by who owns them

### 3.1 Already fixed on `main`: updating the machines is the first step

- **The 30-second pool timeouts (audit F1).** `QueuePool limit of size 6 overflow 2 reached`
  appears on all six machines (on the NUC, in its release-run report). It broke release-run phases on all three Parrot machines,
  killed the Asus drain, stopped Lenn's Wikipedia lane and skipped custody entries (§3.4). The
  task manager's poll also failed: Asus 3,269 of 87,727 calls to `GET /api/scheduler/activity`
  (3.7 %), NUC 1,022 of 24,155 (4.2 %). [Inference] Here the bundle keeps only the frontend's
  bare 500s, so this cause is taken from the audited instance, where the same route failed with
  this exact error. The more-polled `GET /api/scheduler/status` had no failures at all. PR #1166
  raised the small-tier pool from 6+2 to 6+6. All six machines are small-tier, so the fix
  applies to all of them, with the open question in §3.2 item 5.
- **The drain's configuration (F2, F3)** and **one query per article's vocabulary** (PRs #1164
  and #1168) matter directly to Asus, whose 195,081-article backlog resumes automatically at the
  next boot on `main` (`src/api/main.py:105-192`).
- **The counter-freshness probe (F7, PR #1167)** and the scoped source-counter reconcile (F6,
  PRs #1167 and #1170).
- **The keyword-log digest's RAM decline (F12, PR #1166)**, which is fixed but miscalibrated for
  these machines: §3.2 item 4.

### 3.2 New evidence for the indexing-performance session

1. **The write-bound regime is fleet-wide at 140k to 290k articles, not only at 1.3 M.**
   [MEASURED `soak-window.json`] The write gate was busy 94 % of Asus's 127 h process window,
   93 % of the NUC's 61 h and 98.6 % of Qubes-A's 62 h, against 79 % on the audited instance.
   Their stores are only 1.5 to 1.9 times their RAM. So the bulk build (`R23`, `D46`) and the
   write-path work are the machine class's problem, not one instance's. Lenn is the control:
   collection stopped (SCHED-1), and its gate was 0.9 % busy.
2. **The slow INSERTs are execution time, not lock waits.** [MEASURED + CODE-READ] Asus's slow
   log has 2,076 `INSERT INTO keywords` (average 56.2 s, max 272 s) and 2,007
   `INSERT INTO articles` (average 56.2 s, max 295 s), about 229,000 s in all. The write gate is
   taken in `before_flush` (`src/database/writer.py:554-573`), outside the cursor-level timer
   (`src/monitoring/slowquery.py:93-102`), and `busy_timeout` is 30 s
   (`src/database/session.py:136`), so a 295-second statement cannot be a SQLite lock wait. What
   remains is execution: page I/O and decryption through an 8 MB cache, the FTS insert trigger and
   swap pressure, in proportions these files cannot split [HYPOTHESIS]. That answers half of F5's
   attribution question for the INSERT shapes. The count is
   statements, not rows, so rows per statement is still unknown.
3. **F4 is on every machine, and it starts at the unlock.** [MEASURED `recent_runs[].hygiene`]
   The oldest pooled checkout is as old as the session on all six: Asus 126 h, NUC 60 h, Qubes
   51 to 61 h, always from an "AnyIO worker thread". Computing its start time places it within a
   minute of each machine's UNLOCK. The NUC is the one that separates the unlock from the boot:
   it was unlocked 25 minutes after its process started, and its checkout dates from the unlock.
   The unlock endpoint is synchronous and runs `init_db` on its request thread, while the upkeep
   runs on its own named thread. So either the unlock request path leaks a checkout, or the pool
   watcher misses a check-in around `dispose_engine`/`init_db` and reports a phantom
   [HYPOTHESIS]. Checkpoints report the WAL pinned on 12 of 30 passes on Asus and 0 of 30 on the
   NUC, so the checkout does not always hold a snapshot. This is where the unbuilt long-reader
   probe should look first.
4. **`R27`'s one constant over-declines on small machines.** [MEASURED + ARITHMETIC] `main`
   declines `keyword-log-digest.json` when its need of 3,322.8 MiB exceeds half the RAM, so it
   now declines on every machine under about 6.6 GB, all six included. Measured here, that member
   cost 434 to 874 MiB. The need scales with the keyword count: 3,322.8 MiB over 11.0 M keywords
   is about 317 bytes per keyword, which predicts the six machines' measured 434–874 MiB within
   about 25 %. A per-keyword need would run the member on these machines and still decline it at
   11 M keywords on 4 GB. As built, it makes row C's "every member" unreachable on the whole
   small-machine fleet.
5. **The small-tier margin counts only the collector.** [CODE-READ `api_headroom_for`,
   `src/config/memory_budget.py`] The margin is pool size minus collector workers, and the four
   connections left are shared by every API call and every background job: the drain and its
   workers, the bulk qualification job, row 5's re-index, the bundle, the release run and the
   scheduler thread. On Asus the drain itself died of the timeout while those jobs ran.
   [HYPOTHESIS] `main`'s 12 connections can still run out when a drain runs beside the collector.
   The pass summary's `api_headroom` would not show it, since it only counts collector workers.
   Settle it with the pool listing at the moment of a timeout.
6. **Asus is a second, smaller drain machine, and 63 % of its corpus has no keywords.**
   [MEASURED `bulletin-weekly.json` `reindex_backlog`, `keyword-growth.json`] Two import batches
   from 2026-09-03 (110,833 and 84,248 articles) have waited three weeks. Only 106,578 of its
   289,027 articles carry any keyword, so Insights, the briefing and search facets on Asus see a
   third of its corpus. Its drain died on the pool timeout at 730 of 195,081 and made no progress
   in the 47 hours between two readings. On `main` an errored drain still stays errored until the
   next boot or a manual resume: PR #1164 added live metrics to background jobs, not a retry.
   Asus is the "backlog fraction" `D46`(a) needs a number for, and a place to run `D43`'s A/B on
   a 4 GB machine. (The release run's own restore went into a throwaway install and did not add
   to this backlog.)
7. **Two unclean ends on the Qubes VMs look like out-of-memory kills.** [MEASURED
   `session-forensics.json`, the cause is an inference] Qubes-B peaked at 2,945 MB RSS with
   278 MB available and its 1 GB swap full; Qubes-C at 3,057 MB, 174 MB and swap full. Both were
   running row 5's whole-corpus re-index beside collection.
8. **`D45`'s row-size query is not in any bundle member on `main`.** Add it, and the next bundle
   from these six answers `D45` at the scale where the decision is made.
9. **P0.4 unlock is failing on two machines, and `main` adds work to that path.** Asus and Lenn
   spent 4.2 and 4.1 s in `init_db` alone, the NUC 0.7 s with a larger WAL, so the cost is the
   ~30 schema self-heal probes on a cold cache rather than WAL replay [HYPOTHESIS]. PRs #1164 and
   #1169 add boot heals inside `init_db`. The next unlock reading on `main` will show what they
   cost, and recording the machine's boot time beside it will say whether it was cold.


### 3.3 The release run and the chronology: eleven defects, all verified

Ten are in my PR #1162 code; RR-9 is in the fetch path and surfaced through the release run.

Every line reference is to `68b295b`, which is what the machines ran. `main` changed only the
bundle-profile read beside RR-1 (PR #1165); every defect below is still present on `main`.

1. **RR-1 · Row C reads the coverage block from the wrong member.** `_bundle` looks for
   `runtime_coverage` in `debug-bundle.json` (`src/monitoring/release_run.py:962`); the bundle
   writes it at `manifest.json` → `run.runtime_coverage`. It is therefore always null, and row C
   can never read satisfied. **RR-1b:** the "every member non-zero" half is also blind to a
   member skipped by the 300 s deadline, because the bundle writes a 52-byte
   `.skipped-deadline.txt` in its place. `source-audit.json` was skipped that way on four of six
   machines, and `zero_byte_members` stayed empty. *Fix:* read coverage and the per-member
   `outcome` from the manifest; test against an archive built by the real bundle writer, not a
   hand-made zip.
2. **RR-2 · The collect phase is all-or-nothing.** `_collect` (`:892`) reads the soak window and
   the qualification integrity inside one session, so one pool timeout discards every block, and
   `_run_phase` (`:1286`) keeps no partial result on error. The NUC lost rows B, D and E after 72
   hours; Asus lost row 5's quarantine tally after seven hours. *Fix:* collect each block
   separately, retry a pool timeout with backoff, and keep partial results on error.
3. **RR-3 · Row labels overstate.** Row B takes the soak phase's status (`:1037`), so it reads
   "measured" with `reaches_bar: null`; row D reads "skipped" whenever the soak-window block is
   missing (`:1072`), including when the collect phase errored.
   *Fix:* derive each row's status from the evidence it actually holds, and name an error as one.
4. **RR-4 · The soak runs on the wall clock.** Elapsed time, the deadline and the heartbeat
   cadence use `time.time()` (`:1414-1446`), and phases carry wall stamps with no monotonic
   duration. On the NUC, `p0_validation` "ended" at 08:02:55 before it "started" at 19:29:21.
   A forward jump would end a soak early and still claim 72 h; a suspend would count as uptime,
   against the continuous bar ruled in `R20`. *Fix:* monotonic time for every duration and
   deadline, a per-phase `wall_s`, and a `clock_adjustments` list when the two clocks disagree.
5. **RR-5 · The chronology under-reported the NUC's uptime by exactly its clock error.** The
   NUC's clock was **12 h 0 min 3 s fast** at boot: the boot record says 17:03:46Z, while the
   liveness file's monotonic uptime puts the real start at 05:03:43Z [ARITHMETIC]. The summary
   works in wall-clock differences (`src/monitoring/chronology.py:126, 257, 268`). It showed
   175,113 s since the last restart against a real 218,290 s, and **23.8 h remaining to the
   72 h bar when about 11.8 h remained.** Meanwhile the System-tab line, which uses monotonic
   uptime, was right, so two surfaces disagreed. The liveness tick records only a forward gap as
   a "suspend" (`src/monitoring/session_history.py:316-331`). A backward jump is invisible, and a
   forward jump is indistinguishable from a sleep. *Fix:* monotonic uptime as the authority,
   re-base a session's start when the boot stamp disagrees with it, record a `clock-jump` event,
   and on Linux compare `CLOCK_BOOTTIME` with `CLOCK_MONOTONIC` to tell a suspend from a clock
   change.
6. **RR-6 · Row 5 is a multi-day whole-corpus re-index, placed before the soak, and nothing says
   so.** `_row5_quarantine` (`:561`) runs the quarantine pass, then
   `reindex.start(scope="keywords", prune_after=True)` over the whole corpus. PF01 and the
   checkbox label describe it as "the Tier-A quarantine pass" and never state that cost. Ticked
   on five machines, it cost Asus seven hours, and held all three Qubes VMs for 50 to 61 hours
   with no soak started. It was slow, not hung: Qubes-A's log shows "write gate held 60–75 s by
   'reindex-job'" every few minutes throughout 09-21, and the memory guard paused collection four
   times with 182 to 255 MB available. But `_wait_manager` (`:545`) waits with no deadline and
   publishes no progress, so from the outside it is indistinguishable from a hang. *Fix:*
   disclose the cost in the label, bound the wait and publish the job's progress, and move row 5
   after the soak or out of the run (question FD01).
7. **RR-7 · One transient pool timeout ends a long phase.** Asus's row 5 died on a single
   30-second timeout after seven hours of work. *Fix:* retry pool timeouts inside phases and
   waits, with the same backoff as RR-2.
8. **RR-8 · The bundle's release-run member says no run exists while one is 61 hours in.**
   `release-run.json` is `last_release_run_report()` (`src/api/diagnostics/bundle.py:1253`), the
   last SAVED report, and interim reports are written only inside the soak loop. On the three
   Qubes bundles it reads "no 0.4 release run has been made yet", beside a `chronology.json`
   showing the run in `row5_quarantine`. *Fix:* include the live run state in the member, and
   write interim reports from every long phase, not only the soak.
9. **RR-9 · Stale politeness stamps after a clock correction.** The NUC's online probe to
   legislation.gov.uk was refused as `CrawlDelayDeferred ... not before 13:49:23Z` at 06:35Z,
   seven hours ahead, because the host's persisted stamp came from the fast clock. It cost row Q
   one of its three hosts. The sidecar stamp is wall-clock and unclamped
   (`src/ingest/__init__.py:1734-1741`, unchanged on `main`). A legitimate stamp can never lie
   more than its own delay ahead of now, so *fix:* clamp the persisted wait to the persisted
   delay. (The fetch
   path is not my code; it is listed here because it surfaced through the release run.)
10. **RR-10 · The chronology's 72-hour bar counts app uptime, not collection.** On Lenn it reads
   `bar_reached: true`, because the process ran five days after its cancelled run, while the
   collector was stopped for all five (SCHED-1) and the run's own row B says the bar was not
   reached. `R20` kept the bar continuous, and row B's clause is continuous COLLECTION. *Fix:*
   mark the stretches during which collection was actually running (the scheduler's own start
   and stop, recorded as ledger events) and measure the bar on those; when the run was cancelled
   or never armed its soak, say so beside the bar.
11. **RR-11 · The chronology cannot see the crash just before it.** The ledger began with the
   PR #1162 build's first boot, so it reads "0 unclean ends" on Asus, Lenn, Qubes-B and Qubes-C.
   The older forensics sentinel on the same machines recorded that the session before it died
   uncleanly with memory exhausted. *Fix:* when the ledger starts empty, seed it from the
   sentinel's previous-session verdict, labelled as coming from that source.

### 3.4 Collection, the scheduler and source qualification

1. **SCHED-1 · A cancelled exclusive operation stranded Lenn's collector for five days.**
   [MEASURED + CODE-READ] The release run's P0 phase was cancelled at 04:44:16Z on 09-19.
   Leaving its exclusive window calls `resume_after_exclusive_operation`, which retries
   `start()` 19 times at 30-second intervals, about 9.5 minutes in all
   (`src/scheduler/runner.py:2489`). Lenn's in-flight pass took 39 minutes to wind down (it ended
   at 05:23:26Z, recycled "stopping", 3,837 s). The log carries the warning at 04:54:30Z: *"could
   not resume background collection after an exclusive operation"*. Nothing retries after that,
   and autostart is off, so `scheduler.status.running` was still `false` on 09-24.
   The docstring sized the budget against a 438-second worst case for one blocked write, but on a
   write-bound machine a pass's wind-down is the unit, and Lenn's gate held writes for up to
   570 s at a time. Unchanged on `main`. *Fix:* keep the resume pending until the old pass thread
   actually exits (join it or poll `is_running()`), and surface a stranded state in the task
   manager instead of a log line.
2. **QUAL-1 · Source qualification never runs on any of these machines, and the bulk job reports
   "done".** [MEASURED + CODE-READ] Asus reads `Qualifying candidate sources (bulk): done
   [0/79977] starting…` and the NUC `done [0/48977] starting…`. Every machine here is below the
   4 GiB floor. Below it, `run_qualification_pass` declines its whole-corpus scan and returns
   `evaluated: 0` with a reason (`src/catalog/qualification.py:1087-1099`, the S1.3 floor ruling).
   `run_bulk_qualification` reads `evaluated == 0` as "the backlog is empty", marks itself
   `complete: True`, and breaks before updating its progress, so the reason is dropped and
   "starting…" stays on screen (`src/catalog/qualify_job.py:142, 189-191`). The steady per-pass
   ride-along declines the same way: Asus's qualified count moved by 0 over 93 hourly samples,
   with 82,805 candidates waiting. The release run's own arm step had just judged the job safe
   (1,257 MB needed, 1,621 MB available): two estimators, opposite answers. Consequences beyond
   the Sources tab: rows A and E cannot test their clause (§2). Unchanged on `main`. *Fix:* carry
   the decline into the job's result and the task manager as a named refusal with the override,
   never "complete"; make the arm step ask the same floor. Whether small machines should qualify
   at all is question FD03.

3. **CUST-1 · Custody entries are silently skipped whenever the pool times out.** [MEASURED +
   CODE-READ] "custody logging on ingest failed" with the pool-timeout traceback appears 8 times
   on Lenn, 13 on Qubes-A, 19 on Qubes-B and 9 on Qubes-C, inside error logs that cover only 16
   to 48 hours. `_maybe_record_custody` is fail-open by design and logs a warning
   (`src/ingest/pipeline.py:368-401`), and nothing re-records the entry later. So the
   chain-of-custody log, which operators turned on, has gaps no surface reports. PR #1166
   makes the timeout rarer; it does not close the design gap. *Fix:* a reconcile that finds
   stored articles with no INGEST entry and records them marked late, plus a count on the custody
   surface.
4. **The Wikipedia lane stops itself after three failed drains.** [MEASURED] Lenn's log: "the
   wiki lane stopped after 3 consecutive failed drains: TimeoutError: QueuePool limit…". It stays
   stopped until someone restarts it, so the lane that row P measures can be off without anyone
   having turned it off.
5. **The public-holiday calendar lane is dead upstream.** [MEASURED `network.json`,
   `calendar_imports`] All 239 per-country `worldpublicholiday.com` feeds carry zero events on
   Asus and Lenn. The feed URL read "not iCal" in July and August and has answered **HTTP 404**
   since mid-September (checked 09-13 and 09-16). The endpoint is gone, which matters to the
   religious-dates work (`RC13`, Prompt 17b): no public-holiday source currently feeds the Agenda
   on these machines.
6. **Collection rates, for scale.** [MEASURED `recent_runs`, 30 passes each] Stored per hour:
   Asus 240, Lenn 296 (before it stopped), NUC 543, Qubes-A 612, Qubes-B 939, Qubes-C 788, against
   about 45 on the audited 1.3 M-article instance. Passes run 65 to 77 minutes and recycle on
   budget. All six fetch over clearnet. The NUC's governor names a second bottleneck beside the
   writer: its pass summary says "memory-bound", with 345 MB minimum available.
7. **One repeating error floods the error log.** [MEASURED] The frontend's 500 on the task
   manager's poll fills 300 of 300 entries on Asus and 299 of 300 on the NUC, so any other
   warning in that window is invisible in the bundle.

### 3.5 Read paths and product surfaces

1. **Insights' heavy read queries take tens of seconds on every machine, with collection
   paused.** [MEASURED `benchmark.json`, which runs under the bundle's exclusive hold] Median
   super-group totals: Asus 29.9 s, NUC 35.1 s, Qubes-C 15.0 s. Trending: NUC 47.6 s, Qubes-C
   22.8 s. Trending windows: Qubes-C 50.2 s, Qubes-B 85.9 s. Source-country counts: Qubes-C
   28.6 s. The map, who and where aggregates were never measured on any machine, because the
   benchmark shares one 300-second deadline and the slow cases spend it first. Audit 15 §4.6
   names the super-group cost (84 s at 11 M keywords), but none of PRs #1164–#1170 targets it.
   The verifier adds that `trending()` tries the rollup fast path first but then always runs a
   per-candidate Python loop over `session.get(Keyword, …)`, and that the super-group medians
   match on Qubes-A (98.6 % gate busy) and Qubes-C (45 %), so the cost is CPU and query shape,
   not waiting on writers.
2. **The weekly bulletin's cards section came back empty, and the card audit misreports.**
   [MEASURED + CODE-READ] In the bundle's run of the weekly bulletin, the "cards" section ran 0 of
   37 producers on all six machines (`truncated: true`), and the member hit its deadline at 300
   to 305 s. Whether the Bulletins tab's own build hits the same budget is not tested here. A
   SQLite statement deadline, once tripped, interrupts every later statement on that connection. The bulletin's
   section loop and the card audit's producer loop catch each failure and carry on, so one slow
   early section spends the budget and every later one is reported as an independent "error" (15
   of 37 card producers on Asus). The guard that stops this exists already: `run_all_bounded`
   breaks on `deadline_expired(session)` (`src/briefing/registry.py`). *Fix:* port it to both
   loops and report the rest as "skipped: budget spent".
3. **Some Home cards cannot be opened.** [MEASURED `home-cards.json` + CODE-READ] Cards about
   things that are not article sets (a law revision, a count of source candidates, an
   IP-litigation pulse) fall back to a text search on a synthetic key such as
   `law:10:10743308446b`, which matches nothing. The bundle's own card check flags them
   "SEARCH-FALLBACK MISMATCH": all four law-change cards on Lenn, and a source-candidates card on
   the NUC and the Qubes VMs. That breaks the click-through promise of UI invariant #6. *Fix:*
   give those producers their own destination (the law tracker, the Sources tab).
4. **Ten of the 37 card producers never fired on any machine.** Possibly healthy (their triggers
   were never met); the card audit that would tell "no signal" from "error" is itself compromised
   by item 2, so fix that first and re-read.
5. **No local AI runs anywhere in this batch.** Ollama is not installed on any of the six, and
   each machine is below the 6 GB / 4-core bar the app sets for local models, so every
   model-facing diagnostic is empty by design. The next batch needs one machine with a working
   Ollama to exercise those paths at all.
6. **The temp directory was full during the bundle on Asus and the NUC.** [MEASURED] The AI
   self-test failed with "[Errno 28] No space left on device" writing a 2 MB fixture to the
   default temp directory, on exactly the two machines whose release runs completed the backup
   and the fresh-install restore. [HYPOTHESIS] The backup merge switches its own connection to
   file-backed temp storage (`src/backup/merge.py:1571`), and a RAM-backed `/tmp` filled by
   those merges would also press on memory. *Settle it:* `df -h /tmp` on both machines.
7. **Date extraction covers 41 % to 64 % of articles**, with Qubes-B (41 %) well below its two
   same-host siblings (58 %, 59 %); probably sampling variance in the language mix, unconfirmed.

### 3.6 Data safety, and two verification surfaces that report the wrong thing

1. **FIX-1 · The fixity audit reports corruption that is not there.** [MEASURED + CODE-READ,
   unchanged on `main`] It flags 110 of 500 articles on Asus (22 %) and 144 of 500 on Lenn
   (29 %) as "mismatched". Every one is a hazard or law article: 102 and 136 `hazard://usgs`
   rows, plus eight law pages on each. The audit re-hashes whitespace-normalised text
   (`generate_content_hash`, `src/utils/url_utils.py:213`). The hazard ingest stores
   `sha256(url + "\n" + body)` (`src/hazards/ingest.py:168`); law, Wikipedia and statistics
   store an un-normalised hash (`src/law/corpus.py:106`, `src/wiki/corpus.py:311`,
   `src/stats/series_corpus.py:287`). So those rows can never match. The NUC and Qubes read 0 of
   500 only because the audit samples the first 500 ids and their first 500 are scraped
   articles. *Fix:* have the audit re-hash each row with the algorithm that wrote it (a hash
   kind per source type), not change the ingest hashes, which the dedup keys depend on.
2. **INT-1 · The integrity sweep says "no drift" after checking nothing.** [MEASURED +
   CODE-READ, unchanged on `main`] On Asus, `corpus-integrity.json` reads `drift: false` and
   `timed_out: false` while the orphan and dangling counts are all null and the counter-drift
   check reads "interrupted". `_scalar` turns every exception, the deadline included, into
   `None` (`src/monitoring/integrity.py:33-38`). The counter-drift check was interrupted on all
   six machines. *Fix:* a verdict only from completed checks, and `timed_out` or a partial flag
   whenever a check did not finish.
3. **The WAL grew to the size of the database.** [MEASURED `storage-composition.json`
   `wal_history`] Lenn's WAL peaked at 8.1 GB on 2026-09-04, against a 7.4 GB store, and Asus's
   at 1.94 GB on 2026-09-24. At the bundle, Qubes-A's was 803 MB, and its last TRUNCATE
   checkpoint reported busy while the WAL grew from 297.7 to 302.9 MB. A WAL that size slows
   every read and doubles the disk the store needs. This is F4's consequence (§3.2 item 3).
4. **A clean shutdown leaves the WAL behind.** [MEASURED + CODE-READ] The NUC's previous session
   ended cleanly ("lifespan shutdown"), and the next boot still found a 66 MB WAL.
   `dispose_engine()` is a bare `engine.dispose()` with no checkpoint
   (`src/database/session.py:628-630`), while P0.4's own method text says a clean shutdown
   removes the WAL. [HYPOTHESIS] `dispose()` does not close a connection that is still checked
   out, so the F4 checkout that dates from the unlock would also stop the last close from
   happening. That would feed the WAL replay into every next unlock, which is P0.4's bar.
5. **Unclean ends under memory pressure.** [MEASURED forensics + manifest] Asus's previous
   session (09-16 to 09-18) ended uncleanly with its swap completely full (8,225 MB used of an
   8,225 MiB swap) and 76 MB available; Lenn's with 3,631 MB of swap in use. With the two Qubes
   VMs (§3.2 item 7), four of six machines ended a session uncleanly in the last week, three of
   them with swap completely full.
6. **Orphan keywords accumulate on the Qubes VMs.** [MEASURED] 5,835, 372 and 8,330, with the
   30-second-budget prune reporting `complete: false`, while Asus, Lenn and the NUC read
   `complete: true`. Small next to the audited instance's 9.86 M, and here it comes from the
   prune's budget, not from a merge. The three VMs share one host and ran their bundles at the
   same minute, so host contention may explain the difference as well as VM size [HYPOTHESIS].
7. **Known limits, still true:** `dbstat` is missing from the bundled SQLCipher build on all six
   (no per-table sizes), and data-folder persistence reads "unknown" on all six, because the check
   can confirm the volatile case but never the safe one.


## 4. What the bundles could not tell, and what the next bundle should carry

- **Which commit the install runs.** No member records it, so every "fixed on `main`" judgement
  above rests on an inference from which members exist. *Add* the git revision (or "not a git
  checkout") to `manifest.json`.
- **The long-running jobs' own state.** The re-index, quarantine, drain and bulk-qualification
  managers keep state files (`reindex_job.json`, `quarantine_job.json`), but no member carries
  them. The Qubes' 61-hour row-5 re-index left no progress or rate in the bundle at all, which
  cost this analysis a measured re-index rate on a 4 GB machine. *Add* a jobs member: every job's
  status, progress, rate and error.
- **What the operator did.** Lenn's five idle days needed a log line from a 300-entry ring to
  explain. *Add* an operator-and-lifecycle event log (scheduler start and stop, kill-switch
  toggles, exclusive windows entered and left with their outcome, job cancels).
- **Errors other than the one that repeats.** Dedupe the error ring by logger and message with a
  count, so one frontend 500 cannot fill it (§3.4 item 7).
- **The live release run** in `release-run.json` (RR-8).
- **`D45`'s row-size query** (§3.2 item 8).
- **Whether an unlock followed a machine boot**, so P0.4's "cold boot" is measured rather than
  assumed: record the machine's boot time beside the unlock timing.
- **Per-case deadlines in `benchmark.json` and `performance.json`**, so a slow case cannot
  starve the rest (§3.5 item 1).
- **Real searches.** `search-timing.json` captured zero searches on all six machines, so there is
  still no field evidence on search latency.

## 5. The plan

### 5.1 Operator steps, now (no code needed)

1. **Update all six machines to current `main` and restart each with the in-app shutdown.** A
   clean end gives the next boot an honest record, though it does not remove the WAL (§3.6 item
   4). This brings PRs #1164–#1170, above all the 6+6 pool behind most of the timeouts in this
   report. Two differences will be visible. Asus's drain
   restarts by itself at boot. A FULL bundle now declines the keyword-log digest on every one of
   these machines (§3.2 item 4).
2. **Lenn: turn collection back on.** It has been off since 2026-09-19 05:24Z (SCHED-1).
3. **Qubes-A: cancel its release run**, which was still in row 5 at the bundle. **Qubes-B and
   Qubes-C: do not resume theirs.** Row 5 should wait for FD01 and the RR-6 fix.
4. **Swap stays at the 1 GB default** (FD02, answered 2026-09-24). Two of the three Qubes VMs
   ended the way an out-of-memory kill does, so the code has to hold at 4 GB of RAM and 1 GB of
   swap: the release run now runs row 5 after the soak with collection paused, rather than
   beside it.
5. **NUC: turn on network time sync.** Its clock was 12 hours fast at boot, and the correction
   mid-run is what produced RR-4, RR-5 and RR-9 there.
6. **Asus: after the update, leave collection off for a few hours** so the drain runs alone with
   PR #1164's settings. Read `GET /api/backup/reindex-backlog/resume/status` twice, an hour apart,
   and keep both readings. That is `D43`'s A/B on a second, smaller machine, and `D46`(a)'s
   backlog fraction (67 %).
7. **Hold the release-run re-runs until the fix PR in 5.2 lands.** Then re-run release-scale with
   row 5 unticked on the NUC and one Qubes VM, and take a bundle after each.

### 5.2 Engineering, in order

1. **Release-run and chronology fixes: RR-1 to RR-8, RR-10 and RR-11** (mine). `src/monitoring/release_run.py`,
   `chronology.py`, `session_history.py`, the release-run member in the bundle, the row-5 wording
   ×12, tests against a bundle built by the real writer. It touches the indexing session's
   `bundle.py` in one function only.
2. **The field defects outside the write path: SCHED-1, QUAL-1, RR-9, CUST-1** (mine unless
   reassigned). `src/scheduler/runner.py`, `src/catalog/qualify_job.py` and `qualification.py`,
   the arming check in `src/monitoring/expedition.py`, the politeness clamp in
   `src/ingest/__init__.py`, and a custody reconcile. None of these files is in the indexing
   session's plan, but three sit in held beta-pathway slices, so each fix cites its slice:
   `S04-12` (source admission) for the qualification fix, `S04-13` (network budgets and
   politeness) for the clamp, and `S04-08` (the lanes) for the scheduler. The planned-work index
   finds no unanswered decision blocking any of them. FIX-1, INT-1 and the card-audit and
   bulletin guard (§3.5 item 2, §3.6 items 1 and 2) go in the same PR or a third one.
3. **The bundle additions in §4** (mine), coordinated with the indexing session, which also edits
   `src/api/diagnostics/bundle.py`.
4. **The indexing session's inputs, §3.2 items 1 to 9 and §3.5 item 1**, handed over as
   evidence rather than as tasks: their plan and their open decisions (`D43`–`D46`) decide what
   to do with them.
5. **The public-holiday lane** goes to the religious-dates work (`RC13`, Prompt 17b): the upstream
   endpoint is gone, so it needs a replacement source, not a parser fix.
6. **The Home cards that open onto an empty search** (§3.5 item 3) get their own destinations,
   and the ten producers that never fired are re-read once the card audit's guard lands
   (§3.5 item 4).

### 5.3 Hand-off note for the indexing-performance session (paste as is)

> Six all-diagnostics bundles from four-gigabyte machines arrived on 2026-09-24: Asus (289k
> articles), Lenn (193k), a NUC (149k) and three Qubes VMs (141k to 149k), all running `68b295b`,
> so none of PRs #1164–#1170. What they add to `docs/audit/15`:
>
> 1. The write-bound regime is the machine class, not the 1.3 M instance: the gate was busy 94 %
>    (Asus), 93 % (NUC) and 98.6 % (Qubes-A) of the process window, with stores only 1.5 to 1.9
>    times RAM (`soak-window.json`).
> 2. The slow INSERTs are execution, not lock waits. Asus logged 2,076 `INSERT INTO keywords` at
>    an average 56 s (max 272 s) and 2,007 `INSERT INTO articles` at 56 s (max 295 s). The gate is
>    taken in `before_flush`, outside the cursor timer, and `busy_timeout` is 30 s. That is half
>    of F5's attribution question, answered for the INSERT shapes.
> 3. F4 is on every machine and dates from the UNLOCK, not the boot: the oldest checkout is as old
>    as the session, from an "AnyIO worker thread". The NUC, unlocked 25 minutes after its boot,
>    separates the two. Either the unlock request path (`init_db` runs on it) leaks a checkout,
>    or `pool_watch` misses a check-in and reports a phantom. The WAL-pinned checkpoints (12 of
>    30 passes on Asus, 0 of 30 on the NUC) say it does not always hold a snapshot. If the
>    checkout is real, it may also be why a clean shutdown left a 66 MB WAL on the NUC:
>    `engine.dispose()` does not close a checked-out connection. Lenn's WAL reached 8.1 GB.
> 4. `R27`'s constant over-declines here. The keyword-log digest cost 434 to 874 MiB on these
>    machines, against the 3,322.8 MiB that `_MEMBER_RSS_NEED_MB` uses. About 317 bytes per
>    keyword fits all six within 25 % and still declines the member at 11 M keywords on 4 GB. As
>    built, row C's "every member" is unreachable on every small machine.
> 5. `api_headroom_for` counts only collector workers. The drain, bulk qualification, row 5's
>    re-index, the bundle, the release run and the scheduler thread share the four spare
>    connections with the API. Asus's drain died of the timeout beside those jobs.
> 6. Asus has a 195,081-article backlog (67 %) from two imports of 2026-09-03, and its drain
>    restarts at the next boot on `main`: a second machine for `D43`'s A/B and a number for
>    `D46`(a).
> 7. Two Qubes VMs (4 GB, 1 GB swap) ended the way an out-of-memory kill does, at 2.9 to 3.1 GB
>    RSS, during a whole-corpus keyword re-index plus collection.
> 8. `D45`'s query is not in any bundle member; add it and the next bundles answer `D45`.
> 9. P0.4: `init_db` took 4.2 s (Asus) and 4.1 s (Lenn), but 0.7 s on the NUC, which opened the
>    largest WAL, so it is not WAL replay. PRs #1164 and #1169 add boot heals there; the next
>    unlock reading shows their cost.
> 10. Insights reads with collection paused: super-group totals 15 to 35 s, trending 23 to 48 s,
>     trending windows 50 to 86 s; the map, who and where aggregates never ran because the
>     benchmark's shared 300 s deadline ran out.
>
> The full report, with provenance for every figure, is
> `docs/audit/16_FIELD_DIAGNOSTICS_SIX_MACHINES_2026-09-24.md`.


## 6. Questions (answer-sheet format; `ANSWER FDnn:` lines)

**FD01 · Where does row 5 go in the release run?** Row 5 is a quarantine pass plus a
whole-corpus keyword re-index. It ran 50 to 61 hours on the Qubes VMs without finishing, and it
sits before the soak.
- **a** — move it AFTER the soak and state its cost on the checkbox: the soak evidence comes
  first, and row 5 runs on its own time.
- **b** — keep the order, and only state the cost on the checkbox and in PF01.
- **c** — take it out of the release run; run it from its own button when a machine can spare
  the days.
Default if blank: **a**. Recommendation: **a**. The soak is what the gate needs from every
machine; row 5 is needed from one.
`ANSWER FD01:` *(blank at recording; the default **a** is taken as an ASSUMPTION per the
answer-sheet protocol and built in the release-run PR, reversible by answering here)*

**FD02 · The Qubes VMs' memory.** 4 GB of RAM and 1 GB of swap; two of three ended the way an
out-of-memory kill does, during row 5 plus collection.
- **a** — raise swap to at least 4 GB (no code, no tier change).
- **b** — raise RAM to 6 GB: above the floor, so qualification and the whole-corpus scans are no
  longer declined by it, and on the medium tier, where `D44`'s open pool question then applies.
- **c** — leave them as the floor-class test machines, and accept the kills as evidence.
Default if blank: **a**. Recommendation: **a**, and keep one VM at 4 GB as the floor reference.
`ANSWER FD02:` **swap stays at the 1 GB default** — the maintainer, 2026-09-24: «I won't change
swap size (default is 1Gb)». RAM is not ruled. Consequence recorded: the fixes must hold at 4 GB
of RAM and 1 GB of swap.

**FD03 · Source qualification below the memory floor.** Every machine here is below the
4 GiB floor, so no source has been judged on four of them, and the admission funnel is frozen
fleet-wide (82,805 candidates on Asus).
- **a** — keep the floor (S1.3); fix only the honesty (a named refusal, never "complete") and say
  on the Sources surface that qualification is declined on this machine, with the override.
- **b** — also design a qualification pass that fits below the floor (a sampled cohort instead of
  the whole-corpus scan).
- **c** — lower the floor so 3.8 GiB VMs count as 4 GB machines.
Default if blank: **a**. Recommendation: **a now, b as a planned slice.** The honesty fix is
owed under every option; whether small machines should qualify at all is a product question.
`ANSWER FD03:` *(blank at recording; the default **a** is taken as an ASSUMPTION and built in
the field-defects PR, #1173: the floor stays, the decline is named and shown)*

**FD04 · When do my two fix PRs go in?** They touch different files from the indexing session's
plan, except one function in `bundle.py`.
- **a** — now, in parallel with the indexing session.
- **b** — after the indexing session's remaining PRs land.
Default if blank: **a**. Recommendation: **a**. The re-runs in 5.1 step 7 wait on the first one.
`ANSWER FD04:` **a** — the maintainer, 2026-09-24: «commit the report and open both fix PRs».

