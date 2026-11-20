"""The dossier's rails as subtabs (0.8 row A, brief S08-01 S2, row 178 PR 5).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Invariant #18: the subtabs go through THE one component, ``ooSubtabs``, with no inline handler. The
dossier stays a dialog (``<dialog id="dossier">``), so invariant #22c (analysis lives inside Explore)
is untouched. The rendering refusals (a gap keeps its tab, every panel names its provenance, the method
and caveat sit outside every panel) are driven through the real functions by ``dossier_tabs_node_test.js``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.js_source_helper import function_source, read_static


def test_the_rails_are_subtabs_through_the_one_component():
    js = read_static("app-dossier.js")
    paint = function_source(js, "_dossierPaint")
    assert "ooSubtabs(nav, show)" in paint, "invariant #18: one subtab component"
    assert "onclick" not in js
    tabs = function_source(js, "_dossierTabsHtml")
    assert '<nav class="tabs dossier-tabs" id="dossier-tabs"' in tabs and "data-tab=" in tabs


def test_the_dossier_stays_a_dialog_so_explore_keeps_the_analysis():
    html = read_static("index.html")
    assert '<dialog id="dossier"' in html
    assert 'id="tab-dossier"' not in html and 'data-tab="dossier"' not in html


def test_the_tabs_render_through_the_real_functions():
    proc = subprocess.run(
        ["node", str(Path(__file__).resolve().parent / "dossier_tabs_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout
