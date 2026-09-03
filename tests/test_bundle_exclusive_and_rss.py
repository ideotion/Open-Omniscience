"""The all-diagnostics bundle owns the machine, and reports each member's cost honestly.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

S6.1 + S6.2 of the 2026-09-02 crash brief.

S6.1 -- the bundle runs for tens of minutes and competed with a collection pass, the
housekeeping lane and the two rollup builds the whole time. It now takes the existing
exclusive hold. The half that is easy to get wrong is the SECOND one: "every entry point
that starts equivalent work must check the hold" (the 2026-07-24 lesson -- a pause that
only stops the primary loop is honest-sounding and incomplete). ``run_now`` and the
re-index job already checked; the two rollup builds are kicked from a SERVE, so they never
met the pause at all, and a whole-corpus columnar rebuild is the heaviest thing this
process does outside a pass.

S6.2 -- ``rss_delta_kb`` was computed from ``ru_maxrss``, a process high-water mark that
NEVER FALLS, so every member after the first big one reported 0 whatever it allocated. The
discriminating test below is the one that fixes a high peak and asserts the delta still
moves; a test that merely checks the key exists passes against the defect.
"""

from __future__ import annotations

import io
import json
import threading
import zipfile

import pytest

import src.api.diagnostics as d
import src.scheduler.runner as R


# --------------------------------------------------------------------------- #
#  fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def clean_window(monkeypatch):
    """A fresh scheduler + a closed exclusive window, restored afterwards.

    ``_EXCL_WINDOW`` and ``_scheduler`` are process globals, so a test that left either
    raised would silently make every later test's ``run_now`` refuse.
    """
    sched = R.BackgroundScheduler()
    monkeypatch.setattr(R, "_scheduler", sched)
    monkeypatch.setattr(R, "_EXCL_WINDOW", False)
    import src.ingest as I

    monkeypatch.setattr(I, "kill_switch_active", lambda: False)
    yield sched
    monkeypatch.setattr(R, "_EXCL_WINDOW", False)


@pytest.fixture()
def inert_pass(monkeypatch):
    """Make ``run_now``'s spawned thread inert, so the test can prove the path is LIVE
    without actually starting a collection pass. Returns the list it appends to."""
    started: list[int] = []
    done = threading.Event()

    def _fake_do_run(self) -> None:
        started.append(1)
        done.set()

    monkeypatch.setattr(R.BackgroundScheduler, "_do_run", _fake_do_run, raising=True)
    return started, done


def _run_bundle(members, **kw) -> list[dict]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        return d._write_all_diagnostics_zip(members, z, **kw)


def _manifest_of(members, **kw) -> dict:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        d._write_all_diagnostics_zip(members, z, **kw)
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
        return json.loads(z.read("manifest.json"))


class _ScriptedProbe:
    """A probe whose readings are dictated, so a delta is deterministic. ``basis`` is a
    real current-RSS basis, because the point being tested is the ARITHMETIC."""

    def __init__(self, readings: list[int | None]) -> None:
        self._readings = list(readings)
        self.basis = "proc"
        self.reads = 0

    def kb(self) -> int | None:
        self.reads += 1
        if not self._readings:
            return None
        return self._readings.pop(0)


# --------------------------------------------------------------------------- #
#  S6.1 -- the hold itself
# --------------------------------------------------------------------------- #
def test_a_running_bundle_blocks_a_manual_run_now(clean_window, inert_pass):
    """The brief's own acceptance test, with its anti-vacuity half: ``run_now`` must be
    LIVE before the window, refused inside it, and live again after -- otherwise a
    ``run_now`` that always returns False would pass this."""
    started, done = inert_pass

    assert R.get_scheduler().run_now() is True, "anti-vacuity: run_now must be live first"
    assert done.wait(5), "the inert pass thread never ran"

    with d._bundle_exclusive_window() as excl:
        assert excl["held"] is True
        assert R.get_scheduler().run_now() is False, (
            "a manual Run now must be refused while the bundle owns the machine"
        )

    assert R.get_scheduler().run_now() is True, "the hold must be released on exit"
    assert len(started) == 2, f"expected exactly the two live runs, got {started}"


def test_the_bundle_hold_never_clears_an_outer_operations_claim(clean_window, inert_pass):
    """WHY the helper uses ``exclusive_window`` rather than ``hold_exclusive`` directly:
    ``_exclusive_hold`` is a BOOLEAN, so a bundle started during a restore would clear the
    RESTORE's claim on its own release and put a manual Run now back on the machine
    mid-restore. The re-entrant window restores the flag to what it FOUND."""
    _started, _done = inert_pass
    with R.exclusive_window():
        with d._bundle_exclusive_window() as excl:
            assert excl["nested"] is True, "the bundle must SAY it found the machine owned"
            assert R.get_scheduler().run_now() is False
        assert R.get_scheduler().run_now() is False, (
            "the outer operation still owns the machine after the inner bundle exits"
        )
    assert R.get_scheduler().run_now() is True


