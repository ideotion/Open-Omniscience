"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com

---

T4 — markets transport honesty (the 2026-06-12 Tor/indices diagnosis):
transport-aware verdicts ("refused over Tor" ≠ "robots disallows" ≠ "dead
series" ≠ "unreachable"), bounded feed-level retry for transient failures
only, and the retry-failed-feeds affordance (keys= filter).
"""

from __future__ import annotations

import pytest

from src.ingest import FetchFailed, RobotsDisallowed, RobotsUnavailable
from src.markets.csv_feeds import classify_fetch_failure, import_feed


class _StubFetcher:
    """Scripted fetcher: raises per call from a plan, then returns a CSV."""

    def __init__(self, plan):
        self.plan = list(plan)
        self.calls = 0

    def fetch(self, url, require_html=False):
        self.calls += 1
        step = self.plan.pop(0)
        if isinstance(step, Exception):
            raise step

        class R:
            content = "DATE,VALUE\n2026-01-02,10.5\n2026-01-03,11.0\n"
            final_url = url

        return R()


def test_classification_distinguishes_policy_dead_and_transient():
    cases = {
        RobotsDisallowed("disallowed by robots.txt"): ("robots-disallowed", False),
        RobotsUnavailable("robots.txt unavailable"): ("robots-unavailable", False),
        FetchFailed("HTTP 404 for https://x/series.csv"): ("dead-series", False),
        FetchFailed("HTTP 503 for https://x/series.csv"): ("http-error", True),
        ConnectionError("[Errno 111] Connection refused"): ("refused", True),
        FetchFailed("cannot resolve host 'x': gaierror"): ("unreachable", True),
        FetchFailed("network kill switch is active -- collection stopped"): ("offline", False),
    }
    for exc, (verdict, retryable) in cases.items():
        v, note, r = classify_fetch_failure(exc)
        assert v == verdict, f"{exc} -> {v}, expected {verdict}"
        assert r is retryable
        assert note  # every verdict carries its honest explanation


@pytest.fixture()
def db_session():
    from src.database.session import init_db, session_scope

    init_db()
    with session_scope() as s:
        yield s
        s.execute(
            __import__("sqlalchemy").text(
                "DELETE FROM commodity_prices WHERE symbol = 'T4TEST'"
            )
        )


def test_transient_refusal_is_retried_once_and_succeeds(db_session):
    fetcher = _StubFetcher([ConnectionError("Connection refused"), None])
    r = import_feed(
        db_session, url="https://feed.example/x.csv", symbol="T4TEST", fetcher=fetcher
    )
    assert r.status == "imported" and r.attempts == 2
    assert fetcher.calls == 2


def test_dead_series_is_never_retried(db_session):
    fetcher = _StubFetcher([FetchFailed("HTTP 404 for https://feed.example/x.csv")])
    r = import_feed(
        db_session, url="https://feed.example/x.csv", symbol="T4TEST", fetcher=fetcher
    )
    assert r.status == "fetch_failed"
    assert r.verdict == "dead-series" and r.retryable is False and r.attempts == 1
    assert fetcher.calls == 1, "a dead series must not be hammered"
    assert "replacement" in r.verdict_note


def test_robots_disallow_is_honored_not_retried(db_session):
    fetcher = _StubFetcher([RobotsDisallowed("robots.txt disallows /q/d/l")])
    r = import_feed(
        db_session, url="https://stooq.example/q.csv", symbol="T4TEST", fetcher=fetcher
    )
    assert r.verdict == "robots-disallowed" and fetcher.calls == 1
    assert "host's choice" in r.verdict_note


def test_import_all_reports_retryable_keys(monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.markets import feed_catalog
    from src.markets.feed_catalog import Feed

    feeds = [
        Feed(key="t4-ok", name="OK", symbol="T4OK", category="metals",
             url="https://f.example/ok.csv", currency="USD", unit="t", market="m"),
        Feed(key="t4-refused", name="Refused", symbol="T4REF", category="metals",
             url="https://f.example/r.csv", currency="USD", unit="t", market="m"),
        Feed(key="t4-dead", name="Dead", symbol="T4DEAD", category="metals",
             url="https://f.example/d.csv", currency="USD", unit="t", market="m"),
    ]
    monkeypatch.setattr(feed_catalog, "load_feeds", lambda path=None: feeds)


    def _fake_import_feed(session, *, url, symbol, fetcher, **kw):
        from src.markets.csv_feeds import FeedImportResult

        if symbol == "T4OK":
            return FeedImportResult(symbol, "imported", imported=3)
        if symbol == "T4REF":
            return FeedImportResult(
                symbol, "fetch_failed", verdict="refused", retryable=True,
                verdict_note="connection refused", attempts=2,
            )
        return FeedImportResult(
            symbol, "fetch_failed", verdict="dead-series", retryable=False,
            verdict_note="gone upstream", attempts=1,
        )

    monkeypatch.setattr("src.markets.csv_feeds.import_feed", _fake_import_feed)

    with TestClient(app) as client:
        body = client.post("/api/markets/feeds/import-all").json()
        assert body["retryable_failed_keys"] == ["t4-refused"]
        by_key = {r["key"]: r for r in body["results"]}
        assert by_key["t4-dead"]["verdict"] == "dead-series"
        assert by_key["t4-refused"]["retryable"] is True
        # keys= restricts the pass (the retry affordance)
        body2 = client.post("/api/markets/feeds/import-all?keys=t4-refused").json()
        assert body2["feeds"] == 1 and body2["results"][0]["key"] == "t4-refused"
