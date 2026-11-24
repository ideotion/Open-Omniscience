"""The Sources section follows a language switch (row 367, app-sources.js).

Eight renderers wrote translated text once into ordinary nodes, so it stayed in the language that was active when it
was drawn. The filter summaries, the AI check (button and result line), the source trail panel, the import's
unreadable-country sentence, the single and batch feed results (with their hovers and the batch table), the batch
picker's empty and capped lines and the retired-mode notice are now held through ooLive/ooLiveHtml; a panel the reader
opened something inside, or a list drawn over a held line, is let go rather than redrawn. The behaviour is driven as
real code in ``sources_live_node_test.js``; this file is its driver.
"""

from __future__ import annotations

import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_sources_section_follows_a_switch_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "sources_live_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "sources_live_node_test.js: OK" in proc.stdout
