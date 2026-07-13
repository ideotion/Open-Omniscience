"""
Forward-build (audit pipeline Phase 4): the WAL resting ceiling + WAL visibility.

STORAGE_5TB_PLAN §3 Phase-A: `journal_size_limit` was set NOWHERE (so the -wal never
truncated back to a resting size after checkpoints); and the storage diagnostic did not
surface the -wal size (so unbounded WAL growth was invisible). Measurement-first + bounded;
no CREATE-time seam, no network.
"""

from __future__ import annotations

import sqlite3

from src.database import session as S
from src.monitoring.storage import storage_composition


def _apply(conn):
    S._sqlite_pragmas(conn, None)
    return conn


def test_journal_size_limit_default_64mib(monkeypatch):
    monkeypatch.delenv("OO_WAL_SIZE_LIMIT_MB", raising=False)
    conn = _apply(sqlite3.connect(":memory:"))
    assert conn.execute("PRAGMA journal_size_limit").fetchone()[0] == 64 * 1024 * 1024
    conn.close()


def test_journal_size_limit_env_override(monkeypatch):
    monkeypatch.setenv("OO_WAL_SIZE_LIMIT_MB", "16")
    conn = _apply(sqlite3.connect(":memory:"))
    assert conn.execute("PRAGMA journal_size_limit").fetchone()[0] == 16 * 1024 * 1024
    conn.close()


def test_journal_size_limit_disabled_with_nonpositive(monkeypatch):
    monkeypatch.setenv("OO_WAL_SIZE_LIMIT_MB", "0")
    conn = _apply(sqlite3.connect(":memory:"))
    assert conn.execute("PRAGMA journal_size_limit").fetchone()[0] == -1  # SQLite "no limit"
    conn.close()


def test_bad_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("OO_WAL_SIZE_LIMIT_MB", "not-a-number")
    conn = _apply(sqlite3.connect(":memory:"))
    assert conn.execute("PRAGMA journal_size_limit").fetchone()[0] == 64 * 1024 * 1024
    conn.close()


def test_storage_composition_surfaces_wal_and_limit(tmp_path):
    # a real file-backed WAL db with the pragmas + a pending write -> a -wal file exists.
    from sqlalchemy import create_engine, event, text
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base

    db = tmp_path / "c.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    event.listen(engine, "connect", S._sqlite_pragmas)  # apply our pragmas
    Base.metadata.create_all(engine)
    sm = sessionmaker(bind=engine, future=True)
    s = sm()
    s.execute(text("CREATE TABLE _t (x)"))
    s.execute(text("INSERT INTO _t VALUES (1)"))
    s.commit()
    out = storage_composition(s)
    # the WAL ceiling we set is reported, and the actual -wal size is surfaced (visibility).
    assert out.get("journal_size_limit") == 64 * 1024 * 1024
    assert "wal_bytes" in out and isinstance(out["wal_bytes"], int) and out["wal_bytes"] >= 0
    # no score key leaked into the diagnostic
    assert not any("score" in k.lower() for k in out)
    s.close()
