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
9.26 MB with 10 / 4 / 2 checkpoint attempts. Delaying every fsync of this test with
``strace -e inject`` reproduces that shape: 100 ms -> 3-4 attempts and 1.6-2.9 MB;
300 ms -> 1 attempt and 6.2-6.5 MB (over the old bound in every round); 4 or 8 CPU
burners change nothing (13-15 attempts, at most 0.8 MB). The bound is now the fixed
headroom PLUS what the writer appends while the round's slowest attempt is in flight,
each term named in ``_allowed_wal_bytes``.

WHAT THE BYTE BOUND DOES NOT DO, AND WHAT DOES (independent read of the change,
26 Oct): in the build from before the fix every busy TRUNCATE holds the WAL write
lock for its 50 ms busy timeout, which slows the writer to ~5-6.7 MB/s, and the log
ends at 4.5-6.4 MB: INSIDE this bound in 10 of 10 rounds (it was inside the old fixed
6 MiB bound in 9 of 10). So no byte bound killed that mutation, old or new. What kills
it, every round, is the in-scan success: a checkpoint that FINISHED, with its busy
flag clear, after the scan's first chunk was delivered and before the scan ended
(``_in_scan_success``). The earlier test counted every record, including the attempt
still in flight when the scan ended and recorded after the pin was gone, so in the slow
regime this change tunes for the original design bug (commit without closing the
cursor) passed all four assertions; it counts only attempts that began after the first
chunk (the reader already pinned) and ended inside the scan. The byte bound stays as the
promise that the log does not grow without bound while checkpoints report success, and
it is only asserted on a round where it CAN fail: once the allowance reaches every byte
the round could have written (a slow-attempt round, where the in-flight term alone is
most of the scan), the round is INCONCLUSIVE for the bytes, is printed as such with its
numbers, and no round is passed as a byte check it could not have failed. The measured
tables and the probes are in the lane folder's soak-failure-2026-10-26 report and the
independent read's folder; the lesson fragment carries the rule.

