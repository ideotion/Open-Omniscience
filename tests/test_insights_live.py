"""The Insights tab follows a language switch (row 367, app-insights.js).

Fifteen renderers wrote translated text once into ordinary nodes, so it stayed in the language that was active when it
was drawn. They now draw through ooLive/ooLiveHtml: the watches' lines, the keyword explorer (its rows are drawn once,
so an open tag editor, a hidden keyword and a tag being typed stay as they are; only their words are held), the groups
list, the ring gap and ring-load status, the convergences, the lunar screen and single test, and the citation scan
line. The two-tier concept browse is drawn again from what it holds by ``repaintConceptBrowse``, which app-boot's one
``oo:langchange`` listener calls. The behaviour is driven as real code in ``insights_live_node_test.js``; this file is
its driver.
"""

from __future__ import annotations

import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_insights_tab_follows_a_switch_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "insights_live_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "insights_live_node_test.js: OK" in proc.stdout


def test_the_language_listener_redraws_the_concept_browse():
    boot = (_ROOT / "src" / "static" / "app-boot.js").read_text(encoding="utf-8")
    listener = boot.index('"oo:langchange"')
    assert boot.count("repaintConceptBrowse()") == 1
    assert boot.index("repaintConceptBrowse()") > listener
