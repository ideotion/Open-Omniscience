# Quarantined articles leave the keyword figures (R101, `D22` / `PRH-06`)

**Status:** design, before any code. Ruled 2026-09-30 15:34 UTC («3=yes», recorded as `R101`).
Thread «Keyword working session». Nothing here is built yet.

## 1. What the ruling asks for

Quarantined articles (`Article.quarantined IS TRUE`, a REVERSIBLE stamp, never a delete) stop
counting in every keyword figure, **in one slice with one disclosure**: the keyword aggregates,
the per-language series and the equilibrium lever move together (`src/database/snapshots.py`
records that the language pair must move together and that the keyword aggregates are a third
member of that family), with the effect on `furniture_share` measured first.

## 2. Where quarantined articles are counted today (measured by reading, 2026-09-30)

| Surface | How it counts | Quarantine-aware today |
|---|---|---|
| `Keyword.mention_count` / `article_count` | incremental deltas at index time (`index_article`), reconciled by `reconcile_keyword_counters` (a covering-index GROUP BY over the mentions, sliced by keyword id) | no |
| `top_terms`, super-groups, most hot keyword endpoints | read those counters | no |
| the rollup (`keyword_daily`, `rollup_serve`) and the columnar store | per keyword per day | no (`store.py`, `rollup_serve.py`, `columnar.py`: 0 references) |
| `src/analytics/queries.py` | 11 references: the live queries that join to `articles` already filter with `Article.quarantined.isnot(True)` | partly |
| per-language series, `corpus_language_shares`, the equilibrium lever | over `articles` | no, deliberately, and «the two must move together» |
| `furniture_share` (feeds the qualification gate) | a denominator over the same articles | no |
| the signed evidence export (`src/api/reporting.py`) | not part of this ruling | no |

The three surfaces that do agree today (counters, rollup, columnar) all count quarantined
articles. **That agreement is the property to keep**: gating one alone would make the same
`top_terms` call answer differently depending on which path served it.

## 3. The design

**One definition of «counts».** A mention counts iff its article's `quarantined` is not true.
One helper, `src/analytics/counted.py` (new), owns the predicate as SQL and as Python; every
surface below imports it, and a test greps for a second spelling of `quarantined.isnot(True)`
in `src/analytics` outside it.

**The counters (the expensive part).** Two ways to keep them equal to that definition, and only
one is cheap at 100 M mentions:

* At the quarantine stamp and the un-stamp, apply per-keyword deltas from the article's own
  mentions (`-count` / `-1` on stamp, `+count` / `+1` on un-stamp), in the same transaction as
  the stamp. It is O(article), exactly the shape `index_article` already has, so the counters
  stay drift-proof for the same reason.
* **The reconcile sweep must use the same definition or it will undo the deltas.** It cannot
  join every mention to `articles` (that is the sweep the covering index exists to avoid).
  Instead: the existing covering-index GROUP BY (all mentions), MINUS a second GROUP BY over
  the mentions of the quarantined articles only (`ix_mention_article` on `article_id`; the
  quarantined set is small next to the corpus and is read from `idx_article_quarantined`).
  The subtraction is per slice, so the sweep stays bounded, resumable and deadline-friendly.

**The rollup and columnar store.** Their daily rows take the same deltas at the same points
(the (keyword, day) of each of the article's mentions). Their FULL build (a rebuild from
scratch) applies the same MINUS. A rollup whose build predates the change is marked stale by
the existing engine-identity bump (`src/analytics/engine_identity.py`), so it rebuilds under
the new definition instead of serving the old one.

**Served-cache invalidation.** `serve_gate.py` keys a cache on `max(KeywordMention.id)`. A
quarantine transition changes served answers without a new mention id, so the watermark must
also cover it (the largest `quarantined_at` and an un-quarantine counter, or an epoch bump on
each transition). Without this, a cached `top_terms` keeps counting an article the operator
just quarantined. This is decided together with `serve_gate`'s step-1 watermark question and is
the reason that file is left alone until then.

**The language pair and the lever.** `corpus_language_shares` and the per-language series take
the same predicate in the same change, so the lever and its graph still describe one corpus.

**Disclosure, one, everywhere.** Every keyword figure states «N quarantined articles are not
counted» (the number is one indexed count) through the existing honesty envelope, visible by
default (invariant on informed consent), keyed ×12. The quarantine review surface says what
un-quarantining changes.

## 4. Measure first (the ruling's own order)

Before the slice: a read-only diagnostics member (same style as `keyword_write_cost`) that
reports, on the operator's corpus, how many articles and mentions are quarantined, the
per-language share with and without them, and `furniture_share` with and without them, so the
change to the qualification gate's denominator is a stated number before it ships. If
`furniture_share` moves a source across a threshold, that is recorded, not silently absorbed.

## 5. Phases (one PR each, each behind its own Opus review)

1. The measuring member (read-only). Its numbers decide phase 3's disclosure wording.
2. `counted.py` and its grep-guard; the counters' deltas at stamp and un-stamp, and the reconcile
   MINUS, with the differential test «counter == the canonical GROUP BY over counted mentions,
   after ingest, quarantine, un-quarantine, re-index and reconcile».
3. Rollup and columnar (deltas + full build MINUS + engine-identity bump), the served-cache
   watermark, the language pair and the lever, the disclosure ×12.

## 6. What could still go wrong, stated

* A hundred-million-row reconcile with the MINUS is one more indexed range per slice; its
  measured cost goes in the phase-2 PR before it merges.
* Un-quarantining a large batch is a large delta transaction; it is chunked like the job.
* Signed evidence bundles keep carrying quarantined articles until the maintainer rules on
  `reporting.py` (recorded in `OPEN_QUEUE.md`; not this ruling).

## 7. Open questions for the maintainer

None that block phase 1. Phase 3 asks one: whether the disclosure line may read «N quarantined
articles are not counted» on every card, or only on cards whose figure changed by more than a
stated fraction. Recommended: every card (visible by default, per the informed-consent rule).