WHY TWO TESTS OVER ONE SET OF ROUNDS (delta read of 26 Oct): the first version asserted the property
and the bytes in ONE test and could only skip for the property, so a runner whose writer averaged
under about 6.8 MB/s (every round bytes-inconclusive) got a GREEN test that had asserted nothing about
the bytes, with the notice in a ``print`` that ``pytest -q`` throws away for a passing test. The rounds
now run once (a module fixture) and the property and the bytes are asserted by a test each: a test
whose check could not fail in any round SKIPS, with the numbers, so the status itself says it.
``bytes_possible`` is an upper bound built from the measured cost of a row in the log (``_WRITER_ROW_WAL_BYTES``,
frames of ``page_size + 24``, pinned by a test against this SQLite), the seed's own measured log and the rows
the counter can lag by, not the row's payload times a guessed 1.02 (the log ended 3.4-3.9 % above that).
"""
from __future__ import annotations

import math
import threading
import time
from pathlib import Path

import pytest
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
# What one such row costs in the -wal, as an UPPER bound built from SQLite's own layout: the blob spills into overflow pages of
# ``page_size - 4`` payload bytes each, plus the leaf and the page that points at it, each page logged as one frame of ``page_size + 24``
# bytes. Measured on SQLite 3.45.1: 272,538 B per row (66.15 frames), against this 276,040 B (67 frames). A test pins both directions.
_PAGE_SIZE = 4096
_FRAME_BYTES = _PAGE_SIZE + 24
_WRITER_ROW_WAL_BYTES = (math.ceil(_WRITER_ROW_BYTES / (_PAGE_SIZE - 4)) + 2) * _FRAME_BYTES
# The writer's row counter is bumped AFTER its commit and read BEFORE the log's size: the count can lag the log by the row whose commit
# finished but was not yet counted and by the row committed between the two reads.
_ROWS_THE_COUNT_CAN_LAG_BY = 2

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
# How many checkpoint attempts that ANSWERED inside the scan a round needs before "none of them cleared" counts as evidence that the property
# failed. Fewer is a slow disk, not a broken fix: MEASURED 26 Oct with every fsync delayed (strace --seccomp-bpf -e inject), the fixed build
# finished a clear checkpoint inside the scan in every round up to a 60 ms delay (attempts of 0.15-0.27 s, 2-8 of them), in 3 of 4 at 80 ms (one
# attempt in the scan, 0.35 s) and in none at 100 ms (0.43 s, one or two attempts), because an attempt longer than a release window (the scan's
# 0.1 s pause) cannot fit one. Every round with four or more in-scan attempts had its success; the build from before the fix has none in ANY
# regime. A round below this count with no in-scan success is INCONCLUSIVE for the property, and says so.
_MIN_ATTEMPTS_TO_JUDGE = 4


def _wal_engine(db_path: Path, *, seed_rows: int, monkeypatch):
    monkeypatch.setenv("OO_WAL_SIZE_LIMIT_MB", str(_JOURNAL_SIZE_LIMIT_MB))  # undone at the test's end: the 1 MiB limit must not reach another test
    eng = create_engine(f"sqlite:///{db_path}", future=True)
    event.listen(eng, "connect", db_session._sqlite_pragmas)
    with eng.connect() as c:
        c.exec_driver_sql("CREATE TABLE t(x)")
        for _ in range(seed_rows):
            c.exec_driver_sql("INSERT INTO t VALUES (randomblob(4096))")
        c.commit()
    return eng


def _make_scan_producer(first_chunk_at: list[float]):
    """The slow scanning producer. ``first_chunk_at`` receives the monotonic time the first chunk was delivered: from then on the scan's
    snapshot is pinned (or, once the guard has released it, the next window opens), so a checkpoint attempt that began EARLIER proves
    nothing about the property."""

    def _slow_scan_producer(session):
        result = session.execute(text("SELECT x FROM t"))
        for _ in range(8):
            chunk = result.fetchmany(3)
            if chunk and not first_chunk_at:
                first_chunk_at.append(time.monotonic())
            if not chunk:
                break
            time.sleep(0.1)
        return []

    return _slow_scan_producer


def _in_scan_attempts(attempts: list[dict], *, first_chunk: float, scan_ended: float) -> tuple[list[dict], float]:
    """The checkpoint attempts that are evidence about the scan, and how long the slowest one ran INSIDE it.

    Only what the scan could see counts. An attempt whose checkpoint call was issued before the first chunk was delivered met no pinned
    snapshot, and one still running when the scan ended finished after the pin was gone (it is joined and recorded after the measurement):
    neither says anything about the property. An attempt that returned nothing answered nothing. For the bytes, only the part of an attempt
    inside the scan is time the writer appended during (a slow attempt's tail past the scan's end is not).
    """
    evidence = [a for a in attempts if a["busy"] is not None and a["called"] >= first_chunk and a["ended"] <= scan_ended]
    extents = [min(a["ended"], scan_ended) - a["began"] for a in attempts if a["began"] < scan_ended]
    return evidence, max(extents, default=0.0)


def _run_one_round(tmp_path: Path, round_i: int, monkeypatch, *, attempt_delay_s: float = 0.0) -> dict:
    """One full round: a slow scanning producer races a background writer and
    a background checkpointer on its OWN fresh database, mirroring
    test_wal_reader_starvation.py's proven single-pass shape exactly. Returns
    the measured facts for this round's assertions. ``attempt_delay_s`` makes every
    checkpoint attempt take that much longer before it runs (a stand-in for a slow
    fsync inside the attempt: the log is reset when the attempt ends either way).

    Every checkpoint attempt is STAMPED: when it began, when the checkpoint call itself was issued (after the stand-in delay) and when it ended,
    and what it answered, so that what counts as evidence is decided against the scan's own window and not against the end of the thread.
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
    first_chunk_at: list[float] = []
    registry.register("slow_scan", _make_scan_producer(first_chunk_at))

    db_path = tmp_path / f"wal_soak_round_{round_i}.db"
    eng = _wal_engine(db_path, seed_rows=_SEED_ROWS, monkeypatch=monkeypatch)
    wal_path = Path(str(db_path) + "-wal")
    seed_wal_bytes = wal_path.stat().st_size if wal_path.exists() else 0  # measured, not estimated: the log the seeding itself left
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
    attempts: list[dict] = []

    def _checkpointer():
        while not stop_checkpointer.is_set():
            began = time.monotonic()
            if attempt_delay_s:
                time.sleep(attempt_delay_s)
            called = time.monotonic()
            rec = checkpoint_wal(engine=eng, force=True, busy_timeout_ms=50)
            attempts.append({"began": began, "called": called, "ended": time.monotonic(), "busy": None if rec is None else rec["busy"]})
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
        scan_ended = time.monotonic()
        scan_seconds = scan_ended - scan_started
        rows_at_end = rows_written[0]
        wal_bytes_during_window = wal_path.stat().st_size if wal_path.exists() else 0
        stop_writer.set()
        stop_checkpointer.set()
        writer_thread.join(5.0)
        checkpointer_thread.join(5.0)
        Session_bound.close()
        eng.dispose()

    first_chunk = first_chunk_at[0] if first_chunk_at else scan_ended
    in_scan, longest_in_scan = _in_scan_attempts(attempts, first_chunk=first_chunk, scan_ended=scan_ended)
    return {
        "wal_bytes_during_window": wal_bytes_during_window,
        "writer_bytes_per_s": rows_at_end * _WRITER_ROW_BYTES / scan_seconds if scan_seconds else 0.0,
        "bytes_possible": seed_wal_bytes + (rows_at_end + _ROWS_THE_COUNT_CAN_LAG_BY) * _WRITER_ROW_WAL_BYTES,
        "longest_attempt_s": max((a["ended"] - a["began"] for a in attempts), default=0.0),
        "longest_attempt_in_scan_s": longest_in_scan,
        "in_scan_success": any(a["busy"] == 0 for a in in_scan),
        "any_checkpoint_succeeded": any(rec["busy"] == 0 for rec in ckpt_results),
        "checkpoint_attempts": len(ckpt_results),
        "attempts_in_scan": len(in_scan),
        "wal_releases": len(releases),
        "write_error_count": len(write_errors),
    }


