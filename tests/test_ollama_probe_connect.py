"""Row 141: the Ollama liveness probe stops waiting on a refused loopback connect, and only on that.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

On Windows a connect to a loopback port with nothing listening is retried by the stack and takes about 2 s to be refused; the
probe waited for it in full, so every model pull with no daemon running paid it (the Windows CI shard showed three pulls
outlasting a 3 s join). The probe now gives the CONNECT half a second, which a listening port answers in well under a
millisecond however busy the daemon is, and keeps the caller's whole timeout for the reply, so a daemon that is up but slow to
answer still reads as running. These run on every platform; on the nightly Windows legs the second one is the real measurement.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.llm import ollama_lifecycle as ol


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def slow_daemon(monkeypatch):
    """A stand-in daemon on loopback that takes a full second to answer ``/api/tags``."""

    class _Slow(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - the stdlib's name
            time.sleep(1.0)
            body = json.dumps({"models": []}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # quiet
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Slow)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("OO_OLLAMA_URL", f"http://127.0.0.1:{server.server_address[1]}")
    yield
    server.shutdown()
    server.server_close()


def test_a_daemon_slow_to_answer_is_still_running(slow_daemon):
    """The connect cap is not a reply cap: one second of silence after the connect is a busy daemon, not an absent one."""
    assert ol._PROBE_CONNECT_S < 1.0
    assert ol.is_running(timeout=2.0) is True


def test_nothing_listening_is_reported_down_without_waiting_out_the_whole_timeout(monkeypatch):
    monkeypatch.setenv("OO_OLLAMA_URL", f"http://127.0.0.1:{_free_port()}")
    t0 = time.monotonic()
    assert ol.is_running(timeout=2.0) is False
    assert time.monotonic() - t0 < 1.5, "a refused loopback connect was waited out (row 141)"


def test_the_probe_gives_the_connect_its_own_short_limit_and_the_reply_the_whole_timeout(monkeypatch):
    from src.llm.ollama import OllamaClient

    seen = {}
    real = OllamaClient.__init__

    def _spy(self, **kwargs):
        real(self, **kwargs)
        seen["timeout"] = self._client.timeout

    monkeypatch.setattr(OllamaClient, "__init__", _spy)
    monkeypatch.setattr(OllamaClient, "is_available", lambda self: False)
    ol.is_running(timeout=2.0)
    t = seen["timeout"]
    assert t.connect == ol._PROBE_CONNECT_S and t.read == 2.0, t
    ol.is_running(timeout=0.2)  # a caller asking for less than the cap keeps its own limit
    assert seen["timeout"].connect == 0.2
    OllamaClient(timeout=30.0)  # every other client is unchanged: one limit for connect and reply alike
    assert seen["timeout"].connect == 30.0 and seen["timeout"].read == 30.0
