"""A pool timeout on a worker's FIRST checkout is recorded against that source and must not end the pass.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The worker's first pooled checkout is the read of its own copy of the ``Source`` row (``run_scrape_once._worker``), made BEFORE
``_process_source`` and so outside its handler. With the pool exhausted that read times out (30 s), the exception comes out of
``fut.result()`` and the whole pass ends with the remaining sources unscraped, against the loop's own rule that one bad source
must not abort the batch. The benchmark lane's governor run (2026-10-17) died this way once the handler path was closed
(see ``test_process_source_failure_handler.py``); the field's 12 to 24 of the last 30 collector runs ending in a pool timeout fit it.

The fault is injected at the pool, for ONE source's first checkout from inside ``_worker``; every other checkout passes through.
The source is left for the next pass (the deferral list the wind-down already keeps), nothing retries within the pass, and the
other sources carry on. ``test_run_error_counts.py`` keeps its own case: a ``TimeoutError`` that really does come out of
``_process_source`` still ends the pass and is recorded with the pass counts.
"""

from __future__ import annotations

import logging
import sys
import threading
import uuid

import pytest
from sqlalchemy.exc import TimeoutError as PoolTimeout

from src.database.models import Source
from src.ingest import EthicalFetcher
from src.scheduler import runner
from src.scheduler.settings import SchedulerSettings

from .test_process_source_failure_handler import _EmptyFeedSession  # the same canned feed session


def _seed(n: int) -> tuple[str, int]:
    """``n`` qualified feed sources under a tag of their own; returns (tag, the id of the first)."""
    from src.database.session import init_db, session_scope

    init_db()
    word = "fck" + uuid.uuid4().hex[:6]
    with session_scope() as s:
        for i in range(n):
            s.add(Source(
                name=f"F{i}", domain=f"{word}-{i}.example", rss_url=f"https://{word}-{i}.example/feed.xml",
                enabled=True, status="qualified", language="en", tags=word,
            ))
    with session_scope() as s:
        first = s.query(Source).filter(Source.domain == f"{word}-0.example").one().id
    return word, first


@pytest.fixture
def first_checkout_times_out(monkeypatch):
    """The first pooled checkout made from ``_worker`` for ``target['id']`` raises the pool's timeout; the ingest stub stores one
    article per source that gets past it."""
    from src.database.session import engine

    runner._consume_deferred()  # nothing carried over from another test
    target: dict = {"id": None}
    seen = {"timed_out": 0, "stored": 0}
    lock = threading.Lock()
    real_connect = engine.pool.connect

    def connect(*a, **kw):
        frame = sys._getframe(1)
        while frame is not None:
            if frame.f_code.co_name == "_worker":
                if frame.f_locals.get("source_id") == target["id"]:
                    with lock:
                        seen["timed_out"] += 1
                    raise PoolTimeout("QueuePool limit reached for the collector; connection timed out, timeout 30.00")
                break
            frame = frame.f_back
        return real_connect(*a, **kw)

    def ingest(session, source, *, fetcher=None, **kw):
        with lock:
            seen["stored"] += 1
        return {"stored": 1}

    monkeypatch.setattr(engine.pool, "connect", connect)
    monkeypatch.setattr("src.ingest.pipeline.ingest_source", ingest)
    yield target, seen
    runner._consume_deferred()


def _pass(tag: str, parallelism: int) -> dict:
    from src.database.session import SessionLocal

    fetcher = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=_EmptyFeedSession())  # type: ignore[arg-type]
    settings = SchedulerSettings(collect_parallelism=parallelism, select_tags=[tag])
    sel = SessionLocal()
    try:
        return runner.run_scrape_once(sel, fetcher, settings)
    finally:
        sel.close()


@pytest.mark.parametrize("parallelism", [2, 4])  # parallelism 1 is the sequential loop: it has no worker, and no first checkout of its own
def test_a_pool_timeout_on_a_sources_first_checkout_leaves_that_source_for_the_next_pass(first_checkout_times_out, parallelism):
    target, seen = first_checkout_times_out
    tag, first = _seed(5)
    target["id"] = first
    # Our own handler, not caplog: init_db's alembic fileConfig (run by _seed) removes root handlers and disables existing loggers.
    messages: list[str] = []

    class _Keep(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    log = logging.getLogger("src.scheduler.runner")
    log.disabled = False
    handler = _Keep(level=logging.WARNING)
    log.addHandler(handler)
    try:
        result = _pass(tag, parallelism)  # red without the fix: raises sqlalchemy.exc.TimeoutError out of run_scrape_once
    finally:
        log.removeHandler(handler)
    assert seen["timed_out"] == 1, "the failing checkout happened once and nothing retried it within the pass"
    assert seen["stored"] == 4, "the other four sources carried on"
    assert result["sources_processed"] == 4 and result["articles_stored"] == 4
    assert result["tally"].get("errors") == 1, "the source is counted as an error, not lost"
    assert result["deferred_next_pass"] == 1 and result["pool_timeout_deferred"] == 1
    assert "recycled" not in result, "the pass did not wind down: it kept taking sources, so no wind-down reason is reported"
    assert runner.deferred_carryover_count() == 1, "it keeps its run-first claim on the next pass"
    assert any(f"source id {first}" in m for m in messages), "the log line names the source"