def _allowed_wal_bytes(*, writer_bytes_per_s: float, longest_attempt_s: float) -> dict:
    """The most the WAL may hold when the scan ends, as two named terms.

    ``headroom``: the fixed multiple of the configured ceiling, what a fast disk is
    allowed to overshoot by (a round peaks at 0-13% of it on an idle box).
    ``in_flight``: what the writer appends while the round's slowest checkpoint
    attempt runs, counting only the part of that attempt that lies inside the scan
    (``longest_attempt_s`` is ``longest_attempt_in_scan_s``): a TRUNCATE cannot reset
    the log under a writer that keeps committing, so these bytes are unavoidable. A
    slow disk makes the term larger. THIS BOUND DOES NOT FAIL THE BUILD FROM BEFORE THE
    FIX: that build's log ends inside it (4.5 to 6.4 MB against 6.6 to 6.9 MB, 10 of 10
    rounds), and the in-scan success is what does (see the module docstring).
    """
    headroom = _MAX_DURING_WINDOW_MULTIPLE * _JOURNAL_SIZE_LIMIT_BYTES
    in_flight = writer_bytes_per_s * longest_attempt_s
    return {"headroom": headroom, "in_flight": in_flight, "total": headroom + in_flight}


def _round_verdict(r: dict) -> dict:
    """What a round says: red, inconclusive or neither, and why.

    ``red``: reasons the round fails -- no checkpoint finished inside the scan with its busy flag clear although enough attempts answered inside
    it to judge (``_MIN_ATTEMPTS_TO_JUDGE``), no attempt recorded at all, too few in-scan release windows, or a byte check that could fail and
    was exceeded. ``property_conclusive``: False when no in-scan attempt cleared and too few answered to say the fix failed (a slow disk: the
    round is INCONCLUSIVE for the property, never passed as one). ``bytes_conclusive``: False when the allowance already reaches every byte the
    round could have written, so the byte check cannot fail. ``allowed``: the named terms.
    """
    allowed = _allowed_wal_bytes(writer_bytes_per_s=r["writer_bytes_per_s"], longest_attempt_s=r["longest_attempt_in_scan_s"])
    bytes_conclusive = allowed["total"] < r["bytes_possible"]
    judged = r["attempts_in_scan"] >= _MIN_ATTEMPTS_TO_JUDGE
    property_conclusive = r["in_scan_success"] or judged
    red_property = []
    if judged and not r["in_scan_success"]:
        red_property.append("no checkpoint finished inside the scan with its busy flag clear")
    if r["checkpoint_attempts"] == 0:
        red_property.append("no checkpoint attempt recorded at all")
    if r["wal_releases"] < _MIN_RELEASES_PER_ROUND:
        red_property.append(f"{r['wal_releases']} WAL releases, fewer than {_MIN_RELEASES_PER_ROUND}")
    red_bytes = []
    if bytes_conclusive and r["wal_bytes_during_window"] > allowed["total"]:
        red_bytes.append(f"the WAL held {r['wal_bytes_during_window']} B at the end of the scan, over {allowed['total']:.0f} B")
    return {
        "red": red_property + red_bytes,
        "red_property": red_property,
        "red_bytes": red_bytes,
        "property_conclusive": property_conclusive,
        "bytes_conclusive": bytes_conclusive,
        "allowed": allowed,
    }


