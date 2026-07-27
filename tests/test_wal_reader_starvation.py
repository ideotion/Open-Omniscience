"""
Regression test — WAL/checkpoint starvation under a long-lived shared session.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Diagnosed root cause (docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-26_
HARDWARE_DIAGNOSTICS_COMPARISON.md §1 "WAL/checkpoint starvation";
docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-26_EXECUTION_PLAN.md Phase 3,
PR-D (W1)): ``src/briefing/registry.py``'s ``run_all()`` runs every
registered producer on ONE shared session, and today (unpatched) nothing in
its loop ever commits or closes that session between producers. A read
taken by any producer therefore keeps a WAL read snapshot pinned for
``run_all()``'s ENTIRE duration — so ``PRAGMA wal_checkpoint(TRUNCATE)`` can
never reclaim space while it runs, no matter how many times it is
attempted, and the ``-wal`` file grows without bound past
``journal_size_limit`` in the meantime.

This mirrors the SAME field-diagnosed mechanism the brief names for
``src/analytics/columnar.py``'s ``build_keyword_daily`` (a ``session.
execute(SELECT ...)`` held open across a ``fetchmany`` loop while the WAL
keeps growing from ongoing writes) — but ``columnar.py`` needs a live
``duckdb`` connection to even call, and ``duckdb`` is unavailable in this
sandbox (``ModuleNotFoundError: No module named 'duckdb'``, the project's
own documented "columnar/duckdb paths are CI-only" pattern). ``run_all()``
is the SAME class of long-lived-shared-session reader — explicitly named as
one of PR-D's own three fix targets ("commit-between-producers … changes
atomicity") — and is fully reproducible here without duckdb, so this test
drives it directly instead of a synthetic stand-in.

MUST FAIL on unpatched main: with no commit ever issued between producers,
EVERY checkpoint attempted while ``run_all()`` is executing reports
``busy=1`` (the shared session's read snapshot is pinned for the whole
pass) — so a checkpoint attempted mid-pass never once succeeds. This test
asserts the FIXED guarantee instead: that at least one checkpoint attempted
during a ``run_all()`` pass eventually succeeds. That is false today and
will flip true once PR-D's fix (a commit between producers, opening a real
transaction boundary mid-pass) lands.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from src.briefing import registry
from src.database import session as S
from src.monitoring.storage import storage_composition
from src.scheduler import hygiene
from src.scheduler.hygiene import checkpoint_wal

_JOURNAL_SIZE_LIMIT_MB = 1
_JOURNAL_SIZE_LIMIT_BYTES = _JOURNAL_SIZE_LIMIT_MB * 1024 * 1024
_SEED_ROWS = 200  # empirically: enough that the fetchmany() scan below never
# exhausts mid-run (a short seed lets the reader's cursor finish naturally
# and release its snapshot early, defeating the reproduction — verified
# while designing this test: 20 seed rows let SOME mid-pass checkpoints
# through non-deterministically; 200 reproduces 100% of the time).


def _wal_engine(tmp_path, name="wal_starve.db", seed_rows=_SEED_ROWS):
    """A REAL file-backed WAL database, isolated from the shared store.

    Wires the app's OWN connect-time pragmas (``src.database.session.
    _sqlite_pragmas`` — the SAME event-listener pattern
    ``tests/test_wal_ceiling.py``'s ``test_storage_composition_surfaces_
    wal_and_limit`` uses) so ``journal_size_limit`` honours
    ``OO_WAL_SIZE_LIMIT_MB``; ``tests/test_wal_checkpoint.py``'s bare
    ``_wal_engine`` (``PRAGMA journal_mode=WAL`` only, no pragmas event)
    never sets a limit worth asserting growth "past N times" of.
    """
    db = tmp_path / name
    eng = create_engine(f"sqlite:///{db}", future=True)
    event.listen(eng, "connect", S._sqlite_pragmas)
    with eng.connect() as c:
        c.exec_driver_sql("CREATE TABLE t(x)")
        for _ in range(seed_rows):
            c.exec_driver_sql("INSERT INTO t VALUES (randomblob(4096))")
        c.commit()
    return eng, db


def _fresh_cadence(monkeypatch):
    """Reset the module's min-interval memory so each test decides for itself."""
    monkeypatch.setattr(hygiene, "_LAST_CKPT_MONO", None)


