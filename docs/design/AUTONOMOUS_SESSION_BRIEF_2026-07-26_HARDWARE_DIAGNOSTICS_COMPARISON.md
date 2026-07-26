# Hardware Diagnostics Comparison — 2026-07-26

**Status:** investigation complete, nothing built. Seven `all-diagnostics` exports, one per
hardware instance, captured within a ~3-hour window on 2026-07-26 (one instance re-exported ~8
hours later at a much larger corpus size — see instance 1fba378c below), analyzed by seven
independent deep-dive agents each scoped to one instance's directory, then synthesized here.
This is the companion analysis the field-remarks brief
([`AUTONOMOUS_SESSION_BRIEF_2026-07-26_FIELD_REMARKS.md`](AUTONOMOUS_SESSION_BRIEF_2026-07-26_FIELD_REMARKS.md))
flagged as still pending. An eighth zip (`4f21a37c`, dated 2026-07-10) was excluded — it predates
the current diagnostics-bundle format entirely (no hardware/corpus/run header, only 17 of the
current 40+ member files) and isn't comparable.

**Every finding below is cited to a specific file + field from a real export.** Where a pattern
recurs across instances, it is called out explicitly as such — recurrence across independently
provisioned hardware is what makes a finding structural rather than a one-machine fluke.

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
"main database" referenced earlier in this conversation — its article/keyword counts
(700,522 / 6,914,218) match exactly.

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
it has a clear proposed mechanism, and it plausibly explains a large share of every other
performance symptom below.

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
agent's report — see the note below.

This endpoint is polled continuously (roughly every 4–17 seconds on every instance) alongside a
tight group of siblings that are ALSO consistently slow and ALSO consistently polled at the same
cadence: `/api/database/coverage`, `/api/database/figures`, `/api/database/stats`,
`/api/library/overview`, `/api/insights/map-coverage`. The near-identical request counts across
this group on every single instance (e.g. `243c5a14`: all five at exactly 11,230/11,230/11,230/…)
confirm they're polled together by one UI surface — almost certainly the Library/Governments tab
staying open across the whole diagnostics-export window. `EXPLAIN QUERY PLAN` is healthy
everywhere (`COVERING INDEX`, no bare scans) — this is a scaling-ceiling problem in the underlying
aggregation, not a missing-index problem, and it compounds directly with the universal WAL
finding above (the watchdog event-loop-lag logs on multiple instances show lag spikes
time-correlated with this exact endpoint sitting in-flight).

**This is the single most actionable, highest-ROI fix in the whole dataset**: one endpoint (plus
its ~4-5 polling siblings) is responsible for double-digit percentages — in three cases over a
fifth, in one case over 80% combined — of total server processing time on every hardware tier
tested, from a 6-core/15GB machine down to a 2-core/3.5GB one. Per this project's own documented
optimization pattern (already successfully applied to `top_terms_grouped`/`supergroups`/
`who_aggregate` — all confirmed fast via maintained counters in these same exports), this class of
endpoint needs the same treatment: a maintained counter or a persisted/refreshed rollup, not a
live per-request aggregation over the full `sources`/`keyword_mentions` tables.

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

## 5. Bug A / Bug B cross-check — inconclusive on this batch, but with an important refinement

