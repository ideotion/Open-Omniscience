# Amendment brief — the Convergence exploration surface at real scale (2026-07-18)

**This AMENDS `AUTONOMOUS_SESSION_BRIEF_2026-07-18_LEADS_CALIBRATION.md` — the same
executing session delivers both** (it already owns `convergence.py` via that brief's
S4.2, and the place-canonicalization primitive must be built ONCE and shared between
the producer and this exploration surface). All of that brief's gates and honesty
rules apply.

**The trigger:** the maintainer exported Insights → Convergence (default 7-day window)
on the live ~500k corpus. The exploration surface fails the same ways the producer did
— plus two defects of its own, one of which drew an explicit ruling:

**RULING (maintainer, 2026-07-18): REAL, RELIABLE DATA — never capped figures.** A cap
may bound which EXAMPLES are listed; it must never bound a displayed NUMBER. This
extends the standing anti-capping doctrine from computation to display.

---

## §0 The field evidence (acceptance cases)

| # | Observed | Defect | Post-fix expectation |
|---|---|---|---|
| 1 | **"⚠ 50 shared-origin links" on EVERY cluster** | `_shared_origin` (`convergence.py:335`) runs `.limit(50)` then returns `len(rows)` — the display cap IS the reported count | the EXACT count (an aggregate over the HAVING-filtered subquery, no limit); the limit stays only on the example fetch. No displayed figure anywhere on this surface may be a cap |
| 2 | "United States", "America", "Usa" = three separate cluster families; "Uk (gb)" casing | surface-string place identity | country-level aliases merge under the canonical country code (the S4.2 primitive, SHARED with the producer); display via the localized region name; city-level (Washington, New York) stays distinct — real signal |
| 3 | Iran ×3 (06-25→07-02 · 07-03→10 · 07-11→18), Washington ×2, New York ×2, France ×2, China ×2… | sliding-window fragmentation: a continuous story = one cluster per window step | ONE span entry per canonical place — contiguous/overlapping windows collapsed ("Iran: continuous 06-25→07-18, peak 07-11→18, 2,184 articles"), the window steps inside it, not siblings beside it |
| 4 | 1,344 articles · 395 sources for Washington-in-a-week; **8,448 clusters** total | scale-blind: hub-place saturation is the base rate | full-recall EXPLORATION preserved (nothing gated out — the ruled FP/FN discipline) but ORDERED by deviation from each place's own baseline share and GROUPED by place-span; the surprising thing on top, the hub base rate below |
| 5 | source sample = alphabetical prefix ("01Net, 14ymedio, ABC News…"), names truncated mid-word | uninformative at 395 sources | show the source-COUNTRY spread (the independence dimension that matters) and/or top contributors; truncate on word boundaries |
| 6 | windows extending past today (→ 07-20, → 07-21) | legitimate deduced future mentions, but reads as an error | a small label on future-extending spans: "includes future-dated mentions" (the deduced-never-confirmed caveat already covers the semantics) |

## §1 Anchors (verified at `fbcc307`; re-verify)

- `src/analytics/convergence.py` — `find_convergences:184`, `_shared_origin:335` (the
  `.limit(50)` + `len(rows)` bug), the per-cluster
  `shared_origin_links`/`shared_origin_examples` fields `:105–122`.
- `src/api/insights.py:1445 /convergences`; frontend `src/static/app.js:9497
  loadConvergences` (the Insights Convergence subtab, `cat === "convergence"`).
- The shared primitives from the parent brief: place canonicalization by country code
  (S4.2 — build once, both consumers), the baseline-share machinery.
- The space_time_convergence PRODUCER cards inherit every shared fix automatically —
  verify the card payloads after (the parent brief's rows 8–9 already pin them).

## §2 The slices (appended to the parent brief's plan)

### C1 — Exact shared-origin counts (the ruling; smallest, do first)
Split `_shared_origin`: the COUNT is `SELECT count(*)` over the grouped-HAVING
subquery (no limit — exact at any scale); the EXAMPLES keep a small fetch limit
(top-N by citing-article count). Sweep the surface for any other figure that is
secretly a cap (the scan-pool bounds are DIFFERENT — genuine computation bounds
stated in the method line; they stay, disclosed. A displayed per-cluster figure must
be exact). Test: a fixture cluster with 60 shared origins reports 60, examples ≤ 3.
Perf note: the count subquery is by indexed article_id sets — measure on the fixture,
not assumed.

### C2 — Place canonicalization (shared with S4.2, not duplicated)
Country-level surface strings (United States / America / Usa / Uk…) resolve to the
country code for cluster identity; display through the localized region-name path.
City-level places keep their own identity under their country. The SAME function
serves `find_convergences` and the producer.

### C3 — Span-collapse per place
Overlapping/contiguous windows of the same canonical place merge into one SPAN entry
carrying: full extent, peak window, article/source totals per step, and the exact-set
drill (clicking assembles the span's article set; a step drills to the step). §0 row
3 is the acceptance: Iran appears ONCE.

### C4 — Baseline-relative ordering (reorder, never gate)
Exploration stays full-recall: every place-span remains in the list and reachable.
Ordering: deviation of the span's source-share from that place's own baseline share
(the parent brief's baseline machinery), so a suddenly-converged-upon place outranks
a hub country at its normal saturation. The method line states the ordering basis.
Pagination stays; "Showing N of M place-spans" with M now meaningful.

### C5 — Display honesty polish
Source-country spread (counts per producing country — the independence dimension)
replaces/augments the alphabetical prefix; word-boundary truncation; the
future-dated-mentions label (§0 row 6); canonical place names localized.

## §3 Verification additions

- C1's exactness test + the "no displayed figure is a cap" sweep recorded in the PR.
- C2/C3: fixture where United States + America + Usa collapse to one span family and
  Iran's three windows collapse to one span with three steps.
- C4: negative-space — a hub place at its normal share must NOT outrank a small place
  at 5× its baseline; and nothing disappears from the list (full recall pinned).
- The producer cards re-verified after the shared changes (the parent brief's rows).
- Frontend conservative + flagged per fork-3/Q6a; the maintainer's re-export is the
  field acceptance: Iran once; no US triplets; real shared-origin numbers that vary
  by cluster; the surprising place on top.
