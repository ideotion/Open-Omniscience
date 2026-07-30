"""ONE pre-restore safety net per import run, not one per item.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-07-30 (16 backups, ~130 GB, tracking to about a week): every item of
an import queue wrote a full copy of the whole live corpus as its safety net. On that
corpus a 16-item run means ~2 TB written and ~390 GB held at once -- and it was not even
delivering what it appeared to, because ``_SNAPSHOT_KEEP`` is 3: the run's earliest
snapshot (the only one an operator would actually want -- "put it back the way it was
before I started this import") was pruned away by item 4, a defect this project's own
ledger already records.

So the net is now scoped to the RUN, identified by the exclusive window's token. What
these tests pin is the SCOPING RULE and its edges, not a speed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import src.backup.merge as M
import src.scheduler.runner as R


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(M, "_RUN_SNAPSHOT", None, raising=False)
    monkeypatch.setattr(R, "_EXCL_WINDOW", False)
    yield
    monkeypatch.setattr(M, "_RUN_SNAPSHOT", None, raising=False)
    monkeypatch.setattr(R, "_EXCL_WINDOW", False)


class _FakeScheduler:
    running = True

    def hold_exclusive(self) -> None: ...
    def release_exclusive(self) -> None: ...

    def stop(self, timeout: float = 10.0) -> bool:
        was, self.running = self.running, False
        return was

    def start(self) -> bool:
        self.running = True
        return True


@pytest.fixture()
def window(monkeypatch):
    monkeypatch.setattr(R, "get_scheduler", lambda: _FakeScheduler())
    import src.ingest as I

    monkeypatch.setattr(I, "kill_switch_active", lambda: False)
    return R.exclusive_window


# --------------------------------------------------------------------------- #
#  the window token
# --------------------------------------------------------------------------- #
def test_no_window_means_no_run_identity(window):
    assert R.exclusive_window_token() == 0


def test_a_window_has_an_identity_and_a_later_one_differs(window):
    with window():
        first = R.exclusive_window_token()
    with window():
        second = R.exclusive_window_token()
    assert first and second and second > first, "tokens count up; never reused"


def test_a_nested_window_keeps_the_outer_run_identity(window):
    """A nested operation is part of the SAME run -- it must not start a new one, or
    every item of a queue would look like a fresh run and take its own snapshot again."""
    with window():
        outer = R.exclusive_window_token()
        with window():
            assert R.exclusive_window_token() == outer
        assert R.exclusive_window_token() == outer


# --------------------------------------------------------------------------- #
#  the scoping rule
# --------------------------------------------------------------------------- #
def test_a_lone_restore_always_takes_its_own(tmp_path, window):
    """No window (the single-archive REST route) => unchanged behaviour, every time."""
    assert M._run_scoped_snapshot() is None
    snap = tmp_path / "pre-restore-1.db"
    snap.write_bytes(b"x")
    M._remember_run_snapshot(snap)
    assert M._run_scoped_snapshot() is None, "nothing is remembered outside a run"


def test_items_of_one_run_share_the_first_items_snapshot(tmp_path, window):
    snap = tmp_path / "pre-restore-1.db"
    snap.write_bytes(b"x")
    with window():
        assert M._run_scoped_snapshot() is None, "item 1 takes it"
        M._remember_run_snapshot(snap)
        assert M._run_scoped_snapshot() == snap, "item 2 reuses it"
        assert M._run_scoped_snapshot() == snap, "and item 3"


def test_a_later_run_takes_a_fresh_one(tmp_path, window):
    snap = tmp_path / "pre-restore-1.db"
    snap.write_bytes(b"x")
    with window():
        M._remember_run_snapshot(snap)
    with window():
        assert M._run_scoped_snapshot() is None, "a new run gets its own safety net"


def test_a_deleted_snapshot_is_never_reported_as_still_standing(tmp_path, window):
    """The whole value of a safety net is that it EXISTS. If something removed it, the
    honest answer is to take another -- never to keep pointing at a path that is gone."""
    snap = tmp_path / "pre-restore-1.db"
    snap.write_bytes(b"x")
    with window():
        M._remember_run_snapshot(snap)
        assert M._run_scoped_snapshot() == snap
        snap.unlink()
        assert M._run_scoped_snapshot() is None


def test_run_restore_registers_the_reused_snapshot_as_active_staging():
    """A reused net must be protected during EVERY item's commit tail, exactly as the
    writing item's own is -- otherwise the age-based sweep could remove the one thing
    standing between a long import run and an unwindable corpus."""
    import re

    src = Path(__file__).resolve().parents[1] / "src" / "backup" / "merge.py"
    body = re.split(r"\n(?:async )?def run_restore\(", src.read_text(encoding="utf-8"))[1]
    nxt = re.search(r"\n(?:async )?(?:def|class) ", body)
    body = body[: nxt.start()] if nxt else body
    assert "active_staging(_reuse if _reuse is not None else snapshot)" in body
