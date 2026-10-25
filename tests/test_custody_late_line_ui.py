"""The custody "recorded late" line says what it could not read, why, and when.

The endpoint already returns ``recorded_late: null`` with a reason and the time it asked;
a line that drew ``?`` threw that away. The behaviour is driven in node
(``custody_late_line_node_test.js``) against the function EXTRACTED from the shipped
module. The pytest half is the driver the node-suite ratchet requires, plus the claim
that belongs on this side: every string the line introduces is keyed in all twelve locales.
"""

from __future__ import annotations

import json
import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_LOCALES = _ROOT / "src" / "static" / "locales"

_LATE_STRINGS = [
    "{p} ingest entries could not be written when their articles were stored and are queued; "
    "how many have been recorded late could not be read ({reason}).",
    "How many ingest entries have been recorded late could not be read ({reason}).",
    "Asked at {time}.",
    "Counted at {time}.",
]


def test_custody_late_line_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "custody_late_line_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_every_late_line_string_is_keyed_in_all_twelve_locales() -> None:
    missing: list[str] = []
    for path in sorted(_LOCALES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in _LATE_STRINGS:
            if not data.get(key):
                missing.append(f"{path.stem}: {key[:40]}")
    assert not missing, missing
    assert len(list(_LOCALES.glob("*.json"))) == 12
