"""A staging path marked live is unmarked when an interrupt lands right after the mark was made (R171).

``active_staging`` added the path to the live set BEFORE its ``try``, so an interrupt between the add and the ``try`` left the path marked for
the life of the process (tests/test_contextmanager_acquire_before_try.py is the scan that found the shape). Deterministic here: the lock the add
runs under raises a KeyboardInterrupt when the add's ``with`` block ends, after the path was recorded.
"""

from __future__ import annotations

import threading

import pytest

from src.backup import stream_backup as sb


class _InterruptOnFirstExit:
    def __init__(self) -> None:
        self._real = threading.RLock()
        self.fired = False

    def __enter__(self):
        self._real.acquire()
        return self

    def __exit__(self, *exc):
        self._real.release()
        if not self.fired:
            self.fired = True
            raise KeyboardInterrupt
        return False


def test_a_staging_path_marked_then_interrupted_is_unmarked(monkeypatch, tmp_path):
    lock = _InterruptOnFirstExit()
    monkeypatch.setattr(sb, "_ACTIVE_LOCK", lock)
    monkeypatch.setattr(sb, "_ACTIVE_STAGING", set())
    with pytest.raises(KeyboardInterrupt), sb.active_staging(tmp_path):
        pytest.fail("the body must not run")
    assert lock.fired
    assert not sb.is_active_staging(tmp_path), "the path stayed marked as a live job's staging, so its leftovers are never cleaned"


def test_a_marked_path_is_seen_inside_the_block_and_unmarked_after(monkeypatch, tmp_path):
    monkeypatch.setattr(sb, "_ACTIVE_STAGING", set())
    with sb.active_staging(tmp_path):
        assert sb.is_active_staging(tmp_path)
    assert not sb.is_active_staging(tmp_path)
