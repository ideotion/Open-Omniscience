"""A source whose ingest failed must not take the pass down when its failure is being LOGGED.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Found by the benchmark lane (2026-10-17, governor run G0): a collect pass died with an uncaught pool ``TimeoutError`` raised at
``runner._process_source``'s ``except`` clause. After a failed article the worker's session has rolled back, so every attribute of
the ``Source`` row is expired; the handler's log line read ``source.domain``, which makes SQLAlchemy reload the row, which needs a
pooled connection; at saturation that checkout timed out too (30 s), INSIDE the handler, so nothing caught it. It left
``_process_source``, came out of ``fut.result()`` in ``run_scrape_once`` and ended the whole pass, against the handler's own comment
("one bad source must not abort the batch"). It matches the field figure of 12 to 24 of the last 30 collector runs ending in a pool
timeout on 7 of 8 instances.

The fault is injected where it happens: a source's ingest rolls the session back and raises, and ANY pooled checkout made from inside
``_process_source`` after that raises the pool's timeout. The checkout the worker makes BEFORE ``_process_source`` is left alone, so
the test measures the handler and not the pool.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy.exc import TimeoutError as PoolTimeout

from src.database.models import Source
from src.ingest import EthicalFetcher
from src.scheduler import runner
from src.scheduler.settings import SchedulerSettings

_EMPTY_RSS = '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title></channel></rss>'


class _Resp:
    def __init__(self, text="", ct="text/html", url=None, status=200):
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": ct}
        self.url = url

    def close(self):
        pass


class _EmptyFeedSession:
    def __init__(self):
        self.headers: dict = {}
        self.proxies: dict = {}

    def get(self, url, timeout=None, allow_redirects=True, headers=None, proxies=None, stream=None, **kw):
        if url.endswith("/robots.txt"):
            return _Resp(text="User-agent: *\nAllow: /", ct="text/plain", url=url)
        return _Resp(text=_EMPTY_RSS, ct="application/rss+xml", url=url)


def _seed(n: int) -> tuple[str, str]:
    """``n`` qualified feed sources under a tag of their own; returns (tag, the domain of the first)."""
    from src.database.session import init_db, session_scope

    init_db()
    word = "hnd" + uuid.uuid4().hex[:6]
    with session_scope() as s:
        for i in range(n):
            s.add(Source(
                name=f"H{i}", domain=f"{word}-{i}.example", rss_url=f"https://{word}-{i}.example/feed.xml",
                enabled=True, status="qualified", language="en", tags=word,
            ))
    return word, f"{word}-0.example"


@pytest.fixture
def faulty_ingest(monkeypatch):
    """The ingest of ONE source (the first of the tag) rolls its session back and raises; every other source stores one article.

    While the failing source's handler runs, a pooled checkout made from a frame named ``_process_source`` raises the pool's
    timeout. The flag is per thread and is reset at the start of every source's ingest, so no other source sees it.
    """
    import sys

    from src.database.session import engine

    local = threading.local()
    real_connect = engine.pool.connect
    seen = {"failed": [], "stored": 0, "handler_checkouts": 0}

    def connect(*a, **kw):
        if getattr(local, "armed", False):
            frame = sys._getframe(1)
            while frame is not None:
                if frame.f_code.co_name == "_process_source":
                    seen["handler_checkouts"] += 1
                    raise PoolTimeout("QueuePool limit reached for the collector; connection timed out, timeout 30.00")
                frame = frame.f_back
        return real_connect(*a, **kw)

    def ingest(session, source, *, fetcher=None, **kw):
        local.armed = False
        if source.domain.endswith("-0.example"):
            seen["failed"].append(source.domain)
            session.rollback()  # what a failed flush does to the worker's session: every attribute of the row is now expired
            local.armed = True
            raise RuntimeError("the article failed")
        seen["stored"] += 1
        return {"stored": 1}

    monkeypatch.setattr(engine.pool, "connect", connect)
    monkeypatch.setattr("src.ingest.pipeline.ingest_source", ingest)
    return seen


def _pass(tag: str, parallelism: int):
    from src.database.session import SessionLocal

    fetcher = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=_EmptyFeedSession())  # type: ignore[arg-type]
    settings = SchedulerSettings(collect_parallelism=parallelism, select_tags=[tag])
    sel = SessionLocal()
    try:
        return runner.run_scrape_once(sel, fetcher, settings)
    finally:
        sel.close()


@pytest.mark.parametrize("parallelism", [1, 4])
def test_a_pool_timeout_while_the_failure_is_logged_does_not_end_the_pass(faulty_ingest, parallelism):
    tag, _first = _seed(5)
    result = _pass(tag, parallelism)  # red without the fix: raises sqlalchemy.exc.TimeoutError out of the handler
    assert len(faulty_ingest["failed"]) == 1
    assert faulty_ingest["stored"] == 4, "the other four sources carried on"
    assert result.get("sources_processed") == 4, "the failed source is not counted as processed"
    assert result.get("articles_stored") == 4
    assert faulty_ingest["handler_checkouts"] == 0, "the handler asked the pool for nothing: it logs from what it already had"


def test_the_failure_is_still_logged_by_domain(faulty_ingest, caplog):
    import logging

    tag, first = _seed(3)
    with caplog.at_level(logging.WARNING):
        _pass(tag, 1)
    assert any(first in r.getMessage() for r in caplog.records), "the log line names the source that failed"


@pytest.fixture
def faulty_loop_read(monkeypatch):
    """The sequential loop's own read of the NEXT source's label: the first source's ingest rolls the shared caller session back
    (every Source object it holds is now expired) and the next pooled checkout made from ``run_scrape_once`` itself, outside
    ``_process_source``, raises the pool's timeout once. Every other checkout passes through."""
    import sys

    from src.database.session import engine

    state = {"armed": False, "timeouts": 0, "failed": [], "stored": 0}
    real_connect = engine.pool.connect

    def connect(*a, **kw):
        if state["armed"]:
            names = []
            frame = sys._getframe(1)
            while frame is not None:
                names.append(frame.f_code.co_name)
                frame = frame.f_back
            if "run_scrape_once" in names and "_process_source" not in names:
                state["armed"] = False
                state["timeouts"] += 1
                raise PoolTimeout("QueuePool limit reached for the collector; connection timed out, timeout 30.00")
        return real_connect(*a, **kw)

    def ingest(session, source, *, fetcher=None, **kw):
        if not state["failed"]:  # the FIRST source of the pass, whichever the selection puts first: another one always follows it
            state["failed"].append(source.domain)
            session.rollback()  # expires every Source object the caller's session holds
            state["armed"] = True
            raise RuntimeError("the article failed")
        state["stored"] += 1
        return {"stored": 1}

    monkeypatch.setattr(engine.pool, "connect", connect)
    monkeypatch.setattr("src.ingest.pipeline.ingest_source", ingest)
    return state


def test_a_pool_timeout_reading_the_next_sources_label_does_not_end_the_sequential_pass(faulty_loop_read):
    """The sequential loop shares the caller's session between sources. When one source fails inside ingest the rollback expires
    all the others, and the loop's progress line read ``source.domain`` OUTSIDE any try: the same reload through the pool that
    ``_process_source``'s handler had, one line earlier in the loop, and the same way for one source to end the whole pass."""
    tag, _first = _seed(4)
    result = _pass(tag, 1)  # red without the fix: raises sqlalchemy.exc.TimeoutError out of run_scrape_once
    assert faulty_loop_read["timeouts"] == 1 and len(faulty_loop_read["failed"]) == 1
    assert faulty_loop_read["stored"] == 3, "the other three sources carried on"
    assert result["sources_processed"] == 3 and result["articles_stored"] == 3