def test_every_member_still_runs_under_the_hold(clean_window):
    """Ruling 4: the hold changes what ELSE may run, never which members do."""
    members = [(f"m{i}.json", (lambda i=i: {"i": i})) for i in range(4)]
    assert members, "anti-vacuity: the member list must be non-empty"
    with d._bundle_exclusive_window() as excl:
        results = _run_bundle(members, exclusive=excl)
    assert [r["file"] for r in results] == [f"m{i}.json" for i in range(4)]
    assert all(r["outcome"] == "ok" for r in results)


def test_an_unreadable_scheduler_degrades_loudly_and_never_loses_the_bundle(monkeypatch):
    """The bundle is the maintainer's evidence channel; it must never fail for want of the
    hold. The degrade carries a REASON rather than an unexplained absence."""
    import builtins

    real_import = builtins.__import__

    def _boom(name, *a, **kw):
        if name == "src.scheduler.runner":
            raise ImportError("no scheduler here")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _boom)
    with d._bundle_exclusive_window() as excl:
        assert excl["held"] is False
        assert excl["reason"]
    monkeypatch.setattr(builtins, "__import__", real_import)
    results = _run_bundle([("x.json", lambda: {"ok": 1})], exclusive=excl)
    assert results[0]["outcome"] == "ok"


# --------------------------------------------------------------------------- #
#  S6.1 -- the wiring, at BOTH entry points
# --------------------------------------------------------------------------- #
def test_the_sync_route_takes_the_hold(clean_window, monkeypatch):
    """A guard wired into one of two callers is the gate-every-entry-point defect. This
    route can run for 36+ minutes, so it needs the hold as much as the job does."""
    seen: dict = {}

    def _spy(members, zf, **kw):
        seen["open"] = R.exclusive_window_open()
        seen["excl"] = kw.get("exclusive")
        return []

    monkeypatch.setattr(d, "_all_diagnostics_members", lambda db: [])
    monkeypatch.setattr(d, "_write_all_diagnostics_zip", _spy)
    assert R.exclusive_window_open() is False, "anti-vacuity: the window starts closed"
    d.all_diagnostics(db=None)
    assert seen["open"] is True, "the sync route must hold the machine while it builds"
    assert seen["excl"] and seen["excl"]["held"] is True
    assert R.exclusive_window_open() is False, "released on exit"


def test_the_background_job_takes_the_hold(clean_window, monkeypatch, tmp_path):
    """The other entry point, checked the same way."""
    import contextlib

    import src.database.session as S

    seen: dict = {}

    def _spy(members, zf, **kw):
        seen["open"] = R.exclusive_window_open()
        seen["excl"] = kw.get("exclusive")
        return []

    monkeypatch.setattr(d, "_all_diagnostics_dir", lambda: tmp_path)
    monkeypatch.setattr(d, "_all_diagnostics_members", lambda db: [])
    monkeypatch.setattr(d, "_write_all_diagnostics_zip", _spy)
    monkeypatch.setattr(S, "session_scope", lambda: contextlib.nullcontext(None))

    class _Ctx:
        stopping = False

        def set_progress(self, **kw):
            pass

    assert R.exclusive_window_open() is False, "anti-vacuity: the window starts closed"
    d._all_diagnostics_worker(_Ctx())
    assert seen["open"] is True, "the background job must hold the machine while it builds"
    assert seen["excl"] and seen["excl"]["held"] is True
    assert R.exclusive_window_open() is False, "released on exit"


def test_the_manifest_reports_what_the_run_actually_claimed(clean_window):
    """Never a bare ``exclusive: true``. A caller that took the hold publishes the honest
    facts; a caller that did not says so, with a reason."""
    with d._bundle_exclusive_window() as excl:
        man = _manifest_of([("m.json", lambda: {"x": 1})], exclusive=excl)
    block = man["run"]["exclusive"]
    assert block["held"] is True
    assert "paused_collection" in block and isinstance(block["paused_collection"], bool)
    assert block["nested"] is False

    plain = _manifest_of([("m.json", lambda: {"x": 1})])
    assert plain["run"]["exclusive"]["held"] is False
    assert plain["run"]["exclusive"]["reason"]


