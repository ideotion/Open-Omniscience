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
from src.api.diagnostics import bundle as _diag_bundle
from tests.diagnostics_source import diagnostics_source


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
    monkeypatch.setattr(_diag_bundle, "_all_diagnostics_members", lambda db: members)
    monkeypatch.setattr(_diag_bundle, "_all_diagnostics_dir", lambda: tmp_path)
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


# --------------------------------------------------------------------------- #
#  a member call site must pass every FastAPI-defaulted argument EXPLICITLY
# --------------------------------------------------------------------------- #
def test_no_member_call_site_leaves_a_Query_default_unpassed():
    """Field bundle 2026-08-02: `run-journal.json` died with "slice indices must be
    integers or None" -- `_all_diagnostics_members` called `run_journal(download=False)`
    without `limit`, so the Query(20) SENTINEL OBJECT reached `list_runs()[:limit]`.

    The repo already carried this lesson from `ai.json` (an unresolved Depends is a
    sentinel, and Query(False) is TRUTHY), but the guard written then was specific to
    that one member. Two further call sites were wrong at the same moment and nothing
    said so. This is the general form: EVERY route called directly from the member list
    must be handed every argument FastAPI would otherwise resolve.

    Structural on purpose -- it compares each CALL against the callee's real SIGNATURE,
    which is the composition the "a wiring test must compose the actual route" lesson
    asks for. Checking a signature alone would pass while the call was broken, which is
    exactly how this shipped.
    """
    import ast
    import re

    # Q1139 split: `inspect.getsource(package)` returns only `__init__.py`. The shared
    # reader concatenates every slice, which is what this guard has to search.
    src = diagnostics_source()
    tree = ast.parse(src)

    fastapi_defaults: dict[str, list[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        a = node.args
        names = a.args + a.kwonlyargs
        defaults = (
            [None] * (len(a.args) - len(a.defaults)) + list(a.defaults) + list(a.kw_defaults)
        )
        sentinels = [
            arg.arg
            for arg, dflt in zip(names, defaults, strict=False)
            if isinstance(dflt, ast.Call)
            and getattr(getattr(dflt, "func", None), "id", None)
            in ("Query", "Body", "Form", "File", "Depends")
        ]
        if sentinels:
            fastapi_defaults[node.name] = sentinels

    block = src.split("def _all_diagnostics_members", 1)[1].split("\ndef ", 1)[0]
    offenders = []
    for m in re.finditer(r'\("([^"]+)",\s*lambda:\s*([\w_]+)\(([^)]*)\)', block):
        member, fn, argstr = m.group(1), m.group(2), m.group(3)
        if fn not in fastapi_defaults:
            continue
        passed = set(re.findall(r"(\w+)\s*=", argstr))
        missing = [p for p in fastapi_defaults[fn] if p not in passed]
        if missing:
            offenders.append(f"{member} -> {fn}() missing {', '.join(missing)}")

    assert not offenders, (
        "these bundle members call a route directly without passing an argument FastAPI "
        "would have resolved; the unresolved default is a sentinel OBJECT, not its "
        "apparent value:\n  " + "\n  ".join(offenders)
    )


def test_an_unserialisable_leaf_is_marked_in_place_not_thrown_away():
    """`card-audit.json` ran 2,396 s -- 41% of the whole bundle -- and then raised
    "Object of type Query is not JSON serializable" at the ENCODE step, discarding all
    40 minutes of it. One bad leaf must never destroy an expensive report, and the
    marker has to NAME the type so the offending producer is identifiable from the
    artefact instead of by spending the 40 minutes again."""

    class _Weird:
        pass

    payload = {"ok": 1, "nested": {"bad": _Weird(), "fine": "text"}}
    out = json.loads(d._member_bytes(payload))
    assert out["ok"] == 1, "the rest of the report survives"
    assert out["nested"]["fine"] == "text"
    bad = out["nested"]["bad"]
    assert bad[d._UNSERIALISABLE] is True
    assert bad["type"] == "_Weird", "the type is named, so the leak is locatable"


def test_an_unserialisable_leaf_is_never_silently_stringified():
    """`default=str` would have written "<Query object at 0x7f...>" into the report as
    if it were a string field -- a reader could not tell it from real data. A value that
    could not be encoded must be distinguishable from one that was."""

    class _Weird:
        def __str__(self) -> str:
            return "totally normal text"

    out = json.loads(d._member_bytes({"x": _Weird()}))
    assert out["x"] != "totally normal text"
    assert isinstance(out["x"], dict) and out["x"][d._UNSERIALISABLE] is True


# --------------------------------------------------------------------------- #
#  A killed run's journal rides the NEXT bundle (field diagnostics 2026-09-30, B4)
# --------------------------------------------------------------------------- #
def _dead_run_journal(directory, stamp, *, unfinished=None, finished=("a.json",), tail=""):
    """A journal as a hard-killed run leaves it: complete begin/end pairs, then a `begin` with no
    `end` (``unfinished``), then optionally a torn line (``tail``)."""
    path = directory / f"oo-all-diagnostics-{stamp}.zip.journal.jsonl"
    lines = []
    for i, name in enumerate(finished):
        lines.append({"event": "begin", "file": name, "i": i, "total": 9, "started_at": f"2026-09-30T07:0{i}:00"})
        lines.append({"event": "end", "file": name, "outcome": "ok", "wall_s": 1.5})
    if unfinished:
        lines.append({"event": "begin", "file": unfinished, "i": len(finished), "total": 9,
                      "started_at": "2026-09-30T07:10:00"})
    path.write_text("".join(json.dumps(x) + "\n" for x in lines) + tail, encoding="utf-8")
    return path


def test_the_member_running_at_the_kill_is_named_in_the_next_bundle(tiny_members):
    """THE DEFECT: the next run swept the dead run's journal, so the culprit never reached a
    maintainer. Now the worker reads it first; the journal is marked, and the manifest names it."""
    _dead_run_journal(tiny_members, "20260930-070500", unfinished="keyword-log-digest.json")
    res = d._all_diagnostics_worker(_Ctx())
    with zipfile.ZipFile(res["path"]) as z:
        manifest = json.loads(z.read("manifest.json"))
        journal = [json.loads(ln) for ln in z.read("bundle-journal.jsonl").decode().splitlines()]
    prev = manifest["run"]["previous_runs"]
    assert len(prev) == 1
    assert prev[0]["journal"] == "oo-all-diagnostics-20260930-070500.zip.journal.jsonl"
    assert prev[0]["unfinished"] == ["keyword-log-digest.json"]
    assert prev[0]["members_begun"] == 2 and prev[0]["members_ended"] == 1
    assert prev[0]["outcomes"] == {"ok": 1} and prev[0]["started_at"] == "2026-09-30T07:00:00"
    marked = [r for r in journal if r.get("previous_run")]
    assert marked and all(r["previous_run"] == prev[0]["journal"] for r in marked)
    assert [r["event"] for r in marked][-1] == "begin" and marked[-1]["file"] == "keyword-log-digest.json"
    # This run's own lines follow, unmarked, and are still complete pairs.
    own = [r for r in journal if "previous_run" not in r]
    assert [r["event"] for r in own if r["file"] == "a.json"] == ["begin", "end"]
    assert journal.index(marked[-1]) < journal.index(own[0]), "a dead run's lines come first"
    # The sidecar is swept only AFTER it has been carried.
    assert list(tiny_members.glob("*.journal.jsonl")) == []


def test_a_run_with_no_dead_predecessor_says_it_looked(tiny_members):
    res = d._all_diagnostics_worker(_Ctx())
    with zipfile.ZipFile(res["path"]) as z:
        manifest = json.loads(z.read("manifest.json"))
        journal = z.read("bundle-journal.jsonl").decode()
    assert manifest["run"]["previous_runs"] == []
    assert "previous_run" not in journal, "no dead run, no marked line: the file is as it was"
    assert "previous_runs_not_carried" not in manifest["run"]


def test_the_in_memory_route_has_no_journal_and_does_not_pretend_to_have_looked():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        d._write_all_diagnostics_zip([("a.json", lambda: {"x": 1})], z)
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
        manifest = json.loads(z.read("manifest.json"))
        assert "bundle-journal.jsonl" not in z.namelist()
    assert "previous_runs" not in manifest["run"], "absent means nothing looked; [] means it did"


def test_a_torn_last_line_is_kept_as_evidence_not_dropped(tiny_members):
    """A kill can land in the middle of a write. The fragment is itself part of the record."""
    fragment = '{"event": "end", "fi'
    _dead_run_journal(tiny_members, "20260930-070500", unfinished="x.json", tail=fragment)
    res = d._all_diagnostics_worker(_Ctx())
    with zipfile.ZipFile(res["path"]) as z:
        manifest = json.loads(z.read("manifest.json"))
        journal = [json.loads(ln) for ln in z.read("bundle-journal.jsonl").decode().splitlines()]
    assert manifest["run"]["previous_runs"][0]["unparsed_lines"] == 1
    torn = [r for r in journal if r.get("event") == "unparsed"]
    assert len(torn) == 1 and torn[0]["raw"] == fragment and torn[0]["chars"] == len(fragment)
    assert torn[0]["previous_run"].startswith("oo-all-diagnostics-20260930-070500")


def test_an_unparsed_line_keeps_its_first_200_characters_and_says_how_long_it_was(tiny_members):
    """The record of a torn line is bounded: the head is kept, the length says how much was not."""
    long_tail = '{"event": "end", "file": "' + "z" * 700
    _dead_run_journal(tiny_members, "20260930-070500", unfinished="x.json", tail=long_tail)
    res = d._all_diagnostics_worker(_Ctx())
    with zipfile.ZipFile(res["path"]) as z:
        journal = [json.loads(ln) for ln in z.read("bundle-journal.jsonl").decode().splitlines()]
    (torn,) = [r for r in journal if r.get("event") == "unparsed"]
    assert len(torn["raw"]) == 200 and torn["raw"] == long_tail[:200]
    assert torn["chars"] == min(len(long_tail), d._PREVIOUS_JOURNAL_MAX_LINE_CHARS)


def test_several_dead_runs_are_carried_oldest_first_and_the_cap_names_what_it_leaves(
    tiny_members, monkeypatch
):
    monkeypatch.setattr(_diag_bundle, "_PREVIOUS_JOURNAL_MAX_RUNS", 3)
    for day in range(1, 6):  # five dead runs: 1..5, oldest first by name
        _dead_run_journal(tiny_members, f"2026090{day}-000000", unfinished=f"m{day}.json")
    res = d._all_diagnostics_worker(_Ctx())
    with zipfile.ZipFile(res["path"]) as z:
        run = json.loads(z.read("manifest.json"))["run"]
    carried = [r["journal"] for r in run["previous_runs"]]
    assert carried == [f"oo-all-diagnostics-2026090{n}-000000.zip.journal.jsonl" for n in (3, 4, 5)], (
        "the newest deaths are kept, in chronological order"
    )
    left = [r["journal"] for r in run["previous_runs_not_carried"]]
    assert left == [f"oo-all-diagnostics-2026090{n}-000000.zip.journal.jsonl" for n in (2, 1)]
    assert all(r["bytes"] > 0 for r in run["previous_runs_not_carried"])


def test_an_oversize_journal_keeps_its_tail_where_the_last_begin_is(tiny_members, monkeypatch):
    monkeypatch.setattr(_diag_bundle, "_PREVIOUS_JOURNAL_MAX_BYTES", 400)
    _dead_run_journal(
        tiny_members, "20260930-070500", unfinished="the-culprit.json",
        finished=tuple(f"member-{i}.json" for i in range(12)),
    )
    res = d._all_diagnostics_worker(_Ctx())
    with zipfile.ZipFile(res["path"]) as z:
        prev = json.loads(z.read("manifest.json"))["run"]["previous_runs"][0]
    assert prev["truncated"] is True and prev["bytes"] > 400
    assert prev["unfinished"] == ["the-culprit.json"], "the kill evidence is at the END of the file"
    assert prev["unparsed_lines"] == 0, "the line a tail read starts in the middle of is dropped, not kept"
    with zipfile.ZipFile(res["path"]) as z:
        carried = [
            json.loads(ln) for ln in z.read("bundle-journal.jsonl").decode().splitlines()
            if "previous_run" in ln
        ]
    # THE BOUND ON BYTES READ, observed on the output: the head of the file (a sentinel) must not
    # be in what was carried, or the cap read the whole file and only claimed to have truncated.
    assert all(r.get("file") != "member-0.json" for r in carried)
    assert carried[-1]["file"] == "the-culprit.json"


def test_a_cancelled_run_leaves_the_dead_runs_journal_for_the_next_one(tiny_members):
    """Only a run that publishes an archive carrying the journal may delete it."""
    kept = _dead_run_journal(tiny_members, "20260930-070500", unfinished="x.json")
    res = d._all_diagnostics_worker(_Ctx(stop=True))
    assert res.get("cancelled") is True
    assert kept.exists(), "a cancelled run carried nothing out, so it must delete nothing"


def test_this_runs_own_journal_is_never_read_as_a_predecessor(tmp_path):
    own = _dead_run_journal(tmp_path, "20260930-080000", unfinished="x.json")
    other = _dead_run_journal(tmp_path, "20260930-070000", unfinished="y.json")
    got = _diag_bundle._read_previous_run_journals(tmp_path, own)
    assert [c["journal"] for c in got["carried"]] == [other.name]
    assert got["not_carried"] == []


def test_a_missing_directory_carries_nothing(tmp_path):
    got = _diag_bundle._read_previous_run_journals(tmp_path / "missing", tmp_path / "x.journal.jsonl")
    assert got == {"carried": [], "not_carried": []}


def test_a_reader_that_fails_costs_the_bundle_nothing_and_says_so(tiny_members, monkeypatch):
    """Whatever goes wrong reading the left-overs, THIS bundle is still written, and the manifest
    says the read failed (an empty list would claim it looked and found none)."""
    def _boom(out_dir, own):
        raise PermissionError("denied")

    monkeypatch.setattr(_diag_bundle, "_read_previous_run_journals", _boom)
    res = d._all_diagnostics_worker(_Ctx())
    with zipfile.ZipFile(res["path"]) as z:
        run = json.loads(z.read("manifest.json"))["run"]
    assert run["previous_runs"] == []
    assert run["previous_runs_error"].startswith("PermissionError")


def test_a_fold_that_fails_costs_the_bundle_nothing_and_says_so(tiny_members, monkeypatch):
    _dead_run_journal(tiny_members, "20260930-070500", unfinished="x.json")

    def _boom(previous):
        raise RuntimeError("fold broke")

    monkeypatch.setattr(_diag_bundle, "_fold_previous_run_journals", _boom)
    res = d._all_diagnostics_worker(_Ctx())
    with zipfile.ZipFile(res["path"]) as z:
        run = json.loads(z.read("manifest.json"))["run"]
        journal = z.read("bundle-journal.jsonl").decode()
    assert run["previous_runs_error"].startswith("RuntimeError")
    assert "previous_run" not in journal


_KEY = "p4ss'phrase\\with"   # an apostrophe and a backslash; the manifest clips to ASCII, which would rewrite a letter outside it


def test_the_two_failure_texts_of_the_left_over_read_and_fold_never_carry_the_passphrase(tiny_members, monkeypatch):
    """Coordinator's check of the second error-text fold: the manifest's ``previous_runs_error`` and
    the block a failed fold leaves are made from an exception's words, like every member's, and an
    engine's words can carry the statement it failed on (here in two of the forms it is written in)."""
    from src.database import connect as _connect

    monkeypatch.setattr(_connect, "_passphrase", _KEY)
    forms = (_KEY, _KEY.replace("'", "''"))
    _dead_run_journal(tiny_members, "20260930-070500", unfinished="x.json")
    real_read = _diag_bundle._read_previous_run_journals

    def _read_boom(out_dir, own):
        raise PermissionError(f"denied: PRAGMA key = '{forms[1]}'")

    monkeypatch.setattr(_diag_bundle, "_read_previous_run_journals", _read_boom)
    res = d._all_diagnostics_worker(_Ctx())
    with zipfile.ZipFile(res["path"]) as z:
        read_text = json.loads(z.read("manifest.json"))["run"]["previous_runs_error"]
    # parsed, not searched in the encoded file: JSON writes a backslash and a letter outside ASCII
    # differently, so a search of the raw bytes would pass for a text that still carries the key
    assert read_text.startswith("PermissionError: denied") and all(f not in read_text for f in forms)

    def _fold_boom(previous):
        raise RuntimeError(f"fold broke [SQL: PRAGMA key = '{forms[1]}']")

    monkeypatch.setattr(_diag_bundle, "_read_previous_run_journals", real_read)
    _dead_run_journal(tiny_members, "20260930-080500", unfinished="x.json")
    monkeypatch.setattr(_diag_bundle, "_fold_previous_run_journals", _fold_boom)
    res = d._all_diagnostics_worker(_Ctx())
    with zipfile.ZipFile(res["path"]) as z:
        fold_text = json.loads(z.read("manifest.json"))["run"]["previous_runs_error"]
    assert fold_text.startswith("RuntimeError: fold broke") and all(f not in fold_text for f in forms)


# --------------------------------------------------------------------------- #
#  A left-over file is NOT trusted: whatever is in it, this bundle is still written
# --------------------------------------------------------------------------- #
def _carried_lines(*lines, bytes_=None):
    """A hand-built ``carried`` item, bypassing the read's caps, to put a line in front of the fold."""
    return {"carried": [{
        "journal": "oo-all-diagnostics-20260930-070500.zip.journal.jsonl", "bytes": bytes_ or 1,
        "truncated": False, "lines_dropped": 0, "modified": "2026-09-30T07:05:00+00:00",
        "lines": list(lines),
    }], "not_carried": []}


def _strict(text):
    """Parse as STRICT JSON: a bare NaN/Infinity is refused, as a browser's JSON.parse refuses it."""
    def _no(name):
        raise ValueError(name)

    return json.loads(text, parse_constant=_no)


def test_json_nested_deeper_than_the_parser_takes_is_an_unparsed_line_not_a_lost_bundle():
    # 200,000 openers: the C parser on this Python takes far more than the 5,000 that used to
    # stand here before it raises RecursionError, so a smaller line never reached that branch.
    depth = 200_000
    with pytest.raises(RecursionError):
        json.loads("[" * depth)
    text, block = _diag_bundle._fold_previous_run_journals(_carried_lines("[" * depth))
    assert block["runs"][0]["unparsed_lines"] == 1
    (rec,) = [json.loads(ln) for ln in text.splitlines()]
    assert rec["event"] == "unparsed" and rec["chars"] == depth and len(rec["raw"]) == 200


def test_a_lone_surrogate_in_a_left_over_line_cannot_stop_the_archive_encoding(tiny_members):
    bad = '{"event": "begin", "file": "\\ud800-member", "started_at": "\\udfffT"}'
    (tiny_members / "oo-all-diagnostics-20260930-070500.zip.journal.jsonl").write_text(
        bad + "\n", encoding="utf-8",
    )
    res = d._all_diagnostics_worker(_Ctx())  # raised UnicodeEncodeError in writestr before
    with zipfile.ZipFile(res["path"]) as z:
        run = _strict(z.read("manifest.json").decode("utf-8"))["run"]
        body = z.read("bundle-journal.jsonl").decode("ascii")  # ASCII by construction
    assert run["previous_runs"][0]["unfinished"] == ["\\ud800-member"], "the escape is text now"
    assert "\\ud800-member" in body


def test_a_bare_nan_never_reaches_the_manifest_or_the_folded_journal(tiny_members):
    (tiny_members / "oo-all-diagnostics-20260930-070500.zip.journal.jsonl").write_text(
        '{"event": "end", "file": "a.json", "outcome": "ok", "wall_s": NaN}\n'
        '{"event": "begin", "file": "b.json", "started_at": Infinity}\n',
        encoding="utf-8",
    )
    res = d._all_diagnostics_worker(_Ctx())
    with zipfile.ZipFile(res["path"]) as z:
        manifest = _strict(z.read("manifest.json").decode("utf-8"))  # strict: NaN would raise
        for ln in z.read("bundle-journal.jsonl").decode().splitlines():
            _strict(ln)
    assert manifest["run"]["previous_runs"][0]["unparsed_lines"] == 2


def test_a_record_that_names_no_member_never_invents_a_culprit(tiny_members):
    """A journal from another schema: begin/end lines without a string ``file``. The old code
    named the culprit ``"None"``."""
    _text, block = _diag_bundle._fold_previous_run_journals(_carried_lines(
        '{"event": "begin", "i": 1}', '{"event": "begin", "file": 7}', '{"event": "end"}',
    ))
    run = block["runs"][0]
    assert run["unfinished"] == [] and run["unrecognised_lines"] == 3
    assert run["members_begun"] == 0 and run["members_ended"] == 0


def test_the_lines_kept_from_one_journal_are_bounded_not_just_the_bytes_read(tmp_path, monkeypatch):
    """The cap on bytes bounds what is READ; every line becomes a record, so a megabyte of
    one-character lines was half a million records (measured +2 GB of resident size from ten
    files). The tail is kept, the count of what was left is recorded."""
    own = tmp_path / "oo-all-diagnostics-20260930-090000.zip.journal.jsonl"
    path = tmp_path / "oo-all-diagnostics-20260930-070500.zip.journal.jsonl"
    path.write_bytes(b"x\n" * (1 << 19))  # exactly the byte cap: 524,288 lines
    got = _diag_bundle._read_previous_run_journals(tmp_path, own)
    (item,) = got["carried"]
    assert len(item["lines"]) == d._PREVIOUS_JOURNAL_MAX_LINES
    assert item["lines_dropped"] == (1 << 19) - d._PREVIOUS_JOURNAL_MAX_LINES
    text, block = _diag_bundle._fold_previous_run_journals(got)
    assert len(text) < 200_000, "what the bundle carries is bounded by lines, not by what was on disk"
    assert block["runs"][0]["lines_dropped"] == item["lines_dropped"]


def test_a_journal_without_a_trailing_newline_is_held_to_the_line_cap_too(tmp_path):
    """``rsplit`` with a count returns one piece more than the cap, and a file that ends in a
    newline makes the last piece empty (filtered): only a file whose last line has no newline
    reaches the cap itself, and without it the fold kept one line too many."""
    own = tmp_path / "oo-all-diagnostics-20260930-090000.zip.journal.jsonl"
    path = tmp_path / "oo-all-diagnostics-20260930-070500.zip.journal.jsonl"
    path.write_bytes(b"x\n" * 5000 + b"x")  # 5,001 lines, the last one torn (no newline)
    (item,) = _diag_bundle._read_previous_run_journals(tmp_path, own)["carried"]
    assert len(item["lines"]) == d._PREVIOUS_JOURNAL_MAX_LINES
    assert item["lines_dropped"] == 5001 - d._PREVIOUS_JOURNAL_MAX_LINES


def test_a_long_line_is_cut_before_it_is_parsed_or_kept(tmp_path):
    own = tmp_path / "oo-all-diagnostics-20260930-090000.zip.journal.jsonl"
    path = tmp_path / "oo-all-diagnostics-20260930-070500.zip.journal.jsonl"
    path.write_text("y" * 50_000 + "\n", encoding="utf-8")
    (item,) = _diag_bundle._read_previous_run_journals(tmp_path, own)["carried"]
    assert [len(ln) for ln in item["lines"]] == [d._PREVIOUS_JOURNAL_MAX_LINE_CHARS]


def test_the_total_folded_text_has_a_budget_and_the_newest_journals_spend_it_first(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(_diag_bundle, "_PREVIOUS_JOURNAL_MAX_TOTAL_CHARS", 700)
    own = tmp_path / "oo-all-diagnostics-20260930-090000.zip.journal.jsonl"
    for day in (1, 2, 3):
        _dead_run_journal(tmp_path, f"2026090{day}-000000", unfinished=f"m{day}.json")
    got = _diag_bundle._read_previous_run_journals(tmp_path, own)
    assert [c["journal"][19:27] for c in got["carried"]] == ["20260903"], "the newest is carried"
    left = got["not_carried"]
    assert [n["journal"][19:27] for n in left] == ["20260902", "20260901"]
    assert all("budget" in n["reason"] for n in left)


def test_a_journal_that_cannot_be_statted_is_named_not_skipped(tmp_path, monkeypatch):
    own = tmp_path / "oo-all-diagnostics-20260930-090000.zip.journal.jsonl"
    path = _dead_run_journal(tmp_path, "20260930-070500", unfinished="x.json")
    real_stat = type(path).stat

    def _stat(self, *a, **k):
        if self.name == path.name:
            raise PermissionError("denied")
        return real_stat(self, *a, **k)

    monkeypatch.setattr(type(path), "stat", _stat)
    got = _diag_bundle._read_previous_run_journals(tmp_path, own)
    assert got["carried"] == []
    assert got["not_carried"][0]["journal"] == path.name
    assert got["not_carried"][0]["reason"].startswith("could not stat it: PermissionError")
