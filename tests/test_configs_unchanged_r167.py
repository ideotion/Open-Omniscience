"""A run that changes the checkout's configs/ fails, naming the file (row 167).

Under ``-n`` every worker reads the catalogues under configs/ while the others run, and the seeder picks them by
``Path.exists()``: a test that wrote there, even for a moment, would change what another process seeds on some runs only.
``tests/conftest.py`` fingerprints configs/ when each session starts and ends. These tests point it at a scratch folder
(``OO_TEST_CONFIGS_GUARD_DIR``) and run pytest in a child process on a probe that writes there when asked."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_PROBE = "tests/test_configs_unchanged_r167.py::test_the_probe_writes_into_the_guarded_folder_only_when_asked"


def test_the_probe_writes_into_the_guarded_folder_only_when_asked():
    action = os.environ.get("OO_CONFIGS_PROBE")
    folder = Path(os.environ.get("OO_TEST_CONFIGS_GUARD_DIR") or "")
    if action == "write":
        (folder / "catalogue.yml").write_text("sources: []\n", encoding="utf-8")
    elif action == "add":
        (folder / "new.yml").write_text("sources: []\n", encoding="utf-8")


def _run(tmp_path: Path, action: str, *extra: str) -> subprocess.CompletedProcess[str]:
    guarded = tmp_path / "configs"
    guarded.mkdir()
    (guarded / "catalogue.yml").write_text("sources:\n  - {name: A, domain: a.example}\n", encoding="utf-8")
    env = {**os.environ, "OO_TEST_CONFIGS_GUARD_DIR": str(guarded), "OO_CONFIGS_PROBE": action}
    for key in ("PYTEST_XDIST_WORKER", "PYTEST_ADDOPTS"):
        env.pop(key, None)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *extra, _PROBE],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
    )


def test_a_run_that_leaves_configs_alone_passes(tmp_path):
    proc = _run(tmp_path, "none", "-p", "no:xdist")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "changed the checkout's configs/" not in proc.stdout + proc.stderr


def test_a_run_that_rewrites_a_catalogue_fails_and_names_it(tmp_path):
    proc = _run(tmp_path, "write", "-p", "no:xdist")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out
    assert "changed the checkout's configs/ during this run (row 167): catalogue.yml (changed)" in out, out


def test_under_xdist_a_file_added_by_a_worker_fails_the_run(tmp_path):
    proc = _run(tmp_path, "add", "-n", "2")
    out = proc.stdout + proc.stderr
    assert proc.returncode == 1, out
    assert "new.yml (added)" in out, out
