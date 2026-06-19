"""Source IP capture (data-architecture Slice 6a).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The server IP is captured ONLY on a direct clearnet connection -- over a proxy / Tor
the socket reaches the proxy, not the server, so it is honestly UNAVAILABLE, never a
guess. The IP is our vantage point (CDN edge / anycast), not the publisher's origin.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.database.maintenance import ensure_article_ip_columns
from src.database.models import Article, Base, Source
from src.ingest import EthicalFetcher


# --- fake live-socket plumbing (no real network) --------------------------- #
class _Sock:
    def __init__(self, ip):
        self._ip = ip

    def getpeername(self):
        return (self._ip, 443)


class _Conn:
    def __init__(self, sock):
        self.sock = sock


class _Raw:
    def __init__(self, conn):
        self._connection = conn


class _Resp:
    def __init__(self, ip):
        self.raw = _Raw(_Conn(_Sock(ip)))


def _real_fetcher():
    # A real requests.Session -> _real_session is True (the capture path engages).
    return EthicalFetcher(min_interval_s=0.0, session=requests.Session())


def test_clearnet_captures_the_connected_ip():
    f = _real_fetcher()
    ip, reason = f._capture_server_ip(_Resp("203.0.113.7"), proxied=False)
    assert ip == "203.0.113.7"
    assert reason is None


def test_proxy_or_tor_is_honestly_unavailable_never_guessed():
    f = _real_fetcher()
    ip, reason = f._capture_server_ip(_Resp("198.51.100.9"), proxied=True)
    assert ip is None  # NEVER the proxy's address, never a guess
    assert reason == "unavailable (proxy/Tor)"


def test_unreadable_socket_degrades_loudly():
    f = _real_fetcher()

    class _NoSock:
        raw = _Raw(None)  # _connection is None -> .sock raises

    ip, reason = f._capture_server_ip(_NoSock(), proxied=False)
    assert ip is None
    assert reason == "unavailable (socket not readable)"


def test_garbage_peername_is_rejected_not_stored():
    f = _real_fetcher()

    class _BadSock:
        def getpeername(self):
            return ("not-an-ip", 0)

    resp = _Resp("x")
    resp.raw._connection.sock = _BadSock()
    ip, reason = f._capture_server_ip(resp, proxied=False)
    assert ip is None and reason == "unavailable (socket not readable)"


def test_injected_test_session_captures_nothing():
    # A non-requests session (a test double) is not a real socket -> nothing to read,
    # and NO fabricated value.
    class _Stub:
        headers: dict = {}

        def get(self, *a, **k):  # pragma: no cover - never called here
            raise AssertionError

    f = EthicalFetcher(min_interval_s=0.0, session=_Stub())
    assert f._capture_server_ip(_Resp("203.0.113.7"), proxied=False) == (None, None)


# --- the columns persist + self-heal --------------------------------------- #
@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    return s


def _add(db, i, **kw):
    a = Article(
        url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1,
        title="T", content="body", hash=f"h{i}", language="en",
        created_at=datetime.now(UTC), **kw,
    )
    db.add(a)
    db.commit()
    return a.id


def test_ip_columns_round_trip(db):
    now = datetime(2026, 6, 19, tzinfo=UTC)
    clear = db.get(Article, _add(db, 1, server_ip="203.0.113.7", ip_observed_at=now))
    tor = db.get(Article, _add(db, 2, server_ip=None,
                               server_ip_reason="unavailable (proxy/Tor)", ip_observed_at=now))
    assert clear.server_ip == "203.0.113.7" and clear.server_ip_reason is None
    assert tor.server_ip is None and tor.server_ip_reason == "unavailable (proxy/Tor)"


def test_self_heal_adds_ip_columns_no_backfill():
    eng = create_engine("sqlite:///:memory:", future=True)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE articles (id INTEGER PRIMARY KEY, hash VARCHAR(64))"))
        c.execute(text("INSERT INTO articles (id, hash) VALUES (1, 'h')"))
    added = ensure_article_ip_columns(eng)
    assert set(added) == {"server_ip", "ip_observed_at", "server_ip_reason"}
    with eng.begin() as c:
        row = c.execute(text("SELECT server_ip, server_ip_reason FROM articles WHERE id=1")).fetchone()
    assert row == (None, None)  # additive, existing rows honestly empty
    assert ensure_article_ip_columns(eng) == []  # idempotent


def test_pipeline_copies_server_ip_into_the_article(monkeypatch, db):
    # End-to-end through store_fetched (skips locally without feedparser; runs in CI).
    pytest.importorskip("feedparser")
    pytest.importorskip("trafilatura")
    from types import SimpleNamespace

    import src.ingest.pipeline as P

    doc = SimpleNamespace(
        text="A federal budget article body.", title="T", canonical_url=None,
        published_at=None, language="en", author=None,
    )
    monkeypatch.setattr(P, "extract_article", lambda *a, **k: doc)
    fetched = SimpleNamespace(
        requested_url="https://news.test/a", final_url="https://news.test/a",
        content="<html>x</html>", fetched_at=datetime(2026, 6, 19, tzinfo=UTC),
        server_ip="203.0.113.50", server_ip_reason=None,
    )
    src = db.get(Source, 1)
    out = P.store_fetched(db, src, fetched)
    art = db.query(Article).filter(Article.url == "https://news.test/a").one()
    assert art.server_ip == "203.0.113.50"
    # SQLite's DateTime column stores naive datetimes (drops tzinfo), so compare the
    # wall-clock instant rather than aware==naive (the value was copied correctly).
    assert art.ip_observed_at is not None
    observed = art.ip_observed_at
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    assert observed == fetched.fetched_at
    assert out  # an IngestOutcome was returned