def _unclosed_fetchmany(commit: bool):
    """A ``_WalGuardResult.fetchmany`` that never closes the cursor, so the scan keeps its snapshot for the whole scan: the build from before
    the fix (``commit=False``), or the original design bug the class docstring records (``commit=True``: it commits and counts the release
    but the cursor stays open, which releases nothing)."""

    def fetchmany(self, size=None):
        self._reopen_if_needed()
        chunk = self._result.fetchmany(size)
        self._fetched += len(chunk)
        if commit:
            now = time.monotonic()
            if self._last_release_mono is None or now - self._last_release_mono >= registry._WAL_GUARD_MIN_RELEASE_INTERVAL_S:
                registry._release_transaction(self._session)
                self._last_release_mono = now
        return chunk

    return fetchmany


@pytest.fixture(scope="module")
def soak_rounds(tmp_path_factory):
    """The ``_ROUNDS`` independent rounds, run ONCE for the two tests that judge them (the property and the bytes). A module fixture cannot use
    the function-scoped ``monkeypatch``, so the patches live in a context of their own and are undone when the rounds are done."""
    with pytest.MonkeyPatch.context() as mp:
        per_round = [_run_one_round(tmp_path_factory.mktemp(f"soak{i}"), i, mp) for i in range(_ROUNDS)]
    return per_round, [_round_verdict(r) for r in per_round]


def _print_inconclusive(per_round: list[dict], verdicts: list[dict]) -> None:
    for i, (r, v) in enumerate(zip(per_round, verdicts, strict=True)):
        if not v["property_conclusive"]:
            print(
                f"SOAK ROUND {i} INCONCLUSIVE FOR THE PROPERTY: {r['attempts_in_scan']} checkpoint attempt(s) answered inside the scan (fewer than "
                f"{_MIN_ATTEMPTS_TO_JUDGE}) and none cleared; the slowest ran {r['longest_attempt_in_scan_s']:.3f} s inside it (a slow disk, not a verdict)"
            )
        if not v["bytes_conclusive"]:
            print(
                f"SOAK ROUND {i} INCONCLUSIVE FOR THE BYTE BOUND: allowed {v['allowed']['total']:.0f} B >= the {r['bytes_possible']} B the round could "
                f"have written (headroom {v['allowed']['headroom']}, in flight {v['allowed']['in_flight']:.0f})"
            )


def _judge(per_round: list[dict], verdicts: list[dict], *, red_key: str, conclusive_key: str, what: str, numbers) -> None:
    """Fail on a red round; SKIP, with the numbers, when no round could have failed. A check that could not fail in any round is not a pass."""
    _print_inconclusive(per_round, verdicts)
    red_rounds = [(i, v[red_key]) for i, v in enumerate(verdicts) if v[red_key]]
    assert not red_rounds, (
        f"the {what} failed on round(s) (index, reasons) {red_rounds} of {len(verdicts)} -- it must hold on EVERY round, not just the first: "
        f"{per_round} {verdicts}"
    )
    if not any(v[conclusive_key] for v in verdicts):
        pytest.skip(f"every one of the {len(verdicts)} rounds was inconclusive for the {what}, so nothing was checked: {numbers(per_round, verdicts)}")


def test_the_checkpoint_progress_guarantee_holds_reliably_across_repeated_rounds(soak_rounds):
    """The fix's core promise -- a checkpoint can succeed WHILE a producer is still mid-scan, instead of every attempt failing for the whole
    duration (the true unpatched baseline's behaviour, per tests/test_wal_reader_starvation.py) -- must hold on EVERY one of several repeated,
    independent rounds within the SAME process, not just the first. A round too slow to judge is inconclusive for the property, never passed
    as one; when every round is, the test skips with the numbers."""
    per_round, verdicts = soak_rounds
    _judge(
        per_round,
        verdicts,
        red_key="red_property",
        conclusive_key="property_conclusive",
        what="checkpoint-succeeds-while-busy property",
        numbers=lambda rs, _vs: [(r["attempts_in_scan"], round(r["longest_attempt_in_scan_s"], 3)) for r in rs] + ["(attempts in scan, slowest in-scan seconds)"],
    )


