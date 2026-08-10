"""The all-diagnostics bundle must never become unreachable while it exists.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A field report said the built-in diagnostics "takes forever and then seems to stop".
Two independent defects produced that one sentence, and both are about a REACHABILITY
gap rather than about the build itself:

  * the watcher gave up after a fixed 1800 polls and said nothing, freezing the status on
    its last progress line -- covered behaviourally by tests/all_diag_poll_node_test.js,
    driven below;
  * the download gated on the IN-MEMORY job result, which dies with the process, so a
    finished multi-hour archive sitting in data_dir()/diagnostics/ answered 404.

The second is not hypothetical for this app: an OOM during a large import is exactly when
the operator most needs the bundle and least likely to still have the process that built it.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from src.api import diagnostics as D

_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_all_diagnostics_poll_node_suite() -> None:
    """Drives the ceiling with a fake clock and asserts what the operator ends up reading."""
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "all_diag_poll_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ok -" in proc.stdout


# --------------------------------------------------------------------------- #
# The download endpoint: a finished archive is never stranded
# --------------------------------------------------------------------------- #


@pytest.fixture()
def diag_dir(tmp_path, monkeypatch):
    """Point the archive directory at a tmp dir. Called directly (not through FastAPI),
    which is safe here only because this route declares no Query/Depends parameters --
    a route that did would need every one passed explicitly."""
    d = tmp_path / "diagnostics"
    d.mkdir()
    monkeypatch.setattr(D, "_all_diagnostics_dir", lambda: d)
    return d


def _job(state, **result):
    class _J:
        def status(self):
            return {"state": state, "result": dict(result) if result else None}

    return _J()


def _archive(d: Path, name: str, *, mtime: float, body: bytes = b"PK\x03\x04zip") -> Path:
    p = d / name
    p.write_bytes(body)
    import os

    os.utime(p, (mtime, mtime))
    return p


def test_the_running_jobs_own_result_is_served_when_it_has_one(diag_dir, monkeypatch):
    """The pre-existing path, unchanged: a completed job serves the file it published."""
    mine = _archive(diag_dir, "oo-all-diagnostics-20260810-120000.zip", mtime=1000)
    monkeypatch.setattr(
        D, "_ALL_DIAG_JOB", _job("done", path=str(mine), filename=mine.name, bytes=9)
    )
    resp = D.all_diagnostics_job_download()
    assert Path(resp.path) == mine


def test_a_finished_archive_survives_the_process_that_built_it(diag_dir, monkeypatch):
    """THE FIX. The job object is gone (app restarted); the archive is right there."""
    on_disk = _archive(diag_dir, "oo-all-diagnostics-20260810-120000.zip", mtime=1000)
    monkeypatch.setattr(D, "_ALL_DIAG_JOB", _job("idle"))

    resp = D.all_diagnostics_job_download()

    assert Path(resp.path) == on_disk, (
        "a finished archive on disk must be downloadable after a restart -- answering 404 "
        "about a file that exists strands hours of work at the moment it is most needed"
    )


def test_the_newest_archive_wins(diag_dir, monkeypatch):
    _archive(diag_dir, "oo-all-diagnostics-20260809-090000.zip", mtime=1000)
    newer = _archive(diag_dir, "oo-all-diagnostics-20260810-120000.zip", mtime=2000)
    monkeypatch.setattr(D, "_ALL_DIAG_JOB", _job("idle"))
    assert Path(D.all_diagnostics_job_download().path) == newer


def test_a_stale_archive_is_never_served_as_a_running_builds_output(diag_dir, monkeypatch):
    """THE NEGATIVE-SPACE TWIN, and the reason the fallback is conditional.

    The operator asked the NEW run a question. The previous run's archive cannot answer it,
    and handing it over silently would be a fabricated result -- the one thing a diagnostic
    must not produce. So while a build is RUNNING the endpoint still refuses, even though a
    perfectly readable archive is sitting next to it.
    """
    _archive(diag_dir, "oo-all-diagnostics-20260809-090000.zip", mtime=1000)
    monkeypatch.setattr(D, "_ALL_DIAG_JOB", _job("running"))

    with pytest.raises(HTTPException) as exc:
        D.all_diagnostics_job_download()
    assert exc.value.status_code == 404


def test_a_part_file_is_never_served(diag_dir, monkeypatch):
    """An in-flight or abandoned build. Serving a truncated zip to someone already trying
    to diagnose something is the worst available answer."""
    _archive(diag_dir, "oo-all-diagnostics-20260810-120000.zip.part", mtime=2000)
    monkeypatch.setattr(D, "_ALL_DIAG_JOB", _job("idle"))

    with pytest.raises(HTTPException) as exc:
        D.all_diagnostics_job_download()
    assert exc.value.status_code == 404
    assert D._newest_all_diagnostics_archive() is None


def test_nothing_on_disk_still_404s(diag_dir, monkeypatch):
    monkeypatch.setattr(D, "_ALL_DIAG_JOB", _job("idle"))
    with pytest.raises(HTTPException) as exc:
        D.all_diagnostics_job_download()
    assert exc.value.status_code == 404


def test_a_missing_directory_is_a_none_not_a_crash(monkeypatch, tmp_path):
    """The helper degrades: a diagnostics dir that cannot be listed is an absence."""
    monkeypatch.setattr(D, "_all_diagnostics_dir", lambda: tmp_path / "nope")
    assert D._newest_all_diagnostics_archive() is None


# --------------------------------------------------------------------------- #
# Both pollers, scoped to their own bodies
# --------------------------------------------------------------------------- #


def test_neither_poller_can_exit_without_saying_something():
    """A fixed-iteration loop that falls out silently is the defect class, and it existed
    in BOTH job pollers. The node suite proves the behaviour for the all-diagnostics one;
    this pins the P0 poller too, which has no DOM harness, and is scoped to each function's
    own body so it cannot be satisfied by the other one.
    """
    from tests.js_source_helper import function_body, read_static, strip_comments

    app = read_static("app.js")
    for fn in ("runAllDiagnostics", "runP0Validation"):
        body = strip_comments(function_body(app, fn))
        assert "if (!settled) set(" in body, (
            f"{fn} must report an outcome when its loop ends without a terminal job state; "
            "otherwise the last progress line stands as though it were the result"
        )
        assert "settled = true" in body, f"{fn} must latch its terminal branches"
