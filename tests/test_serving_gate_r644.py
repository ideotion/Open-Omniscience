"""R644: the app refuses every request with a fixed 503 until its lifespan's loop check (R642) ran and airplane mode's guard is armed.

``uvicorn --lifespan off`` and this app mounted inside another ASGI app skip the lifespan, so they skip the loop check and the guard it
arms. These tests run both for real (a uvicorn server on loopback, a Starlette mount); since R646 ``OO_NO_SCHEDULER=1``, which the
suite sets, waives nothing, so the gate is live under it. No network: the only sockets are loopback.
"""

from __future__ import annotations

import ast
import http.client
import inspect
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Mount

import src.api.main as main
import src.ingest.airplane as ap

ROOT = Path(__file__).resolve().parent.parent

_needs_uvloop = pytest.mark.skipif(
    not (sys.platform not in ("win32", "cygwin") and sys.implementation.name == "cpython"),
    reason="uvloop is installed only on CPython off Windows",
)


@pytest.fixture
def gate(monkeypatch):
    """The gate as a fresh process sees it: closed, no loop check recorded. ``OO_NO_SCHEDULER`` keeps the suite's ``1`` (R646)."""
    monkeypatch.setattr(main, "_serving_loop_checked", False)
    monkeypatch.setattr(main, "_serving_gate_logged", False)
    monkeypatch.delenv("OO_AIRPLANE_SOCKET_GUARD", raising=False)
    return monkeypatch


def _assert_refused(status: int, body: object) -> None:
    assert status == 503
    assert body == {"detail": main.SERVING_GATE_REFUSAL}


def test_a_request_without_the_lifespan_is_refused_in_fixed_words(gate):
    """TestClient without ``with`` runs no lifespan, exactly as ``--lifespan off``."""
    r = TestClient(main.app).get("/unlock")
    _assert_refused(r.status_code, r.json())


def _serve_once(loop: str) -> tuple[int, object]:
    """A real uvicorn server with ``lifespan="off"`` on loopback, one GET /unlock, then stopped."""
    import uvicorn

    config = uvicorn.Config(main.app, host="127.0.0.1", port=0, lifespan="off", loop=loop, log_level="error", ws="none")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    try:
        deadline = time.monotonic() + 20
        while not (server.started and server.servers) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started, "the loopback server did not start"
        port = server.servers[0].sockets[0].getsockname()[1]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.request("GET", "/unlock")
            resp = conn.getresponse()
            body = resp.read()
            return resp.status, json.loads(body) if resp.status == 503 else body
        finally:
            conn.close()
    finally:
        server.should_exit = True
        t.join(timeout=20)


def test_the_real_uvicorn_lifespan_off_server_is_refused(gate):
    _assert_refused(*_serve_once("asyncio"))


@_needs_uvloop
def test_a_second_server_on_uvloop_cannot_ride_on_an_earlier_check(gate):
    """A lifespan that passed the check somewhere in the process does not vouch for a server started on uvloop with --lifespan off
    after it (security read A): the loop serving the request is checked too."""
    import uvloop  # noqa: F401 - core installs it here (uvicorn[standard])

    gate.setattr(main, "_serving_loop_checked", True)
    gate.setattr(ap, "is_armed", lambda: True)
    _assert_refused(*_serve_once("uvloop"))


@_needs_uvloop
def test_an_open_gate_still_refuses_a_second_server_on_uvloop(gate):
    """Once the gate has opened for a server on the stdlib loop, a second server started on uvloop with --lifespan off in the same
    process is still refused: the loop is checked on every request, never latched (security read B)."""
    import uvloop  # noqa: F401 - core installs it here (uvicorn[standard])

    gate.setattr(main, "_serving_loop_checked", True)
    gate.setattr(ap, "is_armed", lambda: True)
    assert TestClient(main.app).get("/unlock").status_code == 200
    _assert_refused(*_serve_once("uvloop"))


def test_a_closed_gate_logs_its_refusal_once(gate, caplog):
    client = TestClient(main.app)
    with caplog.at_level("ERROR", logger=main.logger.name):
        for _ in range(3):
            assert client.get("/unlock").status_code == 503
    assert [r.getMessage() for r in caplog.records].count(main.SERVING_GATE_REFUSAL) == 1


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_own_launcher_on_a_fresh_locked_store_serves_the_unlock_page(tmp_path):
    """Behavioural: ``python -m src.api.main`` with OO_NO_SCHEDULER and OO_DB_PLAINTEXT unset boots a fresh store LOCKED, before
    ``run_deferred_startup`` ever runs, so only the lifespan can have armed the guard. The unlock page must be served, never the gate's
    503. Loopback only: the boot makes zero network calls."""
    port = _free_port()
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "OO_DATA_DIR": str(tmp_path / "data"),
        "OO_HOST": "127.0.0.1",
        "OO_PORT": str(port),
        "OO_AUTOSEED": "0",
        "OO_LLM_AUTOSTART": "0",
        "PYTHONPATH": str(ROOT),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "src.api.main"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    try:
        status, body = None, b""
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.request("GET", "/unlock")
                resp = conn.getresponse()
                status, body = resp.status, resp.read()
                conn.close()
                break
            except OSError:
                time.sleep(0.25)
        assert status == 200, f"/unlock answered {status}: {body[:300]!r}"
    finally:
        proc.terminate()
        try:
            out, _ = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
    assert main.SERVING_GATE_REFUSAL.encode() not in out