def test_the_log_stays_within_its_bound_while_a_writer_commits_and_checkpoints_run(soak_rounds):
    """Even while a checkpoint is legitimately busy, the WAL stays within a bounded multiple of its configured ceiling plus what the writer
    appends during the slowest attempt, on every round whose byte check CAN fail. A round whose allowance already reaches every byte it could
    have written is inconclusive for the bytes; when every round is, this test SKIPS (the first version passed, printing a notice that CI never
    shows)."""
    per_round, verdicts = soak_rounds
    _judge(
        per_round,
        verdicts,
        red_key="red_bytes",
        conclusive_key="bytes_conclusive",
        what="byte bound",
        numbers=lambda rs, vs: [(round(v["allowed"]["total"]), r["bytes_possible"], r["wal_bytes_during_window"]) for r, v in zip(rs, vs, strict=True)]
        + ["(allowed, possible, ended at: bytes)"],
    )


@pytest.mark.parametrize("commit", [False, True], ids=["never-closes", "commit-without-close"])
def test_a_scan_that_never_releases_its_snapshot_is_red_when_the_attempts_can_judge_it(tmp_path, monkeypatch, commit):
    """The mutation the soak exists for, as a REAL ROUND, not as arithmetic on assumed inputs: the build from before the fix (``never-closes``)
    and the original design bug (``commit-without-close``). Neither can finish a checkpoint with a clear busy flag while the scan holds its
    snapshot, so the round is red for exactly that reason, whatever the byte bound says (it passes both: the log ends inside it, 4.5 to 6.4 MB)."""
    monkeypatch.setattr(registry._WalGuardResult, "fetchmany", _unclosed_fetchmany(commit))
    r = _run_one_round(tmp_path, 0, monkeypatch)
    v = _round_verdict(r)
    # these are the rounds whose log really grows (4.5 to 6.4 MB): the one place the "could not have failed" bound meets a large real log
    assert r["wal_bytes_during_window"] <= r["bytes_possible"], ("bytes_possible is not an upper bound on what a round can put in the log", r)
    assert not r["in_scan_success"], ("a scan that holds its snapshot cannot be checkpointed inside it", r)
    if not v["property_conclusive"]:
        pytest.skip(f"a disk this slow answered {r['attempts_in_scan']} attempt(s) inside the scan, too few to call it (the round is inconclusive, never green)")
    assert "no checkpoint finished inside the scan with its busy flag clear" in v["red"], (r, v)


def test_in_the_slow_regime_the_original_design_bug_is_inconclusive_not_a_pass(tmp_path, monkeypatch):
    """The regime this change tunes for (every checkpoint attempt slow): the original design bug (commit without closing the cursor) used to
    PASS all four assertions there, because its one success was an attempt that finished 0.475 s after the scan ended and was counted. Now that
    attempt is not evidence, and two attempts in the scan are too few to call a failure: the round is inconclusive and says so."""
    monkeypatch.setattr(registry._WalGuardResult, "fetchmany", _unclosed_fetchmany(True))
    r = _run_one_round(tmp_path, 0, monkeypatch, attempt_delay_s=0.45)
    v = _round_verdict(r)
    assert not r["in_scan_success"], r
    assert not v["property_conclusive"] and v["red"] == [], (r, v)
    print(f"SOAK slow-attempt mutant round INCONCLUSIVE FOR THE PROPERTY: {r['attempts_in_scan']} attempt(s) answered inside the scan, none cleared")


