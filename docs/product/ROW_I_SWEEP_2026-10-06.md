# Row I closing sweep, 2026-10-06 (CSP, every drop-down, three widths, every theme)

Gate row I, brief `S05-09`. Written by `scripts/csp_sweep.py` (the sweep) and `scripts/pf10_look.py` (the 390 px map look), run in Chromium against a booted app. Reading rule R126 (2026-10-06): this walk is what closes the UX pass; the maintainer's own click-through is optional.

## What was done, and in what order

**Two sweeps, and the second is the record.** The first sweep (45 runs, original script) found two defects and, when its judge was read back by an independent review, two faults of its own: a pick whose select had been re-rendered was counted as **held** without being read back, and the root Settings pass lost its markers and wasted 30 s per row. Both defects were fixed in this PR and the script was fixed too; **the whole sweep was then run again, 45 runs, at `ad551d20`**, the first commit that carries the saving counter, the read-back script and the offline guard (`885dfd6f` already had the first page fix), and the numbers below are that second sweep's. Later changes were NOT covered by it: the page's last fix, a landed save also invalidating every load that began before it, came in `4b2f1203` (`src/` has not changed since), and the scripts changed in `4b2f1203` and again after it. The Settings tab (9 runs) and the 390 px look were run again at `4b2f1203`; the script edits after `4b2f1203` were smoke-run only (see the script-versions bullet). The first sweep's files stay in `docs/audit/row-i-csp-sweep-2026-10-06/first-sweep-before-the-fixes/` because it is the evidence of what the defects looked like.

At each of 1440×900, 768×1024 and 390×844, in each of the **15** theme settings the picker offers (the 14 named themes and `system`), the sweep visited every sidebar tab and every subtab, opened every foldout, and for each visible `<select>` picked an option other than the current one, waited 400 ms and judged it, then restored the original value. The console (errors and warnings) and every `securitypolicyviolation` event were kept **per width and theme** in `docs/audit/row-i-csp-sweep-2026-10-06/console-<width>-<theme>.txt` beside the per-select results (`selects-<width>-<theme>.json`).

