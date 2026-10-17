"""R163: ``storage_events.record`` trims its event list under ``_LOCK`` in loops that a CLI reaches on the main thread (a write lock's release records a
gate hold: scripts/* -> write_lock -> WriterGate.release -> _note_hold_end -> record). The loops now live in helpers or keep their back-edge inside the
``with`` (see tests/test_gates_survive_an_interrupt.py, ``_uncovered_loop_heads``), and trim exactly as before."""

from __future__ import annotations

from src.monitoring import storage_events
from tests.test_gates_survive_an_interrupt import _uncovered_loop_heads


def test_record_has_no_loop_whose_back_edge_is_outside_the_lock():
    left = _uncovered_loop_heads("src/monitoring/storage_events.py", "record")
    assert not left, f"storage_events.record: a loop's back-edge is outside the with: {sorted(left)}"


def test_a_run_still_open_is_not_pushed_out_and_the_oldest_closed_one_goes(monkeypatch):
    storage_events.reset_for_tests()
    monkeypatch.setitem(storage_events.KEEP, "run_export", 3)
    storage_events.record("run_export", {"what": "open one"}, key="a")
    storage_events.record("run_export", {"what": "closed 1"})
    storage_events.record("run_export", {"what": "closed 2"})
    storage_events.record("run_export", {"what": "closed 3"})
    kept = [e.get("what") for e in storage_events._STATE["run_export"]["events"]]  # noqa: SLF001 - the kept list is exactly what is pinned
    assert kept == ["open one", "closed 2", "closed 3"]
    assert ("run_export", "a") in storage_events._OPEN  # noqa: SLF001
    storage_events.reset_for_tests()


def test_an_evicted_event_forgets_its_open_key(monkeypatch):
    storage_events.reset_for_tests()
    monkeypatch.setitem(storage_events.KEEP, "run_export", 2)
    for i in range(3):  # every one open: when all are live the oldest goes, and its key must go with it
        storage_events.record("run_export", {"what": f"r{i}"}, key=i)
    assert [e.get("what") for e in storage_events._STATE["run_export"]["events"]] == ["r1", "r2"]  # noqa: SLF001
    assert sorted(k for _, k in storage_events._OPEN) == [1, 2]  # noqa: SLF001
    storage_events.reset_for_tests()


def test_the_longest_rule_forgets_the_open_keys_of_events_it_drops(monkeypatch):
    storage_events.reset_for_tests()
    monkeypatch.setitem(storage_events.KEEP, "guard", 3)
    monkeypatch.setitem(storage_events.LONGEST, "guard", ("seconds", 1))
    storage_events.record("guard", {"seconds": 1.0}, key="short-old")
    storage_events.record("guard", {"seconds": 9.0})
    storage_events.record("guard", {"seconds": 2.0})
    storage_events.record("guard", {"seconds": 3.0})
    kept = storage_events._STATE["guard"]["events"]  # noqa: SLF001
    assert len(kept) == 3
    assert ("guard", "short-old") not in storage_events._OPEN  # noqa: SLF001 - dropped from the list, so no key may point at it
    storage_events.reset_for_tests()
