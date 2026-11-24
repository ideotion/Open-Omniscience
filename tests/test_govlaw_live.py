"""The Governments and Law tabs follow a language switch (row 367, app-gov-law.js).

Ten renderers wrote translated text once into ordinary nodes, so it stayed in the language that was active when it was
drawn. The loading and failure lines of Countries, Compare, Aggregates, Groups and the map, the map's "Latest available"
year (the picked year stays picked), the Law pointer and its hover, and the busy words of "Load standard country data",
"Summarize this change" and "Add & track" are now held through ooLive/ooLiveHtml; each button gets its own label back
when the work ends, and the consent still comes before any request. The behaviour is driven as real code in
``govlaw_live_node_test.js``; this file is its driver.
"""

from __future__ import annotations

import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_governments_and_law_tabs_follow_a_switch_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "govlaw_live_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "govlaw_live_node_test.js: OK" in proc.stdout
