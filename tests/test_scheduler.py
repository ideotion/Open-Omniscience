"""
Tests for the scrape runner, the background scheduler, and its API.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The runner is tested against a faked HTTP layer (real ingest, no network). The
scheduler thread is driven with an injected run function and a long interval, so
the first immediate run is observed and the loop is then stopped -- no real
waiting, no network. The API is tested with the singleton's run function stubbed
so starting it can never reach the network.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source
from src.ingest import EthicalFetcher
from src.scheduler.runner import BackgroundScheduler, run_scrape_once
from src.scheduler.settings import SchedulerSettings


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

    def route(self, url, **kwargs):
        self._routes[url] = FakeResponse(url=url, **kwargs)

    def get(self, url, timeout=None, allow_redirects=True):
        if url in self._routes:
            return self._routes[url]
        return FakeResponse(status_code=404, text="not found", url=url)


def _article_html(title, body_sentence):
    body = (body_sentence + " ") * 30
    return (
        f"<html><head><title>{title}</title></head>"
        f"<body><article><h1>{title}</h1><p>{body}</p></article></body></html>"
    )


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    s = Sess()
    s.add(
        Source(
            name="Feed",
            domain="example.com",
            rss_url="https://example.com/feed.xml",
            enabled=True,
            status="qualified",
            priority=1,
            language="en",
        )
    )
    s.add(Source(name="NoFeed", domain="nofeed.test", enabled=True, status="qualified", priority=2))
    s.commit()
    yield s
    s.close()


def test_run_scrape_once_rss(db):
    sess = FakeSession()
    sess.route("https://example.com/robots.txt", status_code=404, text="")
    feed = """<?xml version="1.0"?><rss version="2.0"><channel><title>Ex</title>
      <item><title>One</title><link>https://example.com/1</link></item></channel></rss>"""
    sess.route("https://example.com/feed.xml", text=feed, content_type="application/rss+xml")
    sess.route("https://example.com/1", text=_article_html("One", "First story body."))

    result = run_scrape_once(
        db,
        EthicalFetcher(min_interval_s=0.0, session=sess),
        SchedulerSettings(mode="rss", max_sources_per_run=10),
    )
    assert result["mode"] == "rss"
    assert result["articles_stored"] == 1
    # Only the RSS source counts; the feedless source is skipped, not errored.
    assert result["sources_processed"] == 1
    assert db.query(Article).count() == 1


def test_run_scrape_once_crawl(db):
    sess = FakeSession()
    sess.route("https://example.com/robots.txt", status_code=404, text="")
    sess.route("https://example.com", text=_article_html("Home", "Homepage story body here."))
    sess.route("https://nofeed.test/robots.txt", status_code=404, text="")
    sess.route("https://nofeed.test", text=_article_html("NF", "Nofeed story body here."))

    result = run_scrape_once(
        db,
        EthicalFetcher(min_interval_s=0.0, session=sess),
        SchedulerSettings(
            mode="crawl", max_sources_per_run=10, crawl_max_depth=0, crawl_max_pages=5
        ),
    )
    assert result["mode"] == "crawl"
    assert result["pages_fetched"] >= 1
    assert result["sources_processed"] == 2


def test_scheduler_start_runs_then_stops():
    calls = {"n": 0}

    def fake_run():
        calls["n"] += 1
        return {"ok": True, "run": calls["n"]}

    sched = BackgroundScheduler(
        run_once_fn=fake_run,
        # Long interval: only the immediate first run happens before we stop.
        settings_provider=lambda: SchedulerSettings(interval_minutes=60),
    )
    try:
        assert sched.start() is True
        assert sched.start() is False  # already running

        deadline = time.time() + 5
        while calls["n"] < 1 and time.time() < deadline:
            time.sleep(0.02)
        assert calls["n"] >= 1

        st = sched.status()
        assert st["running"] is True
        assert st["last_result"]["ok"] is True
    finally:
        assert sched.stop() is True
    assert sched.is_running() is False


def test_scheduler_run_now_triggers_run():
    calls = {"n": 0}
    sched = BackgroundScheduler(
        run_once_fn=lambda: (calls.__setitem__("n", calls["n"] + 1), {"ok": True})[1],
        settings_provider=lambda: SchedulerSettings(interval_minutes=60),
    )
    # Not started: run_now should still execute one off-thread run.
    assert sched.run_now() is True
    deadline = time.time() + 5
    while calls["n"] < 1 and time.time() < deadline:
        time.sleep(0.02)
    assert calls["n"] >= 1


def test_scheduler_api(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    # Stub the singleton's run function so an API-driven start never hits the network.
    from src.scheduler.runner import get_scheduler

    get_scheduler()._run_once_fn = lambda: {"ok": True, "stub": True}

    from src.api.main import app

    with TestClient(app) as client:
        assert client.get("/api/scheduler/status").json()["running"] in (True, False)

        # Config validation.
        good = client.put("/api/scheduler/config", json={"interval_minutes": 5, "mode": "crawl"})
        assert good.status_code == 200
        assert good.json()["mode"] == "crawl"
        bad = client.put("/api/scheduler/config", json={"mode": "telepathy"})
        assert bad.status_code == 400
        bad2 = client.put("/api/scheduler/config", json={"interval_minutes": 0})
        assert bad2.status_code == 400

        try:
            started = client.post("/api/scheduler/start").json()
            assert started["started"] is True
            assert started["running"] is True
        finally:
            stopped = client.post("/api/scheduler/stop").json()
            assert stopped["running"] is False
