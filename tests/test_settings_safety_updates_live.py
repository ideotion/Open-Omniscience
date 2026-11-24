"""Settings -> Advanced: the compact, rebuild and update lines and the stoplist view follow a language switch (row 367).

Ten renderers in ``app-settings.js`` wrote translated text once into ordinary nodes, so it stayed in the language
that was active when it was drawn. They now draw through ooLive/ooLiveHtml from what they already hold, and the
rebuild result line has ONE render reading ``_rebuildSt`` and ``_rebuildNote`` (the refusal used to live in
``res.dataset.keep``). The behaviour is driven as real code in ``settings_safety_updates_live_node_test.js``; this
file is its driver.
"""

from __future__ import annotations

import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_settings_safety_and_update_lines_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "settings_safety_updates_live_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "settings_safety_updates_live_node_test.js: OK" in proc.stdout
