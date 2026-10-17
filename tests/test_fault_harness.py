"""The crash-pipeline harness (scripts/fault_harness.py). SLOW (about 40 s a scenario, two real boots each), so it runs only when asked:
``OO_FAULT_HARNESS=1 pytest tests/test_fault_harness.py``. The fast checks below always run."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "fault_harness.py"
_spec = importlib.util.spec_from_file_location("fault_harness", _PATH)
assert _spec and _spec.loader
fh = importlib.util.module_from_spec(_spec)
sys.modules["fault_harness"] = fh
_spec.loader.exec_module(fh)


def test_harness_adds_nothing_to_src():
    src = (_PATH.parent.parent / "src").rglob("*.py")
    assert not [p for p in src if "OO_HARNESS" in p.read_text(encoding="utf-8", errors="replace")]


def test_leak_check_names_each_kind(tmp_path):
    text = f"x {fh.CANARY} y {tmp_path} z someone@example.com"
    kinds = " ".join(fh._leaks(text, tmp_path))
    assert "canary" in kinds and "path" in kinds
    assert not fh._leaks("nothing here", tmp_path)
    assert "e-mail" in " ".join(fh._leaks("a b@c.de", tmp_path))


def test_unknown_scenario_is_refused(capsys):
    assert fh.main(["no-such-scenario"]) == 2


def test_report_assertions_catch_a_missing_native_slot():
    rep = {"previous_session": {"exit_evidence": {"native_in_flight": {"result": "none-in-flight"}}, "previous_session_peaks": {"last_thread_census": {"os_threads": 3}}}}
    assert fh._assert_report("native-abort", rep)
    rep["previous_session"]["exit_evidence"]["native_in_flight"] = {"result": "in-flight", "counts": {"duckdb": 1}}
    assert not fh._assert_report("native-abort", rep)


@pytest.mark.skipif(os.environ.get("OO_FAULT_HARNESS") != "1", reason="slow: two real boots per scenario; set OO_FAULT_HARNESS=1")
@pytest.mark.parametrize("scenario", fh.SCENARIOS)
def test_scenario(scenario):
    assert fh.run_scenario(scenario) == []
