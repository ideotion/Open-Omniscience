"""One custody log per flush, not one per stored article.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Opening a custody log opens a keyed connection to ``custody_log.db``, and on an encrypted install that costs a
key derivation (PBKDF2-HMAC-SHA512 x 256,000: 163 ms of thread CPU median, measured on one core, with 1.2 ms for the
signer and 1.2 ms for the record itself). ``_maybe_record_custody`` used to open one for every stored article. A flush
stores up to ``collect_batch_size()`` articles one after another on one thread, so ``ArticleBatch._flush_batched`` now
opens ONE log for its whole loop (``_CustodyBatch``) and closes it when the loop ends.

What each test fails on:

* the log opened more than once per flush (the old shape), or not closed when the flush ends;
* an entry written through a log that was dropped after a failed write (a connection in an unknown state), or a log
  dropped for a failure that was not the log's (an article read that failed before the log was touched);
* a failed entry that is not queued as owed any more (``pending.note_failed``), or a chain that stops verifying;
* the per-call shape (no batch) changing: still one log opened and closed per entry;
* ``auto_log_on_ingest`` off costing a log;
* ``_flush_batched`` going back to a per-article call;
* a log kept after the settings it was opened under changed (OpenTimestamps consent withdrawn mid-flush still stamping the
  rest of the flush) or after the process lost its passphrase (a crypto-erase mid-flush still writing through a key the
  process no longer holds);
* a failed write whose connection is NOT really closed (a failed INSERT leaves a transaction and a write lock open until
  the connection is closed: tested with a real failing INSERT and a second writer).

Plaintext stores throughout: the point is how many logs a flush opens, which the tests count at ``CustodyLog``.
"""

from __future__ import annotations

