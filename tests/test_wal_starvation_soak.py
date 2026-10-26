"""End-to-end SOAK test for PR-D / W1: the checkpoint-succeeds-during-a-busy-
producer property (the core promise of the fix) must hold RELIABLY and
REPEATABLY across sustained use -- not just once, by luck, on a single
invocation -- and the WAL must never be allowed to grow WITHOUT BOUND: even
while a checkpoint is legitimately busy (a live scan takes real wall-clock
time, patched or not), the observed WAL size stays within a fixed, bounded
multiple of the configured ceiling, round after round.

DESIGN NOTE on why this is 3 INDEPENDENT rounds (fresh engine + fresh
temp-file database each round), not 3 overlapping rounds sharing ONE
accumulating file: an earlier version of this test tried the latter (one
shared WAL file, run_all() called 3 times in a row, each round measuring
where the WAL "settled" once its own threads had been joined) and hit
persistent, unresolved "database table is locked" failures on the SETTLE
checkpoint that neither a short per-writer busy_timeout NOR a bounded
settle-checkpoint retry loop cleared -- a SQLite/connection-pool locking
interaction between the accumulated leftover state of prior rounds' threads
and the checkpoint's own `write_lock()`-guarded PRAGMA call, orthogonal to
whether registry.run_all()'s own commit-between-producers fix is present or
correct. Rather than chase that confound indefinitely, this test isolates
each round on its OWN fresh database, which sidesteps it entirely while
still proving the property that matters: does the fix's checkpoint-progress
guarantee hold up under SUSTAINED, REPEATED use within one process, not
merely on the first call.

(tests/test_wal_reader_starvation.py already proves the single-call version
of this in isolation, at proven 60/60 reliability across many manual
re-runs during development; this file specifically adds the REPEATABILITY
claim on top of that -- and bounds the peak WAL growth observed across every
round, so a fix that degrades or leaks state after repeated use would be
caught here even though it would pass a single-shot test.)

WHY THE ROUND COMPRESSES THE RELEASE INTERVAL (added 2026-08-04, after this
test went red on CI while the SAME commit passed in a sibling run of the same
workflow): the property above needs the scan to OFFER release windows for a
checkpoint to land in. Under production's 30 s throttle a 0.8 s scan offers
exactly ONE -- measured at t=0.009 s -- because every release after the
unconditional first one is throttled out. The round then turns on whether a
checkpointer thread happened to fire inside a nine-millisecond window, which
is luck, and it stopped being lucky on a cold shared runner. Delaying the
checkpointer's first attempt by 0.15 / 0.30 / 0.60 s reproduces the CI failure
at 1/6, 0/6, 0/6 -- and takes the WAL bound with it, from 82% of the ceiling
to 110%, 132%, 158%. See _TEST_RELEASE_INTERVAL_S. Both assertions were
resting on the same accident.

WHY THE WAL BOUND IS RELATIVE TO THE SLOWEST CHECKPOINT ATTEMPT (added
2026-10-26, after the last test of a 1 h 17 min CI run failed it on a docs-only
change, with the code under test unchanged): the byte ceiling was a TIME bound
in disguise. The writer appends ~12.5 MB/s and the WAL read at the end of the
scan is what was written since the last TRUNCATE finished; a TRUNCATE costs 3-4
fsyncs, so on a fast disk (~1 ms) a round peaks at 0-13% of the bound and on a
disk that stalls it does not. The failed run read, round by round, 0.54 / 5.99 /
9.26 MB with 10 / 4 / 2 checkpoint attempts (every round still had its 10 in-scan
releases and a successful checkpoint, so the property held and only the bytes
failed). Delaying every fsync of this test with ``strace -e inject`` reproduces
that shape: 100 ms -> 3-4 attempts and 1.6-2.9 MB; 300 ms -> 1 attempt and
6.2-6.5 MB (over the old bound in every round); 4 or 8 CPU burners change nothing
(13-15 attempts, at most 0.8 MB). The bound is now the fixed headroom PLUS what
the writer appends while the round's slowest attempt is in flight, each term
named in ``_allowed_wal_bytes``. The measured table and the probes are in the
lane folder's soak-failure-2026-10-26 report; the lesson fragment carries the
rule.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from src.briefing import registry
from src.database import session as db_session
from src.scheduler import hygiene
from src.scheduler.hygiene import checkpoint_wal

_JOURNAL_SIZE_LIMIT_MB = 1
_JOURNAL_SIZE_LIMIT_BYTES = _JOURNAL_SIZE_LIMIT_MB * 1024 * 1024
_SEED_ROWS = 200
_ROUNDS = 3
# How far the WAL may grow WHILE a checkpoint is legitimately busy (a live
# scan takes real wall-clock time) before it counts as unbounded growth --
# generous enough to absorb the writer thread's own jitter across repeated
# rounds, but far below what an actually-broken (never-releasing) fix would
# show, which grows for as long as the process keeps running with no ceiling
# at all.
#
# MEASURED HEADROOM (this sandbox, 4 cores, 2026-08-04) with the compressed
# release interval below: a round peaks at 4-13% of this bound. Before that
# compression it peaked at 82% with an idle box and blew straight through it
# -- 110%, 132%, 158% -- as the checkpointer's first attempt was delayed by
# 0.15 s, 0.30 s, 0.60 s. The bound is unchanged; it simply stopped being the
# thing under strain.
_MAX_DURING_WINDOW_MULTIPLE = 6
# One writer row: the blob it inserts. The writer's rate is these bytes per
# second of the round, measured (not assumed) from the rows it committed.
_WRITER_ROW_BYTES = 262144

# The scan in this test lasts ~0.8 s. Production's release throttle
# (registry._WAL_GUARD_MIN_RELEASE_INTERVAL_S) is 30 s, and its own comment
# explains the sizing in terms of a scan that "can run for MINUTES", which
# "comfortably gives such a scan several release windows".
#
# A 0.8 s scan gets NO such thing. Every release after the unconditional
# first one is throttled out, so the whole round hangs on ONE momentary
# window -- MEASURED at t=0.009 s, nine milliseconds in, before the
# checkpointer has finished its first sleep. Whether a checkpoint lands
# inside it is thread-scheduling luck, which is why this test went red on CI
# (run 30889481666) while the SAME commit passed in the sibling run.
#
# So the round compresses the release interval exactly as it already
# compresses the scan itself: several in-scan windows, which is the shape the
# production constant was sized to produce. This does not weaken the
# assertion -- an unpatched build releases ZERO times at ANY interval, and
# the mutation check pinned below fails at 0/5 the moment the in-scan release
# is removed. Production's 30 s is untouched.
_TEST_RELEASE_INTERVAL_S = 0.05
# ...which yields 8 in-scan releases + 1 from run_all's own between-producer
# commit. Asserted (not assumed) per round: without the compression it is 1
# in-scan release, so this floor is what stops a silent regression to the
# single-window shape if the monkeypatch below is ever dropped.
_MIN_RELEASES_PER_ROUND = 4


def _wal_engine(db_path: Path, *, seed_rows: int):
    os.environ["OO_WAL_SIZE_LIMIT_MB"] = str(_JOURNAL_SIZE_LIMIT_MB)
    eng = create_engine(f"sqlite:///{db_path}", future=True)
    event.listen(eng, "connect", db_session._sqlite_pragmas)
    with eng.connect() as c:
        c.exec_driver_sql("CREATE TABLE t(x)")
        for _ in range(seed_rows):
            c.exec_driver_sql("INSERT INTO t VALUES (randomblob(4096))")
        c.commit()
    return eng


def _slow_scan_producer(session):
    result = session.execute(text("SELECT x FROM t"))
    for _ in range(8):
        chunk = result.fetchmany(3)
        if not chunk:
            break
        time.sleep(0.1)
    return []


def _run_one_round(tmp_path: Path, round_i: int, monkeypatch, *, attempt_delay_s: float = 0.0) -> dict:
    """One full round: a slow scanning producer races a background writer and
    a background checkpointer on its OWN fresh database, mirroring
    test_wal_reader_starvation.py's proven single-pass shape exactly. Returns
    the measured facts for this round's assertions. ``attempt_delay_s`` makes every
    checkpoint attempt take that much longer before it runs (a stand-in for a slow
    fsync inside the attempt: the log is reset when the attempt ends either way).
    """
    monkeypatch.setattr(hygiene, "_LAST_CKPT_MONO", None)
    monkeypatch.setattr(registry, "_REGISTRY", [])
    # See _TEST_RELEASE_INTERVAL_S: give this 0.8 s scan the several in-scan
    # release windows a real minutes-long scan gets, instead of the single
    # 9 ms one a sub-second scan gets under the production 30 s throttle.
    monkeypatch.setattr(
        registry, "_WAL_GUARD_MIN_RELEASE_INTERVAL_S", _TEST_RELEASE_INTERVAL_S
    )
    # Count the releases rather than trusting that the patch above took effect
    # (a module-global lookup at call time -- if the wrapper is ever changed to
    # bind the constant at import, this counter is what notices).
    releases: list[float] = []
    _real_release = registry._release_transaction

    def _counting_release(session):
        releases.append(time.monotonic())
        return _real_release(session)

    monkeypatch.setattr(registry, "_release_transaction", _counting_release)
    registry.register("slow_scan", _slow_scan_producer)

    db_path = tmp_path / f"wal_soak_round_{round_i}.db"
    eng = _wal_engine(db_path, seed_rows=_SEED_ROWS)
    wal_path = Path(str(db_path) + "-wal")
    Session = sessionmaker(bind=eng, future=True)

    stop_writer = threading.Event()
    write_errors: list[str] = []
    rows_written = [0]

    def _writer():
        while not stop_writer.is_set():
            try:
                with eng.connect() as c:
                    c.exec_driver_sql(f"INSERT INTO t VALUES (randomblob({_WRITER_ROW_BYTES}))")
                    c.commit()
                    rows_written[0] += 1
            except Exception as exc:  # noqa: BLE001 - collected, never asserted on (see module docstring precedent in test_wal_commit_between_producers.py: write-error counts are a noisy, non-discriminating metric)
                write_errors.append(str(exc))
            time.sleep(0.02)

    writer_thread = threading.Thread(target=_writer)
    writer_thread.start()

    stop_checkpointer = threading.Event()
    ckpt_results: list[dict] = []
    attempt_seconds: list[float] = []

    def _checkpointer():
        while not stop_checkpointer.is_set():
            started = time.monotonic()
            if attempt_delay_s:
                time.sleep(attempt_delay_s)
            rec = checkpoint_wal(engine=eng, force=True, busy_timeout_ms=50)
            attempt_seconds.append(time.monotonic() - started)
            if rec is not None:
                ckpt_results.append(rec)
            time.sleep(0.05)

    checkpointer_thread = threading.Thread(target=_checkpointer)
    checkpointer_thread.start()

    Session_bound = Session()
    scan_started = time.monotonic()
    try:
        registry.run_all(Session_bound)
    finally:
        scan_seconds = time.monotonic() - scan_started
        rows_at_end = rows_written[0]
        wal_bytes_during_window = wal_path.stat().st_size if wal_path.exists() else 0
        stop_writer.set()
        stop_checkpointer.set()
        writer_thread.join(5.0)
        checkpointer_thread.join(5.0)
        Session_bound.close()
        eng.dispose()

    return {
        "wal_bytes_during_window": wal_bytes_during_window,
        "writer_bytes_per_s": rows_at_end * _WRITER_ROW_BYTES / scan_seconds if scan_seconds else 0.0,
        "longest_attempt_s": max(attempt_seconds, default=0.0),
        "any_checkpoint_succeeded": any(rec["busy"] == 0 for rec in ckpt_results),
        "checkpoint_attempts": len(ckpt_results),
        "wal_releases": len(releases),
        "write_error_count": len(write_errors),
    }


def _allowed_wal_bytes(*, writer_bytes_per_s: float, longest_attempt_s: float) -> dict:
    """The most the WAL may hold when the scan ends, as two named terms.

    ``headroom``: the fixed multiple of the configured ceiling, what a fast disk is
    allowed to overshoot by (a round peaks at 0-13% of it on an idle box).
    ``in_flight``: what the writer appends while the round's slowest checkpoint
    attempt runs. A TRUNCATE cannot reset the log under a writer that keeps
    committing, so these bytes are unavoidable; a slow disk makes the term larger and
    a build that never truncates leaves it small (its attempts fail fast), so the
    bound still fails the second and no longer fails the first.
    """
    headroom = _MAX_DURING_WINDOW_MULTIPLE * _JOURNAL_SIZE_LIMIT_BYTES
    in_flight = writer_bytes_per_s * longest_attempt_s
    return {"headroom": headroom, "in_flight": in_flight, "total": headroom + in_flight}


def test_the_checkpoint_progress_guarantee_holds_reliably_across_repeated_rounds(
    tmp_path, monkeypatch
):
    """The fix's core promise -- a checkpoint can succeed WHILE a producer is
    still mid-scan, instead of every attempt failing for the whole duration
    (the true unpatched baseline's behaviour, per
    tests/test_wal_reader_starvation.py) -- must hold on EVERY one of several
    repeated, independent rounds within the SAME process, not just the
    first. And even while legitimately busy, the WAL must stay within a
    bounded multiple of its configured ceiling on every round -- never an
    unbounded, ever-worsening growth as more rounds accumulate.
    """
    per_round: list[dict] = []
    for round_i in range(_ROUNDS):
        per_round.append(_run_one_round(tmp_path, round_i, monkeypatch))

    failed_checkpoint_rounds = [i for i, r in enumerate(per_round) if not r["any_checkpoint_succeeded"]]
    assert not failed_checkpoint_rounds, (
        "the checkpoint-succeeds-while-busy property failed on round(s) "
        f"{failed_checkpoint_rounds} of {_ROUNDS} -- it must hold on EVERY round, "
        f"not just the first: {per_round}"
    )

    oversized_rounds = []
    for i, r in enumerate(per_round):
        allowed = _allowed_wal_bytes(
            writer_bytes_per_s=r["writer_bytes_per_s"], longest_attempt_s=r["longest_attempt_s"]
        )
        if r["wal_bytes_during_window"] > allowed["total"]:
            oversized_rounds.append((i, r["wal_bytes_during_window"], allowed))
    assert not oversized_rounds, (
        f"the WAL grew past {_MAX_DURING_WINDOW_MULTIPLE}x the configured "
        f"{_JOURNAL_SIZE_LIMIT_BYTES}-byte ceiling plus what the writer appends during the "
        "round's slowest checkpoint attempt, DURING the busy window, on round(s) "
        f"(round index, wal_bytes, allowed): {oversized_rounds} -- full per-round data: {per_round}"
    )

    # A genuine attempt was made every round (this is the "sustained, not a
    # one-off" claim -- a round that silently registered ZERO checkpoint
    # attempts at all would make "any_checkpoint_succeeded" vacuously easy to
    # satisfy by simply never trying).
    starved_attempts = [i for i, r in enumerate(per_round) if r["checkpoint_attempts"] == 0]
    assert not starved_attempts, (
        f"round(s) {starved_attempts} recorded ZERO checkpoint attempts at all -- "
        "the background checkpointer thread must have actually run: "
        f"{per_round}"
    )

    # ...and the same anti-vacuity argument one level down: the property above
    # is only meaningfully tested if the scan actually OFFERED several release
    # windows to hit. Under the production 30 s throttle a 0.8 s scan offers
    # exactly ONE (measured: t=0.009 s), and "did a checkpoint happen to land
    # in a 9 ms window" is a coin flip, not a guarantee -- which is what made
    # this test flaky on CI. If the monkeypatch in _run_one_round is ever
    # dropped, this is the assertion that says so instead of the suite going
    # intermittently red for a reason nobody can reproduce locally.
    single_window_rounds = [
        (i, r["wal_releases"])
        for i, r in enumerate(per_round)
        if r["wal_releases"] < _MIN_RELEASES_PER_ROUND
    ]
    assert not single_window_rounds, (
        f"round(s) (index, releases) {single_window_rounds} saw fewer than "
        f"{_MIN_RELEASES_PER_ROUND} WAL releases -- the scan was not given the "
        "several in-scan release windows a real long scan gets, so the "
        "checkpoint-progress assertion above was decided by thread-scheduling "
        f"luck rather than by the fix: {per_round}"
    )


def test_the_wal_bound_gives_a_slow_attempt_the_bytes_the_writer_appends_meanwhile():
    """The failed CI round (9,261,792 B, 2 attempts) was over the old fixed 6 MiB. Its slowest
    attempt is not in the log, so the test says what that attempt would have had to be: with the
    writer at the measured ~12.5 MB/s the bound accepts that round from about a quarter of a
    second per attempt."""
    rate = 12_500_000.0
    needed_s = (9_261_792 - _MAX_DURING_WINDOW_MULTIPLE * _JOURNAL_SIZE_LIMIT_BYTES) / rate
    assert 0.2 < needed_s < 0.3, needed_s
    assert _allowed_wal_bytes(writer_bytes_per_s=rate, longest_attempt_s=0.4)["total"] > 9_261_792
    assert _allowed_wal_bytes(writer_bytes_per_s=rate, longest_attempt_s=0.2)["total"] < 9_261_792
    # Each term is named and they add up.
    t = _allowed_wal_bytes(writer_bytes_per_s=rate, longest_attempt_s=0.4)
    assert t["total"] == t["headroom"] + t["in_flight"] and t["in_flight"] == rate * 0.4


def test_the_wal_bound_still_fails_a_log_nothing_truncated():
    """The mutation this bound must keep killing: a build that never resets the log under a
    scan. Its log holds everything the writer appended (~0.9 s at 12.5 MB/s, about 11 MB) and
    its attempts fail fast (the 50 ms busy timeout), so the in-flight term stays small."""
    t = _allowed_wal_bytes(writer_bytes_per_s=12_500_000.0, longest_attempt_s=0.06)
    assert 11_000_000 > t["total"], t


def test_a_checkpoint_attempt_that_takes_longer_is_measured_and_the_bound_follows_it(tmp_path, monkeypatch):
    """A real round with every attempt held for 0.6 s (the stand-in for a slow fsync). The
    round measures the slowest attempt itself (never assumes it) and the log stays within the
    bound that follows it."""
    r = _run_one_round(tmp_path, 0, monkeypatch, attempt_delay_s=0.6)
    assert r["longest_attempt_s"] >= 0.6, r
    assert r["writer_bytes_per_s"] > 0, r
    allowed = _allowed_wal_bytes(writer_bytes_per_s=r["writer_bytes_per_s"], longest_attempt_s=r["longest_attempt_s"])
    assert r["wal_bytes_during_window"] <= allowed["total"], (r, allowed)
