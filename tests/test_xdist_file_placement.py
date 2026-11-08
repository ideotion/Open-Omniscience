"""The suite's ``--dist loadfile`` placement (tests/_xdist_placement.py) is fixed: same files and workers, same placement, every run.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why it exists: xdist's own loadfile hands the next file to the first free worker, so which files share a process moved with the runner's timing,
and two full runs at one commit (2026-11-08) went red on two different sets of order-dependent tests. CI's full-suite jobs run
``-n auto --dist loadfile`` (tests/test_ci_pytest_flags_and_preflight.py pins the line), and tests/conftest.py swaps the scheduler in.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests._xdist_placement import place

_ROOT = Path(__file__).resolve().parents[1]


def test_longest_first_to_the_least_loaded_worker_whatever_the_order_given():
    costs = {"a.py": 1.0, "b.py": 10.0, "c.py": 4.0, "d.py": 9.0, "e.py": 5.0}
    # b=10 -> 0; d=9 -> 1; e=5 -> 2; c=4 -> 2 (5 < 9 < 10); a=1 -> 1 (loads 10, 9, 9: the tie goes to the lower worker).
    want = {"b.py": 0, "d.py": 1, "e.py": 2, "c.py": 2, "a.py": 1}
    assert place(list(costs), 3, costs) == want
    assert place(list(reversed(list(costs))), 3, costs) == want, "the order the files arrive in must not move one"


def test_an_unlisted_file_weighs_the_median_and_every_file_lands_once():
    costs = {"a.py": 1.0, "b.py": 3.0, "c.py": 100.0}
    out = place(["a.py", "b.py", "c.py", "new.py", "new.py"], 2, costs)
    assert sorted(out) == ["a.py", "b.py", "c.py", "new.py"]
    assert out["c.py"] == 0 and out["new.py"] == 1 and out["b.py"] == 1, out


def test_more_workers_than_files_leaves_the_rest_empty_rather_than_failing():
    assert place(["a.py"], 4, {}) == {"a.py": 0}


def test_the_conftest_hook_takes_only_loadfile():
    import tests.conftest as c

    class _Cfg:
        def __init__(self, dist):
            self._dist = dist

        def getvalue(self, name):
            assert name == "dist"
            return self._dist

    assert c.pytest_xdist_make_scheduler(_Cfg("load"), None) is None
    assert c.pytest_xdist_make_scheduler(_Cfg("worksteal"), None) is None


def test_a_real_run_announces_the_fixed_placement():
    """The swap is said in the log, so a reader never takes it for xdist's own loadfile; and a run through it passes."""
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-n", "2", "--dist", "loadfile", "-p", "no:cacheprovider",
         "tests/test_xdist_file_placement.py", "-k", "longest_first or median"],
        cwd=_ROOT, capture_output=True, text=True, timeout=300,
    )
    assert out.returncode == 0, out.stdout[-3000:] + out.stderr[-3000:]
    assert "fixed file placement" in out.stdout, out.stdout[-2000:]
    assert "2 passed" in out.stdout, out.stdout[-2000:]
