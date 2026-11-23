"""Settings -> Models: the Ollama installer, the models box, the default-model block and the language-detection line
follow a language switch (row 367 batch 4).

Eight renderers in ``app-settings.js`` wrote translated text once into ordinary nodes, so it stayed in the language
that was active when it was drawn. They now draw through ooLive/ooLiveHtml from what they already hold; where a panel
is repainted from inside, its parts are held one by one. The installer's log is one list drawn by one render, and a
non-zero exit says so through ONE keyed frame ("Installer exited with code {code}.") instead of a welded number. The
dead manual language-detection button code (runLangDetect, _paintLangDetectButton) is removed and pinned absent in
test_repo_invariants. The behaviour is driven as real code in ``settings_ai_install_live_node_test.js``; this file is
its driver.
"""

from __future__ import annotations

import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_settings_ai_install_lines_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "settings_ai_install_live_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "settings_ai_install_live_node_test.js: OK" in proc.stdout
