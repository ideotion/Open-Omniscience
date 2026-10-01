"""A pooled checkout names the ROUTE it was taken for, and an invalidation names its holder.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Rank 12 of the 2026-09-30 field diagnostics: every instance showed one "AnyIO worker thread"
checkout for the whole process life, and nothing could say whose. Driven by hand on the real app
(a fresh plaintext store, the first-burst endpoints in Chromium) it appears two seconds after
load and names itself once the route is recorded: ``GET /api/articles`` ->
``insights._data_version``, the pinned probe connection that ``/status``'s cache key needs
(``PRAGMA data_version`` only reports other connections' commits on a long-lived connection).
A thread-pool worker's own name says nothing; its route does. The route comes from a ContextVar
the request middleware sets before calling the endpoint -- Starlette starts the endpoint's task
after that, and anyio copies the context into the worker thread -- so these tests pin the
PROPAGATION, the one property the whole instrument depends on.
"""

from __future__ import annotations

import logging
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event

from src.database import pool_watch
from tests.js_source_helper import python_function_source


@pytest.fixture()
def eng(tmp_path):
    e = create_engine(f"sqlite:///{tmp_path / 'pwe.db'}", future=True)

    @event.listens_for(e, "connect")
    def _p(dbapi, _rec):
        cur = dbapi.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    assert pool_watch.register(e) is True
    pool_watch._reset_for_tests()
    yield e
    e.dispose()


def test_a_checkout_outside_any_request_has_no_endpoint(eng):
    c = eng.connect()
    try:
        (row,) = pool_watch.checked_out()
        assert row["endpoint"] is None
    finally:
        c.close()


def test_the_endpoint_set_before_a_checkout_is_recorded_and_reset_after(eng):
    token = pool_watch.set_endpoint("GET /api/things")
    try:
        c = eng.connect()
        try:
            (row,) = pool_watch.checked_out()
            assert row["endpoint"] == "GET /api/things"
        finally:
            c.close()
    finally:
        pool_watch.reset_endpoint(token)
    c = eng.connect()
    try:
        (row,) = pool_watch.checked_out()
        assert row["endpoint"] is None, "the route must not outlive its request"
    finally:
        c.close()


def test_the_route_reaches_a_thread_pool_worker_through_the_real_middleware_shape(eng):
    """The premise, end to end: a middleware sets the route, a SYNC endpoint (run by anyio in
    a worker thread) checks a connection out, and the listing names that route."""
    app = FastAPI()
    seen: dict = {}

    @app.middleware("http")
    async def _name_the_route(request, call_next):
        token = pool_watch.set_endpoint(f"{request.method} {request.url.path}")
        try:
            return await call_next(request)
        finally:
            pool_watch.reset_endpoint(token)

    @app.get("/api/probe")
    def probe():  # plain def: anyio runs it in a worker thread
        c = eng.connect()
        try:
            seen["rows"] = pool_watch.checked_out()
            seen["thread"] = threading.current_thread().name
        finally:
            c.close()
        return {"ok": True}

    with TestClient(app) as client:
        assert client.get("/api/probe").status_code == 200
    (row,) = seen["rows"]
    assert row["endpoint"] == "GET /api/probe"
    assert seen["thread"] != threading.main_thread().name
    assert pool_watch.checked_out() == []


def test_the_real_app_middleware_sets_and_resets_the_route_around_the_endpoint():
    """Wiring ratchet on the real ``monitor_requests``: the set precedes ``call_next`` and the
    reset sits in a ``finally`` around it, so neither an exception nor a slow response can leave
    a stale route on the context."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "src" / "api" / "main.py").read_text(
        encoding="utf-8"
    )
    body = python_function_source(src, "monitor_requests")
    i_set = body.find("_pool_watch.set_endpoint(")
    i_call = body.find("await call_next(request)")
    i_reset = body.find("_pool_watch.reset_endpoint(")
    assert -1 < i_set < i_call < i_reset, (i_set, i_call, i_reset)
    assert "finally:" in body[i_call:i_reset]


def test_the_stack_at_checkout_is_off_by_default_and_recorded_when_asked(eng, monkeypatch):
    monkeypatch.delenv("OO_POOL_WATCH_STACKS", raising=False)
    c = eng.connect()
    try:
        (row,) = pool_watch.checked_out()
        assert "stack_at_checkout" not in row, "hot path: no stack unless asked"
    finally:
        c.close()
    monkeypatch.setenv("OO_POOL_WATCH_STACKS", "1")
    c = eng.connect()
    try:
        (row,) = pool_watch.checked_out()
        assert any("test_the_stack_at_checkout" in line for line in row["stack_at_checkout"])
    finally:
        c.close()


def test_an_invalidation_is_logged_with_its_holder_and_the_drivers_own_message(eng, caplog):
    token = pool_watch.set_endpoint("GET /api/invalidating")
    try:
        c = eng.connect()
        c.exec_driver_sql("SELECT 1")
        with caplog.at_level(logging.WARNING, logger="src.database.pool_watch"):
            c.invalidate(RuntimeError("disk I/O error"))
        c.close()
    finally:
        pool_watch.reset_endpoint(token)
    inv = pool_watch.invalidations()
    assert inv["total"] == 1
    (rec,) = inv["recent"]
    assert rec["held_by"]["thread"] == threading.current_thread().name
    assert rec["held_by"]["endpoint"] == "GET /api/invalidating"
    assert rec["exception"] == "RuntimeError" and rec["message"] == "disk I/O error"
    assert any("invalidated" in r.getMessage() and "GET /api/invalidating" in r.getMessage()
               for r in caplog.records)


def test_an_invalidation_keeps_the_dbapi_message_never_the_statement_or_parameters(eng):
    c = eng.connect()
    try:
        with pytest.raises(Exception):  # noqa: B017 - any DBAPI error will do
            c.exec_driver_sql("INSERT INTO no_such_table(secret) VALUES (?)", ("hunter2",))
    finally:
        c.close()
    # a failed statement is not an invalidation; force one carrying the wrapped error text
    c = eng.connect()
    wrapped = None
    try:
        try:
            c.exec_driver_sql("INSERT INTO no_such_table(secret) VALUES (?)", ("hunter2",))
        except Exception as exc:  # noqa: BLE001
            wrapped = exc
        c.invalidate(wrapped)
    finally:
        c.close()
    (rec,) = pool_watch.invalidations()["recent"]
    assert "hunter2" not in (rec["message"] or "")
    assert "INSERT" not in (rec["message"] or "")


def test_the_invalidation_ring_is_bounded(eng):
    for _ in range(25):
        c = eng.connect()
        c.exec_driver_sql("SELECT 1")
        c.invalidate(RuntimeError("x"))
        c.close()
    inv = pool_watch.invalidations()
    assert inv["total"] == 25 and len(inv["recent"]) == 20
