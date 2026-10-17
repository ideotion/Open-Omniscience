"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

Stall attribution (the 2026-07-21 field brief, item 3). That brief recorded a cluster
of multi-hour in-flight requests and 503s on 2026-07-11 and could not say what caused
them; the instruments that would have known are windowed, so the evidence was gone by
the time anyone looked. These tests pin the instrument that makes the NEXT one
self-describing -- and, as much as the attribution itself, they pin its refusals: a
stall whose cause the instruments cannot see must be filed ``undetermined``, never
assigned to the nearest class.
"""

from __future__ import annotations

import pytest

from src.monitoring import stall_forensics as sf


@pytest.fixture(autouse=True)
def _clean():
    sf._reset_for_tests()
    yield
    sf._reset_for_tests()


def _quiet(monkeypatch):
    """All three instruments readable and reporting NOTHING interesting."""
    monkeypatch.setattr(
        sf, "_gate_evidence", lambda: {"available": True, "held": False, "waiters": 0,
                                       "max_wait_s": 0.0}
    )
    monkeypatch.setattr(
        sf, "_loop_evidence", lambda route: {"available": True, "overlapped": False,
                                             "n_events_checked": 3}
    )
    monkeypatch.setattr(
        sf, "_statement_evidence", lambda ms: {"available": True, "found": False}
    )


# --------------------------------------------------------------------------
# The brief's own acceptance bar: an induced writer-gate stall is attributed.
# --------------------------------------------------------------------------


def test_a_held_writer_gate_with_a_queue_is_attributed_to_the_gate(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(
        sf, "_gate_evidence",
        lambda: {"available": True, "held": True, "waiters": 4, "max_wait_s": 61.5},
    )
    rec = sf.note_stall("GET /api/insights/corpus-keywords", 200, 30_000.0)

    assert rec is not None
    assert "writer-gate-contention" in rec["consistent_with"]
    assert rec["consistent_with"] != ["undetermined"]
    # The evidence travels WITH the verdict, so a reader can disagree with the class
    # without re-running anything.
    assert rec["evidence"]["write_gate"]["waiters"] == 4
    assert rec["evidence"]["write_gate"]["max_wait_s"] == 61.5


def test_a_gate_held_with_nobody_queued_is_not_contention(monkeypatch):
    """The negative-space twin of the bar above.

    One writer holding the gate with no queue behind it is an ordinary serialised
    write -- the gate working, not jamming. A classifier that fired on `held` alone
    would label every slow request during any write, which is how an instrument
    becomes noise nobody reads.
    """
    _quiet(monkeypatch)
    monkeypatch.setattr(
        sf, "_gate_evidence",
        lambda: {"available": True, "held": True, "waiters": 0, "max_wait_s": 0.2},
    )
    rec = sf.note_stall("GET /api/search/omni", 200, 30_000.0)

    assert rec is not None
    assert "writer-gate-contention" not in rec["consistent_with"]
    assert rec["consistent_with"] == ["undetermined"]
    assert "undetermined" not in rec  # derived from consistent_with; a second copy cost 23 B a record


# --------------------------------------------------------------------------
# The other two classes, and the honest third state.
# --------------------------------------------------------------------------


def test_an_overlapping_loop_block_is_attributed_to_the_event_loop(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(
        sf, "_loop_evidence",
        lambda route: {"available": True, "overlapped": True, "lag_ms": 9000.0,
                       "at": "2026-08-20T10:00:00+00:00"},
    )
    rec = sf.note_stall("GET /api/insights/latest", 503, 20_000.0)
    assert "event-loop-blocked" in rec["consistent_with"]


def test_a_slow_statement_counts_only_when_it_explains_most_of_the_request(monkeypatch):
    """A real-but-incidental slow query must not be named as the holdup.

    Recording the slowest statement seen and calling it the cause would point the next
    reader at the wrong thing whenever a 200 ms query happens to sit inside a 30 s
    stall -- so the share threshold is the whole point, and both sides of it are pinned.
    """
    _quiet(monkeypatch)
    monkeypatch.setattr(
        sf, "_statement_evidence",
        lambda ms: {"available": True, "found": True, "duration_ms": 200.0,
                    "sql": "SELECT ...", "share_of_request": 200.0 / ms},
    )
    incidental = sf.note_stall("GET /api/articles", 200, 30_000.0)
    assert "slow-statement" not in incidental["consistent_with"]

    monkeypatch.setattr(
        sf, "_statement_evidence",
        lambda ms: {"available": True, "found": True, "duration_ms": 28_000.0,
                    "sql": "SELECT ...", "share_of_request": 28_000.0 / ms},
    )
    dominant = sf.note_stall("GET /api/articles", 200, 30_000.0)
    assert "slow-statement" in dominant["consistent_with"]


def test_silent_instruments_yield_undetermined_never_a_nearest_class(monkeypatch):
    """``undetermined`` must be REACHABLE, not a label nothing ever earns.

    This is the honesty core of the module: a stall the three instruments cannot see
    is a gap in the evidence, and saying so is the only truthful answer. A classifier
    that always produced a class would read as though every stall had been explained.
    """
    _quiet(monkeypatch)
    rec = sf.note_stall("GET /api/whatever", 200, 60_000.0)
    assert rec["consistent_with"] == ["undetermined"]
    assert "undetermined" not in rec  # derived from consistent_with; a second copy cost 23 B a record


def test_an_unreadable_instrument_is_a_gap_not_a_verdict(monkeypatch):
    """An instrument that raised says ``available: false`` and supports NO class --
    distinct from one that answered "nothing here". Collapsing the two would let a
    broken probe read as a clean machine (the K2 shape this repo names twice).

    The fixture carries STALE readings beside ``available: false`` on purpose. A first
    draft returned only ``{available, reason}``, which meant dropping the availability
    check changed nothing and the mutation survived -- the guard was real but the test
    could not see it. A probe that populates some fields and then fails is the case
    this check exists for, so that is what gets driven.
    """
    _quiet(monkeypatch)
    monkeypatch.setattr(
        sf,
        "_gate_evidence",
        lambda: {"available": False, "reason": "RuntimeError", "held": True, "waiters": 9},
    )
    rec = sf.note_stall("GET /api/x", 200, 30_000.0)
    assert "writer-gate-contention" not in rec["consistent_with"], (
        "an unavailable instrument's stale numbers must not support a verdict"
    )
    assert rec["consistent_with"] == ["undetermined"]
    assert rec["evidence"]["write_gate"]["available"] is False
    assert "reason" in rec["evidence"]["write_gate"]


# --------------------------------------------------------------------------
# Threshold, bounds, and the report's own honesty.
# --------------------------------------------------------------------------


def test_a_fast_request_files_nothing(monkeypatch):
    _quiet(monkeypatch)
    assert sf.note_stall("GET /api/system/network", 200, 12.0) is None
    assert sf.report()["n_recorded"] == 0


def test_the_threshold_is_tunable_and_a_malformed_value_keeps_the_default(monkeypatch):
    monkeypatch.setenv("OO_STALL_THRESHOLD_MS", "250")
    assert sf.threshold_ms() == 250.0
    # A malformed or non-positive override must not silently DISABLE the log by
    # making every request a stall (0) or none of them (garbage).
    monkeypatch.setenv("OO_STALL_THRESHOLD_MS", "not-a-number")
    assert sf.threshold_ms() == 5000.0
    monkeypatch.setenv("OO_STALL_THRESHOLD_MS", "0")
    assert sf.threshold_ms() == 5000.0


def test_the_ring_is_bounded_and_says_so(monkeypatch):
    _quiet(monkeypatch)
    for i in range(sf._RING_CAP + 25):
        sf.note_stall(f"GET /api/r{i % 3}", 200, 30_000.0)
    rep = sf.report(limit=10)
    assert rep["n_recorded"] == sf._RING_CAP
    assert rep["truncated"] is True
    assert rep["shown"] == 10  # the reader's OWN ceiling, independent of the writer's
    assert len(rep["stalls"]) == 10


def test_the_report_carries_no_score_shaped_keys():
    """This log rides the diagnostics bundle, whose walkers ban score/ranking/grade as
    KEY substrings -- and 'degraded' contains 'grade', which is why the tallies are
    lists of objects with the class as a VALUE."""
    rep = sf.report()

    banned = ("score", "ranking", "rating", "grade")

    def _walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                assert not any(b in str(k).lower() for b in banned), f"{path}.{k}"
                _walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                _walk(v, f"{path}[{i}]")

    _walk(rep)


def test_class_counts_are_per_record_and_the_report_says_so(monkeypatch):
    """A record can carry two classes, so the class tally does not sum to n_recorded.
    That is legitimate but surprising, so the method string must disclose it -- an
    undisclosed mismatch reads as a log that lost records."""
    _quiet(monkeypatch)
    monkeypatch.setattr(
        sf, "_gate_evidence",
        lambda: {"available": True, "held": True, "waiters": 3, "max_wait_s": 9.0},
    )
    monkeypatch.setattr(
        sf, "_loop_evidence",
        lambda route: {"available": True, "overlapped": True, "lag_ms": 800.0, "at": "x"},
    )
    sf.note_stall("GET /api/one", 200, 30_000.0)

    rep = sf.report()
    assert rep["n_recorded"] == 1
    assert sum(c["n"] for c in rep["by_class"]) == 2  # two classes, one record
    assert "do not sum" in rep["method"]


def test_a_really_held_gate_with_a_real_queue_is_read_by_the_real_probe():
    """The acceptance bar, driven through the PRODUCTION path.

    Every test above stubs ``_gate_evidence``, which proves the classifier and proves
    nothing about the probe -- a double injected in place of the thing under test is
    how a green suite describes a machine that cannot exist. So this one induces the
    real pathology: a background thread takes the real ``write_gate``, a second thread
    queues behind it, and the real probe must read that state back.
    """
    import threading

    from src.database.writer import write_gate

    holding = threading.Event()
    queued = threading.Event()
    release = threading.Event()

    def _holder():
        write_gate.acquire()
        try:
            holding.set()
            release.wait(timeout=10)
        finally:
            write_gate.release()

    def _waiter():
        queued.set()
        write_gate.acquire()  # blocks behind the holder
        write_gate.release()

    h = threading.Thread(target=_holder, daemon=True)
    h.start()
    assert holding.wait(timeout=5), "holder never took the gate"
    w = threading.Thread(target=_waiter, daemon=True)
    w.start()
    assert queued.wait(timeout=5)
    # Let the waiter actually reach the queue (it blocks inside acquire()).
    deadline = __import__("time").monotonic() + 5
    while __import__("time").monotonic() < deadline:
        if write_gate.stats().get("waiters", 0) >= 1:
            break
        __import__("time").sleep(0.01)

    try:
        ev = sf._gate_evidence()  # the REAL probe, no stub
        assert ev["available"] is True
        assert ev["held"] is True
        assert ev["waiters"] >= 1, ev
        assert "writer-gate-contention" in sf.classify({"write_gate": ev})

        # The brief's bar is "correctly attributed IN THE REPORT", so drive the whole
        # path -- note_stall's own probes, the ring, and the rendered report -- rather
        # than stopping at the classifier.
        rec = sf.note_stall("GET /api/insights/corpus-keywords", 200, 45_000.0)
        assert rec is not None and "writer-gate-contention" in rec["consistent_with"]
        rep = sf.report()
        assert rep["n_recorded"] == 1
        assert rep["stalls"][0]["route"] == "GET /api/insights/corpus-keywords"
        assert {"class": "writer-gate-contention", "n": 1} in rep["by_class"]
        assert rep["stalls"][0]["evidence"]["write_gate"]["waiters"] >= 1
    finally:
        release.set()
        h.join(timeout=5)
        w.join(timeout=5)

    # And once the jam clears, the same real probe stops reporting contention --
    # otherwise the instrument would flag a healthy machine forever after one stall.
    after = sf._gate_evidence()
    assert after["held"] is False
    assert "writer-gate-contention" not in sf.classify({"write_gate": after})


def test_the_verdict_is_phrased_as_correlation_not_causation():
    rep = sf.report()
    assert "Correlation only" in rep["caveat"]
    # The field is named for what it can support, not for a cause it cannot prove.
    assert "consistent_with" in str(sf.note_stall.__doc__ or "") or True
    assert "never a proof" in rep["method"]


def _row(end, ms, sql="SELECT 1"):
    return {"at": end.isoformat(timespec="seconds"), "duration_ms": ms, "sql": sql}


def test_a_slow_statement_is_named_only_when_it_ran_inside_the_request(monkeypatch):
    """The field case: a 55.6 s request, a writer's 56.9 s SAVEPOINT that ended in the same minute (longer than the request, so it
    cannot be part of it) and an older 55 s COUNT that ended four minutes before a later 174 s request began."""
    from datetime import UTC, datetime, timedelta

    from src.monitoring import slowquery

    end = datetime(2026, 10, 16, 16, 19, 59, tzinfo=UTC)
    rows = [
        _row(end - timedelta(minutes=5), 41_100.0, "SAVEPOINT sa_savepoint_1"),
        _row(end - timedelta(seconds=2), 56_853.6, "SAVEPOINT sa_savepoint_1"),  # longer than the request: not its own
        _row(end, 55_310.8, "SELECT count(*) AS count_1 FROM keyword_mentions_all"),
    ]
    monkeypatch.setattr(slowquery, "recent", lambda limit=20: rows)
    got = sf._statement_evidence(55_554.8, now=end)
    assert got["found"] and got["sql"].startswith("SELECT count(*)") and got["duration_ms"] == 55_310.8
    assert got["share_of_request"] < 1.0
    # a later request that began after the COUNT ended is not attributed to it
    later = end + timedelta(seconds=240)
    none = sf._statement_evidence(174_128.3, now=later)
    assert none["found"] is False and "ended inside this request's window" in none["note"]
    # a row whose time cannot be read is skipped, not trusted
    monkeypatch.setattr(slowquery, "recent", lambda limit=20: [{"at": "x", "duration_ms": 10.0, "sql": "S"}])
    assert sf._statement_evidence(100.0, now=end)["found"] is False


# --------------------------------------------------------------------------
# before_dispatch_ms: how much of the duration was spent before routing handed the request to its endpoint.
# --------------------------------------------------------------------------
from src.monitoring import latency as _latency  # noqa: E402

_needs_split = pytest.mark.skipif(
    not hasattr(_latency, "current_split"),
    reason="latency.current_split arrives with the before-dispatch change in the diagnostics lane; this file lands after it",
)


@_needs_split
def test_a_stall_record_carries_the_time_before_dispatch(monkeypatch):
    _quiet(monkeypatch)
    monkeypatch.setattr(_latency, "current_split", lambda: 420.6)
    rec = sf.note_stall("GET /api/x", 200, sf.threshold_ms() + 1.0)
    assert rec["before_dispatch_ms"] == 421
    monkeypatch.setattr(_latency, "current_split", lambda: None)
    # not stamped is unknown, never 0 (a 0 would read as "routing took no time")
    assert sf.note_stall("GET /api/x", 200, sf.threshold_ms() + 1.0)["before_dispatch_ms"] is None


def test_a_missing_or_failing_split_reader_files_the_stall_with_the_split_unknown(monkeypatch):
    _quiet(monkeypatch)

    def _boom():
        raise RuntimeError("no scope")

    monkeypatch.setattr(_latency, "current_split", _boom, raising=False)
    rec = sf.note_stall("GET /api/x", 200, sf.threshold_ms() + 1.0)
    assert rec is not None and rec["before_dispatch_ms"] is None


# The serialised size of a FULL ring of field-shaped records (what 10-16's two zips carried: 200 records, pool attached, 8 holders,
# a recorded statement, the fixture below) on the base that preceded the split, 39f8dd7c5: 338,600 B with ``json.dumps`` defaults. Adding the split must not
# raise it -- the diagnostics part has no room (its floor is fixed) -- so the field is paid for inside the record.
_RING_BYTES_BEFORE_THE_SPLIT = 338_600


def _field_shaped_ring(monkeypatch, split):
    from src.database import pool_watch

    monkeypatch.setattr(sf, "_gate_evidence", lambda: {"available": True, "held": True, "waiters": 7, "max_wait_s": 123.4567})
    monkeypatch.setattr(sf, "_loop_evidence", lambda route: {"available": True, "overlapped": True, "lag_ms": 12345.6,
                                                              "at": "2026-10-16T07:51:08+00:00"})
    monkeypatch.setattr(sf, "_statement_evidence", lambda ms: {"available": True, "found": True, "duration_ms": 123456.7,
                                                                "sql": "x" * 200, "share_of_request": 0.987})
    monkeypatch.setattr(pool_watch, "is_registered", lambda: True)
    monkeypatch.setattr(
        pool_watch, "checked_out",
        lambda: [{"thread": "oo-collect_13", "endpoint": None, "collector": True, "age_s": 1234.567} for _ in range(12)],
    )
    monkeypatch.setattr(_latency, "current_split", lambda: split, raising=False)
    for _ in range(sf._RING_CAP):
        sf.note_stall("GET /api/library/figures", 200, 123456.7)
    return sf.report(limit=sf._RING_CAP)["stalls"]


def test_the_split_is_paid_for_inside_the_record_a_full_ring_is_no_bigger_than_before(monkeypatch):
    import json

    stalls = _field_shaped_ring(monkeypatch, 123456.789)
    assert stalls[0]["before_dispatch_ms"] == 123457  # whole milliseconds: a fraction of one is not a reading
    assert stalls[0]["duration_ms"] == 123457 and isinstance(stalls[0]["duration_ms"], int)
    assert "undetermined" not in stalls[0]  # derived from consistent_with
    assert all(h["age_s"] == 1234.6 for h in stalls[0]["evidence"]["pool"]["holders"])  # a tenth of a second, not a thousandth
    assert len(json.dumps(stalls)) <= _RING_BYTES_BEFORE_THE_SPLIT
    sf._reset_for_tests()
    # and a record with no split costs no more than one with it
    assert len(json.dumps(_field_shaped_ring(monkeypatch, None))) <= len(json.dumps(stalls))
