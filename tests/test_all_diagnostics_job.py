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

import contextlib
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


def test_worker_sweeps_a_stale_part_from_a_previous_crashed_run(tiny_members):
    """A hard-kill between the .part open and the atomic rename leaves a stale .part; the next
    successful run must sweep it, so orphaned staging can't accumulate across crashes."""
    stale = tiny_members / "oo-all-diagnostics-20200101-000000.zip.part"
    stale.write_bytes(b"half a zip from a killed run")
    ctx = _Ctx()
    res = d._all_diagnostics_worker(ctx)
    assert os.path.exists(res["path"])
    assert not stale.exists(), "a stale .part from a previous crashed run must be swept"
    assert list(tiny_members.glob("*.part")) == []


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


# --------------------------------------------------------------------------- #
# DIAGNOSE-THE-DIAGNOSTICS (2026-07-20): the per-member ENVELOPE, the durable
# begin/end JOURNAL, per-member DEADLINES (DB inline vs non-DB threaded), and the
# manifest run HEADER (corpus counters / app version / schema head / hardware
# profile / runtime coverage). 0.3 gate row 3 tie-in: an hour-long 5M-scale run
# must be diagnosable FROM THE ARCHIVE ITSELF.
# --------------------------------------------------------------------------- #


def _open_zip_manifest(zip_bytes: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        names = set(z.namelist())
        manifest = json.loads(z.read("manifest.json"))
    return names, manifest


def test_envelope_carries_the_new_fields_and_keeps_ok_for_back_compat():
    """Point 1: every member records {file, ok, outcome, started_at, wall_s, bytes[,
    error]} -- `ok` stays a plain bool (True iff outcome == 'ok') for any reader still on
    the old boolean-only shape."""
    import io as _io
    import zipfile as _zipfile

    members = [
        ("good.json", lambda: {"x": 1}),
        ("bad.json", lambda: (_ for _ in ()).throw(RuntimeError("kaboom"))),
    ]
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as z:
        results = d._write_all_diagnostics_zip(members, z)
    by_file = {r["file"]: r for r in results}

    good = by_file["good.json"]
    assert good["ok"] is True and good["outcome"] == "ok"
    assert isinstance(good["started_at"], str) and good["started_at"]
    assert isinstance(good["wall_s"], float) and good["wall_s"] >= 0
    assert good["bytes"] > 0
    assert "error" not in good

    bad = by_file["bad.json"]
    assert bad["ok"] is False and bad["outcome"] == "error"
    assert "kaboom" in bad["error"]
    assert bad["bytes"] == 0


def test_db_touching_member_runs_inline_never_on_a_worker_thread():
    """Point 5 / S8: a member whose thunk closes over `db` (the _member_touches_db
    dispatch key, derived from the ACTUAL closure, not a hand-maintained list) must run
    INLINE on the calling thread -- a shared DB connection is unsafe to touch from a
    worker thread sharing it with the main event loop."""
    import io as _io
    import threading
    import zipfile as _zipfile

    db = "fake-db-session"  # not a real Session -- statement_deadline degrades to a no-op
    seen_thread: dict = {}

    def _db_member():
        seen_thread["name"] = threading.current_thread().name
        return {"touched": db}

    members = [("db-member.json", _db_member)]
    assert d._member_touches_db(_db_member) is True, "the lambda must close over `db`"

    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as z:
        results = d._write_all_diagnostics_zip(members, z, db=db)
    assert results[0]["outcome"] == "ok"
    assert seen_thread["name"] == threading.current_thread().name, (
        "a DB-touching member must run on the CALLING thread, never a spawned worker "
        f"thread (S8 lesson) -- ran on {seen_thread.get('name')!r}"
    )


def test_nondb_member_hung_past_its_deadline_is_skipped_honestly(monkeypatch):
    """Point 5: a NON-DB member (no `db` in its closure) that hangs past its wall-clock
    budget records outcome 'skipped-deadline' (never aborts the whole bundle) and the zip
    carries a <name>.skipped-deadline.txt marker instead of the report."""
    import io as _io
    import threading
    import zipfile as _zipfile

    monkeypatch.setenv("OO_ALL_DIAG_NONDB_MEMBER_DEADLINE_S", "0.05")

    hung = threading.Event()

    def _slow_member():
        hung.wait(5)  # far longer than the 0.05s budget; the thread is simply abandoned
        return {"never": "returned in time"}

    members = [("slow.json", _slow_member), ("fast.json", lambda: {"ok": 1})]
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as z:
        results = d._write_all_diagnostics_zip(members, z)
        names = set(z.namelist())
    hung.set()  # release the abandoned daemon thread so it doesn't linger past the test

    by_file = {r["file"]: r for r in results}
    assert by_file["slow.json"]["outcome"] == "skipped-deadline"
    assert by_file["slow.json"]["ok"] is False
    assert "slow.json.skipped-deadline.txt" in names
    assert "slow.json" not in names, "no partial/stale payload for a deadline-skipped member"
    assert by_file["fast.json"]["outcome"] == "ok", "one deadline-skip must not abort the bundle"


def test_db_member_statement_timeout_is_skipped_deadline_and_continues():
    """Point 5: a DB-touching member whose inline statement deadline fires (StatementTimeout,
    the S8 typed exception) is recorded as 'skipped-deadline', never 'error' -- and the bundle
    continues to the next member."""
    import io as _io
    import zipfile as _zipfile

    from src.database.maintenance import StatementTimeout

    db = "fake-db-session"

    def _timing_out_member():
        _ = db  # closes over `db` -- the dispatch key that routes this member INLINE
        raise StatementTimeout("statement exceeded the 300s deadline and was aborted")

    members = [("timeout.json", _timing_out_member), ("after.json", lambda: {"ok": 1})]
    assert d._member_touches_db(_timing_out_member) is True

    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as z:
        results = d._write_all_diagnostics_zip(members, z, db=db)
        names = set(z.namelist())
    by_file = {r["file"]: r for r in results}
    assert by_file["timeout.json"]["outcome"] == "skipped-deadline"
    assert "timeout.json.skipped-deadline.txt" in names
    assert by_file["after.json"]["outcome"] == "ok", "a DB timeout must not abort the bundle"


def test_journal_crash_forensics_last_begin_has_no_matching_end(tmp_path):
    """Point 2: simulates a HARD kill mid-member (an uncaught BaseException escaping the
    per-member guard, standing in for an OS-level SIGKILL that a real test cannot induce
    in-process) and asserts the journal sidecar -- fsync'd on every begin/end -- survives
    on disk with its last `begin` line unmatched by an `end`, naming the culprit member."""
    import io as _io
    import zipfile as _zipfile

    journal_path = tmp_path / "run.journal.jsonl"
    db = "fake-db-session"

    def _hard_kill_member():
        # Closes over `db` so this member is dispatched INLINE (on the calling thread) --
        # only an inline member can make a BaseException actually escape
        # _write_all_diagnostics_zip; a threaded non-DB member would just die silently
        # inside its own worker thread, which is not the crash this test is simulating.
        _ = db
        raise SystemExit(1)  # BaseException: escapes the per-member except-Exception guard

    members = [
        ("first.json", lambda: {"ok": 1}),
        ("killed.json", _hard_kill_member),
        ("never-reached.json", lambda: {"ok": 1}),
    ]
    buf = _io.BytesIO()
    with pytest.raises(SystemExit), _zipfile.ZipFile(buf, "w") as z:
        d._write_all_diagnostics_zip(members, z, journal_path=journal_path, db=db)

    assert journal_path.exists(), "the sidecar must survive on disk past the crash point"
    lines = [json.loads(ln) for ln in journal_path.read_text(encoding="utf-8").splitlines()]
    # first.json has a complete begin/end pair.
    first_events = [ln for ln in lines if ln["file"] == "first.json"]
    assert {e["event"] for e in first_events} == {"begin", "end"}
    # killed.json has ONLY a begin -- no matching end -- naming the culprit.
    killed_events = [ln for ln in lines if ln["file"] == "killed.json"]
    assert [e["event"] for e in killed_events] == ["begin"], (
        "the culprit member's `begin` must have no matching `end` after a hard kill"
    )
    # never-reached.json never even started.
    assert not any(ln["file"] == "never-reached.json" for ln in lines)


def test_journal_is_folded_into_the_zip_as_bundle_journal_on_completion():
    """Point 2: on a CLEAN finish the sidecar's content is folded into the archive as
    bundle-journal.jsonl (readable from the zip itself, no separate file to go find)."""
    import io as _io
    import zipfile as _zipfile

    journal_path = _all_diag_tmp_journal_path()
    try:
        members = [("a.json", lambda: {"x": 1})]
        buf = _io.BytesIO()
        with _zipfile.ZipFile(buf, "w") as z:
            d._write_all_diagnostics_zip(members, z, journal_path=journal_path)
            names = set(z.namelist())
        assert "bundle-journal.jsonl" in names
        with _zipfile.ZipFile(_io.BytesIO(buf.getvalue())) as z:
            journal_text = z.read("bundle-journal.jsonl").decode("utf-8")
        events = [json.loads(ln)["event"] for ln in journal_text.splitlines()]
        assert events == ["begin", "end"]
    finally:
        with contextlib.suppress(OSError):
            journal_path.unlink()


def _all_diag_tmp_journal_path():
    import tempfile
    from pathlib import Path

    fd, name = tempfile.mkstemp(suffix=".journal.jsonl")
    os.close(fd)
    Path(name).write_text("", encoding="utf-8")
    return Path(name)


def test_manifest_run_header_carries_corpus_version_schema_hardware_and_coverage():
    """Points 3+4: the manifest gains a `run` header -- corpus counters, app version,
    schema head, timestamps/total wall, a slowest-members summary, a hardware profile, and
    the runtime-recomputed coverage block -- alongside the untouched member list."""
    import io as _io
    import zipfile as _zipfile

    members = [
        ("slow.json", lambda: __import__("time").sleep(0.01) or {"x": 1}),
        ("fast.json", lambda: {"y": 2}),
    ]
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as z:
        d._write_all_diagnostics_zip(members, z)
    names, manifest = _open_zip_manifest(buf.getvalue())

    run = manifest["run"]
    assert isinstance(run["app_version"], str) and run["app_version"]
    assert isinstance(run["schema_head"], str) and run["schema_head"]
    assert run["corpus"] == {"available": False, "reason": "no database session"}
    assert run["started_at"] and run["ended_at"]
    assert run["total_wall_s"] >= 0
    assert run["slowest_members"][0]["file"] == "slow.json", "slowest-first ordering"
    assert "score" not in json.dumps(run) and "ranking" not in json.dumps(run)

    hw = run["hardware"]
    for key in (
        "os", "kernel", "cpu_model", "cpu_physical_cores", "cpu_logical_cores",
        "cpu_freq_mhz", "ram_total_bytes", "swap_total_bytes", "disk_free_bytes",
        "disk_rotational", "machine_label",
    ):
        assert key in hw, f"hardware profile missing {key}"

    cov = run["runtime_coverage"]
    assert cov["available"] is True
    assert cov["complete"] is True, f"runtime coverage recompute found a gap: {cov}"


def test_hardware_profile_machine_label_from_env(monkeypatch):
    monkeypatch.setenv("OO_MACHINE_LABEL", "old-thinkpad")
    assert d._hardware_profile()["machine_label"] == "old-thinkpad"


def test_hardware_profile_degrades_honestly_when_psutil_is_unavailable(monkeypatch):
    """Point 4: the psutil-derived fields must degrade to the honest string 'unavailable'
    -- never a fabricated number -- when psutil cannot be imported."""
    import sys as _sys

    monkeypatch.setitem(_sys.modules, "psutil", None)  # forces `import psutil` to raise
    hw = d._hardware_profile()
    for key in (
        "cpu_physical_cores", "cpu_logical_cores", "cpu_freq_mhz",
        "ram_total_bytes", "swap_total_bytes",
    ):
        assert hw[key] == "unavailable", f"{key} must degrade honestly, got {hw[key]!r}"
    # os/kernel/cpu_model/disk fields are independent of psutil and still present.
    assert hw["os"] and hw["kernel"]


def test_disk_rotational_probe_reports_unavailable_on_a_non_linux_platform(monkeypatch):
    """Point 4: the /sys/block probe is Linux-only; every other OS gets the honest
    'unavailable' string, never a guessed value."""
    import sys as _sys

    monkeypatch.setattr(_sys, "platform", "win32")
    assert d._disk_rotational_probe("/tmp") == "unavailable"


def test_cpu_model_degrades_honestly_when_unreadable(monkeypatch):
    import sys as _sys

    monkeypatch.setattr(_sys, "platform", "some-exotic-os")
    monkeypatch.setattr("platform.processor", lambda: "")
    assert d._cpu_model_safe() == "unavailable"


def test_sync_all_route_manifest_carries_the_run_header_too(tiny_members):
    """Absorption gate + run-header parity: the OLD synchronous /all route shares the same
    manifest-building path, so it also gets the run header (db=None degrades corpus
    counters honestly rather than crashing the absorption-gated route)."""
    resp = d.all_diagnostics(db=None)
    with zipfile.ZipFile(io.BytesIO(resp.body)) as z:
        manifest = json.loads(z.read("manifest.json"))
    assert manifest["run"]["corpus"]["available"] is False
    assert manifest["run"]["app_version"]


def test_corpus_counters_available_branch_counts_real_rows(tmp_path):
    """Point 3/9: the corpus-counters run-header field's AVAILABLE=True path (the actual
    articles/keywords/mentions COUNT query), not just the no-session degrade -- a real
    in-memory SQLite session with a couple of rows in each table."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Article, Base, Keyword, KeywordMention, Source

    eng = create_engine(f"sqlite:///{tmp_path / 'counters.db'}", future=True)
    Base.metadata.create_all(eng)
    Sess = sessionmaker(bind=eng, future=True)
    with Sess() as s:
        s.add(Source(name="Web", domain="w.test", source_type="news"))
        s.commit()
        s.add(Article(
            url="https://w.test/1", canonical_url="https://w.test/1", source_id=1,
            title="t", hash="h1", language="en", word_count=100, content="c",
        ))
        s.add(Keyword(term="climate", normalized_term="climate"))
        s.add(Keyword(term="election", normalized_term="election"))
        s.commit()
        s.add(KeywordMention(keyword_id=1, article_id=1, count=3))
        s.add(KeywordMention(keyword_id=2, article_id=1, count=1))
        s.commit()

        counters = d._corpus_counters_safe(s)
    assert counters == {
        "available": True, "articles": 1, "keywords": 2, "mentions": 2,
    }
