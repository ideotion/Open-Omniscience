"""The Wikidata fetch button names the kill switch by OUR sentence, never by a phrase inside another failure's text (R298's anchoring, on the
JS side; found by the read of PR #1546).

``entitySpineFetch`` tested ``/airplane mode/i`` against the error message anywhere, so a failure whose text merely quoted the words (a 502 that
echoed a remote page, a redirect text) toasted "Refused: airplane mode is on". The behaviour is driven as real code in
``wikidata_refusal_node_test.js``; this file is its pytest driver.
"""

from __future__ import annotations

import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_wikidata_refusal_toast_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "wikidata_refusal_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "wikidata_refusal_node_test.js: OK" in proc.stdout
