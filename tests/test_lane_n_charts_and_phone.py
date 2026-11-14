"""Charts, the Explore mind map and Explore at phone width (lane N, round 2, 2026-11-14).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each test pins one fix from the re-walk of the journalist review (2026-09-30, findings
4c, 4f, 4g, 4h and section 6) against main 03fa7267, measured in Chromium first:

* 4c: hovering a line chart printed the reading under the legend and marked nothing on
  the canvas, so the reader looked away from the point to read it;
* 4f: x labels sat at even fractions of the window, a third of a day off their own date;
* 4h: ooChart was capped at 900 px inside a 1116 px card, leaving a dead strip;
* 4g: the Explore radial mind map drew 13 pairs of labels on top of each other;
* section 6: the results table was 422 px wide in a 316 px column at 390 px, and the
  time-scope bar was a focusable div with no name.
(4b, the 0-1-3-4 count axis, was already fixed on main by honestTicks' even integer step.)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.js_source_helper import function_body, read_static

ROOT = Path(__file__).resolve().parent.parent


def test_the_hovered_point_is_marked_on_the_canvas():
    js = read_static("app-markets.js")
    body = function_body(js, "ooChart")
    assert "let hovP = null, hovS = null, hovRaf = 0;" in body
    # marked on a measured point, with its value beside it, one redraw per frame at most
    assert "if (hovP && hovS && !(pinned && pinned === hovP))" in body
    assert "requestAnimationFrame(() => { hovRaf = 0; draw(); })" in body
    assert "ctx.arc(hx, hy, 4.5, 0, 7)" in body
    # the full reading still goes to the line under the legend
    assert "readout.textContent = `${b.s.label}: ${fmtV(b.p.v)}" in body


def test_x_labels_sit_on_the_unit_they_name():
    js = read_static("app-markets.js")
    assert "const ms = _msTickSnap(t0 + (t1 - t0) * g / nTicks, Math.max(t1 - t0, 1));" in function_body(js, "ooChart")
    r = subprocess.run(["node", str(ROOT / "tests" / "chart_tick_snap_node_test.js")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_chart_fills_its_card():
    js = read_static("app-markets.js")
    assert "opts.maxWidth || 1600)" in function_body(js, "ooChart")
    assert "(o && o.maxWidth) || 1600)" in function_body(js, "_ooChartWatch")
    assert "|| 900)" not in function_body(js, "ooChart")


def test_the_radial_mind_map_never_draws_a_label_over_another():
    js = read_static("app-analysis.js")
    body = function_body(js, "renderAnMindmap")
    # labels read away from the centre and move out along their own arm until clear
    assert 'n._anchor = ca > 0.2 ? "start" : ca < -0.2 ? "end" : "middle";' in body
    assert "if (!placed.some((q) => hit(q, bx))) break;" in body
    assert "n._x = cx + r * ca; n._y = cy + r * sa;" in body
    # the picture grows to hold them, never shrinking a word below its own scale
    assert 'viewBox="${vb.join(" ")}"' in body and "min-width:${Math.max(W, vb[2])}px" in body
    # the cloud stays the second view, untouched
    assert "Word cloud SECOND view" in body


def test_explore_results_stack_on_a_phone():
    css = read_static("app.css")
    i = css.index("PHONE WIDTH (lane N")
    block = css[i:css.index("\n    }\n", i)]
    assert "#results tr:first-child:has(> th) { display:none; }" in block
    assert "#results tr { display:flex; flex-wrap:wrap;" in block


def test_the_time_scope_bar_has_a_name():
    js = read_static("app-markets.js")
    assert '<div class="ts-bar" tabindex="-1" role="group" aria-label="${esc(t("Date range"))}">' in function_body(js, "ooTimeScope")
