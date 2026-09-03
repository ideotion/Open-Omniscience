"""S1.2 — an engage RELEASES something, and a swap-out is not a recovery.

Two defects, one slice:

* the guard PAUSED collection and freed nothing resident. Pausing stops NEW
  work; the memory is in the pool's SQLite page caches and the columnar serve
  connections, and nothing touched either. Measured here, on a warm 64 MiB
  cache: ending the transaction freed 0 MB and ``PRAGMA shrink_memory`` freed
  66 MB — so the ladder asks SQLite, rather than hoping a rollback did it.
* the resume condition watched ``available`` rising and RSS falling, which is
  exactly what a SWAP-OUT looks like. The field readings show ``available``
  alternating 200/600 MB while RSS sat at 1600 and ``VmSwap`` climbed.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import subprocess
import sys

import sqlalchemy as sa

from src.monitoring.swap import process_swapping, swap_readings
from src.scheduler import release as R
from src.scheduler.memguard import MemoryGuard


# --------------------------------------------------------------------------- #
# The readings.
# --------------------------------------------------------------------------- #
def test_swap_fields_are_omitted_when_unreadable_never_zero(monkeypatch):
    """A machine with no swap and a machine we could not measure are opposite
    facts; a 0 would let a reader conclude 'nothing is swapping'."""
    monkeypatch.setattr(R, "_rss_mb", R._rss_mb)  # no-op, keeps the import used
    monkeypatch.setattr(
        "src.monitoring.swap._PROC_STATUS", "/nonexistent/proc/status", raising=False
    )
    import builtins

    real_import = builtins.__import__

    def _no_psutil(name, *a, **kw):
        if name == "psutil":
            raise ImportError("blocked")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", _no_psutil)
    got = swap_readings()
    assert got == {}, "unreadable swap must be ABSENT, not zero"
    assert process_swapping() is None, "unmeasurable is a third state, not False"


def test_swap_is_actually_read_where_it_can_be():
    """Anti-vacuity: the omission test above must not be the only one that runs."""
    got = swap_readings()
    assert got, "this platform can read swap — the reader must return something"
    assert set(got) <= {"swap_used_mb", "proc_swap_mb"}
    assert all(isinstance(v, float) for v in got.values())


def test_the_guard_samples_swap_in_its_own_readings():
    from src.scheduler.memguard import _psutil_readings

    r = _psutil_readings()
    assert "proc_swap_mb" in r or "swap_used_mb" in r


def test_the_collector_monitor_samples_swap_too():
    from src.monitoring.collect_perf import _vitals

    v = _vitals()
    assert "proc_swap_mb" in v or "swap_used_mb" in v


# --------------------------------------------------------------------------- #
# The ladder.
# --------------------------------------------------------------------------- #
_WARM_PROBE = r"""
import gc, sqlite3, sys

db = sys.argv[1]
con = sqlite3.connect(db)
con.execute("create table t (id integer primary key, v blob)")
con.executemany("insert into t (v) values (?)", [(b"x" * 4000,) for _ in range(20000)])
con.commit()
con.close()

def rss():
    with open("/proc/self/status", encoding="utf-8") as fh:
        for ln in fh:
            if ln.startswith("VmRSS:"):
                return int(ln.split()[1]) / 1024.0
    return -1.0

