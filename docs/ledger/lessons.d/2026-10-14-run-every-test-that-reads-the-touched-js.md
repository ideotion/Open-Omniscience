## 2026-10-14 — run every test that reads the touched JS, not only the feature's own

**Found:** the T5 layout PR (#1377) changed what `showRingMap` hands to `ooMap` (`caveat: d.caveat` became `caveat: ringCaveat`). `tests/test_ui_ring_map.py::test_counts_only_no_score` asserted the literal `caveat: d.caveat`, so it went red on main the moment #1377 merged, and every other thread's PR then inherited a red `test_ui_ring_map` it had not caused. The follow-up PR (#1381) added a repaint rule and broke two more tests that pinned the old one ("redraw only a map with an svg on screen": `tests/clickthrough_b20_node_test.js` R4 and `tests/test_clickthrough_b20_maps.py`). None of the three was in the targeted test list for the feature, because that list was built from the feature's own file names.

**Cost:** a red main for about a day and a coordinator hunt for whose red it was, found only when another thread reported it.

**Rule:** before pushing a change to a shipped JS file, run every test that reads that file, found by search rather than by feature name: `grep -l "app-insights\|app_js()\|app-boot\|app-map" tests/*.py` (about 2,470 tests, six minutes), plus the node tests under `tests/*_node_test.js`. Where an old test pins a wording of the code you changed, update it to the new rule in the same PR and say so; do not widen the assertion until it passes.
