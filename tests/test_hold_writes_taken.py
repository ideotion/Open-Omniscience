"""Audit 0.5.0 item 13: a second restore reaching the switch while one holds settings writes is REFUSED, not reported as a failure.

``kv_store.hold_writes`` used to raise a bare ``RuntimeError("settings writes are already held")``, which ``_carry_and_swap`` did not map, so the
API answered the second restore with the generic "restore failed" and recorded ``error``. It raises :class:`KvHoldTaken` (still a RuntimeError)
and ``_carry_and_swap`` turns it into :class:`RestoreRefused`, the refusal its two neighbours already give. Nothing is written to the corpus
before the hold, so only the words and the record change.
"""

from __future__ import annotations

import ast
import threading
from pathlib import Path

import pytest

import src.backup.merge as merge
from src.backup.merge import RestoreRefused
from src.config import kv_store

_MERGE_PY = Path(__file__).resolve().parents[1] / "src" / "backup" / "merge.py"


@pytest.fixture
def held_by_another_thread(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'open_omniscience.db'}")
    kv_store.kv_invalidate()
    taken, release = threading.Event(), threading.Event()

    def first_restore():
        with kv_store.hold_writes(1.0):
            taken.set()
            release.wait(30)

    t = threading.Thread(target=first_restore, daemon=True)
    t.start()
    assert taken.wait(30), "the first hold never started"
    yield t
    release.set()
    t.join(30)
    kv_store.kv_invalidate()


def test_a_second_hold_is_a_KvHoldTaken_and_leaves_the_first_hold_alone(held_by_another_thread):
    owner = kv_store._hold_by
    with pytest.raises(kv_store.KvHoldTaken) as raised, kv_store.hold_writes(0):
        pass
    assert isinstance(raised.value, RuntimeError), "a caller that caught the bare RuntimeError must still catch it"
    assert kv_store._hold_by == owner is not None, "the refused second hold took or cleared the first one's hold"


def test_a_restore_that_meets_a_held_switch_is_refused_and_writes_nothing(held_by_another_thread, monkeypatch, tmp_path):
    def never(*_a, **_k):
        raise AssertionError("the restore went on past a hold it did not get")

    monkeypatch.setattr(merge, "swap_in_corpus", never)
    monkeypatch.setattr(merge, "_carry_live_settings", never)
    report: dict = {}
    with pytest.raises(RestoreRefused) as raised:
        merge._carry_and_swap(tmp_path / "working.db", tmp_path / "live.db", report)
    assert "another restore is already switching your corpus" in str(raised.value)
    assert "nothing was written to your corpus" in str(raised.value)
    assert "settings_carry" not in report


def test_carry_and_swap_maps_all_three_settings_hold_exceptions():
    """Source guard: the three ways a hold can be refused each have their own except, so a new one is looked at."""
    tree = ast.parse(_MERGE_PY.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_carry_and_swap")
    mapped = {h.type.id for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers if isinstance(h.type, ast.Name)}
    assert {"KvWriteBusy", "KvLockStuck", "KvHoldTaken"} <= mapped
