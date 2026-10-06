# Row I closing sweep, 2026-10-06 (CSP, every drop-down, three widths, every theme)

Gate row I, brief `S05-09`. Written by `scripts/csp_sweep.py` (the sweep) and `scripts/pf10_look.py` (the 390 px map look), run in Chromium against a booted app. Reading rule R126 (2026-10-06): this walk is what closes the UX pass; the maintainer's own click-through is optional.

## What was done

At each of 1440×900, 768×1024 and 390×844, in each of the **15** theme settings the picker offers (the 14 named themes and `system`), the sweep visited every sidebar tab and every subtab, opened every foldout, and for each visible `<select>` picked an option other than the current one, waited 400 ms and judged it (`held`: the select still shows the pick; `effect`: `ui`, `net`, `dom` or `none`), then restored the original value. The console (errors and warnings) and every `securitypolicyviolation` event were kept **per width and theme** in `docs/audit/row-i-csp-sweep-2026-10-06/console-<width>-<theme>.txt` beside the per-select results (`selects-<width>-<theme>.json`). 45 runs.

The app was booted through the console entry (`from src.api.main import main`) on a seeded state with `OO_DB_PLAINTEXT=1`, `OO_NO_SCHEDULER=1` (airplane mode, no egress). Nothing was fetched from the internet.

## Result

* **CSP violations: 0 of 45 runs had any** (`securitypolicyviolation` events and console lines naming the policy: none). `script-src 'self'` holds across all three widths and all 15 themes.
* **Picks that held: 4691**; picks that read back reverted: 12 (all one control, `ai-backend-select`, a real defect, fixed in this PR, below).
* Picks judged `none` (nothing observable happened; some selects are only read by a later button, which is not a dead binding): 512.
* `ERROR` rows: 1851, of which 1850 are the root Settings pass and 1 is a transient in one run (below).

| width | theme | held | reverted | error | csp | console lines |
|---|---|---:|---:|---:|---:|---:|
| 1440x900 | ink | 55 | 0 | 0 | 0 | 10 |
| 1440x900 | midnight | 118 | 0 | 50 | 0 | 0 |
| 1440x900 | cyber | 118 | 0 | 50 | 0 | 0 |
| 1440x900 | forest | 117 | 1 | 50 | 0 | 0 |
| 1440x900 | aubergine | 117 | 1 | 50 | 0 | 0 |
| 1440x900 | garnet | 118 | 0 | 50 | 0 | 0 |
| 1440x900 | solar | 117 | 1 | 50 | 0 | 0 |
| 1440x900 | sepia | 117 | 1 | 50 | 0 | 0 |
| 1440x900 | terminal | 117 | 1 | 50 | 0 | 0 |
| 1440x900 | contrast | 117 | 1 | 50 | 0 | 0 |
| 1440x900 | light | 58 | 0 | 0 | 0 | 8 |
| 1440x900 | dawn | 118 | 0 | 50 | 0 | 0 |
| 1440x900 | mint | 118 | 0 | 50 | 0 | 0 |
| 1440x900 | paper | 56 | 0 | 0 | 0 | 8 |
| 1440x900 | system | 117 | 1 | 50 | 0 | 0 |
| 768x1024 | ink | 54 | 0 | 0 | 0 | 10 |
| 768x1024 | midnight | 118 | 0 | 50 | 0 | 0 |
| 768x1024 | cyber | 118 | 0 | 50 | 0 | 0 |
| 768x1024 | forest | 117 | 0 | 51 | 0 | 0 |
| 768x1024 | aubergine | 117 | 1 | 50 | 0 | 0 |
| 768x1024 | garnet | 118 | 0 | 50 | 0 | 0 |
| 768x1024 | solar | 117 | 1 | 50 | 0 | 0 |
| 768x1024 | sepia | 118 | 0 | 50 | 0 | 0 |
| 768x1024 | terminal | 118 | 0 | 50 | 0 | 0 |
| 768x1024 | contrast | 118 | 0 | 50 | 0 | 0 |
| 768x1024 | light | 57 | 0 | 0 | 0 | 8 |
| 768x1024 | dawn | 118 | 0 | 50 | 0 | 0 |
| 768x1024 | mint | 118 | 0 | 50 | 0 | 0 |
| 768x1024 | paper | 56 | 0 | 0 | 0 | 8 |
| 768x1024 | system | 118 | 0 | 50 | 0 | 0 |
| 390x844 | ink | 53 | 0 | 0 | 0 | 8 |
| 390x844 | midnight | 110 | 0 | 50 | 0 | 0 |
| 390x844 | cyber | 110 | 0 | 50 | 0 | 0 |
| 390x844 | forest | 110 | 0 | 50 | 0 | 0 |
| 390x844 | aubergine | 109 | 1 | 50 | 0 | 0 |
| 390x844 | garnet | 110 | 0 | 50 | 0 | 0 |
| 390x844 | solar | 110 | 0 | 50 | 0 | 0 |
| 390x844 | sepia | 110 | 0 | 50 | 0 | 0 |
| 390x844 | terminal | 110 | 0 | 50 | 0 | 0 |
| 390x844 | contrast | 110 | 0 | 50 | 0 | 0 |
| 390x844 | light | 110 | 0 | 50 | 0 | 0 |
| 390x844 | dawn | 109 | 1 | 50 | 0 | 0 |
| 390x844 | mint | 52 | 1 | 0 | 0 | 8 |
| 390x844 | paper | 110 | 0 | 50 | 0 | 0 |
| 390x844 | system | 110 | 0 | 50 | 0 | 0 |

