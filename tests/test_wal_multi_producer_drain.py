"""Regression test for PR-D / W1's fix-forward: the mandatory 4-lens adversarial
skeptic matrix's transactional-semantics finding #1 (HIGH).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE GAP THIS FILLS: neither ``tests/test_wal_reader_starvation.py`` nor
``tests/test_wal_starvation_soak.py`` (both drive ``registry.run_all()`` with
exactly ONE registered producer) can distinguish "``_wal_guard`` entered once for
the whole producer loop" from "``_wal_guard`` entered once PER producer" -- with
N=1 those two shapes are behaviorally identical (there is no "between producers"
moment for either shape to handle differently). ``tests/test_wal_commit_between_
producers.py`` also uses two producers, but BOTH are non-scanning (``.scalar()``
only, never ``fetchmany()``), so neither ever creates a ``_WalGuardResult`` left
genuinely mid-flight either.

THE DIAGNOSED BUG (found by the skeptic matrix, root-caused by reading
``src/briefing/registry.py``'s ``_wal_guard``/``_drain_pending`` docstrings):
``run_all()`` originally wrapped its ENTIRE producer loop in a single
``with _wal_guard(session):`` block. ``_drain_pending(session)`` -- the ONLY thing
that ever explicitly ``.close()``s a producer's dangling, not-fully-drained
``_WalGuardResult`` -- runs ONLY at the very START of a ``_wal_guard(...)`` call.
So with one ``_wal_guard`` entry for the whole loop, a producer that leaves its
own ``fetchmany()`` scan mid-flight (rows still unfetched) when it returns keeps
that scan's WAL read-mark pinned for every SUBSEQUENT producer in the SAME pass,
AND for however long the process keeps running after ``run_all()`` itself
returns -- since nothing calls ``_wal_guard`` again until some FUTURE
``run_all()`` invocation, which may be a long time later or may never happen
again in the process's life.

THE FIX: enter ``_wal_guard`` PER PRODUCER (each producer's own
``with _wal_guard(session):`` block), so the NEXT producer's own entry drains
whatever the PREVIOUS one left open before it starts; plus a trailing
``_drain_pending(session)`` call after the loop, closing whatever the LAST
producer left open (there is no further ``_wal_guard`` entry within the same
``run_all()`` call to do that otherwise).

Deterministic, no threads, no timing race -- exactly the discriminating shape
``test_wal_commit_between_producers.py`` establishes as the reliable pattern
(that file's own docstring records why a threaded/timing-race framing was tried
first and abandoned as unreliable for a sibling property).
"""

from __future__ import annotations


from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from src.briefing import registry
from src.database import session as db_session
from src.scheduler import hygiene
from src.scheduler.hygiene import checkpoint_wal

_JOURNAL_SIZE_LIMIT_MB = 1
_SEED_ROWS = 50  # empirically: enough that fetchmany(3) below leaves the bulk of
# the table genuinely unfetched (mirrors test_wal_reader_starvation.py's own
# documented finding that too few seed rows lets a scan exhaust naturally and
# defeat the reproduction).


def _wal_engine(tmp_path, name="wal_multi_producer.db"):
    db = tmp_path / name
    eng = create_engine(f"sqlite:///{db}", future=True)
    event.listen(eng, "connect", db_session._sqlite_pragmas)
    with eng.connect() as c:
        c.exec_driver_sql("CREATE TABLE t(x)")
        for _ in range(_SEED_ROWS):
            c.exec_driver_sql("INSERT INTO t VALUES (randomblob(4096))")
        c.commit()
    return eng, db


