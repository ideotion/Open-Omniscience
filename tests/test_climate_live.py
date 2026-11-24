"""The Climate tab follows a language switch (row 367, app-climate.js).

The tab wrote translated text once into ordinary nodes, so it stayed in the language that was active when it was
drawn. It now draws through ooLive/ooLiveHtml from what it holds: the view's text, the status line, the place form and
its result, and the chart notes are held; the charts are drawn again from the points they hold by
``climateChartsRepaint``, which app-boot's one ``oo:langchange`` listener calls. A field the operator typed in keeps
what was typed. The behaviour is driven as real code in ``climate_live_node_test.js``; this file is its driver.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_climate_tab_follows_a_switch_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "climate_live_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "climate_live_node_test.js: OK" in proc.stdout


def test_the_language_listener_redraws_the_charts_before_the_held_nodes():
    boot = (_ROOT / "src" / "static" / "app-boot.js").read_text(encoding="utf-8")
    charts = re.search(r"climateChartsRepaint\(\)", boot)
    held = re.search(r"ooLiveRepaint\(\)", boot)
    assert charts and held, (
        "app-boot's oo:langchange listener must call climateChartsRepaint() and ooLiveRepaint()"
    )
    assert charts.start() < held.start()
