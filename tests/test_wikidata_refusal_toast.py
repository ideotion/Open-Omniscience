"""The Wikidata fetch button names the kill switch by OUR sentence, never by a phrase inside another failure's text (R298's anchoring, on the
JS side; found by the read of PR #1546).

``entitySpineFetch`` tested ``/airplane mode/i`` against the error message anywhere, so a failure whose text merely quoted the words (a 502 that
echoed a remote page, a redirect text) toasted "Refused: airplane mode is on". The behaviour is driven as real code in
``wikidata_refusal_node_test.js``; this file is its pytest driver.

THE SENTENCE IS THE PYTHON CONSTANT (R328). The routes that refuse before they build a request say ``NETWORK_REFUSED``; the shipped reader
(``_wikidataRefusedByAirplaneMode``) takes the route's 409 status as the refusal and, for a message with no status, matches that sentence at its
start, in two languages that share nothing but the text. The driver builds the reader's input from the constant and hands it to the node run, so a
rewording at the definition that leaves the reader's pattern behind fails here (in the no-status cases, the only ones that read the text), and the
run says which copy it used, so a driver that stopped passing the constant cannot go on passing quietly.
"""

from __future__ import annotations

import os
import pathlib
import subprocess

from src.ingest.fetch_verdict import NETWORK_REFUSED

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_wikidata_refusal_toast_in_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "wikidata_refusal_node_test.js")],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env={**os.environ, "OO_NETWORK_REFUSED": NETWORK_REFUSED},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "wikidata_refusal_node_test.js: OK (sentence from the constant)" in proc.stdout
