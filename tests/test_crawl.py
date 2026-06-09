"""
Tests for the bounded recursive crawler.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Fully faked HTTP (no network). Proves: same-domain fencing, depth/page caps,
one-fetch-per-URL storage of real articles only, and robots fail-closed (the
crawler shares the ethical fetch path).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source
from src.ingest import EthicalFetcher
from src.ingest.crawl import CrawlConfig, crawl_source


class FakeResponse:
    def __init__(self, status_code=200, text="", content_type="text/html", url=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.url = url


class FakeSession:
    def __init__(self):
        self.headers = {}
        self._routes: dict[str, FakeResponse] = {}
        self.fetched: list[str] = []

    def route(self, url, **kwargs):
        self._routes[url] = FakeResponse(url=url, **kwargs)

    def get(self, url, timeout=None, allow_redirects=True):
        self.fetched.append(url)
        if url in self._routes:
            return self._routes[url]
        return FakeResponse(status_code=404, text="not found", url=url)


def _article_html(title, body_sentence, links=()):
    body = (body_sentence + " ") * 30
    anchors = "".join(f'<a href="{href}">{txt}</a>' for href, txt in links)
    return (
        f"<html><head><title>{title}</title></head>"
        f"<body><article><h1>{title}</h1><p>{body}</p>{anchors}</article></body></html>"
    )


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    s = Sess()
    s.add(Source(name="Example", domain="example.com", language="en"))
    s.commit()
    yield s
    s.close()


@pytest.fixture()
def source(db):
    return db.query(Source).first()


def _fetcher(session):
    return EthicalFetcher(min_interval_s=0.0, session=session)


def test_crawl_discovers_same_domain_articles(db, source):
    sess = FakeSession()
    sess.route("https://example.com/robots.txt", status_code=404, text="")
    # Homepage: a section index (too short to be an article) linking to two stories
    # plus an off-domain link that must NOT be followed.
    sess.route(
        "https://example.com",
        text=_article_html(
            "Home",
            "x",  # short body -> not an article
            links=[("/a", "A"), ("/b", "B"), ("https://other.com/x", "ext")],
        ),
    )
    sess.route("https://example.com/a", text=_article_html("Story A", "Real body for A."))
    sess.route("https://example.com/b", text=_article_html("Story B", "Real body for B."))

    report = crawl_source(
        db, source, fetcher=_fetcher(sess), config=CrawlConfig(max_depth=1, max_pages=50)
    )

    assert report.tally["stored"] == 2
    assert db.query(Article).count() == 2
    # The off-domain URL was never even fetched (filtered before queueing).
    assert "https://other.com/x" not in sess.fetched
    assert not any("other.com" in u for u in sess.fetched)


def test_depth_zero_only_fetches_start(db, source):
    sess = FakeSession()
    sess.route("https://example.com/robots.txt", status_code=404, text="")
    sess.route(
        "https://example.com",
        text=_article_html("Home", "Long enough body to be an article here.", links=[("/a", "A")]),
    )
    sess.route("https://example.com/a", text=_article_html("Story A", "Body A."))

    report = crawl_source(
        db, source, fetcher=_fetcher(sess), config=CrawlConfig(max_depth=0, max_pages=50)
    )
    assert report.pages_fetched == 1
    assert "https://example.com/a" not in sess.fetched


def test_max_pages_caps_the_crawl(db, source):
    sess = FakeSession()
    sess.route("https://example.com/robots.txt", status_code=404, text="")
    # A hub linking to many articles; cap stops the crawl early.
    links = [(f"/n{i}", f"N{i}") for i in range(10)]
    sess.route("https://example.com", text=_article_html("Hub", "x", links=links))
    for i in range(10):
        sess.route(f"https://example.com/n{i}", text=_article_html(f"N{i}", f"Body {i}."))

    report = crawl_source(
        db, source, fetcher=_fetcher(sess), config=CrawlConfig(max_depth=2, max_pages=3)
    )
    assert report.pages_fetched == 3
    assert report.stopped_reason == "max_pages"


def test_crawl_respects_robots_fail_closed(db, source):
    sess = FakeSession()
    # robots.txt unreachable -> fail closed -> nothing fetched/stored.
    sess.route("https://example.com", text=_article_html("Home", "Body.", links=[("/a", "A")]))
    # (no robots route -> 404 actually means "allowed"); simulate restriction instead:
    sess.route("https://example.com/robots.txt", status_code=403, text="forbidden")
    report = crawl_source(
        db, source, fetcher=_fetcher(sess), config=CrawlConfig(max_depth=1, max_pages=50)
    )
    assert db.query(Article).count() == 0
    assert report.tally["robots_unavailable"] >= 1
