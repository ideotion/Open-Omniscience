"""The AI backend <select> must not be flipped back by a panel load that started before the pick.

Found by the 2026-10-06 row-I sweep (``ai-backend-select`` read ``REVERTED`` in 12 of 45 width x theme
runs): ``loadAiBackendPanel`` writes the select from the server's stored value, so a load already in
flight when the operator picks holds the OLD value and set the select back for the seconds until the
load that follows the save corrected it. A second ordering (two quick picks, the first save's reload
landing before the second save) was found by the review of the first fix. The behaviour is driven as
real code by ``tests/ai_backend_select_race_node_test.js`` (the shipped functions against a server
this test controls); the text pins below only say the node test is reading the right declarations.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.js_source_helper import read_static

ROOT = Path(__file__).resolve().parents[1]
SRC = read_static("app-ai-tools.js")


def test_the_select_behaves_in_every_ordering_of_picks_loads_and_saves():
    out = subprocess.run(
        ["node", str(ROOT / "tests" / "ai_backend_select_race_node_test.js")],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert out.returncode == 0 and "ai_backend_select_race: ok" in out.stdout, out.stdout + out.stderr


def test_the_counters_are_declared_once_and_the_node_test_reads_them():
    assert SRC.count("let _aiBackendPicks = 0;") == 1
    assert SRC.count("let _aiBackendSaving = 0;") == 1
