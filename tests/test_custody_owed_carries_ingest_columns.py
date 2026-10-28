"""An owed custody entry carries what the ingest knew, so the drain binds it to the bytes that were stored.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``_maybe_record_custody`` reads the article's hash and metadata BEFORE it touches the log, then queues the
entry when the write fails. It queued the article id and nothing else, so the drain read the row's CURRENT hash:
an in-place ``Article.hash`` rewrite between the failure and the drain bound the late entry to bytes the ingest
never stored (and, with a drain that cannot remove an entry it has written, a second marked entry). The columns
are queued whenever the ingest read them; when that read is the failure (the pool is exhausted), the queue
carries the id alone, as before, and the drain reads the row.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.models import Article, Base, Source


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def custody(monkeypatch, tmp_path, db):
    import contextlib

    import src.database.session as dbs

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    (tmp_path / "data").mkdir()

    @contextlib.contextmanager
    def _scope():
        yield db
        db.commit()

    monkeypatch.setattr(dbs, "session_scope", _scope)
    from src.custody.settings import save_settings

    save_settings({"auto_log_on_ingest": True})
    return tmp_path / "data"


def _stored(db) -> Article:
    src = Source(name="c.example", domain="c.example")
    db.add(src)
    db.flush()
    a = Article(url="https://c.example/a", canonical_url="https://c.example/a-canon", source_id=src.id, title="t",
                content="body", hash="hash-at-ingest", language="en", published_at=datetime.now(UTC),
                created_at=datetime.now(UTC))
    db.add(a)
    db.commit()
    return a


def _ingest_entries(item_id: str):
    from src.custody.log import CustodyLog

    with CustodyLog() as log:
        return [e for e in log.entries_for(item_id) if e.action == "ingest"]


def test_the_queued_entry_carries_the_hash_and_columns_the_ingest_read(custody, db, monkeypatch):
    from src.custody import pending
    from src.custody.log import CustodyLog
    from src.ingest.pipeline import _maybe_record_custody

    a = _stored(db)

    def _boom(self, *args, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(CustodyLog, "record", _boom)
    _maybe_record_custody(a)
    (queued,) = pending.read_pending()
    assert queued["article_id"] == a.id
    assert queued["item_hash"] == "hash-at-ingest"
    assert queued["url"] == "https://c.example/a" and queued["canonical_url"] == "https://c.example/a-canon"
    assert queued["source_id"] == a.source_id


def test_a_hash_rewritten_after_the_failure_does_not_change_what_the_late_entry_binds(custody, db, monkeypatch):
    from src.custody import pending
    from src.custody.log import CustodyLog
    from src.ingest.pipeline import _maybe_record_custody

    a = _stored(db)
    aid = a.id
    real = CustodyLog.record

    def _boom(self, *args, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(CustodyLog, "record", _boom)
    _maybe_record_custody(a)
    monkeypatch.setattr(CustodyLog, "record", real)
    a.hash = "hash-rewritten-in-place"
    db.commit()
    assert pending.drain()["recorded"] == 1
    (entry,) = _ingest_entries(f"article:{aid}")
    assert entry.item_hash == "hash-at-ingest", "the entry binds the bytes the ingest stored, not the row's later hash"
    meta = entry.metadata
    assert meta["late"] is True
    assert meta["url"] == "https://c.example/a" and meta["canonical_url"] == "https://c.example/a-canon"
    assert meta["source_id"] == a.source_id, "a queued hash must not cost the late entry its url and source"


def test_a_read_that_is_the_failure_queues_the_id_alone_and_the_drain_reads_the_row(custody, db, monkeypatch):
    """The CUST-1 case: the article's expired columns cannot be reloaded because the pool is exhausted."""
    from src.custody import pending
    from src.ingest.pipeline import _maybe_record_custody

    a = _stored(db)
    aid = a.id
    db.expire(a)
    real_execute = db.execute

    def _exhausted(*args, **kw):
        raise TimeoutError("QueuePool limit of size 6 overflow 2 reached, connection timed out")

    monkeypatch.setattr(db, "execute", _exhausted)
    _maybe_record_custody(a)
    monkeypatch.setattr(db, "execute", real_execute)
    (queued,) = pending.read_pending()
    assert queued["article_id"] == aid
    assert not queued["item_hash"] and not queued["url"], "nothing was read, so nothing is claimed"
    assert pending.drain()["recorded"] == 1
    (entry,) = _ingest_entries(f"article:{aid}")
    assert entry.item_hash == "hash-at-ingest" and entry.metadata["late"] is True
