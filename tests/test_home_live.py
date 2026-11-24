"""The Home tab follows a language switch (row 367, app-home.js).

Thirteen renderers wrote translated text once into ordinary nodes, so it stayed in the language that was active when it
was drawn. The "Loading…" lines (Feed, Latest, Most recent, a weather check, the link preview) are now held until what
they wait for lands; the link preview's lines, the trending strip, a late subtab's label and the dismiss-reason form
are held; the alert strip and the Leads carousel are drawn again from what they hold by ``repaintHomeAlerts`` and
``repaintLeadsCarousel``, which app-boot's one ``oo:langchange`` listener calls. The behaviour is driven as real code in
``home_live_node_test.js``; this file is its driver.
"""

from __future__ import annotations

import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_home_tab_follows_a_switch_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "home_live_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "home_live_node_test.js: OK" in proc.stdout
