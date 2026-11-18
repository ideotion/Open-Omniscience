"""A test that hangs names itself (row 93), proven by running one.

The portability legs lost a whole Windows shard to one test that never returned: job 133057809613 stopped on a row of dots at 23% and was
cancelled at its 60-minute cap, with nothing naming the test. ``tests/conftest.py`` now arms faulthandler's watchdog for every test when
``OO_TEST_HANG_LIMIT_S`` is set; these tests run pytest in a child process on a probe that sleeps, and read what it left behind."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
_PROBE = "tests/test_hang_watchdog.py::test_the_probe_returns_at_once_unless_asked_to_hang"


_TEARDOWN_PROBE = "tests/test_hang_watchdog.py::test_the_probe_fails_and_then_hangs_in_teardown_when_asked"


def test_the_probe_returns_at_once_unless_asked_to_hang():
    if os.environ.get("OO_HANG_PROBE") == "1":
        time.sleep(120)
    assert os.environ.get("OO_HANG_PROBE") != "fail", "the probe was asked to fail\non two lines"


@pytest.fixture
def _teardown_that_hangs_when_asked():
    yield
    if os.environ.get("OO_HANG_PROBE") == "teardown":
        time.sleep(120)


def test_the_probe_fails_and_then_hangs_in_teardown_when_asked(_teardown_that_hangs_when_asked):
    assert os.environ.get("OO_HANG_PROBE") != "teardown"


def _run_probe(tmp_path: Path, *, hang: bool, probe: str = _PROBE, mode: str = "1") -> tuple[subprocess.CompletedProcess[str], Path, float]:
    report = tmp_path / "hang.txt"
    env = {**os.environ, "OO_TEST_HANG_LIMIT_S": "3", "OO_TEST_HANG_REPORT": str(report), "OO_HANG_PROBE": mode if hang else "0"}
    for key in ("PYTEST_XDIST_WORKER", "PYTEST_ADDOPTS", "OO_TEST_SLOW_S"):
        env.pop(key, None)
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", probe],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    return proc, report, time.monotonic() - started


def test_a_test_past_the_limit_ends_the_run_and_the_report_names_it_with_its_traceback(tmp_path):
    proc, report, elapsed = _run_probe(tmp_path, hang=True)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    text = report.read_text(encoding="utf-8")
    first = text.splitlines()[0]
    assert first == f"Running (limit 3 s): {_PROBE}", text
    assert "Timeout (" in text, "the CI step tells a hang from a cap by this line, which faulthandler writes only when the limit fires"
    # The traceback reaches the line the test is stuck on, so the report says WHERE, not only which test.
    assert "test_hang_watchdog.py" in text and "test_the_probe_returns_at_once_unless_asked_to_hang" in text.split("\n", 1)[1], text
    assert elapsed < 110, f"the watchdog did not end the run: {elapsed:.0f} s (the probe sleeps 120 s)"


def test_a_test_that_fails_and_then_hangs_in_teardown_is_still_caught(tmp_path):
    """pytest's faulthandler plugin cancels the timer when a phase fails; the conftest re-arms it, or this hang would run to the cap."""
    proc, report, elapsed = _run_probe(tmp_path, hang=True, probe=_TEARDOWN_PROBE, mode="teardown")
    text = report.read_text(encoding="utf-8")
    assert proc.returncode != 0 and "Timeout (" in text and text.startswith(f"Running (limit 3 s): {_TEARDOWN_PROBE}"), text
    assert elapsed < 110, f"the timer was not re-armed after the failure: {elapsed:.0f} s (the teardown sleeps 120 s)"


def test_the_report_variables_do_not_reach_a_child_pytest():
    """Read once and taken out of the environment, so a test that runs pytest in a child cannot empty this run's report files."""
    mine = {"OO_TEST_HANG_LIMIT_S", "OO_TEST_HANG_REPORT", "OO_TEST_SLOW_S", "OO_TEST_SLOW_REPORT", "OO_TEST_FAIL_REPORT"}
    assert not mine & set(os.environ)


