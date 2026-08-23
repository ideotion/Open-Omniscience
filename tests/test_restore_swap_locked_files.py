"""The restore swap must survive a file the OS will not let go of (Windows).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-08-23, a Windows 11 instance: importing a backup died with
``[WinError 32] ... open_omniscience.db-wal``, raised by the swap step's own
``stale.unlink()``. Nothing was wrong with the backup. ``engine.dispose()``
closes the pool's IDLE connections and leaves the CHECKED-OUT ones to close as
they are returned, so the swap can meet a handle that is on its way out -- and
on POSIX that never mattered, because unlink works on an open file. Windows
refuses, so the whole import failed on a lock that would have cleared by itself.

The three properties these guards hold, and the direction each can fail in:

* the lock is recognised by ERROR CODE, never by message text (the report
  arrived in French, so any substring match would have missed the very report
  that produced the fix) -- and an error that is NOT a lock must not be
  retried, or a read-only volume costs the operator a 20s wait per file to
  reach the same answer;
* a lock is waited out, bounded, and a lock that never clears still raises;
* the WAL is checkpointed BEFORE anything is unlinked, so an abort at any
  point leaves a complete database file -- and that checkpoint is itself
  bounded, because it takes the single-writer gate and that gate's acquire has
  no timeout.
"""

from __future__ import annotations

import errno
import threading
import time

import pytest

from src.backup.merge import (
    _checkpoint_before_swap,
    _clear_stale_side_files,
    _file_is_locked,
    classify_restore_error,
)


def _win_error(winerror: int, message: str) -> PermissionError:
    """A PermissionError shaped like the one Windows raises.

    ``winerror`` is a real attribute of OSError on Windows and simply absent
    elsewhere, so setting it is what makes this fixture faithful on Linux CI.
    """
    exc = PermissionError(errno.EACCES, message)
    exc.winerror = winerror  # type: ignore[attr-defined]
    return exc


# --------------------------------------------------------------------------
# _file_is_locked
# --------------------------------------------------------------------------


def test_the_french_field_report_is_recognised_by_code_not_by_message():
    """The exact shape the field reported: WinError 32, message in French."""
    message = (
        "Le processus ne peut pas acceder au fichier car ce fichier est "
        "utilise par un autre processus"
    )
    assert _file_is_locked(_win_error(32, message))
    # And it is the CODE that decided: the identical message carrying no Windows
    # error code is not recognised, so no substring of it is load-bearing.
    assert not _file_is_locked(PermissionError(errno.EACCES, message))


def test_lock_violation_is_recognised_too():
    assert _file_is_locked(_win_error(33, "lock violation"))


def test_a_non_lock_windows_error_is_not_treated_as_a_lock():
    """ERROR_ACCESS_DENIED (5) is a permissions problem, not a busy file.

    This is the case that killed an errno-based check: Windows maps BOTH 32 and
    5 onto EACCES, so anything reading errno would wait out the whole budget and
    then name the wrong remedy. Waiting cannot change a permissions answer.
    """
    denied = PermissionError(errno.EACCES, "Access is denied")
    denied.winerror = 5  # type: ignore[attr-defined]
    assert denied.errno == errno.EACCES, "the fixture must share errno with a real lock"
    assert not _file_is_locked(denied)


def test_a_missing_file_is_not_a_lock():
    assert not _file_is_locked(FileNotFoundError(errno.ENOENT, "no such file"))


def test_a_posix_permission_error_is_not_treated_as_a_lock():
    """POSIX has no lock to wait out -- unlink succeeds on an open file there.

    EACCES means the directory is not writable, which no amount of waiting will
    change, so a read-only data dir must fail at once instead of costing the
    operator the full budget per file and a misdiagnosis.
    """
    assert not _file_is_locked(PermissionError(errno.EACCES, "Permission denied"))


# --------------------------------------------------------------------------
# _clear_stale_side_files
# --------------------------------------------------------------------------


def test_both_side_files_are_removed(tmp_path):
    db = tmp_path / "corpus.db"
    db.write_bytes(b"db")
    wal = tmp_path / "corpus.db-wal"
    shm = tmp_path / "corpus.db-shm"
    wal.write_bytes(b"wal")
    shm.write_bytes(b"shm")

    _clear_stale_side_files(db, wait_s=1.0)

    assert not wal.exists() and not shm.exists()
    assert db.exists(), "the database itself is replaced by os.replace, never unlinked here"


