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

Why the window is WRITE-GATED, not time-boxed
---------------------------------------------
The reader's window closes once the writer has committed ``_TARGET_WRITES``
times — it is NOT a fixed wall-clock duration. This matters because the two
assertions below are in direct tension:

* (b), the discriminating guard, proves checkpoints now SUCCEED mid-pass;
* a successful checkpoint TRUNCATES the ``-wal`` to 0 bytes;
* so (a), the "the WAL really did grow" precondition, gets harder to
  satisfy exactly as the fix works better.

Originally the window was ``12 x 0.1s`` of wall clock, which made how much
WAL accumulated depend entirely on how many writes a given runner happened
to fit into that fixed time. Three CI lanes failed on this — Linux
core-only at 815,792 B, macOS at 1,087,712 B and 1,631,552 B, all under the
2 MiB bar — while the same code passed locally, purely because the local
writer was faster. Gating on writes observed makes the accumulated volume
deterministic (``_TARGET_WRITES x _WRITER_BLOB_BYTES``); a slow machine
simply takes longer, and ``_WINDOW_CAP_S`` fails loudly rather than
silently measuring less. Measured constant at ~5.2 MB across a 150x
writer-speed sweep, against a 2.1 MB bar.
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
_WRITER_BLOB_BYTES = 1024 * 1024  # per-write payload. 2 MiB was tried and
# REJECTED: it clears (a) more easily but starves the checkpointer (measured
# 0/8 successful attempts at one speed), which would break assertion (b) -- the
# discriminating one. 1 MiB satisfies both, so this is NOT the lever to reach
# for when (a) comes up short; _TARGET_WRITES below is.
_TARGET_WRITES = 12  # the reader's window closes once the writer has committed
# this many times -- NOT after a fixed wall-clock duration. This is what makes
# assertion (a) runner-speed-INDEPENDENT; see the "why the window is
# write-gated" section of the module docstring.
#
# WHY 12 AND NOT 4 (macOS observation lane, 2026-08-02). At 4 this test failed
# on macOS with 2,006,504 bytes against a 2,097,152 bar -- 96% of the way there,
# i.e. calibrated so tightly that a platform yielding slightly less measured
# growth per commit tips it over. It is not runner SPEED (the window is
# write-gated precisely so speed cannot matter); macOS simply accounts ~45% of
# the cumulative growth per commit that the Linux runners do. Measured here,
# same box, same commit:
#
#     writes:   4        8        12        16
#     growth:   4.46 MB  9.33 MB  13.06 MB  16.91 MB   (Linux)
#     ratio:    2.13x    4.45x    6.23x     8.06x      (of the 2 MiB bar)
#     window:   0.22s    0.55s    0.85s     1.05s
#
# Scaling macOS's observed 0.50 MB/commit, 12 writes puts it at ~2.8x -- back to
# the ~2.5x margin this file was designed around, on the WEAKEST platform seen
# rather than the strongest. The assertion THRESHOLD is deliberately untouched:
# more writes is more WAL pressure, so this strengthens the reproduction rather
# than lowering the bar it has to clear. It also helps assertion (b), whose own
# failure message names raising _TARGET_WRITES as the remedy for a window too
# short to observe a checkpoint attempt in. Cost is under a second either way,
# nowhere near _WINDOW_CAP_S.
_WINDOW_CAP_S = 30.0  # safety cap so a hung/failing writer can never hang the
# suite. Exceeding it fails LOUDLY below rather than silently measuring less.
_SEED_ROWS = 200  # empirically: enough that the fetchmany() scan below never
# exhausts mid-run (a short seed lets the reader's cursor finish naturally
# and release its snapshot early, defeating the reproduction — verified
# while designing this test: 20 seed rows let SOME mid-pass checkpoints
# through non-deterministically; 200 reproduces 100% of the time).