def test_an_attempt_that_finishes_after_the_scan_is_not_evidence_and_its_bytes_are_capped_at_the_scans_end(tmp_path, monkeypatch):
    """A real round with every attempt held for 0.6 s (the stand-in for a slow fsync). What this pins is the ACCOUNTING, which is
    deterministic: the slowest attempt is measured on its own clock, only the part of it inside the scan is allowed bytes, and the
    attempt that was still running when the scan ended (it began inside the scan and was joined after) is not an in-scan attempt. Whether
    the one in-scan attempt lands in a release window is not decided here (it is the main test's, over many attempts)."""
    r = _run_one_round(tmp_path, 0, monkeypatch, attempt_delay_s=0.6)
    assert r["longest_attempt_s"] >= 0.6, r
    assert 0.6 <= r["longest_attempt_in_scan_s"] <= r["longest_attempt_s"], r
    assert r["attempts_in_scan"] <= r["checkpoint_attempts"], r
    v = _round_verdict(r)
    assert v["allowed"]["in_flight"] == r["writer_bytes_per_s"] * r["longest_attempt_in_scan_s"], v
    # Slow attempts give the byte check no room to fail: the allowance reaches what the writer could have written, and the round
    # says so instead of passing a check it could not have failed.
    assert not v["bytes_conclusive"], (r, v)
    print(f"SOAK slow-attempt round INCONCLUSIVE FOR THE BYTE BOUND: allowed {v['allowed']['total']:.0f} B, possible {r['bytes_possible']} B")


def test_a_check_that_could_not_fail_in_any_round_skips_and_a_red_round_still_fails():
    """The decision the two tests above end in, on synthetic rounds, so it does not depend on timing: red fails, a check that no round could
    have failed SKIPS (it is not a pass), and one conclusive round is enough to pass."""
    ok = {"writer_bytes_per_s": 12_500_000.0, "bytes_possible": 11_000_000, "in_scan_success": True, "checkpoint_attempts": 9,
          "attempts_in_scan": 8, "wal_releases": 9, "longest_attempt_in_scan_s": 0.02, "wal_bytes_during_window": 800_000}
    slow = ok | {"longest_attempt_in_scan_s": 0.6, "wal_bytes_during_window": 9_000_000}  # the byte check cannot fail here

    def judge(rounds, red_key, conclusive_key):
        _judge(rounds, [_round_verdict(r) for r in rounds], red_key=red_key, conclusive_key=conclusive_key, what="x", numbers=lambda *_: "numbers")

    with pytest.raises(pytest.skip.Exception):
        judge([slow, slow, slow], "red_bytes", "bytes_conclusive")
    judge([slow, slow, slow], "red_property", "property_conclusive")  # the same rounds DO check the property
    judge([slow, ok, slow], "red_bytes", "bytes_conclusive")  # one round that could fail, and did not
    with pytest.raises(AssertionError):
        judge([ok | {"wal_bytes_during_window": 9_000_000}, slow, slow], "red_bytes", "bytes_conclusive")
    with pytest.raises(pytest.skip.Exception):
        judge([ok | {"in_scan_success": False, "attempts_in_scan": 1}] * 3, "red_property", "property_conclusive")
    with pytest.raises(AssertionError):
        judge([ok | {"in_scan_success": False}, ok, ok], "red_property", "property_conclusive")


def test_the_cost_of_a_writer_row_in_the_log_is_bounded_by_the_frame_arithmetic_and_the_bound_is_tight(tmp_path):
    """``bytes_possible`` is an UPPER bound only if the per-row cost is. Measured here on this SQLite, one commit at a time with no checkpoint:
    no row costs more than ``_WRITER_ROW_WAL_BYTES`` (the first version's payload x 1.02 was exceeded by every round's log, by 3.4-3.9 %), and
    the bound is not loose by more than 10 %, so an inconclusive round is not made inconclusive by an inflated number."""
    import sqlite3

    db = tmp_path / "row-cost.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        assert conn.execute("PRAGMA page_size").fetchone()[0] == _PAGE_SIZE, "the frame arithmetic is for this page size"
        conn.execute("CREATE TABLE t(x)")
        conn.commit()
        wal = Path(str(db) + "-wal")
        costs = []
        for _ in range(4):
            before = wal.stat().st_size
            conn.execute(f"INSERT INTO t VALUES (randomblob({_WRITER_ROW_BYTES}))")
            conn.commit()
            costs.append(wal.stat().st_size - before)
    finally:
        conn.close()
    assert max(costs) <= _WRITER_ROW_WAL_BYTES, (costs, _WRITER_ROW_WAL_BYTES)
    assert min(costs) >= 0.9 * _WRITER_ROW_WAL_BYTES, (costs, _WRITER_ROW_WAL_BYTES)


