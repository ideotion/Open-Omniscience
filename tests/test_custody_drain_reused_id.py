"""``pending.drain`` does not take a reused article id for an entry that was already written (R365).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``articles.id`` is a plain ``INTEGER PRIMARY KEY`` (no AUTOINCREMENT): SQLite hands the highest ids out again after
they are deleted, and a restore's swap discards every article committed to the live file after its working copy was
taken, so the NEXT articles take the ids those had. The custody log is a separate, append-only file the swap does not
touch, so ``article:<id>`` can already hold an INGEST entry, with the hash of an article that no longer exists, when
a new article takes that id and its own custody write fails and is queued (``note_failed``).

``drain`` used to settle an owed entry as "already present" when ANY INGEST entry existed for the id, so the new
article never got its entry and nothing said so. It now settles an entry only when an INGEST entry at that id carries
the article's own content hash; an entry at the id for other content leaves the owed entry to be written, marked.

These tests drive the real ``drain`` against a real :class:`CustodyLog` in a temporary data directory.
"""

from __future__ import annotations

from contextlib import contextmanager
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
    """An isolated data dir, plaintext stores, custody auto-log ON, session_scope pointed at the test database."""
    import src.database.session as dbs

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    (tmp_path / "data").mkdir()

    @contextmanager
    def _scope():
        yield db
        db.commit()

    monkeypatch.setattr(dbs, "session_scope", _scope)
    from src.custody.settings import save_settings

    save_settings({"auto_log_on_ingest": True})
    return tmp_path / "data"


def _article(db, n: int, article_hash: str) -> Article:
    src = db.query(Source).filter_by(domain="c.example").first()
    if src is None:
        src = Source(name="c.example", domain="c.example")
        db.add(src)
        db.flush()
    a = Article(url=f"https://c.example/{n}", canonical_url=f"https://c.example/{n}", source_id=src.id, title="t",
                content=f"body {n}", hash=article_hash, language="en", published_at=datetime.now(UTC),
                created_at=datetime.now(UTC))
    db.add(a)
    db.commit()
    return a


def _log_ingest(article_id: int, item_hash: str) -> None:
    from src.custody.log import CustodyAction, CustodyLog

    with CustodyLog() as log:
        log.record(f"article:{article_id}", item_hash, CustodyAction.INGEST, actor="ingest-pipeline",
                   metadata={"url": f"https://old.example/{article_id}"})


def _ingests(article_id: int):
    from src.custody.log import CustodyLog

    with CustodyLog() as log:
        return [e for e in log.entries_for(f"article:{article_id}") if e.action == "ingest"]


def test_an_owed_entry_for_a_reused_id_is_written_and_says_another_hash_was_logged_there(custody, db):
    """The id carries an INGEST entry for the article a restore discarded; the new article at that id owes its own."""
    from src.custody import pending

    a = _article(db, 1, "hash-of-the-new-article")
    _log_ingest(a.id, "hash-of-the-discarded-article")
    pending.note_failed(a.id, error="TimeoutError: pool")
    res = pending.drain()
    assert res["recorded"] == 1 and res["already_present"] == 0, res
    assert pending.read_pending() == []
    got = _ingests(a.id)
    assert [e.item_hash for e in got] == ["hash-of-the-discarded-article", "hash-of-the-new-article"]
    meta = got[1].metadata
    assert meta["late"] is True
    assert meta["earlier_ingest_other_hash"] is True, "the late entry says an entry for other content already sat at this id"
    assert "earlier_ingest_other_hash" not in got[0].metadata


def test_an_owed_entry_whose_own_hash_is_already_logged_is_still_settled_as_present(custody, db):
    """The control: the entry that was written after all is not written twice."""
    from src.custody import pending

    a = _article(db, 1, "the-hash")
    _log_ingest(a.id, "the-hash")
    pending.note_failed(a.id, error="TimeoutError: pool")
    res = pending.drain()
    assert res["recorded"] == 0 and res["already_present"] == 1, res
    assert len(_ingests(a.id)) == 1 and pending.read_pending() == []


def test_the_hash_the_failed_write_carried_is_compared_not_only_the_stored_row(custody, db):
    """A queued record that already has its hash (note_failed(item_hash=...)) is compared without needing the read."""
    from src.custody import pending

    a = _article(db, 1, "hash-now-stored")
    _log_ingest(a.id, "hash-of-the-discarded-article")
    pending.note_failed(a.id, item_hash="hash-of-the-queued-write", error="TimeoutError: pool")
    res = pending.drain()
    assert res["recorded"] == 1 and res["already_present"] == 0, res
    assert [e.item_hash for e in _ingests(a.id)][-1] == "hash-of-the-queued-write"


def test_the_queued_records_hash_wins_over_the_stored_rows_when_they_differ(custody, db):
    """Article.hash is rewritten in place by other lanes: the entry owed is for the hash the failed write CARRIED, so an
    INGEST entry with that hash settles it even though the row now says something else (written twice otherwise)."""
    from src.custody import pending

    a = _article(db, 1, "hash-rewritten-in-place-later")
    _log_ingest(a.id, "hash-of-the-queued-write")
    pending.note_failed(a.id, item_hash="hash-of-the-queued-write", error="TimeoutError: pool")
    res = pending.drain()
    assert res["recorded"] == 0 and res["already_present"] == 1, res
    assert len(_ingests(a.id)) == 1 and pending.read_pending() == []


def test_when_the_rows_cannot_be_read_an_entry_already_at_the_id_cannot_be_judged_and_stays_queued(custody, db, monkeypatch):
    """No hash on the record and no read: we cannot tell whose entry this is, so the owed entry waits for the next
    drain instead of being dropped as 'present'. Once the read works it is written."""
    from src.custody import pending

    a = _article(db, 1, "hash-of-the-new-article")
    _log_ingest(a.id, "hash-of-the-discarded-article")
    pending.note_failed(a.id, error="TimeoutError: pool")
    real = pending._columns_for

    def _boom(ids, session_factory=None):
        raise TimeoutError("QueuePool limit reached")

    monkeypatch.setattr(pending, "_columns_for", _boom)
    res = pending.drain()
    assert res["recorded"] == 0 and res["already_present"] == 0 and res["still_pending"] == 1, res
    assert "read_error" in res
    monkeypatch.setattr(pending, "_columns_for", real)
    res = pending.drain()
    assert res["recorded"] == 1 and res["still_pending"] == 0, res


def test_an_owed_entry_whose_article_is_gone_is_still_settled_without_a_write(custody, db):
    """Nothing is owed for an article that no longer exists; the counting is what it always was."""
    from src.custody import pending

    a = _article(db, 1, "hash-of-the-new-article")
    _log_ingest(a.id, "hash-of-the-discarded-article")
    pending.note_failed(a.id, error="TimeoutError: pool")
    db.delete(a)
    db.commit()
    res = pending.drain()
    assert res["recorded"] == 0 and res["still_pending"] == 0, res
    assert len(_ingests(a.id)) == 1, "no entry was written for an article that is not there"