# --------------------------------------------------------------------------- #
#  S6.1 -- the rollup builds decline while the machine is owned
# --------------------------------------------------------------------------- #
def test_the_keyword_rollup_build_declines_while_an_exclusive_window_is_open(
    clean_window, monkeypatch
):
    from src.analytics import rollup_serve as RS

    built: list[int] = []
    monkeypatch.setattr(RS, "_persisted_serve_active", lambda: False)
    monkeypatch.setattr(RS, "_build_inmemory_and_swap", lambda: built.append(1))
    monkeypatch.setattr(RS, "_memory_verdict", lambda: None)

    with R.exclusive_window():
        RS._BUILD_LOCK.acquire()
        RS._build_and_swap()
    assert built == [], "a whole-corpus rebuild must not start under an exclusive hold"
    assert RS.status()["last_skip"]["reason"] == "exclusive-hold"


def test_the_keyword_rollup_build_proceeds_when_no_window_is_open(clean_window, monkeypatch):
    """The negative twin: a gate that declined ALWAYS would pass the test above."""
    from src.analytics import rollup_serve as RS

    built: list[int] = []
    monkeypatch.setattr(RS, "_persisted_serve_active", lambda: False)
    monkeypatch.setattr(RS, "_build_inmemory_and_swap", lambda: built.append(1))
    monkeypatch.setattr(RS, "_memory_verdict", lambda: None)

    RS._BUILD_LOCK.acquire()
    RS._build_and_swap()
    assert built == [1], "with the machine free the build must run exactly as before"


def test_the_map_rollup_build_declines_while_an_exclusive_window_is_open(
    clean_window, monkeypatch
):
    from src.analytics import map_serve as MS

    import src.analytics.columnar as C

    built: list[int] = []

    monkeypatch.setattr(C, "connect", lambda passphrase=None: built.append(1))

    with R.exclusive_window():
        MS._BUILD_LOCK.acquire()
        MS._build_and_swap()
    assert built == [], "the map rollup must not rebuild under an exclusive hold"
    assert MS.status()["last_skip"]["reason"] == "exclusive-hold"


def test_the_map_rollup_build_reaches_its_work_when_no_window_is_open(
    clean_window, monkeypatch
):
    """The negative twin for the map build."""
    from src.analytics import map_serve as MS
    import src.analytics.columnar as C

    reached: list[int] = []

    def _connect(passphrase=None):
        reached.append(1)
        return None  # a None connection returns early; reaching it is the assertion

    monkeypatch.setattr(C, "connect", _connect)
    MS._BUILD_LOCK.acquire()
    MS._build_and_swap()
    assert reached == [1], "with the machine free the map build must proceed as before"


def test_an_unreadable_scheduler_never_blocks_a_rollup_build(monkeypatch):
    """The blind-guard direction, matching ``_memory_verdict``: an absent measurement is
    not evidence of a claim, so the build proceeds rather than being refused forever."""
    import builtins

    from src.analytics import serve_gate as SG

    real_import = builtins.__import__

    def _boom(name, *a, **kw):
        if name == "src.scheduler.runner":
            raise ImportError("no scheduler here")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _boom)
    assert SG.exclusive_verdict() is None


# --------------------------------------------------------------------------- #
#  S6.2 -- honest member accounting
# --------------------------------------------------------------------------- #
def test_the_member_delta_is_current_rss_not_the_high_water_mark(monkeypatch):
    """THE discriminating test. The process peak is fixed (as it is in any long-lived app
    that has already done something bigger), so the OLD ``ru_maxrss`` delta is 0 for this
    member however much it really allocated. The current-RSS delta still moves."""
    probe = _ScriptedProbe([1_000, 1_500])
    monkeypatch.setattr(d, "_RssProbe", lambda: probe)
    monkeypatch.setattr(d, "_rss_peak_kb", lambda: 9_000_000)  # a peak already set

    results = _run_bundle([("m.json", lambda: {"x": 1})])
    assert results[0]["rss_delta_kb"] == 500
    assert results[0]["rss_peak_rise_kb"] == 0, (
        "the high-water rise IS 0 here -- which is exactly why it cannot be the delta"
    )


def test_the_peak_rise_keeps_its_own_name(monkeypatch):
    """Two different questions -- "did this member allocate 40 MB" and "did it push the
    process past its all-time peak" -- must not share one field."""
    probe = _ScriptedProbe([1_000, 1_200])
    peaks = iter([5_000, 5_300])
    monkeypatch.setattr(d, "_RssProbe", lambda: probe)
    monkeypatch.setattr(d, "_rss_peak_kb", lambda: next(peaks))

    entry = _run_bundle([("m.json", lambda: {"x": 1})])[0]
    assert entry["rss_delta_kb"] == 200
    assert entry["rss_peak_rise_kb"] == 300
    assert entry["rss_delta_kb"] != entry["rss_peak_rise_kb"]


