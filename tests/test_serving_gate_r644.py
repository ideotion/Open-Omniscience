"""R644: the app refuses every request with a fixed 503 until its lifespan's loop check (R642) ran and airplane mode's guard is armed.

``uvicorn --lifespan off`` and this app mounted inside another ASGI app skip the lifespan, so they skip the loop check and the guard it
arms. These tests run both for real (a uvicorn server on loopback, a Starlette mount) with ``OO_NO_SCHEDULER`` cleared, so the gate is
live. No network: the only sockets are loopback.
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
    """The gate as a fresh process sees it: closed, no loop check recorded, OO_NO_SCHEDULER cleared."""
    monkeypatch.setattr(main, "_serving_loop_checked", False)
    monkeypatch.setattr(main, "_serving_gate_open", False)
    monkeypatch.setattr(main, "_serving_gate_logged", False)
    monkeypatch.setenv("OO_NO_SCHEDULER", "0")
    monkeypatch.delenv("OO_AIRPLANE_SOCKET_GUARD", raising=False)
    return monkeypatch


def _assert_refused(status: int, body: object) -> None:
    assert status == 503
    assert body == {"detail": main.SERVING_GATE_REFUSAL}


def test_a_request_without_the_lifespan_is_refused_in_fixed_words(gate):
    """TestClient without ``with`` runs no lifespan, exactly as ``--lifespan off``."""
    r = TestClient(main.app).get("/unlock")
    _assert_refused(r.status_code, r.json())
    assert main._serving_gate_open is False


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
    assert main._serving_gate_open is False


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


def test_both_preconditions_open_the_gate_once(gate):
    gate.setattr(main, "_serving_loop_checked", True)
    gate.setattr(ap, "is_armed", lambda: True)
    client = TestClient(main.app)
    assert client.get("/unlock").status_code == 200
    assert main._serving_gate_open is True
    gate.setattr(ap, "is_armed", lambda: False)  # once open, the gate reads only its flag
    assert client.get("/unlock").status_code == 200


def test_the_documented_guard_opt_out_waives_only_the_guard(gate):
    gate.setenv("OO_AIRPLANE_SOCKET_GUARD", "0")
    gate.setattr(ap, "is_armed", lambda: False)
    r = TestClient(main.app).get("/unlock")
    _assert_refused(r.status_code, r.json())  # the loop check still has to have run
    gate.setattr(main, "_serving_loop_checked", True)
    assert TestClient(main.app).get("/unlock").status_code == 200


def test_a_headless_process_is_waived(gate):
    """OO_NO_SCHEDULER=1 is the mode in which the boot never arms the guard at all (tests, headless): the gate has nothing to hold."""
    gate.setenv("OO_NO_SCHEDULER", "1")
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
    Running the real lifespan with OO_NO_SCHEDULER cleared would start the whole deferred startup."""
    fn = ast.parse(inspect.getsource(main.lifespan)).body[0]
    assert isinstance(fn, ast.AsyncFunctionDef)
    body = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    refusal = next(i for i, n in enumerate(body) if isinstance(n, ast.If) and "_event_loop_is_stdlib" in ast.unparse(n.test))
    assert ast.unparse(body[refusal + 1]) == "global _serving_loop_checked"
    assert ast.unparse(body[refusal + 2]) == "_serving_loop_checked = True"
    arm = body[refusal + 3]
    assert isinstance(arm, ast.If)
    assert ast.unparse(arm.test) == "os.getenv('OO_NO_SCHEDULER', '0') != '1'"
    assert "install_airplane_socket_guard()" in ast.unparse(arm.body)
    # Nothing else in src/ sets the flag.
    assert inspect.getsource(main).count("_serving_loop_checked = True") == 1


def test_the_gate_is_the_outermost_layer_but_compression():
    """Registered just before GZip, so it answers before the lock gate, the rate limiter or any route runs."""
    src = inspect.getsource(main)
    assert src.index("async def _serving_gate(") < src.index("app.add_middleware(GZipMiddleware")
    after = src[src.index("async def _serving_gate(") : src.index("app.add_middleware(GZipMiddleware")]
    assert "@app.middleware" not in after and "add_middleware" not in after
