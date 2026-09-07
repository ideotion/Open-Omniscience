# Prompt 08 — Import performance and the post-import conclusion screen

> **Scope:** the import queue, the merge's remaining cost, the results screen.
> **Gated on:** C2 (checkpoint interval K), C3 (prefetch).
> **Sequencing:** after prompt 07 if both are scheduled; never concurrent with it or prompt 09.

## 0. Working mode

Read `_WORKING_MODE.md`, then the CLAUDE.md entries **"IMPORT PIPELINING + THE PER-BACKUP CHECKPOINT"** and
**"MERGE STEP 3 IS STILL UNEXPLAINED"**, then
`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-29_IMPORT_PERFORMANCE.md`.

## 1. The measured picture

Verified, not assumed. FTS5 was the answer to the 2026-08 merge-step-3 mystery: 98% of merging beats carried
FTS5's internal segment-merge cleanup, and the fix relocated that work off the article step. What remains is
a **15–65× gap** between what the probes extrapolate (~20 minutes at field scale) and what the field
observed (5+ hours) that nothing here reproduces. Candidates: the SQLCipher codec over multi-GB FTS
segments; the operator's virtual disk; merges against ~794k already-indexed documents. `cost_probe` in
merge-diag measures per-row cost **on the operator's machine**, which is how that gap gets closed rather than
argued about.

Two costs are now the majority of what is left and both are deliberate non-changes to date:
`prepare_staged:validate` at ~1,839 s per backup, and `PRAGMA quick_check` + `foreign_key_check` running
whole-corpus per queue item (~17 + 7 minutes per item at 130 GB).

## 2. Slices

### S1 — C2: the checkpoint interval K

Verify + swap once per K backups instead of per backup saves seventeen verifies, snapshots and swaps on an
eighteen-item queue. The cost is durability: nothing is durable until a swap, so today a kill at item 12
keeps eleven merges and skips them on re-run, while at K=18 it loses twelve merges' CPU. The maintainer has
killed this import twice, so the trade is real and K is theirs. The recommended default is 3.

Build it so that K is a setting with a stated safe range, and so the queue's conclusion screen says how many
items are committed versus staged at any moment.

### S2 — C3: prefetch, with the three blockers respected

Reading the seam produced three findings that raise the estimate rather than lower it. Staging lives inside
`VolumeBackupManager._run_restore`, on the singleton manager's worker thread, and that singleton is
one-job-at-a-time **by design** — so a prefetch needs its own staging tree and a `start_restore(..., staged=)`
seam. `cleanup_staging` is in a `finally` owned by the merge thread, so a prefetched tree crosses an
ownership boundary the current code guarantees by construction, and on an encrypted corpus that tree is
**plaintext**, so an orphan is an at-rest hole rather than wasted bytes.

The third is decisive: `find_completed_import` runs **before** staging precisely so an already-merged
artifact costs one small JSON read, and the field log records **8 of 18 imports adding zero articles**. Any
prefetch must run the digest check first or it burns 47–56 minutes per skipped item and defeats an existing
optimisation.

### S3 — The post-import conclusion screen

> **⚠ STALE — CORRECTED 2026-09-07 against `main`@690920e. This slice was already BUILT, in all three
> parts, and the description below was wrong about the code.** The headline has not summed across every
> table since the 2026-07-20 root-cause fix: `_renderImportSummary` (`src/static/app-backup.js:1140`)
> headlines `plan.articles` alone, adds the ruling's labelled per-type breakdown, and keeps the cross-table
> row-sum ONLY behind the explicit label "database records, all types". The corpus delta is
> `merge._corpus_snapshot` (`src/backup/merge.py:4125`) taken before the swap and after it, over exactly the
> six named dimensions, rendered before → after → Δ by `_uxCorpusDeltaView` (`app-backup.js:1077`). The
> work-induced queue is the `queueBlock` at `app-backup.js:1400` plus the corpus-wide `work_induced` tally
> (`merge.py:5455`). What the 2026-09-07 session ADDED here is the checkpoint's own half: committed versus
> staged. Recorded VERIFIED-PRESENT rather than rebuilt, per the working mode's staleness guard.

The ruled redesign, still unbuilt in its delta form. Today the headline sums `new`/`duplicate`/`conflict`
across **every table** of the merge plan, so it mixes articles with keyword-mention, link, entity, date and
custody rows under the single unlabelled word "imported" — a row-sum reads as an article count, and mentions
dominate it by an order of magnitude.

Three parts:
1. **Headline in the user's unit:** articles imported and deduplicated first, then a labelled per-type
   breakdown. A cross-table row-sum may remain only if labelled "database records, all types".
2. **The corpus delta** — before → after per dimension (articles, sources, languages present, countries
   covered, date-range span, distinct keywords), computed by snapshotting the **maintained counters** before
   the merge and diffing after. Never a whole-table scan post-merge.
3. **Work induced** — newly-imported sources awaiting qualification, unindexed articles if indexing lags,
   discovery candidates added.

Framing is positive and every number real: "your corpus grew by X articles from Y new sources spanning Z new
languages" is both celebratory and checkable. Numbers through the shared formatter and `OOI18N.tf` ×12.

### S4 — The aggregated multi-backup conclusion

> **⚠ STALE — CORRECTED 2026-09-07 against `main`@690920e. Already BUILT.** A queue does not produce
> eighteen conclusions: `_uxImQueuePoll` (`src/static/app-backup.js:751`) builds ONE `summaries` list across
> every item and calls `_renderImportSummary` once, which aggregates the run and renders `_uxPerItemView`
> (`app-backup.js:1034`) as per-item rows beneath — with each item's own outcome, article split, elapsed
> time and a bar scaled to the largest item in the run. Items that failed, were cancelled or were skipped
> are excluded from the aggregate by `_uxOutcome().ok` and listed with their outcome. Recorded
> VERIFIED-PRESENT.

Item 3 of the 2026-08-06 asks, never built: a queue of eighteen backups currently produces eighteen
conclusions and no total. Aggregate across the run, with per-item rows beneath.

### S5 — The two deliberate non-changes, re-examined with numbers

`prepare_staged:validate` and the two whole-corpus PRAGMA checks were left alone with reasons. The reasons
were about risk, not about cost, and the cost has since become the majority. Do not change them in this
prompt — **measure** them on a realistic corpus and write the numbers into the design doc, so the next
decision is made on evidence. The structural end-state named in the notes (one working copy per queue run,
or an in-place merge inside one transaction with in-transaction verification) is a full-skeptic-matrix slice
of its own.

## 3. Scope fence

No change to what the merge writes. No change to the additive-restore guarantee. Do not claim a speedup you
did not measure — the field scale is 35× the probe and the honest verdict on an unmeasured improvement is
that it is unmeasured.