def test_run_all_starves_every_checkpoint_for_its_whole_duration(tmp_path, monkeypatch):
    """
    Reproduces the diagnosed WAL-checkpoint-starvation mechanism through the
    REAL ``src.briefing.registry.run_all()`` code path (one of PR-D's named
    fix targets), with a small ``journal_size_limit`` so growth past it is
    fast to observe.

    A generator-shaped producer mimics ``build_keyword_daily``: it calls
    ``session.execute(SELECT ...)`` ONCE and holds the resulting cursor open
    across a ``fetchmany()`` loop with a deliberate ``time.sleep()`` between
    chunks (simulating a slow multi-minute scan, scaled down for a fast
    test). A second thread does many small commits on a SEPARATE connection
    throughout the run (simulating ongoing article ingest — this is what
    actually grows the WAL). A third thread periodically attempts a
    checkpoint on roughly the project's real ~300 s cadence, scaled down so
    the RATIO of attempts landing during the open reader is observable in a
    normal test run.
    """
    monkeypatch.setenv("OO_WAL_SIZE_LIMIT_MB", str(_JOURNAL_SIZE_LIMIT_MB))
    _fresh_cadence(monkeypatch)
    eng, db = _wal_engine(tmp_path)
    wal_path = Path(str(db) + "-wal")

    # Isolate the module-global producer registry for this test only (other
    # tests / production import-time registrations must never run here, and
    # monkeypatch restores the real registry when this test ends).
    monkeypatch.setattr(registry, "_REGISTRY", [])

    def _slow_scan_producer(session):
        # Mimics build_keyword_daily's shape exactly: ONE session.execute()
        # SELECT, held open across a fetchmany() loop with sleeps between
        # chunks -- the SAME cursor stays alive (unfetched rows remaining)
        # for the whole simulated scan, never dereferenced until it
        # completes.
        result = session.execute(text("SELECT x FROM t"))
        for _ in range(8):
            chunk = result.fetchmany(3)
            if not chunk:
                break
            time.sleep(0.1)
        return []

    registry.register("fake_slow_scan_producer", _slow_scan_producer)

    # Writer thread: many small commits on a SEPARATE connection throughout
    # run_all()'s execution (simulating ongoing article ingest).
    stop_writer = threading.Event()
    write_errors: list[str] = []

    def _writer():
        while not stop_writer.is_set():
            try:
                with eng.connect() as c:
                    c.exec_driver_sql("INSERT INTO t VALUES (randomblob(262144))")
                    c.commit()
            except Exception as exc:  # noqa: BLE001 - captured, asserted below
                write_errors.append(str(exc))
            time.sleep(0.02)

    writer_thread = threading.Thread(target=_writer)
    writer_thread.start()

    # Checkpointer thread: periodically attempts a checkpoint -- roughly the
    # project's real ~300 s cadence, scaled to a fast interval so the ratio
    # of attempts landing during the open reader is observable here.
    stop_checkpointer = threading.Event()
    ckpt_results: list[dict] = []

    def _checkpointer():
        while not stop_checkpointer.is_set():
            rec = checkpoint_wal(engine=eng, force=True, busy_timeout_ms=50)
            if rec is not None:
                ckpt_results.append(rec)
            time.sleep(0.05)

    checkpointer_thread = threading.Thread(target=_checkpointer)
    checkpointer_thread.start()

    # Drive the REAL registry.run_all() -- its shared, never-committed
    # session is exactly the mechanism named in the brief.
    Session = sessionmaker(bind=eng, future=True)
    reader_session = Session()
    try:
        registry.run_all(reader_session)
    finally:
        stop_writer.set()
        stop_checkpointer.set()
        writer_thread.join(5.0)
        checkpointer_thread.join(5.0)
        # Measure the WAL's peak size WHILE the reader's snapshot is still
        # pinned (before closing the session) -- so a future fix that
        # cleanly reclaims the WAL once run_all() itself returns can never
        # retroactively shrink what we are about to assert grew.
        wal_bytes_during_window = wal_path.stat().st_size if wal_path.exists() else 0
        reader_session.close()

    assert not write_errors, f"writer thread hit unexpected errors: {write_errors}"
    assert len(ckpt_results) > 0, (
        "no checkpoint attempts landed during run_all()'s window -- widen "
        "the simulated scan (more fetchmany() iterations / longer sleeps) "
        "so the ratio is observable"
    )

    # (a) the WAL genuinely grew past N x journal_size_limit while the
    # simulated reader was still iterating -- proves this reproduces real
    # starvation (sustained, unreclaimed growth), not a trivial edge case.
    assert wal_bytes_during_window > 2 * _JOURNAL_SIZE_LIMIT_BYTES, (
        f"expected the WAL to grow past 2x the {_JOURNAL_SIZE_LIMIT_BYTES}-"
        f"byte journal_size_limit while run_all()'s shared session held its "
        f"read open; observed only {wal_bytes_during_window} bytes -- the "
        "starvation scenario did not reproduce"
    )

    # Cross-check via the app's own diagnostic (storage_composition, the
    # WAL-visibility surface S3 §Phase-A shipped for operators) -- a fresh,
    # short-lived session sees the same unreclaimed growth.
    diag_session = Session()
    try:
        composition = storage_composition(diag_session)
    finally:
        diag_session.close()
    assert composition.get("wal_bytes", 0) > 2 * _JOURNAL_SIZE_LIMIT_BYTES

    # (b) THE REGRESSION (the discriminating assertion): today, with NO
    # commit anywhere in run_all()'s producer loop, the FIRST producer's
    # read pins the WAL snapshot for the WHOLE pass -- so *every* checkpoint
    # attempted while run_all() is still running reports busy=1, never once
    # succeeding. Once PR-D lands (a commit between producers), a genuine
    # transaction boundary opens mid-pass and at least one checkpoint
    # attempted during the window should succeed.
    assert any(rec["busy"] == 0 for rec in ckpt_results), (
        f"every one of the {len(ckpt_results)} checkpoint attempts made "
        "while run_all() was executing reported busy=1 (none ever "
        "succeeded) -- run_all()'s shared session, never committed between "
        "producers, starves the checkpoint for its ENTIRE duration. This is "
        "the diagnosed root cause (PR-D / W1): fix run_all() to commit "
        "between producers so a checkpoint attempted mid-pass can "
        "eventually succeed."
    )

    eng.dispose()
