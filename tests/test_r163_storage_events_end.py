"""R163: ``storage_events.end`` trims the tombstone memory in a loop under ``_LOCK`` that a CLI reaches on the main thread (scripts/analytics45_seed.py ->
kv_set_json -> write_lock -> WriterGate.release -> _note_hold_end -> end). The loop keeps its back-edge inside the ``with`` (see
tests/test_gates_survive_an_interrupt.py, ``_uncovered_loop_heads``), and trims exactly as before."""

from __future__ import annotations

from src.monitoring import storage_events
from tests.test_gates_survive_an_interrupt import _uncovered_loop_heads


def test_the_tombstone_trim_keeps_its_back_edge_inside_the_lock():
    left = _uncovered_loop_heads("src/monitoring/storage_events.py", "end") & {"_ENDED.pop(next(iter(_ENDED)), None)"}
    assert not left, f"storage_events.end: a loop's back-edge is outside the with: {sorted(left)}"


def test_the_tombstone_memory_still_forgets_the_oldest_keys_first_and_stops_at_its_bound(monkeypatch):
    storage_events.reset_for_tests()
    monkeypatch.setattr(storage_events, "ENDED_KEYS_MAX", 3)
    for i in range(7):
        storage_events.end("hold", i, tombstone=True)
    assert list(storage_events._ENDED) == [("hold", 4), ("hold", 5), ("hold", 6)]  # noqa: SLF001 - the bound is exactly what is pinned
    storage_events.reset_for_tests()