def test_a_mounted_app_is_refused(gate):
    """Starlette runs the PARENT's lifespan, never a mount's: the app's own loop check never runs."""
    parent = Starlette(routes=[Mount("/oo", app=main.app)])
    with TestClient(parent) as client:
        r = client.get("/oo/unlock")
    _assert_refused(r.status_code, r.json())


def test_the_loop_check_alone_is_not_enough_without_the_armed_guard(gate):
    gate.setattr(main, "_serving_loop_checked", True)
    gate.setattr(ap, "is_armed", lambda: False)
    r = TestClient(main.app).get("/unlock")
    _assert_refused(r.status_code, r.json())


def test_the_gate_reads_both_facts_on_every_request(gate):
    """R649: nothing latches. A guard that is no longer armed closes an open gate again on the next request."""
    gate.setattr(main, "_serving_loop_checked", True)
    gate.setattr(ap, "is_armed", lambda: True)
    client = TestClient(main.app)
    assert client.get("/unlock").status_code == 200
    gate.setattr(ap, "is_armed", lambda: False)
    r = client.get("/unlock")
    _assert_refused(r.status_code, r.json())
    gate.setattr(ap, "is_armed", lambda: True)
    assert client.get("/unlock").status_code == 200


def test_an_uninstalled_guard_closes_the_gate_again(gate):
    """R649, with the real guard: serving, then ``uninstall_airplane_socket_guard()``, then the next request is refused."""
    gate.setattr(main, "_serving_loop_checked", True)
    was_installed, was_armed = ap.is_installed(), ap._airplane_armed
    assert ap.install_airplane_socket_guard()
    try:
        client = TestClient(main.app)
        assert client.get("/unlock").status_code == 200
        ap.uninstall_airplane_socket_guard()
        r = client.get("/unlock")
        _assert_refused(r.status_code, r.json())
    finally:
        ap.uninstall_airplane_socket_guard()
        if was_installed:
            ap._install_patches()
        ap._airplane_armed = was_armed


def test_a_websocket_is_refused_while_the_gate_is_closed(gate):
    """R649: a pure ASGI middleware, so a websocket scope meets the gate too; ``@app.middleware("http")`` never saw one, and a
    websocket route added later would have gone round it. Refused before it is accepted, with close code 1013."""
    from starlette.websockets import WebSocketDisconnect

    client = TestClient(main.app)
    with pytest.raises(WebSocketDisconnect) as refused, client.websocket_connect("/any-websocket"):
        pass
    assert refused.value.code == 1013
    gate.setattr(main, "_serving_loop_checked", True)
    gate.setattr(ap, "is_armed", lambda: True)
    # Open: the router answers (no websocket route exists), not the gate.
    with pytest.raises(WebSocketDisconnect) as routed, client.websocket_connect("/any-websocket"):
        pass
    assert routed.value.code != 1013


def test_the_documented_guard_opt_out_waives_only_the_guard(gate):
    gate.setenv("OO_AIRPLANE_SOCKET_GUARD", "0")
    gate.setattr(ap, "is_armed", lambda: False)
    r = TestClient(main.app).get("/unlock")
    _assert_refused(r.status_code, r.json())  # the loop check still has to have run
    gate.setattr(main, "_serving_loop_checked", True)
    assert TestClient(main.app).get("/unlock").status_code == 200


def test_a_headless_process_is_not_waived(gate):
    """R646: OO_NO_SCHEDULER=1 no longer waives the gate (R644 had waived it, when the boot never armed the guard under it). The boot
    now arms it there too, so a headless start without the lifespan is refused like any other."""
    gate.setenv("OO_NO_SCHEDULER", "1")
    gate.setattr(ap, "is_armed", lambda: False)
    r = TestClient(main.app).get("/unlock")
    _assert_refused(r.status_code, r.json())
    gate.setattr(main, "_serving_loop_checked", True)
    r = TestClient(main.app).get("/unlock")
    _assert_refused(r.status_code, r.json())  # the loop check alone is not enough under it either
    gate.setattr(ap, "is_armed", lambda: True)
    assert TestClient(main.app).get("/unlock").status_code == 200


def test_is_armed_is_false_for_the_ssrf_half_alone(monkeypatch):
    monkeypatch.setattr(ap, "_installed", True)
    monkeypatch.setattr(ap, "_airplane_armed", False)
    assert ap.is_armed() is False
    monkeypatch.setattr(ap, "_airplane_armed", True)
    assert ap.is_armed() is True
    monkeypatch.setattr(ap, "_installed", False)
    assert ap.is_armed() is False


