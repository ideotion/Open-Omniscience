"""
A retained slow request says how much of its time came BEFORE its endpoint was reached.

2026-10-16 field bundles: ``GET /api/scheduler/status`` costs 0.65 ms in its handler yet had a 67 ms p50 and a 1.1 s p95, and the
record could not say whether that time was spent on the event loop before the handler or after it was handed on. The middleware
now stamps the moment it first sees a request and an application-level dependency stamps the moment routing handed it to its
endpoint; the difference rides on a route's first and slowest call as ``before_dispatch_ms``.

The refusals are the point: an unstamped request is ``None`` (never ``0``, which would read as "reached the handler at once"), a
stamp out of order is ``None``, and what remains of ``ms`` is NOT split further (that is the thread wait and the handler together).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest
from fastapi import (
    WebSocket,  # module level: with deferred annotations FastAPI resolves the handler's annotation from here
)

from src.monitoring import latency


@pytest.fixture(autouse=True)
def _reset():
    latency._reset_for_tests()
    yield
    latency._reset_for_tests()


def _row(route: str) -> dict:
    return {r["route"]: r for r in latency.summary()["routes"]}[route]


def test_the_split_is_the_time_between_the_two_stamps():
    scope = {latency._RECEIVED_KEY: 10.0, latency._DISPATCHED_KEY: 10.25}
    assert latency.before_dispatch_ms(scope) == 250.0


@pytest.mark.parametrize("scope", [
    {},
    {latency._RECEIVED_KEY: 10.0},
    {latency._DISPATCHED_KEY: 10.0},
    {latency._RECEIVED_KEY: 10.5, latency._DISPATCHED_KEY: 10.0},
    {latency._RECEIVED_KEY: "x", latency._DISPATCHED_KEY: 10.0},
    None,
])
def test_an_unstamped_or_misordered_request_is_unknown_never_zero(scope):
    assert latency.before_dispatch_ms(scope) is None


def test_the_split_rides_the_slowest_call():
    scope = {latency._RECEIVED_KEY: 5.0, latency._DISPATCHED_KEY: 5.5}
    latency.note_start(1, "GET /api/x", scope=scope, method="GET")
    latency.record(1, "GET /api/x", 200, 900.0)
    row = _row("GET /api/x")
    assert row["slowest"]["before_dispatch_ms"] == 500.0
    latency.record(2, "GET /api/x", 200, 1.0)  # faster and not in flight: the slowest call keeps its split
    assert _row("GET /api/x")["slowest"]["before_dispatch_ms"] == 500.0
    latency.record(3, "GET /api/x", 200, 2000.0)  # slower but never stamped: unknown, not carried over from the earlier call
    assert _row("GET /api/x")["slowest"]["before_dispatch_ms"] is None


def test_a_call_that_was_never_stamped_says_none():
    latency.record(7, "GET /api/y", 200, 40.0)
    assert _row("GET /api/y")["slowest"]["before_dispatch_ms"] is None


def test_the_stall_note_can_read_the_split_of_the_request_being_recorded(monkeypatch):
    seen: list = []
    monkeypatch.setattr(latency, "_note_stall", lambda route, status, ms: seen.append(latency.current_split()))
    scope = {latency._RECEIVED_KEY: 1.0, latency._DISPATCHED_KEY: 1.75}
    latency.note_start(3, "GET /api/z", scope=scope, method="GET")
    latency.record(3, "GET /api/z", 200, 9000.0)
    assert seen == [750.0]
    assert latency.current_split() is None, "the split must not outlive the record call that set it"


def test_a_real_request_through_the_app_is_stamped_by_both_layers():
    from fastapi.testclient import TestClient

    from src.api.main import app

    client = TestClient(app)
    resp = client.get("/api/scheduler/status")
    assert resp.status_code == 200
    got = _row("GET /api/scheduler/status")["slowest"]["before_dispatch_ms"]
    assert isinstance(got, float) and got >= 0.0, (
        "the middleware's scope and the endpoint's must be the same dict, or the dependency's stamp never reaches the record"
    )


def test_a_split_longer_than_the_request_is_unknown_not_a_guess():
    # ``ms`` is wall time and the stamps are monotonic: after a clock step they can disagree.
    scope = {latency._RECEIVED_KEY: 1.0, latency._DISPATCHED_KEY: 9.0}
    latency.note_start(5, "GET /api/w", scope=scope, method="GET")
    latency.record(5, "GET /api/w", 200, 100.0)
    assert _row("GET /api/w")["slowest"]["before_dispatch_ms"] is None


def test_the_dependency_does_not_break_a_websocket_route():
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from src.api.main import _note_dispatch

    toy = FastAPI(dependencies=[Depends(_note_dispatch)])

    @toy.websocket("/ws")
    async def ws(socket: WebSocket):
        await socket.accept()
        await socket.send_text("ok")
        await socket.close()

    with TestClient(toy).websocket_connect("/ws") as conn:
        assert conn.receive_text() == "ok"