def test_a_round_is_inconclusive_exactly_when_it_could_not_have_failed():
    """The verdict on synthetic rounds (the shapes the real ones take), so the rules themselves do not depend on timing."""
    base = {"writer_bytes_per_s": 12_500_000.0, "bytes_possible": 11_000_000, "in_scan_success": True, "checkpoint_attempts": 9,
            "attempts_in_scan": 8, "wal_releases": 9, "longest_attempt_in_scan_s": 0.02, "wal_bytes_during_window": 800_000}
    ok = _round_verdict(base)
    assert ok["red"] == [] and ok["property_conclusive"] and ok["bytes_conclusive"], ok
    # a byte check that CAN fail and is exceeded is red
    over = _round_verdict(base | {"wal_bytes_during_window": 9_000_000})
    assert over["bytes_conclusive"] and len(over["red"]) == 1 and "over" in over["red"][0], over
    # slow attempts: the allowance already covers everything the writer could have written -> neither red nor a pass of the byte check
    slow = _round_verdict(base | {"longest_attempt_in_scan_s": 0.6, "wal_bytes_during_window": 9_000_000})
    assert not slow["bytes_conclusive"] and slow["red"] == [], slow
    # no clear checkpoint in the scan although enough attempts answered in it: red (the fix failed)
    judged = _round_verdict(base | {"in_scan_success": False})
    assert judged["red"] == ["no checkpoint finished inside the scan with its busy flag clear"] and judged["property_conclusive"], judged
    # ...with too few attempts answering in the scan (every attempt slow): inconclusive, not red and not a pass
    few = _round_verdict(base | {"in_scan_success": False, "attempts_in_scan": _MIN_ATTEMPTS_TO_JUDGE - 1})
    assert few["red"] == [] and not few["property_conclusive"], few
    # a success seen is positive evidence however few attempts there were
    assert _round_verdict(base | {"attempts_in_scan": 1})["property_conclusive"]
    # the other two structural reds
    assert _round_verdict(base | {"checkpoint_attempts": 0})["red"] == ["no checkpoint attempt recorded at all"]
    assert len(_round_verdict(base | {"wal_releases": _MIN_RELEASES_PER_ROUND - 1})["red"]) == 1
    # The failed CI round (9,261,792 B, 2 attempts) was over the old fixed 6 MiB: its slowest in-scan attempt would have had to run about a
    # quarter of a second for the new allowance to take it.
    needed_s = (9_261_792 - _MAX_DURING_WINDOW_MULTIPLE * _JOURNAL_SIZE_LIMIT_BYTES) / 12_500_000.0
    assert 0.2 < needed_s < 0.3, needed_s
    t = _allowed_wal_bytes(writer_bytes_per_s=12_500_000.0, longest_attempt_s=0.4)
    assert t["total"] == t["headroom"] + t["in_flight"] and t["in_flight"] == 12_500_000.0 * 0.4 and t["total"] > 9_261_792


def test_which_attempts_are_evidence_and_how_much_of_a_slow_one_is_inside_the_scan():
    """The accounting on synthetic stamps: the first chunk is delivered at t=1.0, the scan ends at t=2.0."""

    def at(began, called, ended, busy):
        return {"began": began, "called": called, "ended": ended, "busy": busy}

    before_pin = at(0.1, 0.1, 0.2, 0)  # cleared, but before the scan held anything: no evidence
    inside = at(1.2, 1.3, 1.4, 0)
    inside_busy = at(1.5, 1.5, 1.6, 1)
    unanswered = at(1.6, 1.6, 1.7, None)
    spans_the_end = at(1.8, 1.9, 2.4, 0)  # cleared AFTER the scan ended (the old counting's only "success" under the original design bug)
    got, longest = _in_scan_attempts([before_pin, inside, inside_busy, unanswered, spans_the_end], first_chunk=1.0, scan_ended=2.0)
    assert got == [inside, inside_busy]
    assert abs(longest - 0.2) < 1e-9, "the slowest attempt's part inside the scan: 1.8 -> 2.0, not the 0.6 s it ran in all"
    assert _in_scan_attempts([spans_the_end], first_chunk=1.0, scan_ended=2.0)[0] == []
    # an attempt that began after the scan is not in the extents at all
    assert _in_scan_attempts([at(2.1, 2.1, 2.2, 0)], first_chunk=1.0, scan_ended=2.0) == ([], 0.0)
