"""RSS conditional GET: an unchanged feed is a cheap 304, not a re-download.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field log 2026-06-13: ~93% of feed items were duplicates at 1-minute intervals
because unchanged feeds were re-fetched and re-parsed every pass. The fetcher
now sends If-None-Match / If-Modified-Since and treats 304 as a valid result;
ingest_source stores the validators per feed and skips parsing on 304.
"""

from __future__ import annotations

import uuid

import pytest

from src.database.models import FeedFetchState, Source
from src.database.session import SessionLocal, init_db
from src.ingest import EthicalFetcher, FetchResult

_EMPTY_RSS = '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title></channel></rss>'


# --------------------------------------------------------------------------- #
# Fetcher: 304 is a valid result; validators surface; headers are sent
# --------------------------------------------------------------------------- #


class _Resp:
    def __init__(self, status_code=200, text="", content_type="application/rss+xml",
                 url=None, headers=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type, **(headers or {})}
        self.url = url

    def close(self):
        pass


class _Session:
    """Serves a permissive robots.txt and a scripted response for the page,
    recording the request headers it was given."""

    def __init__(self, page_url, page_resp):
        self.headers = {}
        self._page = page_url
        self._page_resp = page_resp
        self.seen_headers = None

    def get(self, url, timeout=None, allow_redirects=True, headers=None, **kwargs):
        if url.endswith("/robots.txt"):
            return _Resp(text="User-agent: *\nAllow: /", content_type="text/plain", url=url)
        if url == self._page:
            self.seen_headers = headers
            return self._page_resp
        return _Resp(status_code=404, url=url)


def _fetcher(session):
    return EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=session)


def test_304_is_a_valid_result_not_an_error():
    page = "https://example.com/feed.xml"
    resp = _Resp(status_code=304, headers={"ETag": '"v1"', "Last-Modified": "Wed, 01 Jan 2026 00:00:00 GMT"})
    sess = _Session(page, resp)
    result = _fetcher(sess).fetch(page, require_html=False, extra_headers={"If-None-Match": '"v1"'})
    assert result.status_code == 304
    assert result.content == ""  # nothing re-downloaded
    assert result.etag == '"v1"'
    assert result.last_modified == "Wed, 01 Jan 2026 00:00:00 GMT"
    # the conditional header was actually sent
    assert sess.seen_headers == {"If-None-Match": '"v1"'}


def test_200_surfaces_validators_for_next_time():
    page = "https://example.com/feed.xml"
    resp = _Resp(status_code=200, text=_EMPTY_RSS, headers={"ETag": '"abc"', "Last-Modified": "X"})
    result = _fetcher(_Session(page, resp)).fetch(page, require_html=False)
    assert result.status_code == 200
    assert result.etag == '"abc"'
    assert result.last_modified == "X"


def test_no_extra_headers_means_no_headers_kwarg_change():
    # Backward compatible: a plain fetch sends no conditional headers.
    page = "https://example.com/feed.xml"
    sess = _Session(page, _Resp(status_code=200, text=_EMPTY_RSS))
    _fetcher(sess).fetch(page, require_html=False)
    assert sess.seen_headers is None


# --------------------------------------------------------------------------- #
# ingest_source: store validators, then skip on 304
# --------------------------------------------------------------------------- #


class _StubFetcher:
    """Records (url, extra_headers) per call and returns scripted FetchResults."""

    def __init__(self, script):
        self._script = list(script)
        self.calls: list[tuple[str, dict | None]] = []

    def fetch(self, url, *, require_html=True, extra_headers=None):
        self.calls.append((url, extra_headers))
        return self._script.pop(0)


@pytest.fixture()
def db():
    init_db()
    s = SessionLocal()
    yield s
    s.close()


def _result(status, *, etag=None, content=_EMPTY_RSS):
    from datetime import UTC, datetime

    return FetchResult(
        requested_url="https://feed.example/rss",
        final_url="https://feed.example/rss",
        status_code=status,
        content=content if status == 200 else "",
        content_type="application/rss+xml",
        fetched_at=datetime.now(UTC),
        etag=etag,
    )


def test_ingest_source_stores_validators_then_skips_on_304():
    from src.ingest.pipeline import ingest_source

    s = SessionLocal()
    init_db()
    try:
        src = Source(name=f"F {uuid.uuid4().hex[:6]}", domain=f"f-{uuid.uuid4().hex[:6]}.example",
                     rss_url="https://feed.example/rss", language="en")
        s.add(src)
        s.commit()

        # Pass 1: no prior state -> no conditional header; server sends 200 + ETag.
        fetcher = _StubFetcher([_result(200, etag='"v1"')])
        tally1 = ingest_source(s, src, fetcher=fetcher)
        s.commit()
        assert fetcher.calls[0][1] is None  # no conditional headers on the first pass
        assert tally1["not_modified"] == 0
        state = s.get(FeedFetchState, src.id)
        assert state is not None and state.etag == '"v1"' and state.last_status == 200

        # Pass 2: stored ETag -> If-None-Match sent; server answers 304 -> skip.
        fetcher2 = _StubFetcher([_result(304, etag='"v1"')])
        tally2 = ingest_source(s, src, fetcher=fetcher2)
        s.commit()
        assert fetcher2.calls[0][1] == {"If-None-Match": '"v1"'}
        assert tally2["not_modified"] == 1
        assert tally2["entries"] == 0  # nothing parsed/ingested
    finally:
        s.close()
