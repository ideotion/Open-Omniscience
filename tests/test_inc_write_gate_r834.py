"""R834 (row 410-A): the staged copy's integrity walk has its verdict before the merge writes the staged copy.

The walk runs beside the merge (R827 R3(a)) and the merge writes the staged copy in one place only: the country-code
step, which rewrites codes the store spells another way. A walk that read pages while that step wrote them could pass
a torn file. So the step waits for the walk's verdict before its first write, and a failed verdict refuses before
anything is written. Both are shown on the plaintext and the keyed (sealed) staged copy, with a real merge.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.backup import staged_key

_META = {"artifact_kind": "oo-backup-2", "origin_fingerprint": "t", "app_version": "0.6", "alembic_rev": "head",
         "manifest": None}


def _build(path: Path, n: int, country: str | None) -> None:
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Article, Base, Source
    from tests._app_engine import app_sqlite_engine

    engine = app_sqlite_engine(path, future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        src = Source(name="s", domain="s.example")
        s.add(src)
        s.flush()
        for i in range(n):
            s.add(Article(url=f"https://s.example/{i}", canonical_url=f"https://s.example/{i}", source_id=src.id,
                          title=f"t{i}", content=f"body {i}", hash=f"h{i}", language="en", country=country,
                          created_at=datetime(2026, 1, 1, tzinfo=UTC)))
        s.commit()
    engine.dispose()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _staged(tmp_path: Path, sealed: bool) -> tuple[Path, Path]:
    work, inc = tmp_path / "work.db", tmp_path / "inc.db"
    _build(work, 0, None)
    _build(inc, 30, "FRA")  # alpha-3 into an alpha-2 store: the country-code step must rewrite every row of inc
    con = sqlite3.connect(inc)
    con.execute("PRAGMA journal_mode=DELETE")  # as a backup's member arrives (and as the seal leaves it): no WAL
    con.close()
    if sealed:
        staged_key.seal_plaintext(inc)
    return work, inc


def _build_inc_codes_already_canonical(inc: Path) -> None:
    """Make the country-code step a no-op, so nothing waits on the write gate and only the COMMIT path is tested."""
    con = staged_key.open_staged(inc, read_only=False)
    try:
        con.execute("UPDATE articles SET country = NULL")
        con.commit()
    finally:
        con.close()


@pytest.mark.parametrize("sealed", [False, True], ids=["plaintext", "keyed"])
def test_the_walk_reads_a_file_nothing_writes_while_it_reads(tmp_path, monkeypatch, sealed):
    import src.backup.sqlite_backup as sb
    from src.backup.merge import _quick_check_alongside, merge_corpus

    work, inc = _staged(tmp_path, sealed)
    seen: dict[str, object] = {}

    def slow_walk(path, **_k):
        seen["before"] = _digest(Path(path))
        time.sleep(0.6)  # long enough that an ungated country-code write would land inside the walk
        seen["after"] = _digest(Path(path))
        seen["ended"] = time.monotonic()
        return 1

    monkeypatch.setattr(sb, "validate_sqlite_file", slow_walk)
    try:
        with _quick_check_alongside(inc):
            counts, _ = merge_corpus(inc, work, _META, cache_mb=8)
        assert seen["before"] == seen["after"], "the staged copy changed while its walk read it"
        assert _digest(inc) != seen["before"], "the country-code step did not write the staged copy at all"
    finally:
        staged_key.forget(inc)
    con = sqlite3.connect(work)
    try:
        assert {r[0] for r in con.execute("SELECT country FROM articles")} == {"fr"}  # the store keeps alpha-2 lower case
    finally:
        con.close()


@pytest.mark.parametrize("sealed", [False, True], ids=["plaintext", "keyed"])
def test_a_failed_walk_refuses_before_the_staged_copy_is_written(tmp_path, monkeypatch, sealed):
    import src.backup.sqlite_backup as sb
    from src.backup.merge import MergeError, _quick_check_alongside, merge_corpus

    work, inc = _staged(tmp_path, sealed)
    before = _digest(inc)

    def failing_walk(path, **_k):
        time.sleep(0.2)
        raise sb.BackupError("integrity check failed")

    monkeypatch.setattr(sb, "validate_sqlite_file", failing_walk)
    try:
        with pytest.raises(MergeError) as refused:
            with _quick_check_alongside(inc):
                merge_corpus(inc, work, _META, cache_mb=8)
        assert "integrity check failed" in str(refused.value)
        assert _digest(inc) == before, "the staged copy was written before its walk's verdict"
    finally:
        staged_key.forget(inc)


def test_without_a_walk_beside_nothing_waits(tmp_path):
    from src.backup.merge import _INC_WRITE_GATE, merge_corpus

    assert _INC_WRITE_GATE.get() is None
    work, inc = _staged(tmp_path, False)
    merge_corpus(inc, work, _META, cache_mb=8)
    con = sqlite3.connect(work)
    try:
        assert {r[0] for r in con.execute("SELECT country FROM articles")} == {"fr"}  # the store keeps alpha-2 lower case
    finally:
        con.close()


@pytest.mark.parametrize("sealed", [False, True], ids=["plaintext-install", "keyed"])
@pytest.mark.parametrize("locked", [True, False], ids=["control-locked-walk", "unlocked-walk"])
def test_a_long_walk_never_holds_the_merges_commits(tmp_path, monkeypatch, sealed, locked):
    """The 4 GB proof run's failure, made small: the walk outlasts the merge connection's busy timeout (0.3 s here, 30 s
    in the app) at a 1 MiB merge cache. A walk that takes SQLite's read lock fails the merge's COMMIT with "database is
    locked" (the control, so the test is not blind); the walk the import runs does not. The plaintext case is a
    plaintext install, where the walk and the merge share the standard driver: the same wait was reachable there."""
    import functools

    import src.database.connect as connect_mod
    from src.backup.merge import _quick_check_alongside, merge_corpus

    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.delenv("OO_DB_PASSPHRASE", raising=False)
    work, inc = _staged(tmp_path, sealed)
    _build_inc_codes_already_canonical(inc)
    real_open = staged_key.open_staged
    reading, merged = threading.Event(), threading.Event()

    def slow_open(path, **kw):
        if locked:
            kw["unlocked"] = False
        conn = real_open(path, **kw)
        conn.execute("BEGIN")
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()  # the read lock, when the open takes one
        reading.set()
        merged.wait(10)  # the walk outlasts the merge, however long the merge takes
        return conn

    monkeypatch.setattr(staged_key, "open_staged", slow_open)
    monkeypatch.setattr(connect_mod, "connect", functools.partial(connect_mod.connect, timeout=0.3))
    try:
        if locked:
            with pytest.raises(Exception, match="locked"):
                with _quick_check_alongside(inc):
                    assert reading.wait(5)
                    try:
                        merge_corpus(inc, work, _META, cache_mb=1)
                    finally:
                        merged.set()
        else:
            with _quick_check_alongside(inc):
                assert reading.wait(5)
                try:
                    merge_corpus(inc, work, _META, cache_mb=1)
                finally:
                    merged.set()
    finally:
        staged_key.forget(inc)


@pytest.mark.parametrize("sealed", [False, True], ids=["plaintext", "keyed"])
@pytest.mark.parametrize("beside", ["-journal", "-wal"])
def test_a_copy_with_a_journal_beside_it_is_walked_with_locks(tmp_path, sealed, beside):
    """An unlocked open skips hot-journal recovery, so it is never used on a file with a journal or WAL beside it: that
    walk takes its read lock (a writer's COMMIT beside it then waits), as every walk did before R834."""
    work, inc = _staged(tmp_path, sealed)
    try:
        def commit_waits() -> bool:
            walk = staged_key.open_staged(inc, unlocked=True)
            walk.isolation_level = None
            walk.execute("BEGIN")
            walk.execute("SELECT count(*) FROM sqlite_master").fetchone()
            other = staged_key.open_staged(inc, read_only=False)
            other.isolation_level = None
            try:
                other.execute("PRAGMA busy_timeout = 100")
                other.execute("BEGIN IMMEDIATE")
                other.execute("UPDATE articles SET country = country")
                try:
                    other.execute("COMMIT")
                    return False
                except Exception:  # noqa: BLE001 - "database is locked"
                    other.execute("ROLLBACK")
                    return True
            finally:
                other.close()
                walk.execute("ROLLBACK")
                walk.close()

        assert commit_waits() is False  # no journal beside it: the walk takes no lock
        Path(f"{inc}{beside}").write_bytes(b"")
        assert commit_waits() is True
    finally:
        Path(f"{inc}{beside}").unlink(missing_ok=True)
        staged_key.forget(inc)
