"""Settings -> AI tools and custody: the setup card, the hero card, the model store, the uninstall panel, the custody
status and verify lines and the overlay merge line follow a language switch (row 367, app-ai-tools.js batch A), and so
do the model catalogue, the backend panel with its Ollama buttons and the vLLM status and install boxes (batch B),
and the source-qualification line, whose run result is now kept for the status read that follows the run.

These renderers wrote translated text once into ordinary nodes, so it stayed in the language that was active when it
was drawn. They now draw through ooLive/ooLiveHtml from what they already hold; a click's state ("Starting…",
"Working…", "Copying…", "Removing…") is part of the render, and status lines are held one by one. Welded strings
became keyed frames (Uninstall {backend}, the labelled migrate counts, keys: {protection}, Signing/Timestamps
labels, "chain intact, signatures valid." with its hover). The behaviour is driven as real code in
``ai_tools_live_node_test.js``; this file is its driver.
"""

from __future__ import annotations

import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_ai_tools_lines_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "ai_tools_live_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ai_tools_live_node_test.js: OK" in proc.stdout


def test_a_language_switch_does_not_re_read_the_qualification_line():
    """The line is a held render; a re-read on a switch would replace a finished run's tally with the backlog."""
    boot = (_ROOT / "src" / "static" / "app-boot.js").read_text(encoding="utf-8")
    code = "\n".join(line.split("//", 1)[0] for line in boot.splitlines())
    assert "loadQualificationGates();" in code
    assert "loadQualifyBulk(" not in code
