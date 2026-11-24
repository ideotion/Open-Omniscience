"""Settings -> Data & backup: the import, newsletter and storage lines follow a language switch (row 367).

Eleven renderers in ``app-settings.js`` wrote translated text once into ordinary nodes, so it stayed in the
language that was active when it was drawn. They now draw through ooLive/ooLiveHtml from what they already
hold. The behaviour is driven as real code in ``settings_imports_live_node_test.js``; this file is its driver.
"""

from __future__ import annotations

import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_settings_import_lines_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "settings_imports_live_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "settings_imports_live_node_test.js: OK" in proc.stdout