def test_an_unreadable_probe_omits_the_delta_rather_than_publishing_zero(monkeypatch):
    """A fabricated 0 would read as "this member allocated nothing"."""
    probe = _ScriptedProbe([None, None])
    probe.basis = "unavailable"
    monkeypatch.setattr(d, "_RssProbe", lambda: probe)
    monkeypatch.setattr(d, "_rss_peak_kb", lambda: None)

    entry = _run_bundle([("m.json", lambda: {"x": 1})])[0]
    assert "rss_delta_kb" not in entry
    assert "rss_peak_rise_kb" not in entry
    assert entry["rss_basis"] == "unavailable", "the basis must NAME the absence"


def test_the_probe_is_resolved_once_not_per_reading(monkeypatch):
    """The 2026-09-03 portability measurement: an instrument rebuilt per reading perturbs
    the very release it measures (0 MB freed, 5/5). One handle, hoisted."""
    made: list[int] = []
    real = d._RssProbe

    def _counting():
        made.append(1)
        return real()

    monkeypatch.setattr(d, "_RssProbe", _counting)
    _run_bundle([(f"m{i}.json", (lambda i=i: {"i": i})) for i in range(5)])
    assert made == [1], f"the probe must be built exactly once per run, was {len(made)}"


def test_the_probe_reuses_the_existing_proc_reader(monkeypatch):
    """"Reuse it, don't write a second one" -- pinned behaviourally, so an inlined second
    ``/proc`` reader fails here rather than passing a source grep."""
    import src.monitoring.merge_diag as MD

    if d._RssProbe().basis != "proc":
        pytest.skip("no /proc on this platform; the psutil fallback is the live path")
    monkeypatch.setattr(MD, "_rss_current_mb", lambda: 42.0)
    assert d._RssProbe().kb() == int(42.0 * 1024)


def test_a_heavy_member_is_trimmed_and_the_release_is_measured(monkeypatch):
    """A retained delta is only a finding once the allocator has been asked to give the
    arenas back -- otherwise it may be allocator noise."""
    big = d._ALL_DIAG_TRIM_AFTER_KB + 1
    probe = _ScriptedProbe([1_000, 1_000 + big, 1_000])  # before, after, post-trim
    monkeypatch.setattr(d, "_RssProbe", lambda: probe)
    monkeypatch.setattr(d, "_rss_peak_kb", lambda: 1)
    monkeypatch.setattr("src.scheduler.hygiene._malloc_trim", lambda: True)

    entry = _run_bundle([("m.json", lambda: {"x": 1})])[0]
    assert entry["release"]["trimmed"] is True
    assert entry["release"]["freed_kb"] == big


def test_a_light_member_is_not_trimmed(monkeypatch):
    """The negative twin: trimming after EVERY member would pass the test above while
    putting an arena walk on the wall clock ~59 times and reporting a freed figure for
    members that allocated nothing."""
    probe = _ScriptedProbe([1_000, 1_010, 1_000])
    monkeypatch.setattr(d, "_RssProbe", lambda: probe)
    monkeypatch.setattr(d, "_rss_peak_kb", lambda: 1)
    monkeypatch.setattr("src.scheduler.hygiene._malloc_trim", lambda: True)

    entry = _run_bundle([("m.json", lambda: {"x": 1})])[0]
    assert "release" not in entry


def test_an_unmeasurable_release_reports_none_never_zero(monkeypatch):
    """``freed_kb: 0`` would read as "the trim freed nothing" -- a measurement. ``None``
    says the release could not be read, which is the truth."""
    big = d._ALL_DIAG_TRIM_AFTER_KB + 1
    probe = _ScriptedProbe([1_000, 1_000 + big, None])  # the post-trim read fails
    monkeypatch.setattr(d, "_RssProbe", lambda: probe)
    monkeypatch.setattr(d, "_rss_peak_kb", lambda: 1)
    monkeypatch.setattr("src.scheduler.hygiene._malloc_trim", lambda: True)

    entry = _run_bundle([("m.json", lambda: {"x": 1})])[0]
    assert entry["release"]["freed_kb"] is None


def test_a_refused_trim_is_not_reported_as_a_release(monkeypatch):
    """On a platform where ``malloc_trim`` is unavailable (or disabled by the operator),
    nothing was returned to the OS and nothing may claim it was."""
    big = d._ALL_DIAG_TRIM_AFTER_KB + 1
    probe = _ScriptedProbe([1_000, 1_000 + big, 1_000])
    monkeypatch.setattr(d, "_RssProbe", lambda: probe)
    monkeypatch.setattr(d, "_rss_peak_kb", lambda: 1)
    monkeypatch.setattr("src.scheduler.hygiene._malloc_trim", lambda: False)

    entry = _run_bundle([("m.json", lambda: {"x": 1})])[0]
    assert "release" not in entry
