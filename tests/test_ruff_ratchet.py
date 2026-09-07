"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The non-growth ratchet on the ADVISORY ruff style lane (ruled 2026-09-07,
PROMPT_20 S7 "decide whether it converges or stays advisory, and record which").

The verdict is: stays advisory. The mechanism is: it may not GROW. PARKED.md
recorded the lane at 344 findings on 2026-08-20 and it measured 432 on
2026-09-07 (442 by the time this PR merged, all of the growth from parallel
branches and none of it this PR's -- verified like-for-like) -- 88 findings of drift nobody saw, because a lane that is allowed to
fail says nothing when it fails a little more. Prose had already been tried.

DELIBERATELY UNLIKE ``_ADHOC_SLICER_BUDGET``, this ratchet permits SLACK. That
budget has a twin forbidding a ceiling above the real count, which is right for a
number only this repo can move; this one moves with ruff's rule set, so a
zero-slack twin would turn any legitimate ruff bump into a red lane on a tree
nobody touched -- the recorded mypy-pin failure, bought a second time.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "ruff_ratchet.py"
_CI = _ROOT / ".github" / "workflows" / "ci.yml"


def _load():
    import importlib.util

    spec = importlib.util.spec_from_file_location("_ruff_ratchet", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_script_exists_and_lints_the_same_paths_as_the_ci_step():
    """A ratchet that measures a different tree than the lane it guards is worse than
    no ratchet: it would go quiet exactly when the lane grew somewhere it cannot see."""
    mod = _load()
    ci = _CI.read_text(encoding="utf-8")
    assert "ruff check src/ tests/" in ci, "the advisory lane's own paths moved"
    assert tuple(mod.TARGETS) == ("src/", "tests/")


def test_ci_invokes_the_ratchet_with_a_ceiling():
    ci = _CI.read_text(encoding="utf-8")
    m = re.search(r"python scripts/ruff_ratchet\.py --max (\d+)", ci)
    assert m, "ci.yml must run the ratchet with an explicit --max"
    assert int(m.group(1)) > 0


@pytest.mark.parametrize(
    ("count", "ceiling", "rc"),
    [(432, 432, 0), (431, 432, 0), (433, 432, 1), (0, 432, 0)],
)
def test_the_verdict_is_growth_only(monkeypatch, capsys, count, ceiling, rc):
    """Equal passes, below passes (and prints the new floor), above fails."""
    mod = _load()
    monkeypatch.setattr(mod, "findings", lambda: [{"code": "I001"}] * count)
    monkeypatch.setattr(sys, "argv", ["ruff_ratchet.py", "--max", str(ceiling)])
    assert mod.main() == rc
    out = capsys.readouterr()
    assert f"ruff advisory findings: {count}" in out.out
    if count < ceiling:
        assert f"--max {count}" in out.out, "a drop must print the new floor to set"


def test_the_failure_message_names_the_ruff_version(monkeypatch, capsys):
    """A count-over-a-tool ratchet is only meaningful while the rule set is fixed, so
    a red run must say which ruff produced the number -- otherwise a version bump
    presents as mystery debt rather than as itself."""
    mod = _load()
    monkeypatch.setattr(mod, "findings", lambda: [{"code": "I001"}] * 999)
    monkeypatch.setattr(mod, "_ruff_version", lambda: "ruff 9.9.9")
    monkeypatch.setattr(sys, "argv", ["ruff_ratchet.py", "--max", "1"])
    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "ruff 9.9.9" in err and "may only be lowered" in err


def test_it_counts_findings_not_output_lines():
    """``ruff check`` prints two SUMMARY lines after the findings ("Found N errors",
    "[*] N fixable"), so a ``wc -l`` implementation over-reports by two and drifts the
    day ruff changes its summary. The script reads ruff's own JSON; this drives the
    real thing to prove the parse works against the installed version."""
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--max", "100000"],
        capture_output=True,
        text=True,
        cwd=_ROOT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    m = re.search(r"ruff advisory findings: (\d+)", proc.stdout)
    assert m, proc.stdout
    # No assertion on the VALUE: it moves with the ruff version, which is the whole
    # reason the ceiling lives in ci.yml and not in this file.
    assert int(m.group(1)) >= 0
