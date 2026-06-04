"""
Tests for the ingestion pipeline (Action Plan Phase 1.2-1.4).

Drives ethical fetch -> extract -> dedup -> store with a fully faked HTTP layer
(no network), proving:
  * robots.txt is honoured and FAIL-CLOSED (network error => do not fetch);
  * one fetch path, no raw bypass;
  * trafilatura extraction, with explicit failure (no junk stored);
  * dedup by canonical URL and by content hash;
  * provenance fields populated;
  * RSS feeds are fetched through the same ethical path.
"""

from __future__ import annotations

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source
from src.ingest import EthicalFetcher, RobotsDisallowed, RobotsUnavailable
from src.ingest.pipeline import IngestResult, ingest_source, ingest_url


# --------------------------------------------------------------------------- #
# Fake HTTP layer
# --------------------------------------------------------------------------- #

class FakeResponse:
    def __init__(self, status_code=200, text="", content_type="text/html", url=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.url = url


class FakeSession:
    """Maps URLs to FakeResponse; raises for URLs registered as network errors."""

    def __init__(self):
        self.headers = {}
        self._routes: dict[str, FakeResponse] = {}
        self._errors: set[str] = set()

    def route(self, url, **kwargs):
        self._routes[url] = FakeResponse(url=url, **kwargs)

    def error(self, url):
        self._errors.add(url)

    def get(self, url, timeout=None, allow_redirects=True):
        if url in self._errors:
            raise requests.ConnectionError(f"simulated network error for {url}")
        if url in self._routes:
            return self._routes[url]
        return FakeResponse(status_code=404, text="not found", url=url)


def _article_html(title, body_sentence):
    body = (body_sentence + " ") * 30  # well over the extractor's min length
    return (
        f"<html><head><title>{title}</title>"
        f"<meta property='og:title' content='{title}'></head>"
        f"<body><article><h1>{title}</h1><p>{body}</p></article></body></html>"
    )


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    s = Sess()
    s.add(Source(name="Example", domain="example.com", rss_url="https://example.com/feed.xml",
                 language="en"))
    s.commit()
    yield s
    s.close()


@pytest.fixture()
def source(db):
    return db.query(Source).first()


def _fetcher(session):
    # min_interval_s=0 -> no real sleeping in tests.
    return EthicalFetcher(min_interval_s=0.0, session=session)


# --------------------------------------------------------------------------- #
# robots.txt: fail-closed
# --------------------------------------------------------------------------- #

def test_robots_disallow_blocks_fetch(db, source):
    sess = FakeSession()
    sess.route("https://example.com/robots.txt", text="User-agent: *\nDisallow: /private/")
    sess.route("https://example.com/private/secret",
               text=_article_html("Secret", "should never be fetched"))
    out = ingest_url(db, source, "https://example.com/private/secret", fetcher=_fetcher(sess))
    assert out.result is IngestResult.BLOCKED_ROBOTS
    assert db.query(Article).count() == 0


def test_robots_network_error_fails_closed(db, source):
    sess = FakeSession()
    sess.error("https://example.com/robots.txt")  # cannot determine robots
    sess.route("https://example.com/a", text=_article_html("A", "real content here"))
    out = ingest_url(db, source, "https://example.com/a", fetcher=_fetcher(sess))
    assert out.result is IngestResult.ROBOTS_UNAVAILABLE
    assert db.query(Article).count() == 0


def test_robots_403_treats_site_as_offlimits(db, source):
    sess = FakeSession()
    sess.route("https://example.com/robots.txt", status_code=403, text="forbidden")
    sess.route("https://example.com/a", text=_article_html("A", "real content here"))
    out = ingest_url(db, source, "https://example.com/a", fetcher=_fetcher(sess))
    assert out.result is IngestResult.ROBOTS_UNAVAILABLE


# --------------------------------------------------------------------------- #
# happy path + provenance
# --------------------------------------------------------------------------- #

def test_stores_article_with_provenance(db, source):
    sess = FakeSession()
    sess.route("https://example.com/robots.txt", status_code=404, text="")
    sess.route("https://example.com/news/1",
               text=_article_html("Big Story", "Investigative journalism matters."))
    out = ingest_url(db, source, "https://example.com/news/1", fetcher=_fetcher(sess))
    assert out.result is IngestResult.STORED
    art = db.query(Article).one()
    assert art.title == "Big Story"
    assert "Investigative journalism matters." in art.content
    # provenance
    assert art.url == "https://example.com/news/1"
    assert art.canonical_url
    assert art.hash and len(art.hash) == 64
    assert art.source_id == source.id
    assert art.language == "en"
    assert art.word_count > 0


# --------------------------------------------------------------------------- #
# dedup
# --------------------------------------------------------------------------- #

def test_dedup_same_url(db, source):
    sess = FakeSession()
    sess.route("https://example.com/robots.txt", status_code=404, text="")
    sess.route("https://example.com/news/1",
               text=_article_html("Big Story", "Investigative journalism matters."))
    f = _fetcher(sess)
    assert ingest_url(db, source, "https://example.com/news/1", fetcher=f).result is IngestResult.STORED
    second = ingest_url(db, source, "https://example.com/news/1", fetcher=f)
    assert second.result is IngestResult.DUPLICATE
    assert db.query(Article).count() == 1


def test_dedup_same_content_different_url(db, source):
    sess = FakeSession()
    sess.route("https://example.com/robots.txt", status_code=404, text="")
    html = _article_html("Same", "Identical body content for both urls.")
    sess.route("https://example.com/a", text=html)
    sess.route("https://example.com/b", text=html)
    f = _fetcher(sess)
    assert ingest_url(db, source, "https://example.com/a", fetcher=f).result is IngestResult.STORED
    out = ingest_url(db, source, "https://example.com/b", fetcher=f)
    assert out.result is IngestResult.DUPLICATE
    assert db.query(Article).count() == 1


# --------------------------------------------------------------------------- #
# failure modes (no junk stored)
# --------------------------------------------------------------------------- #

def test_extract_failure_stores_nothing(db, source):
    sess = FakeSession()
    sess.route("https://example.com/robots.txt", status_code=404, text="")
    sess.route("https://example.com/thin", text="<html><body><p>too short</p></body></html>")
    out = ingest_url(db, source, "https://example.com/thin", fetcher=_fetcher(sess))
    assert out.result is IngestResult.EXTRACT_FAILED
    assert db.query(Article).count() == 0


def test_non_html_is_rejected(db, source):
    sess = FakeSession()
    sess.route("https://example.com/robots.txt", status_code=404, text="")
    sess.route("https://example.com/data.json", text="{}", content_type="application/json")
    out = ingest_url(db, source, "https://example.com/data.json", fetcher=_fetcher(sess))
    assert out.result is IngestResult.FETCH_FAILED
    assert db.query(Article).count() == 0


# --------------------------------------------------------------------------- #
# RSS feed ingestion through the ethical path
# --------------------------------------------------------------------------- #

def test_ingest_source_via_rss(db, source):
    sess = FakeSession()
    sess.route("https://example.com/robots.txt", status_code=404, text="")
    feed = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Example</title>
      <item><title>One</title><link>https://example.com/1</link></item>
      <item><title>Two</title><link>https://example.com/2</link></item>
    </channel></rss>"""
    sess.route("https://example.com/feed.xml", text=feed, content_type="application/rss+xml")
    sess.route("https://example.com/1", text=_article_html("One", "First article body text."))
    sess.route("https://example.com/2", text=_article_html("Two", "Second article body text."))

    tally = ingest_source(db, source, fetcher=_fetcher(sess))
    assert tally["entries"] == 2
    assert tally[IngestResult.STORED.value] == 2
    assert db.query(Article).count() == 2


def test_fetcher_raises_typed_errors_directly():
    """The fetcher itself raises typed errors (independent of the pipeline)."""
    sess = FakeSession()
    sess.route("https://x.test/robots.txt", text="User-agent: *\nDisallow: /")
    sess.route("https://x.test/page", text="<html></html>")
    f = EthicalFetcher(min_interval_s=0.0, session=sess)
    with pytest.raises(RobotsDisallowed):
        f.fetch("https://x.test/page")

    sess2 = FakeSession()
    sess2.error("https://y.test/robots.txt")
    f2 = EthicalFetcher(min_interval_s=0.0, session=sess2)
    with pytest.raises(RobotsUnavailable):
        f2.fetch("https://y.test/page")