def test_the_lifespan_records_the_loop_check_right_after_it_and_arms_the_guard():
    """Source-level: the flag is set by the lifespan, immediately after R642's refusal, and the guard is installed before the yield.
    Since R646 the install is not inside any ``if`` (tests/test_guard_always_installed_r646.py runs the real lifespan)."""
    fn = ast.parse(inspect.getsource(main.lifespan)).body[0]
    assert isinstance(fn, ast.AsyncFunctionDef)
    body = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    refusal = next(i for i, n in enumerate(body) if isinstance(n, ast.If) and "_event_loop_is_stdlib" in ast.unparse(n.test))
    assert ast.unparse(body[refusal + 1]) == "global _serving_loop_checked"
    assert ast.unparse(body[refusal + 2]) == "_serving_loop_checked = True"
    arm = body[refusal + 3]
    assert isinstance(arm, ast.Try)
    assert "install_airplane_socket_guard()" in ast.unparse(arm.body)
    # Nothing else in src/ sets the flag.
    assert inspect.getsource(main).count("_serving_loop_checked = True") == 1


def test_the_gate_is_the_outermost_layer_but_compression():
    """Registered just before GZip, so it answers before the lock gate, the rate limiter or any route runs: in the module's top-level
    statements, nothing that adds a middleware sits between the gate's definition and the GZip registration."""
    tree = ast.parse(Path(main.__file__).read_text(encoding="utf-8"))

    def adds_middleware(node: ast.stmt) -> bool:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return any("middleware" in ast.unparse(d) for d in node.decorator_list)
        return isinstance(node, ast.Expr) and "add_middleware" in ast.unparse(node)

    order = [n for n in tree.body if adds_middleware(n)]
    names = [n.name if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) else ast.unparse(n) for n in order]
    assert names[-1] == "app.add_middleware(GZipMiddleware, minimum_size=500)"
    assert names[-2] == "app.add_middleware(_ServingGate)"


def test_a_real_socket_call_written_back_over_the_guard_closes_the_gate(gate):
    """Security reads A and B on #1901: both flags stay set when a real call is written back over a patched one, so the gate
    also asks ``removed_while_installed()``."""
    gate.setattr(main, "_serving_loop_checked", True)
    was_installed, was_armed = ap.is_installed(), ap._airplane_armed
    assert ap.install_airplane_socket_guard()
    wrapper = socket.getaddrinfo
    try:
        client = TestClient(main.app)
        assert client.get("/unlock").status_code == 200
        socket.getaddrinfo = ap._orig_getaddrinfo  # the real call back over the wrapper, as a stray assignment would
        assert ap.is_armed() and ap.removed_while_installed()
        r = client.get("/unlock")
        _assert_refused(r.status_code, r.json())
    finally:
        socket.getaddrinfo = wrapper
        ap.uninstall_airplane_socket_guard()
        if was_installed:
            ap._install_patches()
        ap._airplane_armed = was_armed


def _drive(scope: dict) -> list[str]:
    """Run the gate alone on one scope with an inner app that records being reached; returns the event log."""
    import asyncio

    log: list[str] = []

    async def inner(scope, receive, send):
        log.append("inner")

    async def receive():
        log.append("receive")
        return {"type": "websocket.connect"}

    async def send(message):
        log.append(message["type"])

    asyncio.run(main._ServingGate(inner)(scope, receive, send))
    return log


def test_an_unknown_scope_type_reaches_nothing_while_the_gate_is_closed(gate):
    """Security read A on #1901: only a lifespan scope passes ungated, so a future scope type fails closed by construction."""
    assert _drive({"type": "webtransport"}) == []
    assert _drive({"type": "lifespan"}) == ["inner"]


def test_a_refused_websocket_takes_the_connect_event_before_it_closes(gate):
    """Security read B on #1901: the protocol hands the app its websocket.connect first; the close follows it."""
    assert _drive({"type": "websocket", "path": "/x"}) == ["receive", "websocket.close"]


def test_a_gate_that_closes_again_logs_again(gate, caplog):
    """Security read B on #1901: once the gate is open the logged flag is cleared, so a later closing has its own line."""
    client = TestClient(main.app)
    with caplog.at_level("ERROR", logger=main.logger.name):
        assert client.get("/unlock").status_code == 503
        gate.setattr(main, "_serving_loop_checked", True)
        gate.setattr(ap, "is_armed", lambda: True)
        gate.setattr(ap, "removed_while_installed", lambda: [])
        assert client.get("/unlock").status_code == 200
        gate.setattr(ap, "is_armed", lambda: False)
        assert client.get("/unlock").status_code == 503
    assert [r.getMessage() for r in caplog.records].count(main.SERVING_GATE_REFUSAL) == 2