Neither of the two already-root-caused job bugs from the field-remarks brief (source-tags'
0/0-batches-then-crash; keyword-triage's silent pause-reads-as-done) could be **directly**
confirmed OR refuted by this batch, because **6 of the 7 instances have never run either job at
all** — `source-tags-run.json`/`keyword-triage-run.json` report `available: false` on
`0bfa36df`, `243c5a14`, `4663bbc5`, `6557d2cf`, `c1e1a30d`, and `ea11e68c`, in every case because
no working local LLM backend was reachable at export time (`ai.json`'s
`ollama_available: false` where the file exists at all; the 3 older-schema instances lack the
file entirely, predating the AI-stack work).

**Only `1fba378c` (the 700k-article main DB) has real, live run data**, and it shows a THIRD,
previously-unconsidered failure mode: **neither job has crashed or paused — both are simply
running very slowly.** `keyword-triage-run.json`: `state: "in_progress"`, `batches_logged: 84`
after roughly 7 hours (≈2,100 of 6,914,218 keywords judged — ~0.03% coverage). `source-tags-run.json`:
`state: "in_progress"`, `detail_records_logged: 1012` against a 200-source scope, also after ~7
hours. Neither shows `state=="error"` and this run-summary schema doesn't expose `complete`/
`paused_reason`, so the exact "paused-reads-as-done" collapse from the code-level root cause
couldn't be directly observed here — but the sheer slowness on this instance's own hardware
(6-core/15GB, otherwise healthy) is itself consistent with, and a plausible trigger for, an
eventual `LLMUnavailable`/`LLMError` given enough elapsed time; the batch was simply still
running at export time, not yet at the point of failure.

**A genuinely new, valuable finding surfaced instead**: `1fba378c`'s `perception-eval-live.json`
shows the active model (**`mistral:7b`** — the maintainer-ruled default) scored **precision 0.0526
/ recall 0.1667 / hallucination_rate 0.9474 (94.7%!)** on "who" extraction in a live 17-case eval
run against the real perception harness. `perception-extract-run.json` confirms the fail-safe
worked exactly as designed: all 700,242 gated articles were refused, zero who/where/when
candidates stored anywhere in this 700k-article corpus. This is real field evidence that
Mistral-7B — the maintainer's chosen default model — may not clear the perception-extraction
quality bar at all, at least for "who" extraction, worth surfacing before more effort goes into
that feature on this model.

**One more relevant fact for context**: `ai.json`'s disclosed context-window gap (Ollama has no
RAM-derived `num_ctx` auto-tune, unlike vLLM's `compute_server_args` — confirmed present and
unaddressed on every instance that has `ai.json`) is a plausible contributing factor to
`LLMError`/context-overflow symptoms given source-tags' large embedded tag vocabulary
(`vocabulary_size: 202` on `1fba378c`) — but this batch doesn't contain a crashed run to confirm
it fired.

## 6. NEW finding — schema/migration drift, reproduced on 3 of the newer-schema instances

`schema-drift.json` on `4663bbc5`, `6557d2cf`, and `ea11e68c` (all three of the "newer schema"
group) independently shows the same two facts: **the database's own alembic stamp lags the
running code's migration head** (stamped at the older revision `95120f685050` while the code runs
at `4fc4be4dffef`), and **the `sources` table is missing its `last_crawled_at` index**
(`missing_indexes: ["last_crawled_at"]`). This is not cosmetic: on `6557d2cf`, the crawl-by-default
feature is confirmed actively enabled (`scheduler.status.settings.crawl_supplement: true,
crawl_per_pass: 3`), meaning its least-recently-crawled selection query is very likely running an
unindexed sort over a 76,000+ row `sources` table on hardware already shown to be write-gate/WAL
constrained. Self-heal appears to have back-filled every column on these instances but missed
this one index. Recommend an `alembic upgrade head` (or equivalent self-heal fix) pass across
these instances, and checking why this specific index's migration step isn't being applied by
the self-heal path.

## 7. NEW finding — a power-profile diagnostic reports the wrong effective value

`243c5a14`'s `power-profile.json` reports the "optimized" profile's effective
`collect_parallelism` as **1** (`source: "profile:optimized"`), while the SAME instance's live
`debug-bundle.json → scheduler.status.settings.collect_parallelism` is actually **50**. Either the
power-profile diagnostic isn't correctly reading the value actually in effect, or its "source"
label is wrong once some other mechanism (an operator override, a different code path) has raised
the real ceiling above the profile's own table value. Worth reconciling since this diagnostic's
whole purpose is to be the authoritative "what's actually in effect right now" surface — CLAUDE.md
records the power-profile "Low"/"Max" tiers as still provisional pending measurement, and this is
exactly the kind of discrepancy that measurement work needs to catch.

## 8. NEW finding — a second unfiltered third-party logger, distinct from the already-fixed one

CLAUDE.md's own lessons record that `htmldate.meta`'s `"impossible to clear cache"` WARNING-noise
was already found and filtered (2026-07-23) after it was found to be 85 of 93 "problems" logged in
one export. **This batch surfaces a second, still-unfiltered instance of exactly the same class**:
on `0bfa36df`, **175 of a 300-record error-log sample (58%)** are `trafilatura.metadata: error in
JSON metadata extraction: 'NoneType'/'list' object...` WARNING-level noise — a different logger
than the one already fixed, drowning the real signal (`problems_this_session: 873` on that
instance, most of it plausibly this one source). `6557d2cf` independently shows the same
`trafilatura.metadata` pattern (105+ occurrences in its own 300-record sample) alongside a THIRD
noise source: `GET /v1/models` returning 404 (the vLLM-availability probe on GPU-less hardware) —
**511–617 such requests per instance**, all correctly-failing-as-designed but adding continuous
low-value load and log noise on already resource-constrained machines. Recommend extending the
existing noise-filter mechanism (`_HtmldateCacheNoiseFilter`) to cover `trafilatura.metadata` the
same way, and considering whether the `/v1/models` health-probe interval should back off when
vLLM is confirmed absent rather than polling indefinitely.

