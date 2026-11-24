"""Settings -> Leads and Models: the Leads catalogue, the AI behaviour line, the Copy buttons, the custom-model box and
the model downloads follow a language switch (row 367 batch 3).

Nine renderers in ``app-settings.js`` wrote translated text once into ordinary nodes, so it stayed in the language
that was active when it was drawn. They now draw through ooLive/ooLiveHtml from what they already hold. The Leads
catalogue is a form: its redraw starts from the form as it stands (``_cardFormState``), so what was ticked or typed and
not saved yet, and which families were open, survive a switch. The behaviour is driven as real code in
``settings_models_live_node_test.js``; this file is its driver.
"""

from __future__ import annotations

import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_settings_leads_and_models_lines_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "settings_models_live_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "settings_models_live_node_test.js: OK" in proc.stdout