import inspect
import re
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.custody import pending
from src.custody.log import CustodyLog
from src.custody.settings import CustodySettings
from src.database.models import Article, Base, Source
from src.ingest.pipeline import _CustodyBatch, _maybe_record_custody


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", future=True, poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def custody(monkeypatch, tmp_path):
    """An isolated data dir with plaintext stores and custody auto-log ON (pinned: the setting lives in the main database)."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    (tmp_path / "data").mkdir()
    monkeypatch.setattr("src.custody.settings.load_settings", lambda: CustodySettings(auto_log_on_ingest=True))
    return tmp_path / "data"


class _Opens:
    """Counts the custody logs opened (``CustodyLog()`` constructed), and the closes."""

    def __init__(self, monkeypatch) -> None:
        self.opened = 0
        self.closed = 0
        real_init, real_close = CustodyLog.__init__, CustodyLog.close
        outer = self

        def init(this, *a, **kw):
            outer.opened += 1
            real_init(this, *a, **kw)

        def close(this):
            outer.closed += 1
            real_close(this)

        monkeypatch.setattr(CustodyLog, "__init__", init)
        monkeypatch.setattr(CustodyLog, "close", close)


@pytest.fixture()
def opens(monkeypatch, custody):
    return _Opens(monkeypatch)


def _stored(db, n: int) -> list[Article]:
    src = Source(name="c", domain="c.example", rss_url="https://c.example/feed.xml", language="en")
    db.add(src)
    db.flush()
    tag = uuid.uuid4().hex[:6]
    arts = []
    for i in range(n):
        a = Article(
            url=f"https://c.example/{tag}/{i}",
            canonical_url=f"https://c.example/{tag}/{i}",
            source_id=src.id,
            title=f"t{i}",
            content=f"body {i}",
            hash=f"hash-{tag}-{i}",
        )
        db.add(a)
        arts.append(a)
    db.commit()
    return arts


def _entries(item_id: str):
    with CustodyLog() as log:
        return [e for e in log.entries_for(item_id) if e.action == "ingest"]


def test_one_log_serves_a_whole_flush_and_every_entry_is_chained(db, opens):
    arts = _stored(db, 6)
    opens.opened = opens.closed = 0
    with _CustodyBatch() as custody:
        for a in arts:
            _maybe_record_custody(a, batch=custody)
        assert custody.opened == 1
    assert opens.opened == 1, "six articles, one log: the old shape opened six"
    assert opens.closed == 1, "and it is closed when the block ends"
    opens.opened = opens.closed = 0
    with CustodyLog() as log:
        ok, issues = log.verify()
        assert ok, issues
        seqs = [e.seq for e in log.all_entries()]
    assert len(seqs) == 6 and seqs == sorted(seqs) and len(set(seqs)) == 6, "six entries, one chain"
    for a in arts:
        assert [e.item_hash for e in _entries(f"article:{a.id}")] == [a.hash]


def test_without_a_batch_every_entry_opens_and_closes_its_own_log(db, opens):
    arts = _stored(db, 3)
    opens.opened = opens.closed = 0
    for a in arts:
        _maybe_record_custody(a)
    assert opens.opened == 3 and opens.closed == 3, "the per-call shape (the redo path, the unbatched store) is unchanged"


def test_a_failed_write_drops_the_log_and_the_next_article_opens_a_fresh_one(db, opens, monkeypatch):
    a1, a2, a3 = _stored(db, 3)
    opens.opened = opens.closed = 0
    real = CustodyLog.record

    def flaky(self, item_id, *args, **kw):
        if item_id == f"article:{a2.id}":
            raise TimeoutError("database is locked")
        return real(self, item_id, *args, **kw)

    monkeypatch.setattr(CustodyLog, "record", flaky)
    with _CustodyBatch() as custody:
        for a in (a1, a2, a3):
            _maybe_record_custody(a, batch=custody)
        assert custody.opened == 2
    assert opens.opened == 2, "article 2's failure cost the log; article 3 opened another, as every article did before"
    assert opens.closed == 2, "both closed: the failed one when it was dropped, the other when the block ended"
    monkeypatch.setattr(CustodyLog, "record", real)
    assert len(_entries(f"article:{a1.id}")) == 1 and len(_entries(f"article:{a3.id}")) == 1
    assert _entries(f"article:{a2.id}") == []
    assert [q["article_id"] for q in pending.read_pending()] == [a2.id], "only the failed one is owed, and it is queued"
    with CustodyLog() as log:
        ok, issues = log.verify()
        assert ok, issues


def test_a_log_that_cannot_be_opened_fails_each_article_as_it_did_before(db, opens, monkeypatch):
    arts = _stored(db, 3)
    attempts = []

    def refuse(self, *a, **kw):
        attempts.append(1)
        raise OSError("custody_log.db is unreachable")

    monkeypatch.setattr(CustodyLog, "__init__", refuse)
    with _CustodyBatch() as custody:
        for a in arts:
            _maybe_record_custody(a, batch=custody)  # never raises into ingestion
        assert custody.opened == 0
    assert len(attempts) == 3, "no log is held, so every article tries to open one, as before"
    assert sorted(q["article_id"] for q in pending.read_pending()) == sorted(a.id for a in arts)


def test_a_real_failed_insert_leaves_no_lock_behind_and_the_chain_stays_valid(db, opens, custody, monkeypatch):
    """A failed INSERT leaves a transaction and a write lock open on its connection until it is closed. Fail a real one (a
    duplicate entry hash), then try to take the write lock from a second connection straight away."""
    import sqlite3

    import src.custody.log as custody_log

    a1, a2, a3 = _stored(db, 3)
    ids = [a.id for a in (a1, a2, a3)]
    db.commit()
    with _CustodyBatch() as batch:
        _maybe_record_custody(a1, batch=batch)
        first_hash = _entries(f"article:{ids[0]}")[0].entry_hash
        real_digest = custody_log._entry_digest
        monkeypatch.setattr(custody_log, "_entry_digest", lambda core: first_hash)
        _maybe_record_custody(a2, batch=batch)  # the INSERT fails on UNIQUE(entry_hash), after the lock was taken
        monkeypatch.setattr(custody_log, "_entry_digest", real_digest)
        other = sqlite3.connect(str(custody / "custody_log.db"), timeout=0.2)
        try:
            other.execute("BEGIN IMMEDIATE")  # raises "database is locked" if the failed connection still holds the lock
            other.rollback()
        finally:
            other.close()
        _maybe_record_custody(a3, batch=batch)
        assert batch.opened == 2, "the failed write dropped the log; the next article opened a fresh one"
    assert [q["article_id"] for q in pending.read_pending()] == [ids[1]]
    assert _entries(f"article:{ids[1]}") == []
    with CustodyLog() as log:
        ok, issues = log.verify()
        assert ok, issues
        assert [e.item_id for e in log.all_entries()] == [f"article:{ids[0]}", f"article:{ids[2]}"]


def test_withdrawing_opentimestamps_mid_flush_takes_effect_at_the_next_entry(db, opens, monkeypatch):
    """The log fixes its anchoring mode when it is opened. An operator who sets anchoring back to local while a flush is
    running must not see the rest of that flush still sent to the public calendars (invariant #14f)."""
    import src.custody.log as custody_log
    from src.custody.timestamp import local_timestamp

    stamped: list[int] = []

    def fake_ots(digest):
        stamped.append(1)
        return local_timestamp(digest)

    monkeypatch.setattr(custody_log, "ots_stamp", fake_ots)
    current = {"prefs": CustodySettings(auto_log_on_ingest=True, anchoring_mode="opentimestamps")}
    monkeypatch.setattr("src.custody.settings.load_settings", lambda: current["prefs"])
    arts = _stored(db, 4)
    opens.opened = opens.closed = 0
    with _CustodyBatch() as batch:
        _maybe_record_custody(arts[0], batch=batch)
        assert len(stamped) == 1
        current["prefs"] = CustodySettings(auto_log_on_ingest=True, anchoring_mode="local")
        _maybe_record_custody(arts[1], batch=batch)
        _maybe_record_custody(arts[2], batch=batch)
        assert len(stamped) == 1, "consent withdrawn: nothing more is stamped"
        assert batch.opened == 2 and opens.opened == 2, "one re-open for the new setting, then the new log is reused"
        current["prefs"] = CustodySettings(auto_log_on_ingest=True, anchoring_mode="opentimestamps")
        _maybe_record_custody(arts[3], batch=batch)
        assert len(stamped) == 2, "and turning it back on is honoured as well"
    assert batch.opened == 3


class _DummyLog:
    """Stands in for CustodyLog where the test is about when a log is reopened, not about what it writes."""

    made = 0

    def __init__(self) -> None:
        type(self).made += 1

    def close(self) -> None:
        pass


@pytest.mark.parametrize(
    ("changed", "reopens"),
    [
        ({}, False),
        ({"default_actor": "someone-else"}, False),  # the actor is an argument of every entry, not part of the log
        ({"anchoring_mode": "opentimestamps"}, True),
        ({"pqc_enabled": True}, True),
    ],
)
def test_only_the_settings_a_log_is_opened_under_reopen_it(monkeypatch, changed, reopens):
    import src.custody.log as custody_log

    _DummyLog.made = 0
    monkeypatch.setattr(custody_log, "CustodyLog", _DummyLog)
    with _CustodyBatch() as batch:
        batch.log(CustodySettings())
        batch.log(CustodySettings(**changed))
        assert batch.opened == (2 if reopens else 1)
    assert _DummyLog.made == batch.opened


def test_a_cleared_passphrase_mid_flush_stops_the_writes_through_the_old_key(db, tmp_path, monkeypatch):
    """crypto-erase and a lock clear the process passphrase, and this connection is one they cannot reach. The next entry
    must not be written through it: it opens afresh, fails for want of a key, and is queued as owed."""
    import secrets

    pytest.importorskip("sqlcipher3")
    from src.database import connect

    data = tmp_path / "enc-data"
    data.mkdir()
    monkeypatch.setenv("OO_DATA_DIR", str(data))
    monkeypatch.delenv("OO_DB_PLAINTEXT", raising=False)
    monkeypatch.setattr("src.custody.settings.load_settings", lambda: CustodySettings(auto_log_on_ingest=True))
    connect.set_passphrase(secrets.token_hex(16))  # a throwaway key for a throwaway store
    try:
        a1, a2 = _stored(db, 2)
        ids = [a1.id, a2.id]
        db.commit()
        with _CustodyBatch() as batch:
            _maybe_record_custody(a1, batch=batch)
            assert batch.opened == 1
            connect.set_passphrase(None)
            _maybe_record_custody(a2, batch=batch)
            assert batch._log is None, "the log opened under the old key is gone"
    finally:
        connect.set_passphrase(None)
    assert [q["article_id"] for q in pending.read_pending()] == [ids[1]]


def test_a_read_that_fails_before_the_log_is_touched_costs_the_batch_nothing(db, opens, monkeypatch):
    """The field failure of CUST-1: the pool is exhausted and the expired article cannot be reloaded. That is not the
    log's failure: the healthy log stays, the article is owed, the next article uses the same log."""
    from sqlalchemy.engine import Engine

    a1, a2, a3 = _stored(db, 3)
    ids = [a.id for a in (a1, a2, a3)]
    db.commit()
    opens.opened = opens.closed = 0
    real_connect = Engine.connect

    def exhausted(self, *a, **kw):
        raise TimeoutError("QueuePool limit of size 6 overflow 2 reached, connection timed out")

    with _CustodyBatch() as custody:
        _maybe_record_custody(a1, batch=custody)  # reloads its columns, opens the log
        db.commit()  # ends the read transaction and expires every column again: the pipeline's shape
        monkeypatch.setattr(Engine, "connect", exhausted)
        _maybe_record_custody(a2, batch=custody)  # its read fails before the log is touched
        monkeypatch.setattr(Engine, "connect", real_connect)
        _maybe_record_custody(a3, batch=custody)
        assert custody.opened == 1
    assert opens.opened == 1, "one log for all three: the read that failed did not cost the batch its log"
    assert [q["article_id"] for q in pending.read_pending()] == [ids[1]]
    assert len(_entries(f"article:{ids[0]}")) == 1 and len(_entries(f"article:{ids[2]}")) == 1


def test_a_read_that_fails_first_opens_no_log_for_nothing(db, opens, monkeypatch):
    from sqlalchemy.engine import Engine

    (a,) = _stored(db, 1)
    aid = a.id
    db.commit()  # ends the read transaction and expires every column: the pipeline's shape
    opens.opened = opens.closed = 0

    def exhausted(self, *a, **kw):
        raise TimeoutError("QueuePool limit of size 6 overflow 2 reached, connection timed out")

    monkeypatch.setattr(Engine, "connect", exhausted)
    with _CustodyBatch() as custody:
        _maybe_record_custody(a, batch=custody)
        assert custody.opened == 0
    assert opens.opened == 0, "a log is opened when there is an entry to write, not before"
    assert [q["article_id"] for q in pending.read_pending()] == [aid]


def test_the_setting_off_opens_no_log(db, opens, monkeypatch):
    arts = _stored(db, 3)
    opens.opened = opens.closed = 0
    monkeypatch.setattr("src.custody.settings.load_settings", lambda: CustodySettings(auto_log_on_ingest=False))
    with _CustodyBatch() as custody:
        for a in arts:
            _maybe_record_custody(a, batch=custody)
        assert custody.opened == 0
    assert opens.opened == 0 and opens.closed == 0


def test_the_log_is_closed_when_the_block_is_left_by_a_raise(db, opens):
    (a,) = _stored(db, 1)
    opens.opened = opens.closed = 0
    with pytest.raises(RuntimeError), _CustodyBatch() as custody:
        _maybe_record_custody(a, batch=custody)
        assert opens.closed == 0
        raise RuntimeError("a later step of the flush failed")
    assert opens.opened == 1 and opens.closed == 1, "a failing flush leaves no connection behind"


def test_dropping_never_raises_and_forgets_the_log(opens, monkeypatch):
    custody = _CustodyBatch()
    custody.drop()  # nothing open: nothing to do
    custody.log(CustodySettings())

    held = custody._log
    real_close = CustodyLog.close

    def boom(this):
        raise OSError("close failed")

    monkeypatch.setattr(CustodyLog, "close", boom)
    custody.drop()
    assert custody._log is None
    monkeypatch.setattr(CustodyLog, "close", real_close)
    real_close(held)
    custody.log(CustodySettings())
    assert custody.opened == 2, "a dropped log is opened afresh, not reused"
    custody.drop()


def test_nothing_outlives_the_block(db, opens):
    """No module state, no attribute elsewhere: a second flush opens its own log, so a passphrase change or a restore
    between two flushes has nothing stale to hit."""
    arts = _stored(db, 4)
    opens.opened = opens.closed = 0
    for pair in (arts[:2], arts[2:]):
        with _CustodyBatch() as custody:
            for a in pair:
                _maybe_record_custody(a, batch=custody)
    assert opens.opened == 2 and opens.closed == 2, "two flushes, two logs"
    from src.ingest import pipeline

    held = [v for k, v in vars(pipeline).items() if isinstance(v, (CustodyLog, _CustodyBatch))]
    assert held == [], "the pipeline module keeps no log between calls"


def test_flush_batched_opens_one_log_for_its_whole_loop(opens, monkeypatch):
    """Through the real flush: a source of five articles, batch of five, one flush, one custody log."""
    import requests

    from src.ingest import EthicalFetcher
    from src.ingest.pipeline import ingest_source

    class _Resp:
        def __init__(self, text="", ct="text/html", url=None):
            self.status_code = 200
            self.text = text
            self.content = text.encode("utf-8")
            self.headers = {"Content-Type": ct}
            self.url = url

        def close(self):
            pass

    domain = "flush-one-log.example"
    routes: dict[str, _Resp] = {}
    items = "".join(f"<item><title>i{i}</title><link>https://{domain}/n/{i}</link></item>" for i in range(5))
    routes[f"https://{domain}/feed.xml"] = _Resp(
        f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>',
        "application/rss+xml",
        f"https://{domain}/feed.xml",
    )
    for i in range(5):
        body = (f"unique {domain} body {i} datum ") * 30
        routes[f"https://{domain}/n/{i}"] = _Resp(
            f"<html><head><title>T{i}</title></head><body><article><h1>T{i}</h1><p>{body}</p></article></body></html>",
            "text/html",
            f"https://{domain}/n/{i}",
        )

    class _Session:
        headers: dict = {}
        proxies: dict = {}

        def get(self, url, timeout=None, allow_redirects=True, headers=None, proxies=None, stream=None, **kw):
            if url.endswith("/robots.txt"):
                return _Resp("User-agent: *\nAllow: /", "text/plain", url)
            if url in routes:
                return routes[url]
            raise requests.ConnectionError(f"unrouted url {url}")

    monkeypatch.setenv("OO_COLLECT_COMMIT_BATCH", "5")
    eng = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, future=True)()
    source = Source(name=domain, domain=domain, rss_url=f"https://{domain}/feed.xml", language="en")
    s.add(source)
    s.commit()
    opens.opened = opens.closed = 0
    tally = ingest_source(s, source, fetcher=EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=_Session()))
    assert tally["stored"] == 5
    assert opens.opened == 1 and opens.closed == 1, "five stored articles, one flush, one custody log"
    with CustodyLog() as log:
        assert len([e for e in log.all_entries() if e.action == "ingest"]) == 5
        ok, issues = log.verify()
        assert ok, issues
    s.close()


def test_the_flush_uses_the_batch_and_never_the_per_article_call():
    """The source pin: the final loop of ``_flush_batched`` is inside the batch and passes it on."""
    from src.ingest.batch import ArticleBatch

    src = inspect.getsource(ArticleBatch._flush_batched)
    assert "with _CustodyBatch() as" in src
    assert re.search(r"_maybe_record_custody\(a,\s*batch=", src), "the call must hand the flush's log on"
    assert not re.search(r"_maybe_record_custody\(a\)", src), "a per-article call here is the 163 ms per article again"


def test_the_entry_is_read_before_the_log_is_touched():
    """The ordering the read-failure tests rely on, pinned at the source: nothing of the article is read after
    ``batch.log(...)`` or ``CustodyLog()`` is called."""
    src = inspect.getsource(_maybe_record_custody)
    body = src[src.index('item_id = f"article:'):]
    first_log_call = min(body.index("batch.log("), body.index("CustodyLog()"))
    before = body[:first_log_call]
    assert "article.id" in before and "article.hash" in before and "article.url" in before
    assert "article." not in body[first_log_call : body.index("except Exception")]
