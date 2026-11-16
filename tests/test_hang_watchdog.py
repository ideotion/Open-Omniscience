"""A test that hangs names itself (row 93), proven by running one.

The portability legs lost a whole Windows shard to one test that never returned: job 133057809613 stopped on a row of dots at 23% and was
cancelled at its 60-minute cap, with nothing naming the test. ``tests/conftest.py`` now arms faulthandler's watchdog for every test when
``OO_TEST_HANG_LIMIT_S`` is set; these tests run pytest in a child process on a probe that sleeps, and read what it left behind."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
_PROBE = "tests/test_hang_watchdog.py::test_the_probe_returns_at_once_unless_asked_to_hang"


def test_the_probe_returns_at_once_unless_asked_to_hang():
    if os.environ.get("OO_HANG_PROBE") == "1":
        time.sleep(120)


def _run_probe(tmp_path: Path, *, hang: bool) -> tuple[subprocess.CompletedProcess[str], Path, float]:
    report = tmp_path / "hang.txt"
    env = {**os.environ, "OO_TEST_HANG_LIMIT_S": "3", "OO_TEST_HANG_REPORT": str(report), "OO_HANG_PROBE": "1" if hang else "0"}
    env.pop("PYTEST_XDIST_WORKER", None)
    env.pop("PYTEST_ADDOPTS", None)
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", _PROBE],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    return proc, report, time.monotonic() - started


def test_a_test_past_the_limit_ends_the_run_and_the_report_names_it_with_its_traceback(tmp_path):
    proc, report, elapsed = _run_probe(tmp_path, hang=True)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    text = report.read_text(encoding="utf-8")
    first = text.splitlines()[0]
    assert first.startswith("Test still running after 3 s, so the run was ended: ") and first.endswith(_PROBE), text
    # The traceback reaches the line the test is stuck on, so the report says WHERE, not only which test.
    assert "test_hang_watchdog.py" in text and "test_the_probe_returns_at_once_unless_asked_to_hang" in text.split("\n", 1)[1], text
    assert elapsed < 110, f"the watchdog did not end the run: {elapsed:.0f} s (the probe sleeps 120 s)"


def test_a_test_that_returns_leaves_the_report_empty(tmp_path):
    proc, report, _ = _run_probe(tmp_path, hang=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert report.read_text(encoding="utf-8") == "", "the report holds text after every test returned, so the CI step would name a hang that never happened"


def test_the_portability_legs_arm_the_watchdog_and_print_its_report():
    job = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))["jobs"]["portability"]
    steps = {s.get("name"): s for s in job["steps"]}
    test_step = steps["Test (pytest)"]
    limit = float(test_step["env"]["OO_TEST_HANG_LIMIT_S"])
    assert 0 < limit * 3 <= job["timeout-minutes"] * 60, "the hang limit must sit well under the leg's cap, or the cap cancels first and names nothing"
    report = test_step["env"]["OO_TEST_HANG_REPORT"]
    printer = steps["Name the test that hung (if one did)"]
    assert printer.get("if") == "always()" and report in printer["run"]