## Findings, each with its disposition

1. **The AI backend select flipped back after a pick (real defect, fixed here).** `ai-backend-select` read `REVERTED` in 12 of 45 runs. Cause: `loadAiBackendPanel` writes the select from the server's stored value, so a load already in flight when the operator picks holds the OLD value and set the select back until the load that follows the save corrected it. Reproduced in Chromium with the first `/api/llm/backend` answer delayed 1.2 s, stored value `auto`, pick `ollama`: **before** the select read `auto` for about two seconds; **after** it held `ollama`. The fix counts picks and lets a load write the select only when no pick happened since it started (`src/static/app-ai-tools.js`, pinned by `tests/test_ai_backend_select_race.py`). The Settings tab re-swept on the fixed tree (ink and system, three widths): `ai-backend-select` held in all six, 0 reverted, 0 errors, 0 CSP events.
2. **`python -m src.api.main` served a half-broken app, and `--ephemeral` relaunches itself that way (real defect, fixed here).** Booted as `__main__`, the file is imported a second time under its real name by `src/api/insights.py` and dies on the Prometheus `DuplicateTimeseries`: a 500 on the Mindmap graph (first recorded 2026-09-17 in `docs/audit/concept-map-clickthrough-2026-09-17/README.md`, not fixed then). The sweep tripped it by launching the app that way. Nothing documented tells a person to launch it so (`install.ps1 -Check` runs only `doctor`, which does not serve), but `_run_ephemeral` does. The `__main__` block now registers the running module under its real name; `tests/test_main_module_alias.py` fails without it.
3. **Root Settings pass: 50 `ERROR` rows per run (a sweep artefact, not an app fault).** The root pass of the Settings tab lists the 50 id-less selects of the Advanced subtab before that subtab is open; each timed out waiting for a marker the page had re-rendered away. The same 50 selects were then swept under `settings > advanced` and all **held** in every one of those runs (ids compared run by run). The ERRORs also cost 30 s each, which is why the first 31 runs took hours; the remaining 14 ran with a 4 s default timeout (`page.set_default_timeout`), same results.
   The first run of each sweep process (ink at each width in the original three processes; light, paper and mint in the relaunch) shows about 55 held and 0 errors instead of about 118 and 50: the Advanced catalogue's 50 id-less selects had not been rendered yet. Those 50 are swept in the other 12 themes at 1440×900 and 768×1024 and the other 13 at 390×844, and of the 43 distinct select ids swept, 35 appear in all 45 runs; the other 8 (`ing-source`, `feeddir-kind`, `bul-cadence`, `wiki-lang`, `home-recent-tag`, `osm-pick-add`, `gov-agg-pick`, `sky-measure`) appear in 37 to 42 of them, absent where their options had not loaded yet (a select with fewer than two options is not swept) and each was swept at least once at each width.