def test_absent_side_files_are_not_an_error(tmp_path):
    """The common case after a clean checkpoint: SQLite already removed them."""
    db = tmp_path / "corpus.db"
    db.write_bytes(b"db")
    _clear_stale_side_files(db, wait_s=1.0)  # must not raise


def test_a_lock_that_clears_is_waited_out(tmp_path, monkeypatch):
    """The field's actual case: a handle on its way out.

    Two refusals then success -- the import completes instead of failing on a
    lock that was about to disappear.
    """
    db = tmp_path / "corpus.db"
    db.write_bytes(b"db")
    (tmp_path / "corpus.db-wal").write_bytes(b"wal")

    real_unlink = type(db).unlink
    refusals = {"n": 0}

    def flaky(self, missing_ok=False):
        if self.name.endswith("-wal") and refusals["n"] < 2:
            refusals["n"] += 1
            raise _win_error(32, "utilise par un autre processus")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(type(db), "unlink", flaky)

    started = time.monotonic()
    _clear_stale_side_files(db, wait_s=5.0)
    elapsed = time.monotonic() - started

    assert refusals["n"] == 2, "the retry must actually have been exercised"
    assert not (tmp_path / "corpus.db-wal").exists()
    assert elapsed < 5.0, "it must return as soon as the lock clears, not burn the budget"


def test_a_lock_that_never_clears_still_raises(tmp_path, monkeypatch):
    """The honest half: waiting is bounded, and a permanent lock is reported.

    Never silently carrying on -- leaving a stale WAL beside the incoming
    database would have SQLite replay the old log into the new file, which is
    corruption rather than a failed import.
    """
    db = tmp_path / "corpus.db"
    db.write_bytes(b"db")
    (tmp_path / "corpus.db-wal").write_bytes(b"wal")

    def always_locked(self, missing_ok=False):
        raise _win_error(32, "utilise par un autre processus")

    monkeypatch.setattr(type(db), "unlink", always_locked)

    started = time.monotonic()
    with pytest.raises(PermissionError):
        _clear_stale_side_files(db, wait_s=0.5)
    elapsed = time.monotonic() - started

    assert 0.4 <= elapsed < 3.0, f"must give up at the budget, took {elapsed:.2f}s"


def test_an_error_that_is_not_a_lock_is_not_retried(tmp_path, monkeypatch):
    """A read-only volume answers instantly, and the answer will not change.

    The negative-space twin of the retry: a fix that retried every OSError
    would pass every test above and cost the operator the full budget per file
    to reach an identical failure.
    """
    db = tmp_path / "corpus.db"
    db.write_bytes(b"db")
    (tmp_path / "corpus.db-wal").write_bytes(b"wal")

    def read_only(self, missing_ok=False):
        raise OSError(errno.EROFS, "Read-only file system")

    monkeypatch.setattr(type(db), "unlink", read_only)

    started = time.monotonic()
    with pytest.raises(OSError) as caught:
        _clear_stale_side_files(db, wait_s=30.0)
    elapsed = time.monotonic() - started

    assert caught.value.errno == errno.EROFS
    assert elapsed < 1.0, f"a non-lock error must raise at once, took {elapsed:.2f}s"


# --------------------------------------------------------------------------
# _checkpoint_before_swap
# --------------------------------------------------------------------------


def test_a_checkpoint_that_completes_reports_true(monkeypatch):
    import src.scheduler.hygiene as hygiene

    monkeypatch.setattr(hygiene, "checkpoint_wal", lambda force=False: None)
    assert _checkpoint_before_swap(2.0) is True


