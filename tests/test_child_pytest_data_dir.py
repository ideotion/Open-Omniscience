"""A pytest that a test starts in a child process never runs on its parent's live data directory (row 218).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``tests/test_search_advanced_fixture_order.py`` runs one case in a fresh ``python -m pytest`` with the whole environment passed on. The
conftest gave a new process its own directory only when it was an xdist worker that had inherited the CONTROLLER's, so this child kept
the worker's own ``OO_DATA_DIR`` and booted the app on that worker's live database from a second process (eleven files appeared in it,
``open_omniscience.db`` among them). On macOS shard 3 the worker's later tests then failed with "disk I/O error" on every new connection,
on two unrelated PRs on 2026-11-20. Red before the conftest change, in a plain run and under xdist alike: the child named the parent's
directory and wrote into it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import tests.conftest as conftest

ROOT = Path(__file__).resolve().parent.parent

_CHILD = '''
import os
from pathlib import Path


def test_report_the_directory(tmp_path):
    here = Path(os.environ["OO_DATA_DIR"])
    (here / "child-was-here.txt").write_text("x", encoding="utf-8")
    Path(os.environ["CHILD_REPORT"]).write_text(str(here), encoding="utf-8")
'''


def _run_child(tmp_path: Path, env: dict[str, str]) -> tuple[subprocess.CompletedProcess, Path]:
    child = tmp_path / "child"
    child.mkdir()
    (child / "test_child.py").write_text(textwrap.dedent(_CHILD), encoding="utf-8")
    report = tmp_path / "report.txt"
    env = {**env, "CHILD_REPORT": str(report)}
    env.pop("PYTEST_ADDOPTS", None)
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "tests.conftest", "--rootdir", str(child), str(child)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    return done, report


def test_a_child_pytest_with_the_whole_environment_takes_its_own_directory(tmp_path):
    """The shape of tests/test_search_advanced_fixture_order.py: everything inherited, the worker's variables included."""
    parent = Path(conftest._SUITE_DATA_DIR)
    assert os.environ["OO_DATA_DIR"] == conftest._SUITE_DATA_DIR, "the suite still runs on the directory it started on"
    done, report = _run_child(tmp_path, dict(os.environ))
    assert done.returncode == 0, (done.stdout + done.stderr)[-2000:]
    used = Path(report.read_text(encoding="utf-8"))
    assert used.resolve() != parent.resolve(), f"the child ran on its parent's live directory {parent}"
    assert not (parent / "child-was-here.txt").exists(), "the child wrote into its parent's live directory"


def test_a_directory_the_caller_chose_is_still_kept(tmp_path):
    """Only an inherited suite default is replaced: a directory set on purpose (CI, a scenario, a test's tmp_path) stays."""
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    done, report = _run_child(tmp_path, {**os.environ, "OO_DATA_DIR": str(chosen)})
    assert done.returncode == 0, (done.stdout + done.stderr)[-2000:]
    assert Path(report.read_text(encoding="utf-8")).resolve() == chosen.resolve()
