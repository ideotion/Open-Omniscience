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
_SCAN_CHUNKS = 12  # fetchmany() iterations in the simulated slow scan. Widened
# from 8 (2026-07-28) so the window is long enough for BOTH the writer to
# accumulate WAL past the bar and the checkpointer to get enough attempts in on
# a slower runner.
_WRITER_BLOB_BYTES = 1024 * 1024  # per-write payload. Raised from 256 KiB
# (2026-07-28): measured across writer speeds, 256 KiB peaked at only ~1.2 MB on
# a slow writer -- under the 2x bar -- which is how the macOS lane failed at
# 1.63 MB. 1 MiB clears the bar at every speed measured (2.1-14.9 MB). 2 MiB was
# tried and REJECTED: it clears (a) even more easily but starves the
# checkpointer (measured 0/8 successful attempts at one speed), which would
# break assertion (b) -- the discriminating one. 1 MiB satisfies both.
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
        for _ in range(_SCAN_CHUNKS):
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
                    c.exec_driver_sql(f"INSERT INTO t VALUES (randomblob({_WRITER_BLOB_BYTES}))")
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

    # Sampler thread: track the WAL's PEAK size across the window.
    #
    # WHY A TRACKED PEAK AND NOT A SINGLE stat() AT THE END (a macOS-CI
    # failure, root-caused 2026-07-28): a SUCCESSFUL checkpoint TRUNCATES the
    # -wal file to 0 bytes (empirically confirmed: sampling right after each
    # busy=0 attempt reads 0). Once PR-D's fix landed, checkpoints DO succeed
    # mid-window -- that is the whole point of assertion (b) below -- so an
    # end-of-window stat() no longer measures "how far the WAL grew"; it
    # measures only whatever the writer thread happened to re-accumulate
    # since the LAST successful truncation. That is a pure race against
    # writer throughput: the Linux runner re-accumulated ~4.9 MB (passing),
    # the macOS runner only ~1.63 MB (failing the > 2 MB bar) for reasons
    # entirely unrelated to the behaviour under test. So the assertion was
    # structurally SELF-DEFEATING -- the better the fix works, the more
    # likely it failed -- and it never measured the "peak" its own comment
    # claimed. Tracking the real running maximum restores the stated intent
    # (prove the scenario produces genuine sustained growth) and is immune to
    # the fix's own truncations.
    wal_peak_bytes = 0

    def _sample_wal_peak():
        nonlocal wal_peak_bytes
        while not stop_checkpointer.is_set():
            if wal_path.exists():
                wal_peak_bytes = max(wal_peak_bytes, wal_path.stat().st_size)
            time.sleep(0.01)

    sampler_thread = threading.Thread(target=_sample_wal_peak)
    sampler_thread.start()

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
        sampler_thread.join(5.0)
        # One last sample WHILE the reader's snapshot is still pinned (before
        # closing the session), folded into the running peak -- so a future
        # fix that cleanly reclaims the WAL once run_all() itself returns can
        # never retroactively shrink what we are about to assert grew.
        if wal_path.exists():
            wal_peak_bytes = max(wal_peak_bytes, wal_path.stat().st_size)
        reader_session.close()

    assert not write_errors, f"writer thread hit unexpected errors: {write_errors}"
    assert len(ckpt_results) > 0, (
        "no checkpoint attempts landed during run_all()'s window -- widen "
        "the simulated scan (more fetchmany() iterations / longer sleeps) "
        "so the ratio is observable"
    )

    # (a) the WAL genuinely grew past N x journal_size_limit at some point
    # while the simulated reader was still iterating -- proves this
    # reproduces real starvation (sustained growth outrunning the
    # checkpointer), not a trivial edge case. Asserted against the tracked
    # PEAK, never an end-of-window snapshot: see _sample_wal_peak above for
    # why a single trailing stat() raced the fix's own truncations.
    assert wal_peak_bytes > 2 * _JOURNAL_SIZE_LIMIT_BYTES, (
        f"expected the WAL to grow past 2x the {_JOURNAL_SIZE_LIMIT_BYTES}-"
        f"byte journal_size_limit at some point while run_all()'s shared "
        f"session held its read open; peak observed was only "
        f"{wal_peak_bytes} bytes -- the starvation scenario did not "
        "reproduce (widen the simulated scan or the writer's blob size)"
    )

    # Cross-check via the app's own diagnostic (storage_composition, the
    # WAL-visibility surface S3 §Phase-A shipped for operators): the operator
    # surface genuinely reports the WAL. NOT asserted against a size
    # threshold -- this runs AFTER the window, by which point a successful
    # checkpoint may legitimately have truncated the file to 0, so any
    # threshold here would race the very fix under test (the same defect
    # assertion (a) above was fixed for).
    diag_session = Session()
    try:
        composition = storage_composition(diag_session)
    finally:
        diag_session.close()
    assert isinstance(composition.get("wal_bytes"), int), (
        "storage_composition must surface wal_bytes for operators"
    )

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