def test_a_checkpoint_blocked_behind_a_writer_is_bounded(monkeypatch):
    """The reason this is bounded at all.

    ``checkpoint_wal`` takes the single-writer gate and that gate's acquire has
    NO timeout, so calling it straight would turn an import that fails fast into
    one that hangs forever behind another writer. A checkpoint that cannot
    finish MEANS a writer is active, which is the one condition the swap must
    not run under -- so False here makes the caller abort, and the corpus is
    left exactly as it was.
    """
    import src.scheduler.hygiene as hygiene
    from src.database.writer import write_lock

    entered = threading.Event()
    finished = threading.Event()
    release = threading.Event()
    holder_in = threading.Event()

    def blocked(force=False):
        entered.set()
        with write_lock():
            pass
        finished.set()

    monkeypatch.setattr(hygiene, "checkpoint_wal", blocked)

    def holder():
        with write_lock():
            holder_in.set()
            release.wait(30)

    thread = threading.Thread(target=holder, daemon=True)
    thread.start()
    try:
        assert holder_in.wait(5), "the fixture never took the write gate"

        started = time.monotonic()
        answered = _checkpoint_before_swap(1.0)
        elapsed = time.monotonic() - started
        # Captured HERE: releasing the gate below lets the worker finish, so
        # asserting on the events afterwards would read the wrong moment.
        was_entered, was_finished = entered.is_set(), finished.is_set()
    finally:
        release.set()

    assert answered is False
    assert 0.9 <= elapsed < 3.0, f"must give up at the budget, took {elapsed:.2f}s"
    assert was_entered and not was_finished, "the checkpoint must genuinely have been stuck"
    assert finished.wait(5), "and it drains once the gate frees -- never abandoned mid-write"


# --------------------------------------------------------------------------
# classify_restore_error
# --------------------------------------------------------------------------


def test_a_locked_file_is_explained_and_the_corpus_declared_untouched():
    detail = classify_restore_error("restore", _win_error(32, "utilise par un autre processus"))
    assert "still has your corpus open" in detail
    assert "Nothing was changed" in detail, (
        "the reassurance is the important half -- this is raised before the swap"
    )
    assert "utilise par un autre processus" in detail, "the original detail is kept, not lost"


def test_an_integrity_error_is_still_classified_as_a_data_merge_conflict():
    """Negative-space twin: the new branch must not swallow the old ones.

    It sits ABOVE the integrity branch, so a lock check that were too broad
    would relabel every constraint failure as a locked file.
    """
    import sqlite3

    detail = classify_restore_error(
        "restore", sqlite3.IntegrityError("UNIQUE constraint failed: keyword_mentions.keyword_id")
    )
    assert "data-merge issue, not a version mismatch" in detail
    assert "still has your corpus open" not in detail


# --------------------------------------------------------------------------
# the order of the swap steps
# --------------------------------------------------------------------------


def test_the_swap_checkpoints_before_it_unlinks_anything():
    """Order is load-bearing, so it is asserted from the parse tree.

    Committed transactions live in the WAL until a checkpoint moves them into
    the database file. Unlinking a NON-empty WAL and then failing to finish the
    replace would lose exactly those -- so the checkpoint has to come first, and
    then an abort at any later point is free: the database file is complete on
    its own and nothing has been written to it.

    Read through ``ast`` rather than as text: a comment explaining this ordering
    necessarily names the same calls, so a substring search would be satisfied
    by the explanation of the rule instead of the rule.
    """
    import ast
    import inspect

    from src.backup import merge as merge_mod

    tree = ast.parse(inspect.getsource(merge_mod))
    body = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "run_restore"
    )

    wanted = {"_checkpoint_before_swap", "dispose_engine", "_clear_stale_side_files", "replace"}
    seen: list[tuple[int, str]] = []
    for node in ast.walk(body):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
        if name in wanted:
            seen.append((node.lineno, name))
    order = [name for _, name in sorted(seen)]

    for name in wanted:
        assert name in order, f"{name} is not called in run_restore at all"

    where = {name: order.index(name) for name in wanted}
    assert where["_checkpoint_before_swap"] < where["dispose_engine"], (
        "the checkpoint needs a live engine, so it must run before dispose"
    )
    assert where["dispose_engine"] < where["_clear_stale_side_files"], (
        "dispose first, or the pool's own idle handles are what blocks the unlink"
    )
    assert where["_clear_stale_side_files"] < where["replace"], (
        "the stale WAL must be gone before the incoming database takes its place, "
        "or SQLite replays the old log into the new file"
    )
