"""Living sources follows a language switch (row 367, app-living.js).

Seven renderers wrote translated text once into ordinary nodes, so it stayed in the language that was active when it
was drawn. Every loading and failure line of the Living views, the overview's failure line and a diff's Show/Hide
button are now held through ooLive/ooLiveHtml, and the cached-view repaint of the cross-edition compare no longer blanks
a loading or failure line it has no answer for. The behaviour is driven as real code in ``living_live_node_test.js``;
this file is its driver.
"""

from __future__ import annotations

import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_living_sources_follows_a_switch_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "living_live_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "living_live_node_test.js: OK" in proc.stdout
