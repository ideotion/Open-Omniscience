# Field diagnostics, first batch: appendix tables

Companion to `16_FIELD_DIAGNOSTICS_SIX_MACHINES_2026-09-24.md`. These are the six analysts' comparison tables, produced by
Sonnet agents and re-checked by six Sonnet verifiers. Cells found wrong on hand-verification are corrected
in place and marked **[corrected]**; where the main report differs, the main report wins.

## Latency, the write gate, the pool and slow statements

| Metric (MEASURED unless noted) | Asus | Lenn | NUC | QubesA | QubesB | QubesC |
|---|---|---|---|---|---|---|
| Process uptime at capture (soak-window.json `window.hours`) | 127.42 h | 128.18 h | 60.64 h | 61.74 h | 1.28 h | 1.28 h |
| Write-gate busy_share (soak-window.json) | **0.940** | 0.0092 | 0.930 | **0.986** | 0.618 | 0.454 |
| Write-gate contended_share_of_grants | 0.561 | 0.058 | 0.713 | 0.312 | 0.172 | 0.000 |
| Write-gate grants / contended | 17,044 / 9,563 | 260 / 15 | 14,299 / 10,191 | 76,829 / 23,946 | 314 / 54 | 132 / 0 |
| Write-gate max_wait_s | 928.9 | **1041.3** | 315.4 | 288.1 | 368.1 | 0.0 |
| stall-forensics n_recorded (cap 200) | 200 (truncated) | 74 | 200 (truncated) | 200 (truncated) | 7 | 8 |
| stall-forensics writer-gate-contention share | 197/200 (98.5%) | 45/74 (60.8%) | 192/200 (96%) | 200/200 (100%) | 0/7 | 0/8 |
| Stalls on GET /api/scheduler/activity | 198/200 | 42/74 | 200/200 | 199/200 | 0/7 | 0/8 |
| /api/scheduler/activity: n / 500-count / rate | 87,727 / 3,269 / 3.7% | 603 / 34 / 5.6% | 24,155 / 1,022 / 4.2% | 30,767 / 246 / 0.8% | 1,431 / 0 / 0% | 1,497 / 0 / 0% |
| /api/scheduler/activity p50/p95/p99/max (ms) | 186.6/15486.1/30012.7/42021.7 | 34.5/438.1/1059.1/45020.7 | 46.0/12040.1/30011.6/37704.5 | 26.9/90.7/557.4/30748.5 | 24.8/133.2/413.7/4824.6 | 25.2/102.6/1288.8/2908.0 |
| event-loop watchdog max_lag_ms (n=50 events) | 11,873.6 | 19,184.1 | 938.5 | 794.9 | 521.2 | 585.5 |
| snappy_bar: pass/fail/low_n/breaching (of interactive) | 5/1/63/19 (69) | 6/1/68/26 (75) | 5/1/57/26 (63) | 7/0/65/15 (72) | 7/0/64/18 (71) | 6/1/63/22 (70) |
| slow-queries top statement (shape) | INSERT keywords, 2076x, avg 56.2s, max 272.3s | SELECT keyword_mentions..., 1x, 1120.2s | INSERT keywords, 2813x, avg 18.9s, max 55.2s | INSERT keywords, 3104x, avg 12.4s, max 191.5s | INSERT keywords, 50x, avg 24.0s, max 259.5s | INSERT articles, 33x, avg 16.0s, max 26.4s |
| performance.json / benchmark.json outcome | partial-deadline / partial-deadline | partial-deadline / partial-deadline | partial-deadline / partial-deadline | partial-deadline / partial-deadline | partial-deadline / partial-deadline | partial-deadline / partial-deadline |
| performance.json insights_trending probe (run1) | interrupted | **270,566 ms** | 36,416 ms | 32,314 ms | 26,655 ms | 28,574 ms |
| benchmark.json cases_ok / cases_failed (of 15) | 9 / 6 | 9 / 6 | 10 / 5 | 11 / 4 | 11 / 4 | 12 / 3 |
| benchmark "supergroups" median (optimized-this-session) | 29.9s | 25.8s | 35.1s | 16.3s | 14.6s | 15.0s |
| benchmark "trending_windows" median | interrupted | interrupted | interrupted | 59.9s | **85.9s** | 50.2s |
| frontend-errors captured / on scheduler/activity | 500 / 500 (100%) | 429 / 424 (98.8%) | 500 / 500 (100%) | 260 / 254 (97.7%) | 275 / 269 (97.8%) | 269 / 267 (99.3%) |
| QueuePool text count (grep, all members) | 3 | 170 | 0 | 66 | 133 | 71 |
| manifest: source-audit.json / keyword-log-digest.json bytes | 0 / 495,864B ok | 0 / 638,892B ok | 0 / 652,340B ok | 0 / **0 (skipped)** | 30,xxx ok / 444,720B ok | ok / 544,364B ok |
| Release-gate row C ("every member non-zero") | VIOLATED (1 empty) | VIOLATED (1 empty) | VIOLATED (1 empty) | VIOLATED (2 empty, worst) | satisfied | satisfied |
| -wal file size (windows-locks.json) | 7.6 MB | 468.2 MB | 65.2 MB | **802.9 MB** | 67.1 MB | 67.1 MB |
| search-timing.json searches captured | 0 | 0 | 0 | 0 | 0 | 0 |

