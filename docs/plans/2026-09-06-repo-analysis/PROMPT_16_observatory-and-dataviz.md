# Prompt 16 — The Observatory, and the data-visualisation vocabulary

> **Scope:** a new `ooSky` renderer, the Observatory tab, the unwired `ooViz` primitives.
> **Gated on:** H1 ⛔ — the Observatory is a flagship surface and cannot be shipped conservative-and-flagged.
> **Sequencing:** after prompt 15's S8 settles the verification bar, and after the super-group statistics
> core it consumes.

## 0. Working mode

Read `_WORKING_MODE.md` and then `docs/design/OBSERVATORY_DESIGN.md` in full — it is a complete design, and
this prompt is an implementation, not a redesign. Also read `docs/research/dataviz/` (the committed chart
decision framework: the perceptual ranking, the honesty gate and the reject list) and
`docs/plans/2026-08-04-gui-visualization-plan.md`.

The 2026-07-13 ruling Q5a deprioritised the 3D explorer; the 2026-07-18 Observatory ruling **supersedes** it
under its own resolution — hand-rolled canvas 2.5D, **no WebGL and no Three.js**.

## 1. What exists

The backend slices S0 and S1 are shipped (`src/analytics/observatory.py` and its endpoint). There is no
frontend. The design's own prerequisites are the super-group statistics core (prompt 17's S1) and the sky
quality that the keyword cleanups (prompt 05) produce — an Observatory drawn over unfiltered caps furniture
would be a beautiful picture of the junk.

## 2. The design's load-bearing constraints, restated because they are what make it honest

- **One self-similar polar grammar.** Angle encodes category (a domain wedge at the universe tier, a tag arm
  at the galaxy tier, with within-sector jitter from a stable hash and disclosed as meaningless). Radius
  encodes **one** measure — article spread by default, because breadth resists single-source flooding — on a
  log scale with **labelled** orbit gridlines. Never an "importance" blend.
- Size is mentions (sqrt, with a reference-star legend). Colour is language by default; temperature as a
  *chosen* lens shows windowed trend, where red is a **measured** decline with its method stated and
  old-but-steady stays white — cross-time recall is sacred.
- Association is a **drawn** constellation edge (PMI, with n shown), never proximity.
- Novae are trending spikes under the `supergroup_rising` gates (count floors and FDR), never a bare spike.
- The nebula is the un-curated long tail as a **disclosed aggregate density** — "N stars shown · M in the
  nebula" is the anti-capping answer, and it is what lets the render stay bounded without hiding anything.
- Arms carry the Item-AC topic tags with cardinality guarded **by construction**: top-K ≤ 6 by member count
  plus a labelled "untagged/other (N)" disc.
- Depth is **navigational only**, with screen-space marks — perspective must never distort magnitude.
- Static when idle: no animation loops. LOD rides the hierarchy (≈5k sprites plus the nebula).
- The sr-list and keyboard path are not an afterthought; the tabular views stay canonical.

One additive backend change: the design needs a `domain:` field in `configs/keyword_supergroups.yml` — today
the twelve domains live only in a comment.

## 3. The wider vocabulary (the standing maintainer wish)

"Too little data-visualisation creativity" is a recorded standing wish, and the framework plus the primitives
already exist for it. Eleven `ooViz` primitives have zero call sites — `binCounts1D`, `bin2D`,
`fiveNumberSummary`, `sqrtAreaScale`/`symbolRadii`, `pathWithGaps` and others. The maths is written, the
honesty semantics are encoded, the tests pass. What is missing is call sites.

Candidates measured and dispositioned in the 2026-08-04 plan, so this prompt starts from evidence rather than
taste:

- **Article-length histogram — build with caveats.** The data is exact and already binned and is surfaced
  nowhere. But it needs an explicit action rather than a tab-select autoload (its fetch is a full `articles`
  scan with no route guard); the corpus-wide summary silently pools zh/ja/th with Latin text, so the primary
  chart must be built from the `by_language` entries where `unsegmented` is false, stating the excluded n; the
  report applies no quarantine filter unlike every other analytics path; and the buckets are **unequal width**,
  so it is a categorical bar chart over labelled ranges, never a density histogram.
- **Qualification histogram — blocked, no data.** All four candidate distributions fail on their own terms;
  the one genuinely histogram-shaped distribution comes from an endpoint measured to time out at target scale.
- **Per-language small multiples — the highest-value candidate, gated on a feed.** The renderer ships. What is
  missing is data: every per-language `group_by` in the tree is a point-in-time snapshot, and `KeywordMention`
  has no language column. It matters because `language_equilibrium` is a live scheduler lever on a strongly
  non-Anglophone corpus and an operator tuning it has **no** feedback surface.
- **Corpus-delta slope chart — refused**, with three live-reproduced defects behind the refusal.
- **Waffle — refused** as decoration; the framework's own part-to-whole prescription is sorted bars or a
  single stacked bar, and `_ooShareBars` already exists.

## 4. Scope fence

No WebGL, no Three.js, no CDN. No composite score anywhere in the payload or the encoding. The Observatory is
a lens over the corpus and must never become a second source of truth. Ship nothing here as
"conservative + flagged" — H1 gates it precisely because it cannot be verified by reading.
