# Autonomous session brief — the source selection engine (qualification + quality audit)

**Status:** PENDING execution · one CLI session · draft-PR-only
**Evidence:** two real `source-quality` exports from the maintainer's merged 8-instance corpus,
2026-08-03 (`oo-source-quality-2`, 457 and 473 sources with articles, 34,263 / 35,345 articles).
**Companion brief:** `AUTONOMOUS_SESSION_BRIEF_2026-08-03_MERGE_TABLES.md` (disjoint file scope —
this one touches `src/analytics/`, `src/catalog/`; that one touches `src/backup/merge.py`).

After this ships the maintainer RUNS it on the live corpus and sends the logs back, so every
change must be visible in the exported report — a fix nobody can see in the next export is not
finished.

---

## 0. The headline, measured

**The qualification gate cannot currently disqualify any source in this corpus. Not one of 457.**

`derive_status` only ever reaches `degraded`/`failing` — the two states
`qualification.evaluate_and_stamp` acts on — through the ONE `extraction_failure` criterion
(`pathology_rate`); every soft criterion is capped at `watch` by design, correctly.
`pathology_rate` fires when `pathology_furniture_repetition` is true, and across BOTH exports:

| | sq1 | sq2 |
|---|---|---|
| pathological articles, whole corpus | **24** / 34,263 | **26** / 35,345 |
| sources with any | 9 | 10 |
| worst source's rate (`bisnow.com`) | **0.195** | **0.211** |
| `PATHOLOGY_ABS_FLOOR` (`source_audit.py:48`) | **0.5** | 0.5 |

The strongest real signal in the corpus is **less than half the floor**, and the cohort-tail path
additionally requires `_MIN_PATHOLOGY_ARTICLES` raw articles. So the admission gate passes
everything — not because the sources are all good, but because its one decisive criterion is
calibrated above the observable range.

This is the thing to fix. Everything below is either an input to it or noise around it.

---

## 1. Findings, each re-derived from the exports

### F1 — "14,353 flagged articles" (41.9%) is arithmetic, not a measurement

`flag_criteria`/the Layer-B outlier pass flags an article when any of 4 ratios sits outside its
cohort's p10/p90. Eight buckets (4 metrics × 2 tails), each firing on ~10% of the corpus **by the
definition of a percentile**:

```
type_token          low  3387      mention_density     high 3372
single_kw_dominance high 3383      vocab_sparsity      high 3368
vocab_sparsity      low  3374      single_kw_dominance low  3326
mention_density     low  3373      type_token          high 3316
```

Every bucket lands within 2% of every other. And the flagged rate is **~42% in every language**,
from `hu` (n=270, 41.5%) to `en` (n=21,343, 42.4%) — range 37.6–44.4% across 15 cohorts spanning
two orders of magnitude in n. A real quality signal varies with the data. This one cannot: it is
a restatement of "10% of things are in the top decile."

The number is not wrong, it is **empty** — and the report headlines it as `flagged_articles`,
which reads as a finding. The genuinely diagnostic quantity, the *conjunction*
(`pathology_furniture_repetition`), is 24 — and is buried inside the 14,353.

**Fix:** headline the conjunction; demote the tails to what they honestly are — a *sampling frame*
for the human review sample, never a verdict. Rename the manifest key so no reader can mistake
one for the other (`flagged_articles` → `outlier_sampling_frame`, plus a new
`pathological_articles`). Keep the tails computed — they are the sampling frame and they work as
one; only their presentation and name change.

### F2 — the furniture detector cannot fire, and lowering the cut is the WRONG fix

`furniture_ubiquity_cut = max(5, round(0.30 × n_sources))` = **137** (sq1) / **142** (sq2), against
a maximum observed `cross_source_df` of **71** / **80** over 5,484 / 5,676 fingerprint entries.
`furniture_flagged_sources: 0` in both runs. `source_fingerprint` therefore contributed **zero**
articles to the review sample; the selector exists and has never once selected.