4. **One transient `ERROR` (`living > law`, 34 options, 768×1024 forest):** the law panel re-rendered between collect and pick in that run; the same select held in the other 44 runs.
5. **Console noise that is not a CSP violation.** 404 for `/static/osm_borders/admin0.world.json`, `admin1.world.json`, `/static/osm_admin0.json`, `osm_admin1.json`: the boundary files row E builds on a machine (an operator step); the maps fall back and say so. Two 429s on `/api/insights/lunar-correlation` while three sweeps ran against one app at once (the loopback rate limit working). Everything else: no console errors or warnings.

## What this does not show

* Only surfaces that paint on the seeded sandbox state were swept. The world-map choropleths that need row E's boundary files (insights, law, library, settings offline maps) render their empty or fallback state here; their map controls at 390 px are checked by the PF10 look only where a map paints (below), and the rest is `not-measurable-here` until the boundary build runs.
* The first 45 runs used the app tree at `bdadf698` with the alias fix; the backend-select fix was verified on the fixed tree by the targeted re-sweep above, not by repeating all 45 runs.
* Chromium only; Gecko best-effort.
* Sweep script versions: the 31 runs before 09:30 UTC ran the original script (30 s default timeout); the last 14 ran with the 4 s default timeout. Both versions judge picks identically.

## PF10 at 390 px (every map surface that paints, in three themes)

Below 600 px the in-map control groups collapse into one in-map button (PF10 = a, PR #1253). For each map the look measures the closed state (toggle visible, panel hidden, share of the map the toggle covers), opens it (`aria-expanded` flips, panel visible, where it sits), picks another option in every drop-down inside the opened panel, and closes it again.

| surface | theme | toggle covers map | opened: panel over map | opened: panel below map | panel drop-downs picked | closed again | verdict |
|---|---|---:|---:|---|---|---|---|
| library > coverage | ink | 6% | 0% | yes | 1/1 | yes | pass |
| living > law | ink | 6% | 0% | yes | 1/1 | yes | pass |
| timemap | ink | 6% | 0% | yes | 1/1 | yes | pass |
| timemap > coverage | ink | 6% | 0% | yes | 1/1 | yes | pass |
| timemap > stories | ink | 6% | 0% | yes | 1/1 | yes | pass |
| timemap > places | ink | 6% | 0% | yes | 1/1 | yes | pass |
| timemap > servers | ink | 6% | 0% | yes | 1/1 | yes | pass |
| library | light | 6% | 0% | yes | 1/1 | yes | pass |
| library > coverage | light | 6% | 0% | yes | 1/1 | yes | pass |
| living > law | light | 6% | 0% | yes | 1/1 | yes | pass |
| timemap | light | 6% | 0% | yes | 1/1 | yes | pass |
| timemap > coverage | light | 6% | 0% | yes | 1/1 | yes | pass |
| timemap > stories | light | 6% | 0% | yes | 1/1 | yes | pass |
| timemap > places | light | 6% | 0% | yes | 1/1 | yes | pass |
| timemap > servers | light | 6% | 0% | yes | 1/1 | yes | pass |
| library | cyber | 6% | 0% | yes | 1/1 | yes | pass |
| library > coverage | cyber | 6% | 0% | yes | 1/1 | yes | pass |
| living > law | cyber | 6% | 0% | yes | 1/1 | yes | pass |
| timemap | cyber | 6% | 0% | yes | 1/1 | yes | pass |
| timemap > coverage | cyber | 6% | 0% | yes | 1/1 | yes | pass |
| timemap > stories | cyber | 6% | 0% | yes | 1/1 | yes | pass |
| timemap > places | cyber | 6% | 0% | yes | 1/1 | yes | pass |
| timemap > servers | cyber | 6% | 0% | yes | 1/1 | yes | pass |

Against the 2026-09-16 measure (the groups covered 79 % of the map, 112 % with the worldview picker): closed, the one button covers 6 %; opened, the panel stacks below the map and covers none of it. The one drop-down in every opened panel was picked and held.

23 of 23 passed every check. Console text: `docs/audit/row-i-csp-sweep-2026-10-06/pf10-390-console.txt`; per-row detail: `pf10-390.json`.
