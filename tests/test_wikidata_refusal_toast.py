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


def test_the_job_error_text_the_node_test_uses_is_what_a_real_job_carries():
    """R334's read: a job's error is ``record_text(exc, typed=True)``, which puts the class name in front, so the JS reader must be shown THAT text
    (the refusal as a bare sentence is what the 409 branch gets, never what a job holds). The string in the node test is pinned to the live constant."""
    from src.entities.items import REFUSAL, AirplaneRefusal
    from src.monitoring.secret_scrub import record_text

    real = record_text(AirplaneRefusal(REFUSAL), limit=300, typed=True)
    assert real.startswith("AirplaneRefusal: network refused: airplane mode is engaged")
    node = (_ROOT / "tests" / "wikidata_refusal_node_test.js").read_text(encoding="utf-8")
    assert real in node, (
        "update REAL_JOB_ERROR in wikidata_refusal_node_test.js to the text a job really carries"
    )
