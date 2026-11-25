"""R827 R3(a) (row 408): the staged copy's quick_check runs alongside the merge, and a failure refuses
before the swap.

The page walk used to run before the merge, on the critical path (32 minutes of the field's largest
import). It now runs on its own thread while the merge reads the same staged copy, and the merge
stage waits for it at its end. These tests pin the three things that must hold:
- a damaged copy is still refused, before the verify stage and any swap;
- a merge that fails stops the walk and keeps its own error;
- run_restore really wires it that way (the walk is deferred out of prepare_staged and wrapped
  around the merge, ahead of verify).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from tests.js_source_helper import python_function_source

_ROOT = Path(__file__).resolve().parents[1]


def _healthy(path: Path, rows: int = 4000) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT)")
    con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, source_id INT, body TEXT)")
    con.execute("CREATE INDEX ix_articles_source ON articles(source_id)")
    con.executemany(
        "INSERT INTO articles (source_id, body) VALUES (?, ?)",
        [(i % 50, f"body {i} " * 20) for i in range(rows)],
    )
    con.commit()
    con.close()
    return path


def _damaged(path: Path) -> Path:
    _healthy(path)
    size = path.stat().st_size
    with path.open("r+b") as fh:  # garbage over pages in the middle: the b-tree no longer adds up
        fh.seek((size // 4096 // 2) * 4096)
        fh.write(b"\xa5" * 4096 * 3)
    return path


class _Rec:
    def __init__(self) -> None:
        self.seen: dict[str, float] = {}

    def record(self, name: str, seconds: float) -> None:
        self.seen[name] = seconds


def test_a_healthy_copy_passes_and_both_times_are_recorded(tmp_path):
    from src.backup.merge import _quick_check_alongside

    rec = _Rec()
    ran = []
    with _quick_check_alongside(_healthy(tmp_path / "s.db"), rec):
        ran.append("merge")
    assert ran == ["merge"]
    assert set(rec.seen) == {"merge:quick_check", "merge:quick_check_wait"}
    assert all(v >= 0 for v in rec.seen.values())


def test_a_damaged_copy_is_refused_after_the_merge_and_before_anything_else(tmp_path):
    from src.backup.merge import MergeError, _quick_check_alongside
    from src.backup.sqlite_backup import validate_sqlite_file

    bad = _damaged(tmp_path / "s.db")
    # the structure look alone still passes, so the refusal below is the page walk's
    validate_sqlite_file(bad, quick_check=False)
    ran = []
    after = []
    with pytest.raises(MergeError) as exc:
        with _quick_check_alongside(bad, _Rec()):
            ran.append("merge")
        after.append("verify")  # never reached: nothing after the merge runs on a damaged copy
    assert ran == ["merge"] and after == []
    assert "integrity check failed" in str(exc.value) or "not a valid SQLite database" in str(exc.value)


def test_a_failing_merge_stops_the_walk_and_keeps_its_own_error(tmp_path, monkeypatch):
    import src.backup.sqlite_backup as sb
    from src.backup.merge import _quick_check_alongside

    stopped = threading.Event()

    def _slow_walk(path, *, connection_cb=None, should_stop=None, quick_check=True, alongside=False):
        con = sqlite3.connect(":memory:")
        if connection_cb is not None:
            connection_cb(con)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if should_stop is not None and should_stop():
                stopped.set()
                raise sb.BackupError("integrity check stopped before it finished")
            time.sleep(0.01)
        return 2

    monkeypatch.setattr(sb, "validate_sqlite_file", _slow_walk)
    t0 = time.monotonic()
    with (
        pytest.raises(ValueError, match="the merge failed"),
        _quick_check_alongside(tmp_path / "s.db", _Rec()),
    ):
        raise ValueError("the merge failed")
    assert stopped.is_set(), "the walk was not told to stop"
    assert time.monotonic() - t0 < 10, "the failed merge waited for the whole walk"


def test_a_walk_that_cannot_run_is_a_refusal_never_a_pass(tmp_path, monkeypatch):
    import src.backup.sqlite_backup as sb
    from src.backup.merge import MergeError, _quick_check_alongside

    def _broken(path, **kw):
        raise OSError("disk went away")

    monkeypatch.setattr(sb, "validate_sqlite_file", _broken)
    with pytest.raises(MergeError, match="could not run"), _quick_check_alongside(tmp_path / "s.db", None):
        pass


def test_run_restore_defers_the_walk_and_waits_for_it_before_verify():
    src = (_ROOT / "src/backup/merge.py").read_text(encoding="utf-8")
    restore = python_function_source(src, "run_restore")
    assert "defer_quick_check=True" in restore
    wrapped = "_quick_check_alongside(staged.corpus_path, timings),"
    assert wrapped in restore, "the walk runs around the merge"
    assert restore.index(wrapped) < restore.index('_abort_point("verify")'), (
        "the walk is waited for before the verify stage, so before any swap"
    )
    prepare = python_function_source(src, "prepare_staged_corpus")
    assert "validate_sqlite_file(staged.corpus_path, quick_check=not defer_quick_check)" in prepare
