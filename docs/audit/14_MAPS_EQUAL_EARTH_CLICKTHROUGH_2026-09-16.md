# Maps click-through — Equal Earth and the contested borders · 2026-09-16 (S04-11, `RELEASE_0.4_GATE` row R)

**Status: EXECUTED in the sandbox (Q1128 = a: Chromium here + the maintainer's own pass).**
36 observations — 5 surfaces + the worldview toggle × 2 widths (1440×900, 390×844) × 3 locales
(en, fr, ar).

Following the 2026-08-13 / 2026-08-20 / 2026-09-16 precedent, the full screenshot set is NOT
committed; the three images this report's findings actually cite are, under
[`maps-equal-earth-2026-09-16/`](maps-equal-earth-2026-09-16/). Everything else below is a
measurement reproduced in the text.

## 1. The false positive this run started as, and why it is worth recording

The first pass reported **every** surface rendering a map, including two that draw nothing. The
cause is that `ooMap` writes `<svg id="oo-choro">` into *every* host it is given, so several
surfaces carry the same element id at once and a global `document.querySelector('#oo-choro')`
returns the **World map's** svg from a hidden tab whatever surface you are looking at. Tabs are
hidden, not destroyed, so the stale element is always there after the first map renders.

Every query in the final run is scoped to the surface's own host element
(`#gov-map-host #oo-choro`, and so on). **Nothing was wrong with the app** — the instrument was
answering a question about the World map and labelling it with another surface's name, which is
the recorded "a guard that passes for a reason that has nothing to do with its claim" shape.

*(The duplicate `id` across simultaneously-rendered ooMap surfaces is pre-existing and was not
introduced or changed by S04-11. It is invalid HTML and it is what made the mis-measurement
possible; not fixed here because `id="oo-choro"` is read by existing code and tests.)*

## 2. What rendered

| Surface | host | 1440×900 | 390×844 |
|---|---|---|---|
| World map tab (`_renderOoMapDim`) | `oo-coverage-map` | **map**, en/fr/ar | **map**, en/fr/ar |
| Sources coverage (`renderCoverageMap`) | `coverage-map` | **map**, en/fr/ar | **map**, en/fr/ar |
| Governments → Map (`renderGovMap`) | `gov-map-host` | honest empty state | honest empty state |
| Governments → Statistics (`renderStatMap`) | `statfig-map` | not reached | not reached |
| Insights → Supergroups (`showRingMap`) | `sg-ringmap` | not reached | not reached |

Where a map rendered, it measured **identically in all six combinations**:

```
viewBox            0 0 720 350.44      (the projection's own aspect, not a chosen box)
rendered aspect    2.0547              (EE_X_MAX / EE_Y_MAX = 2.0545821300028537)
country paths      229                 (Natural Earth 50m; the 110m set had 175)
contested areas    28
meridians          13 polylines        (curved — a straight <line> would be a fabricated shape)
sphere outline     present             (the world is a lens; the box corners are not map)
legend             "Equal Earth · equal-area"
contested caveat   visible             (never behind a toggle)
worldview picker   on screen, 34 options
horizontal overflow  none, at either width
page errors        none
```

**The two surfaces that draw nothing are drawing the right thing.** The Governments map needs
per-country indicator data that only a networked collect produces, and it says so in the
reader's language — `"Country data loads automatically in the background when online — the map
fills in once it lands."`, and correctly in fr (`"Les données par pays se chargent
automatiquement en arrière-plan…"`) and ar (`"تُحمَّل بيانات الدول تلقائيًا في الخلفية عند الاتصال…"`).
Statistics and the Supergroups ring map need data this synthetic corpus does not contain.

**That all five share one seam is proven at source level, not by driving each**: there is one
`ooMap`, every coordinate in it goes through `project()`, and
`tests/test_map_projection.py::test_no_residual_plate_carree_arithmetic_survives_anywhere`
asserts no module carries projection arithmetic of its own — by name *and* by arithmetic
pattern, so a second projection under a different name reddens.

## 3. The worldview toggle, exercised

Driven with a real `select_option` on `[data-oomap-worldview]`, in all six combinations:

```
contested → in :  attributed 0 → 27,  contested areas still drawn = 28
en  "Contested: 28 · every claim shown, none assigned"
 →  "Contested: 28 · attributed under India"
fr  "Contestées: 28 · toutes les revendications affichées, aucune attribuée"
 →  "Contestées: 28 · attribuées selon Inde"
ar  "متنازع عليها: 28 · كل المطالبات معروضة، ولا واحدة منسوبة"
 →  "متنازع عليها: 28 · منسوبة وفق الهند"
```

**The second number is the one that matters.** Switching worldview re-attributes the disputes
(0 → 27 areas gain a country) and still draws **all 28** of them hatched. A worldview can change
what an area is attributed to; it can never hide that the area is disputed. 27 rather than 28
because one area has no attribution under India's view — correct, and it keeps its hatch and its
claim list.

## 4. Finding: the in-map control clusters cover the map at phone width

Measured on the World map in both states, isolating a single element:

| | 1440×900 | 390×844 |
|---|---|---|
| map area covered by control groups, **without** the worldview picker | 4.3 % | **79.4 %** |
| …**with** it | 7.6 % | **111.7 %** |
| attributable to the picker | +3.3 pp | **+32.3 pp** |

(Over 100 % because the three groups overlap one another.) The second state is produced by
removing **only** `.oomap-worldview` from the live page, so nothing else differs; a git-stash
baseline would also have reverted the 50m geometry and the contested layer and could not have
attributed anything to one control.

**The dominant fact is the pre-existing one**: at 390px the map is already almost entirely hidden
behind its own controls before anything is added. S04-11 reduced its own share where it could —
below 600px the picker's visible label is CLIPPED (the `.sr-only` clip, **never**
`display:none`; the select keeps its own `aria-label`, verified 1×1px with
`display: block`), taking that row from 211px to 150px — but the select still forces one extra
wrap row, which is where the +32.3 pp lives.

Making the in-map controls usable at phone width is a change to the "controls inside the map"
convention across every group and every ooMap surface, not a map slice. Recorded in
`OPEN_QUEUE.md` with three candidate shapes and none chosen.

## 5. How to reproduce

```
OO_DATA_DIR=<tmp> OO_DB_PLAINTEXT=1 OO_NO_SCHEDULER=1 .venv/bin/python scripts/ui_clickthrough_seed.py
OO_DATA_DIR=<tmp> OO_DB_PLAINTEXT=1 OO_NO_SCHEDULER=1 .venv/bin/uvicorn src.api.main:app --port 8011
```
then drive the five hosts above, scoping every query to the host. No network is touched by any of
it: `world_countries.json` and `world_disputed.json` are bundled and served from loopback.