def test_a_test_that_returns_leaves_the_report_empty(tmp_path):
    proc, report, _ = _run_probe(tmp_path, hang=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert report.read_text(encoding="utf-8") == "", "the report holds text after every test returned, so the CI step would name a hang that never happened"


@pytest.mark.parametrize("job_name", ["portability", "portability-windows"])
def test_the_portability_legs_arm_the_watchdog_and_print_its_report(job_name):
    job = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))["jobs"][job_name]
    steps = {s.get("name"): s for s in job["steps"]}
    test_step = steps["Test (pytest)"]
    limit = float(test_step["env"]["OO_TEST_HANG_LIMIT_S"])
    shortest_cap_s = 60 * min(int(n) for n in re.findall(r"\b(\d+)\b", str(job["timeout-minutes"])))
    assert 0 < limit * 3 <= shortest_cap_s, "the hang limit must sit well under the leg's cap, or the cap cancels first and names nothing"
    report = test_step["env"]["OO_TEST_HANG_REPORT"]
    printer = steps["Name a test that hung, and the slow tests"]
    assert printer.get("if") == "always()" and report in printer["run"] and "^Timeout (" in printer["run"]
    assert test_step["env"]["OO_TEST_SLOW_REPORT"] in printer["run"]
    assert test_step["env"]["OO_TEST_FAIL_REPORT"] in printer["run"], "a leg the cap stops never prints pytest's own failure list (row 109)"


def test_slow_tests_are_listed_as_they_end(tmp_path):
    report = tmp_path / "slow.txt"
    env = {**os.environ, "OO_TEST_SLOW_S": "0.000001", "OO_TEST_SLOW_REPORT": str(report), "OO_HANG_PROBE": "0"}
    for key in ("PYTEST_XDIST_WORKER", "PYTEST_ADDOPTS", "OO_TEST_HANG_LIMIT_S"):
        env.pop(key, None)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", _PROBE],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = report.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and lines[0].endswith(" s  " + _PROBE), lines


def test_a_failure_is_written_down_as_it_happens(tmp_path):
    """Row 109: a Windows leg the cap stopped showed some 170 F marks and no reason, because ``-rsfE`` prints only at the end."""
    report = tmp_path / "fail.txt"
    env = {**os.environ, "OO_TEST_FAIL_REPORT": str(report), "OO_HANG_PROBE": "fail"}
    for key in ("PYTEST_XDIST_WORKER", "PYTEST_ADDOPTS", "OO_TEST_HANG_LIMIT_S", "OO_TEST_SLOW_S"):
        env.pop(key, None)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", _PROBE],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    lines = report.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3 and lines[0] == f"FAILED (call) {_PROBE}", lines
    assert lines[1].strip().startswith("at ") and "test_hang_watchdog.py:" in lines[1], lines
    assert "the probe was asked to fail | on two lines" in lines[2], "the message is kept, on one line"


def _run_probe_in_workers(tmp_path: Path, mode: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Row 163: the portability legs run ``-n 4``; the controller takes the variables out of the environment, so they reach a worker only
    through ``workerinput``. Run the probe under ``-n 2`` and read what the WORKER wrote."""
    env = {
        **os.environ, "OO_TEST_HANG_LIMIT_S": "3", "OO_TEST_HANG_REPORT": str(tmp_path / "hang.txt"),
        "OO_TEST_SLOW_S": "0.000001", "OO_TEST_SLOW_REPORT": str(tmp_path / "slow.txt"),
        "OO_TEST_FAIL_REPORT": str(tmp_path / "fail.txt"), "OO_HANG_PROBE": mode,
    }
    for key in ("PYTEST_XDIST_WORKER", "PYTEST_ADDOPTS"):
        env.pop(key, None)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-n", "2", "--dist", "loadfile", _PROBE],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    return proc, tmp_path


def _worker_files(folder: Path, name: str) -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(folder.glob(name + ".gw*"))}


def test_under_xdist_the_worker_writes_the_slow_and_fail_reports_and_the_controller_writes_none(tmp_path):
    proc, folder = _run_probe_in_workers(tmp_path, "fail")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    for name in ("hang.txt", "slow.txt", "fail.txt"):
        assert not (folder / name).exists(), f"the controller runs no test, so it must not write {name} (the CI step would read it as the run's)"
    slow = [line for text in _worker_files(folder, "slow.txt").values() for line in text.splitlines()]
    assert len(slow) == 1 and slow[0].endswith(" s  " + _PROBE), _worker_files(folder, "slow.txt")
    fails = "".join(_worker_files(folder, "fail.txt").values())
    assert fails.startswith(f"FAILED (call) {_PROBE}\n"), fails
    hangs = _worker_files(folder, "hang.txt")
    assert hangs and all(text == "" for text in hangs.values()), "every worker was armed, and its file is empty after a test that returned"


def test_under_xdist_a_hang_ends_the_worker_and_its_file_names_the_test(tmp_path):
    proc, folder = _run_probe_in_workers(tmp_path, "1")
    assert proc.returncode != 0, proc.stdout + proc.stderr
    hung = [text for text in _worker_files(folder, "hang.txt").values() if "Timeout (" in text]
    assert len(hung) == 1 and hung[0].startswith(f"Running (limit 3 s): {_PROBE}"), _worker_files(folder, "hang.txt")
