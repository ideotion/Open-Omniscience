"""Regression test for PR-D / W1: registry.run_all() must commit BETWEEN
producers, not merely release the WAL-guard's own scan cursors.

This test is DELIBERATELY NOT the same shape as
tests/test_wal_reader_starvation.py (which proves the WAL-guard's per-
statement release cadence keeps a checkpoint from being starved for the
WHOLE duration of a long scanning producer). This file isolates a DIFFERENT,
narrower property: run_all()'s OWN trailing `_release_transaction(session)`
call, called after EVERY producer, must itself commit the session's pending
work -- independent of whatever the WAL-guard's fetchmany()-driven release
does.

Why a separate, non-threaded test is the right shape here (recorded so a
future reader does not "simplify" this back into a threaded race):

  - The real caller this guards is `refresh_briefing()`, which runs
    `evaluate_watches(session)` (a WRITE -- it flushes a pending insert but
    does NOT commit) immediately followed by `registry.run_all(session)`.
    If run_all's per-producer commit were removed, that watch-evaluation
    write would sit uncommitted in the session for the ENTIRE producer loop,
    and -- because a dirty/uncommitted SQLite connection pins the WAL
    regardless of whether any individual scan cursor is closed -- a
    concurrent checkpointer would starve for that whole duration too.

  - An earlier attempt at this test used TWO SCANNING (fetchmany-loop)
    producers plus background writer/checkpointer THREADS, mirroring
    test_wal_reader_starvation.py's shape, to look for a checkpoint that
    succeeds "during producer B but not producer A". That property does
    NOT hold: once producer A leaves its OWN scan statement un-reset when
    it returns (the WAL-guard's 30s throttle deliberately does not force-
    close it), that dangling statement pins the WHOLE CONNECTION's WAL
    reader mark for the rest of the run_all() pass -- so producer B never
    gets an independent checkpoint success either way, ablated or patched.
    That framing was a dead end (verified empirically, not merely reasoned
    about) and is NOT what this test checks.

  - A THIRD framing -- counting "database is locked" errors from a
    concurrent writer thread -- was measured and found NOISY: ablated runs
    showed 21/26/21 lock errors across three repeats, patched runs showed
    1/24/1. The ranges overlap; it is not a reliable discriminator.

  - What DOES cleanly and deterministically discriminate patched from
    ablated, with ZERO threads and ZERO timing races, is exactly the
    scenario below: two trivial NON-scanning producers (each does a plain
    `session.execute(text(...)).scalar()`, which SQLAlchemy's own
    `Result.first()` semantics soft-close immediately -- so the WAL-guard's
    fetchmany()-driven release is NEVER exercised by either producer, and
    the ONLY commit mechanism in play is run_all()'s own trailing
    `_release_transaction()` call) around a pre-existing PENDING write
    (mimicking evaluate_watches()'s flush-but-not-commit). With
    `_release_transaction(session)` present: the pending write becomes
    visible to a wholly separate connection, and a deterministic
    (non-threaded) post-run_all checkpoint attempt succeeds (busy=0, WAL
    fully truncated). With it removed (`pass`), NEITHER holds: the write
    stays invisible, and the SAME checkpoint attempt reports busy=1 --
    because the reader_session's connection still has an open, uncommitted
    transaction pinning the WAL, regardless of the producer statements
    having self-closed.

Both directions were run three times each during development; the result
was identical every time (patched: visible=1/busy=0/fully-truncated three
for three; ablated: visible=0/busy=1/untouched three for three).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from src.briefing import registry
from src.database import session as db_session
from src.scheduler import hygiene
from src.scheduler.hygiene import checkpoint_wal


def _fresh_wal_engine(db_path: Path):
    eng = create_engine(f"sqlite:///{db_path}", future=True)
    event.listen(eng, "connect", db_session._sqlite_pragmas)
    with eng.connect() as c:
        c.exec_driver_sql("CREATE TABLE t(x)")
        c.commit()
    return eng


def _simple_producer_1(session):
    """A plain, non-scanning producer: one .scalar() call, no fetchmany()."""
    session.execute(text("SELECT 1")).scalar()
    return []


def _simple_producer_2(session):
    session.execute(text("SELECT 2")).scalar()
    return []


def test_run_all_commit_between_producers_persists_a_pending_write_and_unblocks_a_checkpoint(
    tmp_path, monkeypatch
):
    """run_all()'s trailing _release_transaction() must (a) durably commit a
    pending write made BEFORE run_all() was called (mimicking
    evaluate_watches()'s flush-then-run_all pattern from refresh_briefing),
    and (b) as a direct consequence, leave the connection in a state where a
    checkpoint immediately AFTER run_all() returns can succeed -- neither of
    which the WAL-guard's own fetchmany()-driven release mechanism provides
    on its own, since neither producer here ever calls fetchmany().
    """
    monkeypatch.setattr(hygiene, "_LAST_CKPT_MONO", None)
    monkeypatch.setattr(registry, "_REGISTRY", [])
    registry.register("simple_1", _simple_producer_1)
    registry.register("simple_2", _simple_producer_2)

    db_path = Path(tempfile.mkdtemp()) / "wal_commit_between_producers.db"
    eng = _fresh_wal_engine(db_path)
    Session = sessionmaker(bind=eng, future=True)
    reader_session = Session()
    try:
        # Mimic refresh_briefing's real shape: a prior step (evaluate_watches
        # in production) writes and FLUSHES but does NOT commit, before
        # run_all() runs.
        reader_session.execute(text("INSERT INTO t VALUES ('flush_marker')"))

        registry.run_all(reader_session)

        # (a) durability: a wholly separate connection must see the row --
        # i.e. it was actually COMMITTED at some point during run_all(), not
        # merely sitting in reader_session's own open transaction.
        with eng.connect() as check_conn:
            n = check_conn.exec_driver_sql("SELECT COUNT(*) FROM t").scalar()
        assert n == 1, (
            "run_all() must commit a pending pre-existing write between "
            "producers (evaluate_watches()'s flush-then-run_all pattern), "
            "not merely release its own WAL-guard scan cursors"
        )

        # (b) consequence: with the pending write durably committed and
        # neither producer's own statement ever pinning the WAL (both used
        # only .scalar(), never fetchmany()), a checkpoint attempted right
        # after run_all() returns must succeed and fully truncate the WAL.
        rec = checkpoint_wal(engine=eng, force=True, busy_timeout_ms=200)
        assert rec is not None
        assert rec["busy"] == 0, (
            "a checkpoint immediately after run_all() must succeed once the "
            "pending write is committed -- a busy=1 here means the reader "
            "session's connection still has an open, uncommitted "
            "transaction pinning the WAL"
        )
        assert rec["wal_bytes_after"] == 0
    finally:
        reader_session.close()
        eng.dispose()