# This test's scan lasts ~0.85 s (12 write-gated fetchmany() calls).
# Production's release throttle (registry._WAL_GUARD_MIN_RELEASE_INTERVAL_S)
# is 30 s, and its own comment sizes it for a scan that "can run for
# MINUTES", which "comfortably gives such a scan several release windows".
#
# A sub-second scan gets no such thing. Every release after the
# unconditional first one is throttled out, so the whole test hangs on ONE
# momentary window and whether the checkpointer's 20 ms poll lands inside it
# is thread-scheduling luck. That is why this test went red on the PR lane of
# run 33881993602 while the SAME commit (2d12708) passed both in that run's
# own `test` lane and in the push lane's Core-only job.
#
# MEASURED on this sandbox (4 cores), 12 spinners = 3x oversubscription, the
# loaded-shared-runner shape: as-is 4 pass / 6 fail; with the interval below
# 10 pass / 0 fail. Idle it passed either way, which is exactly why the
# failure only ever appeared on CI.
#
# This does NOT weaken the guard. It raises the pressure the guard is fed
# rather than lowering the bar it must clear, and an unpatched build cannot
# benefit: the constant has exactly ONE read site (registry.py's
# _WalGuardResult.fetchmany), which is a method an unpatched build does not
# have at all. Production's 30 s is untouched.
#
# This is the same recorded lesson the SIBLING soak test already carries
# (tests/test_wal_starvation_soak.py, 2026-08-04: "a test that compresses
# time must compress the throttles too"); this file simply never got it.
_TEST_RELEASE_INTERVAL_S = 0.05
# ...and the floor below is what stops a silent regression to the
# single-window shape if the monkeypatch is ever dropped. MEASURED on this
# sandbox, same box, same commit -- releases observed during one scan:
#
#     uncompressed (production 30 s):  3, 3, 3          (deterministic)
#     compressed, idle:                8
#     compressed, 3x oversubscribed:   8,8,8,8,8,8,10,12 (min 8)
#
# so 4 sits between the two populations with margin on both sides: it cannot
# false-fail a compressed run (min observed is double it) and it does catch an
# uncompressed one. Asserted, never assumed.
_MIN_RELEASES = 4


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
    across a ``fetchmany()`` loop (simulating a slow multi-minute scan,
    scaled down for a fast test). A second thread does many small commits on
    a SEPARATE connection throughout the run (simulating ongoing article
    ingest — this is what actually grows the WAL). A third thread repeatedly
    attempts a checkpoint, standing in for the project's real ~300 s cadence
    at a scale where the RATIO of attempts landing during the open reader is
    observable in a fast test.

    The producer advances ONE ``fetchmany()`` per write it observes, so the
    window is bounded by WRITES rather than wall clock — see the module
    docstring's "why the window is write-gated" section for the three CI
    failures that motivated it. A fourth thread samples the ``-wal`` to
    accumulate its total GROWTH, which a mid-window truncation cannot erase.
    """
    monkeypatch.setenv("OO_WAL_SIZE_LIMIT_MB", str(_JOURNAL_SIZE_LIMIT_MB))
    _fresh_cadence(monkeypatch)
    eng, db = _wal_engine(tmp_path)
    wal_path = Path(str(db) + "-wal")

    # Isolate the module-global producer registry for this test only (other
    # tests / production import-time registrations must never run here, and
    # monkeypatch restores the real registry when this test ends).
    monkeypatch.setattr(registry, "_REGISTRY", [])

    # Give this sub-second scan the several in-scan release windows a real
    # minutes-long scan gets under the production 30 s throttle, instead of
    # the single momentary one it would otherwise hang on. See
    # _TEST_RELEASE_INTERVAL_S for the measurement and for why this cannot
    # weaken the discriminating assertion below.
    monkeypatch.setattr(
        registry, "_WAL_GUARD_MIN_RELEASE_INTERVAL_S", _TEST_RELEASE_INTERVAL_S
    )

    # Count the releases rather than trusting the patch above took effect. The
    # constant is read as a module global at call time; if that wrapper is ever
    # changed to bind it at import, or the monkeypatch is dropped, this counter
    # is what notices -- loudly, instead of the test quietly going back to
    # being a coin flip.
    releases: list[float] = []
    _real_release = registry._release_transaction

    def _counting_release(session):
        releases.append(time.monotonic())
        return _real_release(session)

    monkeypatch.setattr(registry, "_release_transaction", _counting_release)

    # Signalled once per committed write, so the reader below can gate its
    # window on WRITES OBSERVED rather than on wall-clock time.
    write_ticks = threading.Semaphore(0)
    writes_committed = 0
    window_timed_out = False
    window_open_mono = 0.0
    window_close_mono = 0.0

    def _slow_scan_producer(session):
        # Mimics build_keyword_daily's shape exactly: ONE session.execute()
        # SELECT, held open across a fetchmany() loop -- the SAME cursor
        # stays alive (unfetched rows remaining) for the whole simulated
        # scan, never dereferenced until it completes.
        #
        # One fetchmany() per OBSERVED WRITE, instead of a fixed iteration
        # count with a fixed sleep. See the module docstring: this is what
        # decouples how much WAL accumulates from how fast the runner is.
        nonlocal window_timed_out, window_open_mono, window_close_mono
        result = session.execute(text("SELECT x FROM t"))
        window_open_mono = time.monotonic()
        deadline = window_open_mono + _WINDOW_CAP_S
        seen = 0
        while seen < _TARGET_WRITES:
            if time.monotonic() > deadline:
                window_timed_out = True
                break
            if not write_ticks.acquire(timeout=0.25):
                continue  # writer is slow -- keep the cursor open and wait
            seen += 1
            chunk = result.fetchmany(3)
            if not chunk:
                break  # cursor exhausted (cannot happen: _SEED_ROWS >> reads)
        # Stamped BEFORE returning, i.e. while the cursor is still open. Any
        # checkpoint attempt after this instant is OUTSIDE the window under
        # test -- run_all() releases the snapshot on the way out, so a late
        # attempt succeeds even on unpatched code and would make assertion
        # (b) pass spuriously. Measured: that race made the unpatched run
        # pass 1 time in 3 before this filter existed.
        window_close_mono = time.monotonic()
        return []

    registry.register("fake_slow_scan_producer", _slow_scan_producer)

    # Writer thread: many small commits on a SEPARATE connection throughout
    # run_all()'s execution (simulating ongoing article ingest).
    stop_writer = threading.Event()
    write_errors: list[str] = []

    def _writer():
        nonlocal writes_committed
        while not stop_writer.is_set():
            try:
                with eng.connect() as c:
                    c.exec_driver_sql(f"INSERT INTO t VALUES (randomblob({_WRITER_BLOB_BYTES}))")
                    c.commit()
                writes_committed += 1
                write_ticks.release()
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
                ckpt_results.append({**rec, "_mono": time.monotonic()})
            # 0.02s, not 0.05s: on a FAST runner the write-gated window can be
            # ~0.1s, which at 0.05s left only 2 attempts. This raises the
            # sample count without coupling WAL VOLUME to wall clock (that
            # stays write-gated) -- the checkpointer just needs enough tries.
            time.sleep(0.02)

    checkpointer_thread = threading.Thread(target=_checkpointer)
    checkpointer_thread.start()

    # Sampler thread: track CUMULATIVE WAL growth across the window -- the sum
    # of every positive size delta, so a truncation subtracts nothing.
    #
    # WHY CUMULATIVE AND NOT A TRAILING stat(), NOR EVEN A PEAK (root-caused
    # 2026-07-28 from three CI failures): a SUCCESSFUL checkpoint TRUNCATES
    # the -wal to 0 bytes (empirically confirmed by sampling right after each
    # busy=0 attempt). Once PR-D's fix landed, checkpoints DO succeed
    # mid-window -- that is exactly what assertion (b) proves -- so:
    #
    #   * a trailing stat() measures only what the writer re-accumulated
    #     since the LAST truncation. Observed in CI: 815,792 B (Linux
    #     core-only), 1,087,712 B and 1,631,552 B (macOS) -- all under the
    #     2 MiB bar, for reasons unrelated to the behaviour under test.
    #   * a tracked PEAK is better but STILL insufficient: measured here
    #     across a writer-speed sweep, the peak plateaus at 2,010,592 B once
    #     the writer is slow enough that only two writes land between
    #     truncations -- just UNDER the 2,097,152 B bar. A peak-only fix
    #     would have kept this lane red.
    #
    # Assertions (a) and (b) are in direct TENSION: the better the fix works,
    # the more the WAL is reclaimed, and the harder an instantaneous-size
    # assertion is to satisfy. Cumulative growth removes that tension --
    # truncation cannot erase it -- so (a) becomes a genuine, fix-INVARIANT
    # precondition ("the scenario really did put the WAL under sustained
    # pressure") while (b) stays the discriminating regression guard.
    wal_growth_bytes = 0

    def _sample_wal_growth():
        nonlocal wal_growth_bytes
        previous = 0
        while not stop_checkpointer.is_set():
            try:
                current = wal_path.stat().st_size if wal_path.exists() else 0
            except OSError:  # raced a truncation/unlink -- treat as 0, never crash
                current = 0
            if current > previous:
                wal_growth_bytes += current - previous
            previous = current
            time.sleep(0.005)

    sampler_thread = threading.Thread(target=_sample_wal_growth)
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
        reader_session.close()

    assert not write_errors, f"writer thread hit unexpected errors: {write_errors}"
    assert not window_timed_out, (
        f"the reader's window hit its {_WINDOW_CAP_S}s safety cap before the "
        f"writer committed {_TARGET_WRITES} times (only {writes_committed} "
        "landed) -- the runner is far slower than any measured here, or the "
        "writer thread is wedged. Failing loudly rather than silently "
        "measuring a shorter window."
    )
    assert len(ckpt_results) > 0, (
        "no checkpoint attempts landed during run_all()'s window -- widen "
        "the simulated scan (raise _TARGET_WRITES) so the ratio is observable"
    )

    # (a) PRECONDITION: the WAL genuinely accumulated past 2x
    # journal_size_limit while the simulated reader held its read open --
    # proving this reproduces real sustained pressure, not a trivial edge
    # case. Asserted against CUMULATIVE growth, never an instantaneous size:
    # see _sample_wal_growth above for why both a trailing stat() and a
    # tracked peak raced the fix's own truncations.
    #
    # Measured stability of this figure across a 150x writer-speed sweep
    # (0.02s -> 3.0s per write), which is what makes it runner-independent:
    #   trailing stat(): 1,062,992 -> 0          (fails below ~0.5s/write)
    #   tracked peak:    2,125,952 -> 2,010,592  (fails below ~1.0s/write)
    #   cumulative:      5,203,688 -> 5,203,688  (constant; ~2.5x the bar)
    assert wal_growth_bytes > 2 * _JOURNAL_SIZE_LIMIT_BYTES, (
        f"expected the WAL to accumulate more than 2x the "
        f"{_JOURNAL_SIZE_LIMIT_BYTES}-byte journal_size_limit while "
        f"run_all()'s shared session held its read open; total growth was "
        f"only {wal_growth_bytes} bytes across {writes_committed} writes -- "
        "the starvation scenario did not reproduce (raise _TARGET_WRITES or "
        "_WRITER_BLOB_BYTES)"
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

    # Anti-vacuity: prove the compression above actually took effect BEFORE
    # the discriminating assertion (b) below runs. Uncompressed the scan
    # releases 3 times (measured), assertion (b) becomes a coin flip, and its
    # failure message would blame run_all() for a defect that is really this
    # test's own throttle. Failing here instead names the real cause.
    assert len(releases) >= _MIN_RELEASES, (
        f"only {len(releases)} WAL release(s) happened during the scan -- "
        f"expected at least {_MIN_RELEASES}. TWO causes produce this and the "
        "count cannot tell them apart, so check both: (1) the production fix "
        "is gone or weakened -- _WalGuardResult.fetchmany no longer releases "
        "mid-scan, which is the very regression this file exists to catch "
        "(measured: 2 releases with it removed); or (2) this test's own "
        "release-interval compression did not take effect -- the monkeypatch "
        "above was dropped, or _WalGuardResult now binds the constant at "
        "import instead of reading it per call (measured: 3 releases), which "
        "would leave assertion (b) below a coin flip rather than a guard."
    )

    # (b) THE REGRESSION (the discriminating assertion): today, with NO
    # commit anywhere in run_all()'s producer loop, the FIRST producer's
    # read pins the WAL snapshot for the WHOLE pass -- so *every* checkpoint
    # attempted while run_all() is still running reports busy=1, never once
    # succeeding. Once PR-D lands (a commit between producers), a genuine
    # transaction boundary opens mid-pass and at least one checkpoint
    # attempted during the window should succeed.
    #
    # Restricted to attempts that landed STRICTLY INSIDE the producer's
    # held-cursor window. run_all() releases the read snapshot on its way out
    # (the between-producer commit, and the WAL-guard context's exit cleanup),
    # so an attempt landing in the gap between run_all() returning and the
    # checkpointer thread observing its stop flag succeeds even on UNPATCHED
    # code. Measured before this filter existed: the unpatched run passed 1
    # time in 3 on that race alone -- i.e. the guard silently stopped
    # discriminating a third of the time.
    in_window = [
        rec for rec in ckpt_results
        if window_open_mono <= rec["_mono"] <= window_close_mono
    ]
    assert in_window, (
        f"no checkpoint attempt landed inside the producer's held-cursor "
        f"window ({window_close_mono - window_open_mono:.3f}s, "
        f"{len(ckpt_results)} attempts total) -- the window is too short to "
        "observe anything; raise _TARGET_WRITES."
    )
    assert any(rec["busy"] == 0 for rec in in_window), (
        f"every one of the {len(in_window)} checkpoint attempts made while "
        "run_all()'s producer held its cursor open reported busy=1 (none "
        "ever succeeded) -- run_all()'s shared session, never committed "
        "between producers, starves the checkpoint for its ENTIRE duration. "
        "This is the diagnosed root cause (PR-D / W1): fix run_all() to "
        "commit between producers so a checkpoint attempted mid-pass can "
        "eventually succeed."
    )

    eng.dispose()