**Do not simply lower the cut.** Here is the actual top of the DF distribution (sq1):

```
71 world   64 data    54 public   48 state   44 government  39 media
38 company 31 president 31 research 30 down   28 trump      26 global
26 security 25 read   25 added    25 national 22 home       22 team
```

At a cut of 20–25 the "furniture" set becomes *world, data, public, state, government, media,
company, president, research* — real topical vocabulary. That is precisely the recorded
**"OPEN-CLASS keyword garbage has NO safe blanket rule"** lesson (CLAUDE.md, 2026-07-01 #530):
DF-ubiquity cannot separate publishing furniture from generic content words, because both are
ubiquitous. A lower cut would manufacture a furniture verdict over ordinary journalism.

Note also that `read`, `home`, `added`, `down`, `access`, `post`, `every`, `best`, `find`, `set`
are in the top-DF band **and none of them is in `global_stopwords()`** (verified). So part of what
the detector sees is upstream stoplist leakage, not source pathology.

**Fix (pick one, in the PR body say which and why):**
- **(a) Retire the cross-source-DF detector** as unable to discriminate at this corpus shape, and
  say so in the manifest (`furniture_detection: "not discriminating at this corpus shape"` with
  the observed max DF vs the cut). Honest, one commit, no fabricated signal.
- **(b) Make it require corroboration** — furniture = high DF **AND** the term is in the existing
  `PUBLISHING_BOILERPLATE_SCOPED` / `PLATFORM_STOPWORDS` channel (`src/services/stopwords.py`).
  Closed-class by construction, so `world`/`government` can never enter.

(a) is recommended if (b) turns out to flag nothing either — which it may, and that would itself
be the honest answer. **Never** ship a cut that puts `government` in the furniture set.

### F3 — the expensive selector is barely better than chance

Measured against the unbiased `random_per_source` control that ships in the same export:

| selector | n sampled | with a pre-label | rate |
|---|---|---|---|
| `keyword_outlier` | 3,276 | 562 | **17.2%** |
| `random_per_source` (control) | 457 | 48 | **10.5%** |

**1.64× enrichment for 90% of the human review budget.** And the pre-labels doing the
discriminating — `high_link_density` (415 of 675 label hits), `very_short` (138),
`boilerplate_phrase` (122) — are computed in `_pre_label` (`source_quality.py:355`) from
`external_link_count / word_count` and `word_count` alone: **metadata only, no decrypt, no keyword
join.** They are nearly free and they outperform the machinery that costs the most.

**Fix:** promote the pre-label signals to first-class selectors. Add a `cheap_signal` selector that
picks articles by `high_link_density` / `very_short` / `boilerplate_phrase` directly, and report
each selector's own enrichment-over-control in the manifest so the next export *measures its own
selectors* instead of assuming them. Keep `keyword_outlier` (it is the sampling frame for the
ratios and it does beat chance) — this adds a selector, it does not remove one.

### F4 — synthetic internal provenance classes are audited as if they were news sources

The 100%-outlier-rate cohort is led by the app's **own** synthetic sources:

```
194 arts  hazard.usgs.local   type_token     (a hazard "article" is "M 5.0 - Kermadec Islands
  5 arts  law.uk.local        type_token      region", word_count None, language unknown)
  2 arts  law.de.local        type_token
  1 arts  law.us.local        type_token
  1 arts  law.ca.local        type_token
```

`source_quality.py` has **no provenance-class exemption and no quarantine filter** (verified by
grep: zero `quarantined` references, zero `source_type` gating in the collectors). So 194
non-prose synthetic records sit inside the `unknown` language cohort (n=3,698) shaping everyone
else's p10/p90 baseline, and the hazard/law classes are reported as pathological-looking sources.

This is the same shape as the recorded Leads-calibration finding (the `.eml` import flagged
"capacity implausible") whose S1 slice already ruled provenance exemptions — the source auditor
never got them.

Checked and **not** a live danger: those sources have **zero** `pathology_furniture_repetition`
articles, so nothing would auto-demote them today. The cost is cohort distortion and a misleading
report, not a wrong verdict. Fix it anyway, and say in the PR that the verdict was never at risk —
do not overstate it.

**Fix:** exempt non-web provenance classes (`hazard`, `law`, `wiki`, newsletter — reuse
`PROVENANCE_CLASSES` / `provenance_of` from `src/catalog/provenance.py`, never a new list) from
the ratio cohorts, count them separately in the manifest, and apply
`Article.quarantined.isnot(True)` to every collector (the standing quarantine remainder).

### F5 — the report's own config should carry its observed range

Every threshold in `config` is printed without the distribution it was meant to cut. A reader
cannot tell that `furniture_ubiquity_cut: 137` is unreachable without recomputing it from a 5,484-line
file. Add an `observed` block beside `config`: max/p90/p99 `cross_source_df`, max `pathology_rate`,
the per-selector enrichment. **A threshold that no observation can reach should say so in the
artifact that reports it** — that is what turns the next export into a measurement instead of a
re-run.

---

## 2. The work, ordered

Each slice its own commit; the whole set may be one PR. `⚠` = mandatory adversarial skeptic pass
with the negative-space lens before push.

1. **F1 naming + the conjunction headline.** Report `pathological_articles` as the finding;
   rename the tail count to a sampling-frame name; add the `observed` block (F5). No maths change.
2. **⚠ F4 provenance exemption + quarantine filter** in the `source_quality` collectors and
   `source_audit.per_source_metrics`. Negative space: a *legitimately* terse real news source must
   still be audited — the exemption is by provenance class, never by "looks unusual".
3. **⚠ F2 furniture decision.** (a) or (b), with the evidence in the PR body. Negative space: a
   test that `government`/`world`/`data` can never be classified furniture at any cut the code can
   produce.
4. **⚠ F3 `cheap_signal` selector + per-selector enrichment-over-control in the manifest.**
   Negative space: the control selector must stay genuinely unbiased (same seed, no filtering) or
   the enrichment figure is meaningless.
5. **⚠ The calibration question — `PATHOLOGY_ABS_FLOOR`.** This one is a **maintainer decision, not
   a session decision.** Do NOT quietly lower 0.5 to 0.2 to make the gate fire; that would tune a
   data-safety threshold to make a number move, which is the inverse of the recorded
   WAL-recalibration lesson ("raising the input a guard is fed strengthens a reproduction;
   lowering the bar it must clear weakens it"). Instead:
   - Compute and report the **full observed `pathology_rate` distribution per source** in the
     export (currently absent — only the boolean per article is emitted).
   - State plainly in the manifest that no source in this corpus can reach the floor.
   - Put the options to the maintainer in the PR body: keep 0.5 and accept that this criterion is
     a rare-catastrophe detector; or lower it *with* a stated new meaning; or add a second,
     differently-shaped extraction-failure criterion (F3's `high_link_density` is the obvious
     candidate — it is the strongest measured discriminator in the whole corpus and it is
     currently only a review hint, never a criterion).
   Ship the measurement, not the new threshold.

**Explicitly out of scope:** the retroactive quarantine execution (still gated on the maintainer's
review of the calibration report); the stoplist additions F2 hints at (`read`/`home`/`added` are
open-class — that is the propose→human-review→apply loop, a different session); any change to
`derive_status`'s soft-criteria cap (it is correct and load-bearing).

## 3. Gates

`ruff check --select=F,B --extend-ignore=B008` · `python3 -m mypy <changed>` (ratchet ≤127) ·
`bandit==1.9.4 -r src -ll -q` · full `pytest -q` · `scripts/i18n_report.py --min 100` if any UI
string moves. Baseline-diff the suite against clean `main` and **check the pass-count delta**, not
only the failure-name diff (recorded lesson: a name-diff is empty when the head side never ran).