* `held` is the select **read back from where it is after the pick** (its id, or its panel's id plus its index): a pick whose select was gone or rebuilt with other options is `unread` and fails the run. `held` shows that the pick **stuck**; it does not show the pick did anything.
* `effect` is `ui`, `net`, `dom` or `none`, credited only beyond what the page did on its own in ONE 400 ms sample taken just before the pick (`idle_net` and `idle_mut`). That **reduces** the page's own activity and does not remove it: `net` and `dom` still include requests the page makes on its own. Two controls whose handlers send no request, `fetch-mode` (`onFetchModeChange`) and `feeddir-sort` (`renderFeedDir`), still scored `net` in 11 and 4 of the 45 runs, always with `idle_net` 0. `effect` is evidence of activity, not proof the pick caused it, and `none` is not a dead binding (some selects are only read by a later button).
* The sweep **refuses** a non-loopback `--url` and an app that does not answer `online:false` on `GET /api/system/network`, and exits non-zero on a revert, a CSP event, an ERROR, an unread pick or a run that picked nothing.

**How the app was launched.** Console entry (`python -c "from src.api.main import main; main()"`), on a seeded state copy, `OO_DB_PLAINTEXT=1 OO_AUTOSEED=0`, and **without** `OO_NO_SCHEDULER` (that variable skips the boot's offline engage; the first sweep ran with it, so that app was ONLINE with no kill switch and no socket guard, and nothing in that sweep measured egress). The second sweep's app answered `{"online":false}`, asserted when each width's browser context starts (and once at the start of the PF10 look) and re-checked by hand at the end, and its server log was searched afterwards (below). The 45 runs used the tree at `ad551d20`; the Settings re-sweep and the PF10 look used `4b2f1203`.

## Result (the second sweep)

* **CSP violations: 0 of 45 runs had any** (`securitypolicyviolation` events, kept across reloads, and console lines naming the policy: none). `script-src 'self'` holds across all three widths and all 15 themes.
* **Picks read back holding the pick: 6798**; reverted: 0; unread: 0; `ERROR`: 0; skipped (no other enabled option): 0.
* Picks with no effect beyond the page's own activity (`none`): 898.

| width | theme | held | reverted | unread | error | csp | console lines |
|---|---|---:|---:|---:|---:|---:|---:|
| 1440x900 | ink | 59 | 0 | 0 | 0 | 0 | 8 |
| 1440x900 | midnight | 168 | 0 | 0 | 0 | 0 | 0 |
| 1440x900 | cyber | 168 | 0 | 0 | 0 | 0 | 0 |
| 1440x900 | forest | 168 | 0 | 0 | 0 | 0 | 0 |
| 1440x900 | aubergine | 168 | 0 | 0 | 0 | 0 | 0 |
| 1440x900 | garnet | 168 | 0 | 0 | 0 | 0 | 0 |
| 1440x900 | solar | 168 | 0 | 0 | 0 | 0 | 0 |
| 1440x900 | sepia | 168 | 0 | 0 | 0 | 0 | 0 |
| 1440x900 | terminal | 168 | 0 | 0 | 0 | 0 | 0 |
| 1440x900 | contrast | 168 | 0 | 0 | 0 | 0 | 0 |
| 1440x900 | light | 168 | 0 | 0 | 0 | 0 | 0 |
| 1440x900 | dawn | 62 | 0 | 0 | 0 | 0 | 8 |
| 1440x900 | mint | 168 | 0 | 0 | 0 | 0 | 0 |
| 1440x900 | paper | 168 | 0 | 0 | 0 | 0 | 0 |
| 1440x900 | system | 168 | 0 | 0 | 0 | 0 | 0 |
| 768x1024 | ink | 59 | 0 | 0 | 0 | 0 | 8 |
| 768x1024 | midnight | 168 | 0 | 0 | 0 | 0 | 0 |
| 768x1024 | cyber | 168 | 0 | 0 | 0 | 0 | 0 |
| 768x1024 | forest | 168 | 0 | 0 | 0 | 0 | 0 |
| 768x1024 | aubergine | 168 | 0 | 0 | 0 | 0 | 0 |
| 768x1024 | garnet | 168 | 0 | 0 | 0 | 0 | 0 |
| 768x1024 | solar | 168 | 0 | 0 | 0 | 0 | 0 |
| 768x1024 | sepia | 168 | 0 | 0 | 0 | 0 | 0 |
| 768x1024 | terminal | 168 | 0 | 0 | 0 | 0 | 0 |
| 768x1024 | contrast | 168 | 0 | 0 | 0 | 0 | 0 |
| 768x1024 | light | 168 | 0 | 0 | 0 | 0 | 0 |
| 768x1024 | dawn | 61 | 0 | 0 | 0 | 0 | 8 |
| 768x1024 | mint | 168 | 0 | 0 | 0 | 0 | 0 |
| 768x1024 | paper | 168 | 0 | 0 | 0 | 0 | 0 |
| 768x1024 | system | 168 | 0 | 0 | 0 | 0 | 0 |
| 390x844 | ink | 55 | 0 | 0 | 0 | 0 | 8 |
| 390x844 | midnight | 160 | 0 | 0 | 0 | 0 | 0 |
| 390x844 | cyber | 160 | 0 | 0 | 0 | 0 | 0 |
| 390x844 | forest | 160 | 0 | 0 | 0 | 0 | 0 |
| 390x844 | aubergine | 160 | 0 | 0 | 0 | 0 | 0 |
| 390x844 | garnet | 160 | 0 | 0 | 0 | 0 | 0 |
| 390x844 | solar | 160 | 0 | 0 | 0 | 0 | 0 |
| 390x844 | sepia | 160 | 0 | 0 | 0 | 0 | 0 |
| 390x844 | terminal | 160 | 0 | 0 | 0 | 0 | 0 |
| 390x844 | contrast | 160 | 0 | 0 | 0 | 0 | 0 |
| 390x844 | light | 160 | 0 | 0 | 0 | 0 | 0 |
| 390x844 | dawn | 160 | 0 | 0 | 0 | 0 | 0 |
| 390x844 | mint | 54 | 0 | 0 | 0 | 0 | 8 |
| 390x844 | paper | 160 | 0 | 0 | 0 | 0 | 0 |
| 390x844 | system | 160 | 0 | 0 | 0 | 0 | 0 |

Distinct selects swept: 99; 40 of them in all 45 runs. The others, and why: the three map-panel drop-downs (`coverage-map[0]`, `oo-coverage-map[0]`, `law-amend-map[0]`) are collapsed behind the in-map button below 600 px, so at 390×844 they are not visible and are covered by the PF10 look instead (below), which opens them; at the other two widths they are in every run (`coverage-map[0]` lacks only 1440 ink, whose map had not painted yet); the 50 id-less `src-table[0..49]` selects (the Advanced catalogue) and `ing-source`, `feeddir-kind`, `bul-cadence` are absent from the first run of each of the six processes (1440 ink, 1440 dawn, 768 ink, 768 dawn, 390 ink, 390 mint), whose catalogue had not rendered, and a select with fewer than two options is not swept; `home-recent-tag`, `wiki-lang` and `osm-pick-add` are absent from one to four runs for the same reason. Every one of them was swept and read back holding the pick in the runs that had it.

## Findings, each with its disposition

1. **The AI backend select flipped back after a pick (real defect, fixed here).** In the first sweep `ai-backend-select` read `REVERTED` in 12 of 45 runs (10 of the first 32 runs, the original script; 2 of the last 13, the 4 s timeout; files in `first-sweep-before-the-fixes/`). Cause: `loadAiBackendPanel` writes the select from the server's stored value, so a load already in flight when the operator picks holds the OLD value and set the select back. A first fix (count picks, write only if none happened since the load began) still reverted on two picks in one tick, which the review reproduced; the page now also counts saves in flight and writes only when none is. **Measured before and after in one Chromium, through `scripts/ai_backend_race_repro.py`, which serves each variant of the file to the same app** (`repro-ai-backend-race.json`, readings every 250 ms; the committed file predates the `served_sha256` field the script now writes, and was not re-run for it): with the first backend answer 1.2 s late and one pick, `main` showed the pick for 1.5 s and then the stored value for the rest of the 3.5 s window; the picks-only fix and the fixed file held the pick in all 14 readings. With two picks in one tick and the second save 0.8 s late, `main` and the picks-only fix each showed the first pick again for three readings (0.75 s) after the second; the fixed file held the second pick in all 16 readings and stored it. `tests/ai_backend_select_race_node_test.js` runs the real functions with controllable answers (seven scenarios, mutation-checked by hand: the capture moved after the await, either counter removed; not kept as a file); in-app confirmation: **`ai-backend-select` held in every one of the 45 runs of the second sweep, 0 reverted**, and, because the last fix (a landed save also invalidates every load that began before it) came after that sweep, the Settings tab was swept again at `4b2f1203` (ink, light and system at the three widths, `final-settings-resweep/`, the page being the final one: `src/` has not changed since): 9 runs, 751 picks read back holding the pick, 0 reverted, 0 unread, 0 errors, 0 CSP events; `ai-backend-select` read back holding the pick in 9 of 9 runs, reverted in 0. The three ink runs swept only 14, 15 and 14 of the 118 selects (their Advanced catalogue had not rendered yet, the same first-run effect as above), so the total is 3 x about 14 + 6 x 118.
2. **`python -m src.api.main` served a half-broken app, and `--ephemeral` relaunches itself that way (real defect, fixed here).** Booted as `__main__`, the file is imported a second time under its real name by `src/api/insights.py` and dies on the Prometheus `DuplicateTimeseries`: a 500 on the Mindmap graph (first recorded 2026-09-17 in `docs/audit/concept-map-clickthrough-2026-09-17/README.md`, not fixed then). Trial launches of the sweep's app with `python -m` tripped it; every recorded run used the console entry. The `__main__` block now registers the running module under its real name and as the package's `main` attribute; `tests/test_main_module_alias.py` fails without it and runs in its own data directory.
3. **The first sweep's own faults, found by the independent read and fixed.** (a) 215 of its 4,691 "held" rows had never been read back (the map panels' select, re-rendered by the pick): they are now read back, and every one holds (second sweep: 0 unread); (b) the root Settings pass lost its markers once a pick redrew the panel and each lost marker cost 30 s (1,850 `ERROR` rows, hours per sweep): selects are now found by a path that survives a redraw and the default timeout is 4 s; (c) `effect` counted background polling as `net`: reduced by a pre-pick sample, not removed (see the `effect` bullet above); `__csp` was lost on a reload: now kept in `sessionStorage` and reset per theme; (d) the sweep could pass with every pick failing: it cannot now.
4. **Console noise that is not a CSP violation.** 404 for `/static/osm_borders/admin0.world.json`, `admin1.world.json`, `/static/osm_admin0.json`, `osm_admin1.json`: the boundary files row E builds on a machine (an operator step); the maps fall back and say so. Everything else: no console errors or warnings.

## What this does not show

* **Egress.** The second sweep ran against an app that answered `online:false` when each width's context started (asserted by the script, which refuses a non-loopback URL) and again, checked by hand, after the last run of the second boot. Its server log (52,703 lines over the second sweep, the redo and the first PF10 look; the counts are in `server-log-check.txt`) says it booted in airplane mode, names **no http(s) URL whose extracted host lacks `127.0.0.1` or `localhost`** (all the grep can see), and holds no error or traceback; the app still answered `online:false` afterwards. That is the absence of any logged outbound attempt; egress itself was not observed by a packet capture.
* Only surfaces that paint on the seeded sandbox state were swept. The world-map choropleths that need row E's boundary files render their empty or fallback state here; their 390 px controls are checked by the PF10 look only where a map paints (below), and the rest is `not-measurable-here` until the boundary build runs.
* `held` shows that a pick stuck, not that it did anything; `effect: none` rows (898) are picks with nothing observable beyond the page's own activity in 400 ms, so some of them are selects that a later button reads, and some may be selects with no handler. The record does not separate the two.
* Chromium only; Gecko not run.
* **Script versions.** The 45-run second sweep and its 11-run repeat ran `scripts/csp_sweep.py` as of ad551d20; the edits after it (the docstring wording, the per-theme reset of the kept CSP events, the split of the loopback check) were exercised by the Settings re-sweep and the PF10 look, which ran the scripts of `4b2f1203`. The numbers in the table are therefore from the earlier version of the script. `scripts/pf10_look.py` had its own edits in `4b2f1203` too (the panel scoped to the opened host, a has-a-dropdown check in the verdict) and imports from `csp_sweep.py`, so the PF10 look ran the `4b2f1203` pair. After `4b2f1203` the loopback check was made strict, the late-CSP-event tally added (also read once after each width's last theme) and the port pattern made `[0-9]{1,5}`; those were exercised only by a smoke run (one tab, two themes, a refused URL; one transient `agenda-group` ERROR on its first theme, as the first full run had), not by a sweep.
* **Three processes at once hit the app's loopback rate limit.** The second sweep ran the three widths as three parallel processes; in the last four themes of each (dawn, mint, paper, system) the app answered `429 Too Many Requests` to `/api/articles` (258 console lines in 11 runs) and 19 subtab clicks timed out. Those 11 runs were repeated one process at a time (`1440x900` dawn, mint, paper, system; `768x1024` dawn, mint, paper, system; `390x844` mint, paper, system): all clean, no 429; the files here for those 11 are the repeat, and the first pass of them is kept in `first-pass-429-runs/`.

## The first sweep, for the record

45 runs on the first version of the script, files in `first-sweep-before-the-fixes/`: ok 4,691, `REVERTED` 12 (all `ai-backend-select`), `ERROR` 1,851 (1,850 the root Settings pass, 1 a transient `living > law`), CSP events 0, `effect: none` 512, 43 distinct ids. 32 runs ran with Playwright's 30 s default timeout (10 of them showed the revert) and 13 with a 4 s timeout (2 showed it). Its app was online (`OO_NO_SCHEDULER=1`). 215 of its "ok" picks (the map panels' select) had never been read back. It is kept as the evidence of the defects, not as the closing measure.

## PF10 at 390 px (every map surface that paints, in three themes)

Below 600 px the in-map control groups collapse into one in-map button (PF10 = a, PR #1253). For each map the look measures the closed state (toggle visible, panel hidden, share of the map the toggle covers), opens it (`aria-expanded` flips, panel visible, where it sits), picks another option in every drop-down inside THAT host's opened `.oomap-panel` (marked, so another open map's panel is not read into the row) and **reads it back**, and closes it again. The verdict needs at least one drop-down, every one read back holding the pick, the panel below the map covering none of it, and the closed toggle covering at most 6 %. This look ran the scripts of `4b2f1203`.

| surface | theme | toggle covers map | opened: panel over map | opened: panel below map | panel drop-downs read back holding | closed again | verdict |
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

23 of 23 passed every check. `library` in ink is the one missing row (the library map had not painted within the look's 1.5 s wait on the first visit of the first theme; light and cyber have all eight), so 7 + 8 + 8 rows. All 23 panel drop-downs were picked and **read back holding the pick** (first sweep: 0 of 23 had been read back). Against the 2026-09-16 measure (the groups covered 79 % of the map, 112 % with the worldview picker): closed, the one button covers 6 %; opened, the panel stacks below the map and covers none of it. Console text: `docs/audit/row-i-csp-sweep-2026-10-06/pf10-390-console.txt`; per-row detail: `pf10-390.json`. The first look (the judge that read nothing back, 23 rows) is kept as `first-sweep-before-the-fixes/pf10-390.json` and its console file.