## 9. Findings specific to the main production instance (`1fba378c`, 700,522 articles)

This instance is qualitatively different from the other 6 (which read as parallel test/staging
VMs) and is where the project's own still-open scale-gate concerns become directly visible:

- **~97.8 GB of accumulated stale pre-restore snapshots** — three full `.db` backup snapshots
  (32.36 GB, 32.28 GB, 32.06 GB) created within a ~36-hour window, none flagged for cleanup by the
  app's own crash-leftover detector (they don't look orphaned/crashed — they look like intentional
  but unmanaged accumulation from frequent restores/merges). Combined with the live 33.84 GB
  database and a 19.38 GB Ollama model store, total footprint is **~151 GB against 172 GB free at
  export time** — more than half the total footprint is these stale snapshots, and unmanaged this
  could approach disk exhaustion within days if the restore cadence continues. **Highest-priority
  single fix on this instance.**
- **Cold-boot unlock time is growing with corpus scale**: two measurements on this instance show
  17.7s → 29.7s across two boots — both far above the P0 `<2000ms` bar and far above the 540.8ms
  the 2026-07-18/20/21 P0-validation run measured on a smaller (474,556-article/22.2GB) snapshot
  of this same corpus. This is the closest real signal in the whole dataset to the still-open
  "K1: warm unlock at 100GB+" project gate, and it's trending the wrong direction.
- **Severe keyword-counter drift, unverifiable at this scale**: `corpus-integrity.json` counts
  only 120,965 genuine orphan keywords, but `keyword-engine.json` reports 6,472,070 keywords
  (93.6% of the whole 6.9M-keyword table) showing a maintained `mention_count` counter of exactly
  zero — a ~6.35M-keyword gap between the counter and reality. The app's own drift-sampling check
  couldn't even complete (`counter_drift_error: "interrupted"`) — the true extent is currently
  unverifiable in-app at this scale.
- **Two diagnostic members categorically cannot complete within their 300s deadline at this
  scale**: `keyword-log-digest.json` and `source-audit.json` both hit `outcome: "skipped-deadline"`
  on 6.9M keywords / 76,679 sources. The fixed 300s budget doesn't scale with corpus size; these
  may need a background-job form (mirroring the existing `all-job` pattern) rather than a
  synchronous GET.

## Actionable recommendations, prioritized

1. **Investigate WAL-checkpoint starvation as a root-cause fix, not a per-symptom patch**
   (Finding 1). Confirmed on all 7 instances at every hardware tier and every corpus size.
   Plausible mechanism: a long-lived reader (the diagnostics export's own heavy scans, or a
   concurrently-rebuilding in-memory rollup) blocks periodic truncation. Fixing this may reduce
   or eliminate several of the other symptoms below as a side effect.
2. **Optimize `/api/database/countries` (and its polling-sibling group) the same way
   `top_terms_grouped`/`supergroups`/`who_aggregate` were already fixed** (Finding 2) — a
   maintained counter or a refreshed rollup instead of a live per-request aggregation. This is
   the sole cause of the KPI board's only consistently-red metric across every instance measured.
3. **Fix the schema/migration-stamp drift + missing `sources.last_crawled_at` index** on the
   newer-schema instances (Finding 6) — an `alembic upgrade head` self-heal gap with a concrete,
   actively-relevant consequence (the enabled crawl-by-default feature).
4. **Filter the `trafilatura.metadata` logger noise** the same way `htmldate.meta` was already
   fixed (Finding 8) — a mechanical, low-risk fix with the exact precedent already in the
   codebase.
5. **Clean up (or add automatic cleanup for) stale pre-restore snapshots on the main instance**
   (Finding 9) — the single most urgent disk-safety item found in this whole batch.
6. **Reconcile the power-profile diagnostic's reported `collect_parallelism` against the live
   scheduler setting** (Finding 7) — small, but undermines trust in a diagnostic whose whole job
   is to report ground truth.
7. **Re-run the two AI-job bugs' investigation once a working local model is reachable on more
   than one instance** — this batch could not confirm or refute either bug directly; only one
   instance had any live data, and it surfaced the different, arguably more urgent finding that
   Mistral-7B (the ruled default model) may not clear the perception-extraction quality bar at
   all (94.7% hallucination on "who"). Worth flagging to the maintainer alongside the job-bug fix
   work.
8. **Consider whether the 300s-per-member diagnostics deadline should scale with corpus size**
   (Finding 9) — two members already can't complete at ~700k articles / 6.9M keywords.
