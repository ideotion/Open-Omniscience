"""The app's chrome follows a language switch (row 367, app-core.js).

Eleven renderers wrote translated text once into ordinary nodes, so it stayed in the language that was active when it
was drawn. The health pill and its hover, the crash screen (its retry button keeps its listener), the airplane pop-up's
OK, the network consent popup's lane list and interfaces line, the guided setup's interfaces line, the AI install
question's default reason and the Coverage loading line are now held through ooLive/ooLiveHtml; the task manager's
Active, Queue, Schedule and Coverage panels are drawn again from what they last read by ``repaintTaskManager``, which
app-boot's one ``oo:langchange`` listener calls (never a fetch, nothing for a panel never drawn). The behaviour is
driven as real code in ``core_live_node_test.js``; this file is its driver.
"""

from __future__ import annotations

import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_app_chrome_follows_a_switch_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "core_live_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "core_live_node_test.js: OK" in proc.stdout
