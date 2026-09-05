"""Driver for tests/gate_fields_node_test.js.

Required by ``test_every_node_suite_has_a_driver``: an unrun node suite looks exactly
like coverage in a file listing and gates nothing. This one matters more than most,
because the defect it guards WAS a silence — the per-field refusals existed in the
payload and never reached the operator — and a guard against a silence that is itself
never executed reproduces the original failure one layer up.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_gate_fields_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "gate_fields_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout
