"""Driver for tests/import_conclusion_node_test.js.

WHY THIS FILE EXISTS AT ALL. The node suite it runs was written months ago and was
the ONE `*_node_test.js` in the tree with no pytest driver -- so it had never gated
anything. That is not a filing detail: the 2026-08-03 re-index deferral shipped with
a renderer reading ``reindex_deferred`` and no producer writing it, and this suite is
precisely the harness that would have caught it, sitting unrun. A test that does not
execute is documentation, and a green lane over it is a fabricated pass.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_import_conclusion_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "import_conclusion_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout


def test_every_node_suite_has_a_driver() -> None:
    """The ratchet. One orphan already cost a shipped defect; the class must not regrow.

    A ``*_node_test.js`` nobody runs looks exactly like coverage in a file listing and
    provides none, so membership is asserted rather than left to whoever adds the next
    one remembering.
    """
    tests = _ROOT / "tests"
    drivers = "\n".join(p.read_text(encoding="utf-8") for p in tests.glob("test_*.py"))
    orphans = [p.name for p in sorted(tests.glob("*_node_test.js")) if p.name not in drivers]
    assert not orphans, (
        f"these node suites are never executed by pytest: {orphans}. Add a driver "
        "(see this file) -- an unrun test gates nothing."
    )