## Collection, the scheduler, the network and sources

| Metric | Asus | Lenn | NUC | QubesA | QubesB | QubesC |
|---|---|---|---|---|---|---|
| Collector running/active (bundle time) | True/True | **False/False** | True/True | True/True | True/True | True/True |
| Phase | collecting | — (idle since 09-19) | maintenance | collecting | collecting | collecting |
| Last recycle reason (last pass) | budget | **stopping** | budget | budget | budget (1 None) | budget |
| Kill switch (measured) | False | False | False | False | False | False |
| Transport | clearnet (no Tor/proxy evidence on any of the six; default `fetch_mode="transparent"`) | same | same | same | same | same |
| Recent-runs span covered | 09-22→09-24 | 09-15→09-19 (stopped) | 09-20→09-21 | 09-20→09-21 | 09-19→09-21 | 09-20→09-21 |
| Mean pass duration | 4,635 s | 4,491 s | 4,046 s | 4,138 s | 3,934 s | 4,069 s |
| Mean stored/pass | 312 | 370 | 610 | 692 | 1,025 | 876 |
| Mean stored/hour | 240.3 | 296.3 | 542.6 | 612.0 | 939.4 | 788.3 |
| fetch_failed (sum/30) | 994 | 379 | 875 | 1,255 | 1,458 | 1,446 |
| errors (sum/30) | 62 | 207 | 593 | 171 | 278 | 278 |
| robots_unavailable (sum/30) | 106 | 77 | 221 | 257 | 259 | 342 |
| Dominant collect_perf adjust_reason | writer-saturated (189/200) | at-ceiling (199/199, last pass) | mixed: at-ceiling 123 / writer-saturated 65 | mixed: at-learned-ceiling 97 / writer-saturated 87 | at-learned-ceiling (168/200) | at-learned-ceiling (200/200) |
| Governor bottleneck verdict (pass-end summary, where present) | n/a (mid-pass) | **writer-bound** | **memory-bound** | n/a | n/a | n/a |
| Permits (typical) | 1 | 8 (at ceiling) | 1–8 (mixed) | 1–2 | 2 | 1 |
| WAL reader oldest_age_s at bundle time | **457,537 (127.1 h)** | 3,869 (1.1 h) | **215,710 (59.9 h)** | **221,064 (61.4 h)** | 3,484 (1.0 h) | 3,509 (1.0 h) |
| source-audit.json | **skipped (300s deadline)** | **skipped** | **skipped** | **skipped** | completed | completed |
| Total RAM (measured) vs 4,096 MB floor | 3,739.5 MB (below) | 3,296.0 MB (below) | 3,794.9 MB (below) | 3,924.4 MB (below) | 3,924.4 MB (below) | 3,924.4 MB (below) |
| Bulk-qualification job | **done [0/79977] "starting…"**, +0/93h | not started this window | **done [0/48977] "starting…"**, +0/83h | not started (its release run never reached the soak) **[corrected]** | not started | not started |
| qualification-integrity: with_judging_attempt | 657 (all historical, static) | 511 (all historical, static) | **0** | **0** | **0** | **0** |
| source-qualification-export: qualified_by_curation share | 2,739/3,396 (81%) | 3,811/4,322 (88%) | **6,195/6,195 (100%)** | **6,195/6,195 (100%)** | **6,195/6,195 (100%)** | **6,195/6,195 (100%)** |
| Calendar lane: worldpublicholiday.com per-country feeds attempted / with events | 239 / **0** | 239 / **0** | 0 (lane untouched) | 0 | 0 | 0 |
| Law lane: documents / re_extracted / eu robots_blocked | 23 / 0 / 4/4 | 23 / 0 / 4/4 | 23 / 0 / 4/4 | 23 / 0 / 4/4 | 23 / 0 / 4/4 | 23 / 0 / 4/4 |

## Storage, integrity and data safety

| Metric | Asus | Lenn | NUC | QubesA | QubesB | QubesC |
|---|---|---|---|---|---|---|
| Articles | 289,027 | 192,710 | 149,334 | 147,985 | 141,282 | 149,489 |
| DB file (`storage-footprint` "database") | 6.77 GB | 7.36 GB | 5.88 GB | 6.04 GB | 5.74 GB | 6.05 GB |
| Data-dir total (`grand_total_bytes`) | 7.19 GB | 8.05 GB | 6.14 GB | 6.99 GB | 5.99 GB | 6.31 GB |
| RAM (given) | 3.9 GB | 3.4 GB | 4.0 GB | 4.1 GB | 4.1 GB | 4.1 GB |
| Store / RAM ratio (ARITHMETIC, data-dir/RAM) | ≈1.84x | ≈2.37x | ≈1.53x | ≈1.70x | ≈1.46x | ≈1.54x |
| page_size / page_count / freelist | 16384 / 443,526 / 0 | 16384 / 482,352 / 0 | 16384 / 385,610 / 10 | 16384 / 396,162 / 19 | 16384 / 376,149 / 6 | 16384 / 396,393 / 2 |
| auto_vacuum | incremental | incremental | incremental | incremental | incremental | incremental |
| WAL now | 7.6 MB | 446.5 MB | 65.2 MB (64.0MB in footprint snapshot) | 802.9 MB | 67.1 MB | 67.1 MB |
| WAL history max (`wal_history.series`) | 1.94 GB (09-24 08:00) | 8.1 GB (09-04 21:00) | 383 MB (09-17 16:00) | 311 MB (09-19 04:00) | 82 MB (09-20 09:00) | 81 MB (09-19 16:00) |
| Last TRUNCATE checkpoint: busy / before→after bytes | 0 / 111.6M→0 (drained) | 1 / 277.0M→277.0M (stalled) | 0 / 67.1M→0 (drained) | 1 / 297.7M→302.9M (GREW) | 1 / 118.7M→118.7M (stalled) | 0 / 67.1M→0 (drained) |
| Oldest open reader ("AnyIO worker thread") | 127.2 h | 65 min | 59.9 h | 61.6 h | 69 min | 59.1 h |
| corpus_integrity: orphan_keywords / drift | null (interrupted) / false | 0 / false | 0 / false | 5,835 / **true** | 372 / **true** | 8,330 / **true** |
| corpus_integrity: counter_drift_error | interrupted (6/6) | interrupted | interrupted | interrupted | interrupted | interrupted |
| corpus_integrity: timed_out (top-level flag) | false | false | false | false | false | false |
| fixity: mismatched / 500 (all hazard://+law URLs) | 110 (22.0%) | 144 (28.8%) | 0 | 0 (no P0/fixity run scope tested) | 0 | 0 |
| schema-drift / country-code duplicates | clean / 0 | clean / 0 | clean / 0 | clean / 0 | clean / 0 | clean / 0 |
| dbstat (per-table breakdown) available | No | No | No | No | No | No |
| P0-4 unlock (ms, bar 2000) | 5,356 **FAIL** | 6,581 **FAIL** | 1,763 **PASS** | not run | not run | not run |
| P0 summary (pass/fail/not-measurable) | 3/1/1 | 1/1/3 | 5/0/0 | n/a | n/a | n/a |
| Preceding session ended | unclean (near-OOM, swap ~8.2/8.6GB) | unclean (swap 3.6/7.6GB) | clean (WAL still present next boot) | n/a in scope | n/a | n/a |
| data-dir-persistence at_risk | unknown | unknown | unknown | unknown | unknown | unknown |
| custody_log.db (from forensics "Data folder") | 359.0 MB | 223.9 MB | 188.2 MB | not available (no forensics file) | not available | not available |
| index_pages_above_guard (non-article-scan) | 0.80% | 0.47% | 0.19% | 0.18% | 0.18% | 0.19% |

## The keyword index, the re-index backlog and search quality

| Metric | Asus | Lenn | NUC | QubesA | QubesB | QubesC |
|---|---|---|---|---|---|---|
| Articles (manifest) | 289,027 | 192,710 | 149,334 | 147,985 | 141,282 | 149,489 |
| Keywords | 1,501,132 | 2,338,025 | 2,491,360 | 2,333,987 | 2,184,098 | 2,344,295 |
| Mentions | 8,462,304 | 15,194,245 | 11,540,862 | 11,558,567 | 11,089,020 | 11,680,330 |
| Zero-mention (orphan) keywords | 7 | 0 | 0 | 5,426–5,835 | 372 | 8,330 |
| Articles with ≥1 keyword (keyword-growth.json) | 106,578 | 192,702 | 149,328 | 147,982 | 141,242 | 149,468 |
| **Index coverage share** | **36.9%** | 99.996% | 99.996% | 99.998% | 99.972% | 99.986% |
| Mentions / indexed article | 79.40 | 78.85 | 77.28 | 78.11 | 78.51 | 78.14 |
| Re-index backlog (imports) | **stuck 730/195,081 from two imports of 2026-09-03, ≥47 h no progress, error=pool timeout **[corrected: not from the release run's restore, which went into a throwaway install]**** | none | none | none **[corrected]** | n/a | n/a |
| keyword-log-digest outcome | ok, 225.4s, 495,864 KB Δrss | partial-deadline, 331.0s, 638,892 KB Δrss | ok, 166.2s, 652,340 KB Δrss | **skipped-deadline, 300.7s, 0 bytes, 895,068 KB Δrss** | ok, 201.4s, 444,720 KB Δrss | ok, 196.1s, 544,364 KB Δrss |
| corpus-integrity counter_drift | error/interrupted | error/interrupted | error/interrupted | error/interrupted | error/interrupted | error/interrupted |
| corpus-integrity orphan/dangling scalars | orphan=null, dangling=null (timed out) | orphan=0, dangling=null | orphan=0, dangling=0 | orphan=5,835, dangling=0 | orphan=372, dangling=0 | orphan=8,330, dangling=0 |
| keyword-engine selftest / ir-eval / triage-selftest | 49/49, 10/10, pass | 49/49, 10/10, pass | 49/49, 10/10, pass | 49/49, 10/10, pass | 49/49, 10/10, pass | 49/49, 10/10, pass |
| keyword-triage proposal/run | not run (no local model) | not run | not run | not run | not run | not run |
| Heaps beta / mint_start→mint_end (per 1,000 words) | 0.808 / 70.6→47.6 | 0.764 / 84.8→110.3 (rising) | 0.885 / 102.2→74.5 | 0.809 / 93.4→92.2 | 0.765 / 93.4→101.3 (rising) | 0.811 / 93.6→81.8 |
| Distinct languages in keyword-engine | 55 | 58 | 75 | 76 | 76 | 76 |

## Sessions, memory, the chronology and the release run

| Metric | Asus | Lenn | NUC | QubesA | QubesB | QubesC |
|---|---|---|---|---|---|---|
| Pre-ledger previous session (forensics sentinel) | unclean-end | unclean-end | clean | clean | unclean-end | unclean-end |
| Prev-session peak RSS / RAM | 1579.2 / 3739 MB | 1654.2 / 3296 MB | n/a (clean) | n/a (clean) | 2944.8 / 3925 MB | 3056.8 / 3925 MB |
| Prev-session avail_min | 76.2 MB | 291.1 MB | n/a | n/a | 278.4 MB | 173.7 MB |
| Prev-session swap used / total | 8225.1 / 8224.9 MB (100%) | 3631.1 / 7601.6 MB (48%) | n/a | n/a | 1024.0 / 1024.0 MB (100%) | 1024.0 / 1024.0 MB (100%) |
| Ledger sessions recorded (this build) | 1 | 1 | 2 | 1 | 2 | 2 |
| Ledger restarts / unclean ends / suspends | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 1 / 1 / 0 | 1 / 1 / 0 |
| Ledger gaps | 0 | 0 | 1 (181s) | 0 | 1 (33955s) | 1 (4118s) |
| Wall-clock non-monotonicity defect observed | no | no | **yes (2 forms)** | no | no | no |
| Release run outcome | done | cancelled | done (interim seen mid-soak; final = done) | still in row 5, no report written **[corrected]** | still in row 5, no report written **[corrected]** | still in row 5, no report written **[corrected]** |
| Soak elapsed / requested | 72.00 / 72.00 h | 0 (never armed) | 72.00 / 72.00 h | 0 (never reached) | 0 (never reached) | 0 (never reached) |
| row5_quarantine outcome | error @ 7h07m (pool timeout) | error @ 2m38s (pool timeout) | skipped (not opted in) | still running after 61 h: the re-index held the write gate 60–75 s every few minutes **[corrected: slow, not hung]** | running ~51 h, then the process died uncleanly **[corrected]** | running ~59 h, then the process died uncleanly **[corrected]** |
| Board row B status vs. reaches_bar/window_hours | measured / true, 80.46h | skipped / false, — | **measured / null, null** (collect died) | skipped (no soak phase run) | skipped | skipped |
| Board row C coverage_complete | **null (code defect, manifest shows complete:true)** | n/a (run cancelled) | **null (same code defect)** | n/a | n/a | n/a |
| Chronology summary.bar_reached | true | **true (contradicts run's own row B)** | false (60.6/72h so far) | false | false | false |
| Heartbeat RSS min–max (first→last) | 788–1623 MB (958.7→1260.9) | none (soak never armed) | 1060.6–2140.6 MB (1110.0→1479.7) | none | none | none |
| Memory-guard engagements during soak/window | 0 | 0 | 0 | n/a | n/a | n/a |
| Largest single-member RSS riser (manifest) | keyword-log-digest.json (~484 MB) | keyword-log-digest.json (~624 MB) | keyword-log-digest.json (~637 MB) | keyword-log-digest.json (~874 MB) | keyword-log-digest.json (~434 MB) | keyword-log-digest.json (~532 MB) |
| Current-session pass-tail died_during | none | none | none | none | none | none |

## AI, perception, qualification and the product surfaces

| Metric | Asus | Lenn | NUC | QubesA | QubesB | QubesC |
|---|---|---|---|---|---|---|
| RAM / cores (ai.json) | 3.7 GB / 4 | 3.2 GB / 2 | 3.7 GB / 4 | 3.8 GB / 2 | 3.8 GB / 2 | 3.8 GB / 2 |
| AI backend reachable | No | No | No | No | No | No |
| recursive-loop all_green (of 23) | false (22/23) | true (23/23) | false (22/23) | true (23/23) | true (23/23) | true (23/23) |
| ai-activity-selftest | **FAIL** ENOSPC | pass | **FAIL** ENOSPC | pass | pass | pass |
| card-audit ok / no-signal / error (of 37) | 3 / 19 / 15 | 4 / 18 / 15 | 5 / 18 / 14 | 5 / 21 / 11 | 5 / 22 / 10 | 5 / 21 / 11 |
| card-audit first true failure @ s | rising_now @60.0 | rising_now @60.1 | framing_split @22.2 | diet_self_audit @15.4 | echo_chamber @0.05* | diet_self_audit @24.2 |
| card-audit elapsed_s (member ok) | 75.5 | 69.8 | 69.5 | 66.7 | 65.3 | 65.8 |
| home-cards total / mismatched | 54 / 0 | 51 / **4** (law_change 100%) | 51 / 1 | 48 / 1 | 52 / **2** | 44 / 1 |
| bulletin-weekly outcome / wall_s | partial-deadline / 301.1 | partial-deadline / 301.7 | partial-deadline / 301.7 | partial-deadline / 305.1 | partial-deadline / 300.2 | partial-deadline / 301.4 |
| bulletin-weekly cards producers_run | 0/37 | 0/37 | 0/37 | 0/37 | 0/37 | 0/37 |
| leads-quality count / producers_run / outcome | 0 / 1 / **partial-deadline** | 5 / 1 / ok | 12 / 10 / ok | 15 / 16 / ok | 13 / 16 / ok | 21 / 18 / ok |
| date-extraction coverage_pct (n=1500 sample) | 53.8% | 63.8% | 57.5% | 59.1% | **41.1%** | 57.9% |
| elections-floor covered/floor | 10/140 (identical static catalog, all six) | " | " | " | " | " |

*QubesB's first failure at 0.05 s implies an earlier, non-raising producer already exhausted the 60 s budget before echo_chamber's turn.

## Verification verdicts

Every medium-or-higher finding went to an adversarial verifier. None was refuted.

| Finding | Title | Reproduced | Status on `main` | Owner | Severity after review |
|---|---|---|---|---|---|
| PERF-01 | Insights aq.trending()/trending_windows() and supergroups take 12s-270s on every machine, universally blowi... | yes | open | indexing-performance-session | high |
| PERF-02 | The write gate is more saturated on 3/6 machines than the audit-15 reference instance, and virtually every ... | yes | partly-addressed-on-main | indexing-performance-session | high |
| PERF-03 | Individual slow INSERT statements dominate write-gate hold time on the three heavily-loaded machines, at a ... | yes | open | indexing-performance-session | high |
| PERF-04 | Release-gate row C ('every member non-zero, coverage complete') is violated on 4 of 6 machines at 68b295b, ... | yes | partly-addressed-on-main | release-run-and-diagnostics | high |
| PERF-05 | Current main's RAM-floor decline (R27, absent from all six machines' code) would auto-decline keyword-log-d... | yes | open | release-run-and-diagnostics | medium |
| PERF-06 | search-timing.json records zero real searches on all six field machines | yes | not-a-defect | operator | info |
| COLL01 | Live source qualification is dead on every one of the six field machines by design — all six sit below the ... | yes | open | collector-and-network | high |
| COLL02 | A machine-floor decline is silently reported as job COMPLETE with zero progress, never as 'declined' or 'pa... | yes | open | collector-and-network | high |
| COLL03 | A read transaction held by an 'AnyIO worker thread' pins the WAL for 60-127 hours on three of six machines **[corrected: the hygiene samples show it on all six, dating from each unlock]** | yes | open | indexing-performance-session | high |
| COLL04 | QueuePool exhaustion (F1) confirmed on all six machines, through more subsystems than audit 15 described | yes | partly-addressed-on-main | indexing-performance-session | high |
| COLL05 | The worldpublicholiday.com per-country calendar-feed lane is completely non-functional — 0/239 country feed... | yes | open | collector-and-network | medium |
| COLL06 | NUC's governor bottleneck is memory-bound, not writer-saturated — the field fleet does not uniformly match ... | partly | not-a-defect | collector-and-network | info |
| COLL07 | Lenn's collector has been idle for ~5.35 days; the trigger cannot be pinned from the available diagnostics | yes | cannot-tell | operator | high |
| STORE-01 | Asus and Lenn's preceding sessions ended uncleanly with peak RSS/swap close to the machine's ceiling, and e... | yes | not-a-defect | collector-and-network | medium |
| STORE-02 | P0.4 unlock (2,000ms bar) fails on 2 of 3 release-scale machines, both dominated by init_db; NUC is the onl... | yes | open | indexing-performance-session | high |
| STORE-03 | Long-held 'AnyIO worker thread' read transactions pin the WAL and stall TRUNCATE checkpoints on 3 of 6 mach... | yes | open | indexing-performance-session | high |
| STORE-04 | fixity.json reports 22-29% 'mismatched' articles on Asus/Lenn, but this is a false positive: 4 non-scrape i... | yes | open | other | high |
| STORE-05 | corpus_integrity's 'timed_out' flag stays false even when the deadline visibly interrupted every sub-check,... | yes | open | release-run-and-diagnostics | high |
| STORE-06 | Real, measured keyword-orphan drift on all three Qubes VMs, correlated with an auto_cleanup prune pass that... | yes | open | indexing-performance-session | medium |
| STORE-07 | dbstat (per-table storage breakdown) is unavailable on all 6 field machines — the app's SQLite/SQLCipher bu... | yes | open | release-run-and-diagnostics | medium |
| STORE-11 | A 'clean' shutdown does not guarantee the WAL is checkpointed/removed by the next boot — the app's own P0.4... | yes | open | release-run-and-diagnostics | high |
| KW01 | Asus: re-index drain stuck, 63% of the corpus has zero keyword index **[corrected: the backlog is from the 2026-09-03 imports]** | yes | open | indexing-performance-session | high |
| KW02 | corpus-integrity's counter-drift check fails on all six machines, and the top-level drift flag folds an unm... | yes | open | indexing-performance-session | high |
| KW03 | keyword-log-digest.json is expensive and unreliable near its own deadline, and QubesA's failure looks like ... | yes | partly-addressed-on-main | release-run-and-diagnostics | low |
| STAB01 | row5_quarantine hangs forever with no deadline; silent on all 3 Qubes VMs, 2 of 3 ended in an unclean (OOM-... | yes | open | release-run-and-diagnostics | critical |
| STAB02 | Row C's coverage_complete is unconditionally null: _bundle() reads the wrong archive member/key for runtime... | yes | open | release-run-and-diagnostics | high |
| STAB03 | Board row B's status is decoupled from its own headline evidence -- it can read 'measured' while reaches_ba... | yes | open | release-run-and-diagnostics | high |
| STAB04 | chronology.summary.bar_reached is independent of the release run's own outcome/soak status -- it read true ... | yes | open | release-run-and-diagnostics | high |
| STAB05 | Backward wall-clock correction on NUC produces an impossible event ordering AND a phase that ends before it... | yes | open | release-run-and-diagnostics | medium |
| STAB06 | A phase's generic-exception path discards all partial evidence it had already gathered -- 7 hours of write-... | yes | open | release-run-and-diagnostics | medium |
| PROD-01 | A shared-connection statement-deadline cascade -- already fixed once in run_all_bounded -- recurs unfixed i... | yes | open | product-surfaces | high |
| PROD-02 | Cards about non-article entities (law revisions, source candidates, IP litigation) click through to a searc... | partly | open | product-surfaces | high |
| PROD-03 | ai-activity-selftest fails with ENOSPC on Asus and NUC, tied to the default temp directory rather than the ... | yes | open | product-surfaces | medium |
| PROD-05 | 10 of 37 registered home-card producers never fired on any of the six real corpora | yes | open | product-surfaces | medium |

Hand-verification changed three verdicts beyond the verifiers': STAB01 (row 5) is slow, not hung, and rated high rather than critical; KW01's backlog comes from the 2026-09-03 imports; COLL05's feeds now answer HTTP 404. COLL07 (Lenn's idle collector) is resolved by the logged scheduler warning (SCHED-1 in the main report).
