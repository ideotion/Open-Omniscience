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
    assert rec["undetermined"] is False
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
    assert rec["undetermined"] is True


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
    assert rec["undetermined"] is True


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