live = sqlite3.connect(db)
live.execute("PRAGMA cache_size = -65536")   # 64 MiB, the shipped value
# A bare SELECT opens no transaction under sqlite3's default isolation, and the
# claim under test is about ENDING one -- so open it explicitly, exactly as a
# Session holding a read transaction does.
live.execute("BEGIN")
live.execute("select count(*) from t where v is not null").fetchone()
gc.collect(); warm = rss()
live.execute("rollback")                     # what the app already did
gc.collect(); after_rollback = rss()
live.execute("PRAGMA shrink_memory")
gc.collect(); after_shrink = rss()
live.close()
print(warm, after_rollback, after_shrink)
"""


def test_shrink_memory_is_what_frees_a_warm_page_cache(tmp_path):
    """The measurement the ladder is built on, re-run as a test.

    Without it the ladder is a guess: ending a transaction -- which is what the
    app already did everywhere -- frees nothing at all.

    RUN IN A SUBPROCESS, and that is not a convenience. The instrument is process
    RSS, and inside the full suite this process already holds ~1.5 GB across the
    allocator's arenas, so a 64 MiB page cache being handed back is invisible: the
    test passed alone and failed in the suite, reading as "shrink_memory does
    nothing" when it was the MEASUREMENT that could not see. A fresh interpreter is
    where the docstring's own numbers were taken, and it is the only place this
    claim is measurable at all.
    """
    out = subprocess.run(
        [sys.executable, "-c", _WARM_PROBE, str(tmp_path / "warm.db")],
        capture_output=True, text=True, timeout=300, check=True,
    )
    warm, after_rollback, after_shrink = (float(x) for x in out.stdout.split())

    assert warm > 40.0, (
        f"the probe never warmed a page cache (RSS {warm:.1f} MB) — nothing below it means anything"
    )
    assert after_rollback > warm - 5.0, (
        f"ending the transaction should free ~nothing (warm {warm:.1f} -> "
        f"{after_rollback:.1f} MB) — if this ever changes, the ladder's premise has"
    )
    assert warm - after_shrink > 20.0, (
        f"shrink_memory must free the page cache (warm {warm:.1f} -> "
        f"{after_shrink:.1f} MB)"
    )


def test_the_ladder_runs_every_step_and_reports_each_freed_mb():
    rec = R.release_residents()
    names = [s["step"] for s in rec["steps"]]
    assert names == [
        "dispose_idle_pool",
        "shrink_memory",
        "close_serves",
        "gc_collect",
        "malloc_trim",
    ]
    for s in rec["steps"]:
        assert "freed_mb" in s, s
    assert "freed_mb" in rec and "duration_ms" in rec


def test_a_step_that_fails_never_stops_the_ladder(monkeypatch):
    """This runs when the machine is already in trouble."""

    def _boom() -> dict:
        raise RuntimeError("no")

    monkeypatch.setattr(R, "_shrink_sqlite", _boom)
    rec = R.release_residents()
    assert len(rec["steps"]) == 5
    assert any(s.get("ok") is False and "RuntimeError" in s.get("error", "") for s in rec["steps"])


def test_gc_is_skipped_while_our_pages_are_in_swap(monkeypatch):
    """A heap walk faults swapped pages back in — the field measurement of doing
    it anyway is a pass whose RSS ROSE 1668 -> 1751 MB."""
    monkeypatch.setattr("src.monitoring.swap.process_swapping", lambda: True)
    rec = R.release_residents()
    gc_step = next(s for s in rec["steps"] if s["step"] == "gc_collect")
    assert gc_step["skipped"] == "this process has pages in swap"
    assert "collected" not in gc_step

    # ...and the twin: on a machine that is NOT swapping it must still run, or
    # the skip is a permanent disabling wearing a condition.
    monkeypatch.setattr("src.monitoring.swap.process_swapping", lambda: False)
    rec = R.release_residents()
    gc_step = next(s for s in rec["steps"] if s["step"] == "gc_collect")
    assert "collected" in gc_step and "skipped" not in gc_step


def test_gc_is_skipped_when_swap_cannot_be_measured(monkeypatch):
    """Unmeasurable is not False: taking the not-swapping branch off a
    measurement never made is the fabricated-pass shape."""
    monkeypatch.setattr("src.monitoring.swap.process_swapping", lambda: None)
    rec = R.release_residents()
    gc_step = next(s for s in rec["steps"] if s["step"] == "gc_collect")
    assert "unmeasurable" in gc_step["skipped"]


def test_disposing_the_pool_closes_idle_connections_only():
    """Two halves, and BOTH are load-bearing: the idle connections must actually
    be CLOSED (each takes its page cache with it — the whole point of the step),
    and a checked-out one must survive, because it closes on RETURN rather than
    being cut off mid-statement.

    The action half exists because asserting only the safety half passes with
    ``pool.dispose()`` deleted, which is the mutation this step is for.
    """
    from src.database.session import engine

    # The held connection is taken FIRST: a checkout reuses an idle connection,
    # so taking it afterwards would silently consume one of the fixture's own.
    held = engine.connect()
    try:
        held.execute(sa.text("select 1"))

        # Make some genuinely idle connections.
        idle = [engine.connect() for _ in range(2)]
        for c in idle:
            c.execute(sa.text("select 1"))
            c.close()
        before = engine.pool.checkedin()
        assert before >= 2, "the fixture failed to leave idle connections"

        rec = R._dispose_idle_pool()
        assert rec["ok"] is True
        # the ACTION: nothing idle is left holding a page cache
        assert engine.pool.checkedin() == 0, (
            f"dispose left {engine.pool.checkedin()} idle connections resident — "
            "the step frees nothing"
        )
        assert rec["closed"] == before, "the record must say how many it closed"
        # the SAFETY: the checked-out connection is still usable
        assert held.execute(sa.text("select 1")).scalar() == 1
    finally:
        held.close()


def test_the_shrink_step_actually_issues_the_pragma(monkeypatch):
    """The measurement above proves ``shrink_memory`` is what frees a page cache;
    this proves the SHIPPED step is the thing that issues it.

    Without this, replacing the PRAGMA with a no-op leaves ``ok: True`` and every
    other test green — the step reports success and frees nothing.
    """
    issued: list[str] = []

    class _Rec:
        def execute(self, sql, *a):
            issued.append(str(sql))

        def close(self):
            issued.append("close")

    from src.database import session as dbsession

    monkeypatch.setattr(dbsession.engine, "raw_connection", lambda: _Rec())
    rec = R._shrink_sqlite()
    assert rec["ok"] is True
    assert any("shrink_memory" in q for q in issued), (
        f"the step reported success without issuing the PRAGMA (saw {issued})"
    )
    assert issued[-1] == "close", "the short-lived connection must be closed"


def test_closing_the_serves_marks_them_not_built():
    from src.analytics import rollup_serve

    with rollup_serve._LOCK:
        rollup_serve._STATE["con"] = object()  # a handle that cannot be closed
        rollup_serve._STATE["built_at"] = 123.0
    rec = R._close_serves()
    assert rec["ok"] is True
    with rollup_serve._LOCK:
        assert rollup_serve._STATE["con"] is None
        assert rollup_serve._STATE["built_at"] == 0.0
    assert "rollup_serve" in rec["closed"]


# --------------------------------------------------------------------------- #
# The guard.
# --------------------------------------------------------------------------- #
def _trip(guard, **kw):
    for _ in range(guard.trip_after):
        guard.observe(rss_mb=kw.get("rss", 900.0), mem_avail_mb=100.0, mem_total_mb=1000.0)


def test_an_engage_runs_the_release_and_keeps_the_record():
    calls: list[int] = []
    g = MemoryGuard(trip_after=1, release_fn=lambda: (calls.append(1), {"freed_mb": 42.0})[1])
    assert g.observe(rss_mb=900.0, mem_avail_mb=10.0, mem_total_mb=1000.0) is True
    assert calls == [1], "engaging must run the ladder"
    assert g.last_release() == {"freed_mb": 42.0}


def test_a_failing_release_never_breaks_the_pause():
    def _boom():
        raise RuntimeError("no")

    g = MemoryGuard(trip_after=1, release_fn=_boom)
    assert g.observe(rss_mb=900.0, mem_avail_mb=10.0, mem_total_mb=1000.0) is True
    assert g.engaged is True, "the pause must stand even if the release failed"
    assert g.last_release() is None


def test_a_swap_out_does_not_read_as_a_recovery():
    """RSS flat at 1600 while available alternates 200/600 and VmSwap climbs —
    the field signature. The guard must stay ENGAGED."""
    g = MemoryGuard(trip_after=1, resume_after=2, release_fn=lambda: {})
    assert g.observe(rss_mb=1600.0, mem_avail_mb=200.0, mem_total_mb=2000.0, proc_swap_mb=100.0)
    for i, avail in enumerate((600.0, 600.0, 600.0, 600.0)):
        # RSS falls a little and available rises — but only because we are paging out.
        g.observe(
            rss_mb=1500.0,
            mem_avail_mb=avail,
            mem_total_mb=2000.0,
            proc_swap_mb=200.0 + 100.0 * i,
        )
    assert g.engaged is True, "a swap-out must not release the guard"


def test_a_real_recovery_still_resumes():
    """The mandatory twin: an over-eager swap check that never resumed would pin
    the guard on forever, which is a worse failure than the one being fixed."""
    g = MemoryGuard(trip_after=1, resume_after=2, release_fn=lambda: {})
    assert g.observe(rss_mb=1600.0, mem_avail_mb=200.0, mem_total_mb=2000.0, proc_swap_mb=100.0)
    for _ in range(3):
        g.observe(
            rss_mb=1000.0, mem_avail_mb=1200.0, mem_total_mb=2000.0, proc_swap_mb=100.0
        )
    assert g.engaged is False, "steady swap + genuinely healthy readings must resume"


def test_swap_readings_are_absent_from_the_sample_when_not_supplied():
    """Omit, never zero: a caller that cannot measure swap must not make the
    guard's own record claim it saw none."""
    g = MemoryGuard(trip_after=99, release_fn=lambda: {})
    g.observe(rss_mb=100.0, mem_avail_mb=900.0, mem_total_mb=1000.0)
    assert g.state()["last_reading"]["proc_swap_mb"] is None
    assert g.state()["last_reading"]["proc_swap_rising"] is None