def _partial_scan_producer(session):
    """A producer that leaves its OWN fetchmany() scan genuinely mid-flight when
    it returns -- calls fetchmany() TWICE and returns without ever exhausting the
    Result, deliberately never calling .close() or .fetchall() itself. This is
    the exact shape build_keyword_daily-style scanning producers have, and the
    exact shape _drain_pending exists to clean up after.

    TWO calls, not one: _WalGuardResult.fetchmany()'s OWN per-statement release
    throttle (registry.py's `_WAL_GUARD_MIN_RELEASE_INTERVAL_S` mechanism, a
    SEPARATE, already-shipped fix) unconditionally releases on the FIRST
    fetchmany() call any wrapper ever sees (`_last_release_mono is None`), no
    matter which _wal_guard scope is in play -- so a producer that calls
    fetchmany() exactly once can never demonstrate THIS finding; its own single
    call already self-releases regardless. The SECOND call, made well within the
    30s throttle window of the first, does NOT trigger a release (`due=False`)
    and genuinely leaves the wrapper holding an open, unclosed cursor -- the one
    shape only `_drain_pending` (not the per-call throttle) can reclaim.
    """
    result = session.execute(text("SELECT x FROM t"))
    result.fetchmany(3)  # first call: always releases unconditionally (a SEPARATE mechanism)
    result.fetchmany(3)  # second call, same 30s window: does NOT release -- leaves the cursor open
    return []


def _trivial_producer(session):
    """A plain, non-scanning producer -- one .scalar() call, no fetchmany(). Runs
    AFTER the partial-scan producer above, so it is the one that would (on the
    unpatched shape) inherit the still-pinned WAL snapshot the prior producer left
    behind.
    """
    session.execute(text("SELECT 1")).scalar()
    return []


def test_a_checkpoint_succeeds_immediately_after_run_all_returns_even_when_an_earlier_producer_left_its_scan_mid_flight(
    tmp_path, monkeypatch
):
    """MUST FAIL on the unpatched (whole-loop) `_wal_guard` shape: the
    partial-scan producer's dangling `_WalGuardResult` is never drained within
    this `run_all()` call (only a FUTURE `_wal_guard(...)` entry would drain it,
    and there isn't one), so it stays referenced -- and hence pinned -- through
    the trivial producer's own turn and past `run_all()`'s own return. A
    checkpoint attempted IMMEDIATELY after `run_all()` returns (no delay, no
    threads) therefore still reports busy=1.

    PASSES on the fixed (per-producer) shape: the trivial producer's own
    `_wal_guard` entry drains the partial-scan producer's leftover BEFORE the
    trivial producer runs, and the trailing `_drain_pending` after the loop
    closes anything the trivial producer itself left open -- so by the time
    `run_all()` returns, nothing is pinning the WAL and the checkpoint succeeds.
    """
    monkeypatch.setenv("OO_WAL_SIZE_LIMIT_MB", str(_JOURNAL_SIZE_LIMIT_MB))
    monkeypatch.setattr(hygiene, "_LAST_CKPT_MONO", None)
    monkeypatch.setattr(registry, "_REGISTRY", [])
    registry.register("partial_scan", _partial_scan_producer)
    registry.register("trivial_after", _trivial_producer)

    eng, db = _wal_engine(tmp_path)
    Session = sessionmaker(bind=eng, future=True)
    reader_session = Session()
    try:
        registry.run_all(reader_session)

        # Grow the WAL from a SEPARATE connection so there is genuinely
        # something for the checkpoint to reclaim -- a checkpoint on an
        # unchanged WAL trivially "succeeds" (busy=0) regardless of any pin,
        # which would make this assertion vacuous.
        with eng.connect() as c:
            c.exec_driver_sql("INSERT INTO t VALUES (randomblob(262144))")
            c.commit()

        rec = checkpoint_wal(engine=eng, force=True, busy_timeout_ms=200)
        assert rec is not None
        assert rec["busy"] == 0, (
            "a checkpoint attempted immediately after run_all() returns must "
            "succeed (busy=0) -- busy=1 here means an EARLIER producer's "
            "mid-flight scan is still pinning the WAL after the WHOLE pass has "
            "finished, because _wal_guard wrapped the entire producer loop in "
            "ONE call instead of entering it per producer (so _drain_pending "
            "never ran between producers, nor after the loop, within this "
            "run_all() invocation)"
        )
        assert rec["wal_bytes_after"] == 0, (
            "the checkpoint reported busy=0 but did not fully truncate the "
            "WAL -- expected a clean full checkpoint once nothing pins it"
        )
    finally:
        reader_session.close()
        eng.dispose()
