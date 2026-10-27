"""A retry that meets a long ``Crawl-delay`` follows a request that WAS made (R293 read, finding 2).

``EthicalFetcher._fetch_locked`` runs the per-host pacing check at the top of EVERY attempt. A host that
declares a ``Crawl-delay`` above ``OO_CRAWL_DELAY_MAX_WAIT`` (180 s) therefore deferred the RETRY of a request
that had already gone out and failed (a 5xx, a 429, a timeout): the caller saw a ``CrawlDelayDeferred`` with one
real failed request behind it, counted it as "nothing failed" (the collector's own bucket, the law tracker's
restored check time), and the failure got no back-off. Measured before the fix with a real fetcher and a stub
session, Crawl-delay 600: one request made, ``CrawlDelayDeferred`` raised, and the law document left unstamped.

What stays: a deferral on the FIRST attempt is still a deferral (no request was made, S04-13 S2, Q1013 = a), and a
short Crawl-delay still retries.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.robotparser import RobotFileParser

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument
from src.ingest import (
    CrawlDelayDeferred,
    EthicalFetcher,
    FetchFailed,
    clear_kill_switch,
)
from src.law.track import track_document

_HOST = "https://slow.example"


class _Resp:
    def __init__(self, code: int):
        self.status_code = code
        self.headers = {"Content-Type": "text/html"}

    def close(self) -> None:
        pass


class _Session:
    headers: dict = {}


def _fetcher(tmp_path: Path, *, delay: int, answer):
    """A real ``EthicalFetcher`` whose only stub is the HTTP call: ``answer()`` returns a status code or raises."""
    f = EthicalFetcher(robots_cache_path=tmp_path / "robots_cache.json", retry_backoff_s=0, session=_Session())
    rp = RobotFileParser()
    rp.parse(["User-agent: *", f"Crawl-delay: {delay}"])
    f._robots[_HOST] = (rp, f._now() + 9999)
    f._sleep = lambda s: None
    calls: list[str] = []

    def http_get(url, extra_headers=None, proxies=None):
        calls.append(url)
        return _Resp(answer()), url

    f._http_get = http_get
    return f, calls


@pytest.fixture(autouse=True)
def _switch_clear(monkeypatch):
    monkeypatch.delenv("OO_CRAWL_DELAY_MAX_WAIT", raising=False)  # the 600 s delay must be over the cap
    clear_kill_switch()
    yield
    clear_kill_switch()


def test_a_503_on_a_long_crawl_delay_host_is_the_failure_not_a_deferral(tmp_path):
    f, calls = _fetcher(tmp_path, delay=600, answer=lambda: 503)
    with pytest.raises(FetchFailed) as exc:
        f.fetch(f"{_HOST}/act1", require_html=False)
    assert not isinstance(exc.value, CrawlDelayDeferred)
    assert "HTTP 503" in str(exc.value)
    assert len(calls) == 1, "one request went out and failed; the retry was held back by the host's own delay"


def test_a_network_error_on_a_long_crawl_delay_host_is_the_failure_not_a_deferral(tmp_path):
    def boom():
        raise requests.ConnectionError("connection reset")

    f, calls = _fetcher(tmp_path, delay=600, answer=boom)
    with pytest.raises(FetchFailed) as exc:
        f.fetch(f"{_HOST}/act1", require_html=False)
    assert not isinstance(exc.value, CrawlDelayDeferred)
    assert "request error" in str(exc.value)
    assert len(calls) == 1


def test_a_deferral_on_the_first_attempt_is_still_a_deferral_with_no_request(tmp_path):
    """The negative-space twin: the host was just contacted, so the NEXT fetch defers before any request."""
    f, calls = _fetcher(tmp_path, delay=600, answer=lambda: 404)
    with pytest.raises(FetchFailed):
        f.fetch(f"{_HOST}/act1", require_html=False)  # first touch is free; a 404 is not retried
    assert len(calls) == 1
    with pytest.raises(CrawlDelayDeferred):
        f.fetch(f"{_HOST}/act2", require_html=False)
    assert len(calls) == 1, "a deferral made no request"


def test_a_short_crawl_delay_still_retries_a_503(tmp_path):
    f, calls = _fetcher(tmp_path, delay=2, answer=lambda: 503)
    with pytest.raises(FetchFailed) as exc:
        f.fetch(f"{_HOST}/act1", require_html=False)
    assert "HTTP 503" in str(exc.value)
    assert len(calls) == f.max_retries + 1


def test_the_law_tracker_stamps_a_failed_request_on_a_long_crawl_delay_host(tmp_path):
    """The consequence that mattered (R293): the failed request is a real check, so the document is backed off."""
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    doc = LawDocument(
        jurisdiction="uk", title="Act", url=f"{_HOST}/act1", watched=True, last_status="unchanged",
        last_checked_at=datetime.now(UTC) - timedelta(days=3),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    before = doc.last_checked_at
    f, calls = _fetcher(tmp_path, delay=600, answer=lambda: 503)
    out = track_document(db, f, doc)
    db.refresh(doc)
    assert len(calls) == 1
    assert out["status"] == "error", "one real request failed: an error, not a deferral"
    assert doc.last_checked_at > before
