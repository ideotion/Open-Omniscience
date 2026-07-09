"""The all-diagnostics export as a background JOB (D2 / field-test Item 10, 36+ min blocking).

The old synchronous GET /api/diagnostics/all held a threadpool thread for the whole 36-min
build. These pin the job version: it builds the SAME members off the request thread to a
server-side file, reports per-member progress, cancels cooperatively between members, and
serves the finished file — AND the old sync route still works during the transition (the A2
contract lesson: a changed contract with an unwired UI mints false statements).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import io
import json
import os
import zipfile

import pytest

from src.api import diagnostics as d


class _Ctx:
    """A stub JobContext: records progress, reports a fixed stopping flag."""

    def __init__(self, stop: bool = False) -> None:
        self._stop = stop
        self.progress: list[tuple] = []

    @property
    def stopping(self) -> bool:
        return self._stop

    def set_progress(self, *, done=None, total=None, detail=None) -> None:
        self.progress.append((done, total, detail))


@pytest.fixture()
def tiny_members(monkeypatch, tmp_path):
    """Replace the (heavy, corpus-dependent) member set with fast deterministic stubs and
    redirect the output dir into a tmp dir, so the tests exercise the ORCHESTRATION, not the
    real 36-minute build."""
    def _boom():
        raise RuntimeError("this log failed")

    members = [
        ("a.json", lambda: {"x": 1}),
        ("bad.json", _boom),  # a failing member must not abort the bundle
        ("b.json", lambda: {"y": 2}),
    ]
    monkeypatch.setattr(d, "_all_diagnostics_members", lambda db: members)
    monkeypatch.setattr(d, "_all_diagnostics_dir", lambda: tmp_path)
    return tmp_path


def test_worker_builds_a_file_reports_progress_and_survives_a_failing_member(tiny_members):
    ctx = _Ctx()
    res = d._all_diagnostics_worker(ctx)

    assert os.path.exists(res["path"]), "the archive is a real server-side file"
    assert res["filename"].endswith(".zip") and res["bytes"] > 0
    with zipfile.ZipFile(res["path"]) as z:
        names = set(z.namelist())
        assert "a.json" in names and "b.json" in names and "manifest.json" in names
        assert "bad.json.error.txt" in names, "a failing member is recorded, never aborts"
        manifest = json.loads(z.read("manifest.json"))
        assert manifest["kind"] == "all-diagnostics"
        by_file = {m["file"]: m for m in manifest["members"]}
        assert by_file["bad.json"]["ok"] is False and by_file["a.json"]["ok"] is True
    # progress was reported per member + a final "done"
    details = [p[2] for p in ctx.progress]
    assert "a.json" in details and "done" in details
    # exactly one archive kept (old ones cleaned)
    assert len(list(tiny_members.glob("oo-all-diagnostics-*.zip"))) == 1
    assert list(tiny_members.glob("*.part")) == [], "no partial left behind"


def test_worker_cancel_between_members_leaves_no_served_file(tiny_members):
    ctx = _Ctx(stop=True)  # stopping from the start -> break before the first member
    res = d._all_diagnostics_worker(ctx)
    assert res.get("cancelled") is True
    assert list(tiny_members.glob("*.zip")) == [], "a cancelled build publishes no archive"
    assert list(tiny_members.glob("*.part")) == [], "the partial is cleaned up"


def test_sync_all_route_still_works_and_shares_the_same_members(tiny_members):
    """Absorption gate: the OLD synchronous /all still returns a valid archive built from the
    SAME members the job uses (single source of truth)."""
    resp = d.all_diagnostics(db=None)  # tiny_members ignore db
    assert resp.media_type == "application/zip"
    with zipfile.ZipFile(io.BytesIO(resp.body)) as z:
        names = set(z.namelist())
    assert {"a.json", "b.json", "manifest.json", "bad.json.error.txt"} <= names


def test_download_404_until_ready_then_serves(tiny_members):
    from fastapi import HTTPException

    job = d._ALL_DIAG_JOB
    with job._lock:  # force a clean, no-result state
        job._state = "idle"
        job._result = None
    with pytest.raises(HTTPException) as ei:
        d.all_diagnostics_job_download()
    assert ei.value.status_code == 404

    # A completed build: status reports ready, download serves the file.
    p = tiny_members / "oo-all-diagnostics-ready.zip"
    p.write_bytes(b"PK\x03\x04zip")
    with job._lock:
        job._state = "done"
        job._result = {"path": str(p), "filename": p.name, "bytes": p.stat().st_size}
    st = json.loads(bytes(d.all_diagnostics_job_status().body))
    assert st["ready"] is True and st["download_filename"] == p.name
    resp = d.all_diagnostics_job_download()
    assert resp.path == str(p) and resp.media_type == "application/zip"
    # reset so the shared singleton doesn't leak state into other tests
    with job._lock:
        job._state = "idle"
        job._result = None
