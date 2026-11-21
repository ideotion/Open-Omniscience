"""R770 and R771: the local AI is reached directly, and a daemon the app starts listens only on this computer.

R770 (row 242). ``OllamaClient`` and ``VllmClient`` built ``httpx.Client`` with ``trust_env`` left on, so with
``HTTP_PROXY`` / ``HTTPS_PROXY`` / ``ALL_PROXY`` set and no ``NO_PROXY``, a request to ``http://127.0.0.1`` went through the
proxy: prompts and article text reached it, past the loopback rule, which only judges the URL. Both clients now ignore the
environment's proxies. The status and lifecycle probes reach the same addresses through these two clients, so they are
covered by the same change; the raw ``connect_ex`` in ``vllm_lifecycle.port_occupant`` is a socket, which no proxy setting
reaches. The sweep found no other client of a loopback-only server: the terminal panel's ``http.client`` connection reads no
proxy variables.

The test is behavioural: a real server on 127.0.0.1 plays the local AI, a second one plays the proxy and counts what reaches
it, and the proxy variables name the second. Both are on this computer, so nothing here can leave it even on a regression.

R771 (row 243). ``ollama_lifecycle.start()`` handed the daemon the inherited environment, so ``OLLAMA_HOST=0.0.0.0`` started
a daemon on the local network, and a loopback ``OO_OLLAMA_URL`` on another port started one the app never reached. The child
now gets ``OLLAMA_HOST`` = the configured loopback host and port, always.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import src.llm.ollama_lifecycle as life
from src.llm.ollama import OllamaClient
from src.llm.vllm_client import VllmClient

_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


@pytest.fixture(autouse=True)
def _online():
    """The kill switch OFF, so the requests below are the ones a working, online app would make."""
    from src.ingest import activate_kill_switch, clear_kill_switch, kill_switch_active

    was = kill_switch_active()
    clear_kill_switch()
    yield
    if was:
        activate_kill_switch()
    else:
        clear_kill_switch()


def _serve(body: dict) -> tuple[ThreadingHTTPServer, list[str]]:
    """A server on 127.0.0.1 that answers every GET with ``body`` and records each request line it saw."""
    seen: list[str] = []

    class _H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - the stdlib's name
            seen.append(self.requestline)
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):  # keep the test output quiet
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, seen


@pytest.fixture
def ai_and_proxy(monkeypatch):
    """(AI server port, requests the proxy saw); every proxy variable names the counting proxy, and NO_PROXY is unset."""
    ai, _ = _serve({"models": [{"name": "m:1"}], "data": [{"id": "m", "owned_by": "vllm"}]})
    try:
        proxy, proxied = _serve({"proxied": True})
    except Exception:
        ai.shutdown()
        ai.server_close()
        raise
    proxy_url = f"http://127.0.0.1:{proxy.server_address[1]}"
    for var in _PROXY_VARS:
        monkeypatch.setenv(var, proxy_url)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    yield ai.server_address[1], proxied
    for srv in (ai, proxy):
        srv.shutdown()
        srv.server_close()


def test_the_ollama_client_goes_direct_with_every_proxy_variable_set(ai_and_proxy, monkeypatch):
    port, proxied = ai_and_proxy
    monkeypatch.setenv("OO_OLLAMA_URL", f"http://127.0.0.1:{port}")
    client = OllamaClient(timeout=5)
    try:
        assert client.list_installed() == ["m:1"]
    finally:
        client._client.close()
    assert proxied == []


def test_the_vllm_client_goes_direct_with_every_proxy_variable_set(ai_and_proxy, monkeypatch):
    port, proxied = ai_and_proxy
    monkeypatch.setenv("OO_VLLM_URL", f"http://127.0.0.1:{port}")
    client = VllmClient(timeout=5)
    try:
        assert client.is_available()
    finally:
        client._client.close()
    assert proxied == []


def test_the_liveness_probe_goes_direct_too(ai_and_proxy, monkeypatch):
    """``ollama_lifecycle.is_running`` (the Settings and pill probe) builds the same client."""
    port, proxied = ai_and_proxy
    monkeypatch.setenv("OO_OLLAMA_URL", f"http://127.0.0.1:{port}")
    assert life.is_running(timeout=5) is True
    assert proxied == []


def test_the_counting_proxy_would_see_a_client_that_honours_the_environment(ai_and_proxy):
    """The control: with ``trust_env`` on, httpx DOES send a loopback request to the proxy -- so the tests above are not
    passing because the proxy variables were never read."""
    import httpx

    port, proxied = ai_and_proxy
    with httpx.Client(timeout=5) as c:
        c.get(f"http://127.0.0.1:{port}/api/tags")
    assert proxied, "httpx did not route through the proxy variables, so the direct-connection tests prove nothing"


def test_every_httpx_client_in_the_app_ignores_the_environments_proxies():
    """The sweep, pinned by the parse tree: every ``httpx`` ``Client``/``AsyncClient`` built in ``src/`` passes
    ``trust_env=False``, none of httpx's module-level request functions (which read the proxies) is called, and the only
    modules that build one are the two local-AI clients."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src"
    builders: dict[str, int] = {}
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {"httpx"}  # every name httpx is imported as, and the names imported from it
        direct: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.asname or a.name for a in node.names if a.name == "httpx"}
            elif isinstance(node, ast.ImportFrom) and node.module == "httpx":
                direct |= {(a.asname or a.name): a.name for a in node.names}
        rel = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in names:
                what = f.attr
            elif isinstance(f, ast.Name) and f.id in direct:
                what = direct[f.id]
            else:
                continue
            assert what not in {"get", "post", "put", "patch", "delete", "head", "options", "request", "stream"}, (
                f"{rel}:{node.lineno} calls httpx.{what}, which routes through the environment's proxies"
            )
            if what in {"Client", "AsyncClient"}:
                kw = {k.arg: k.value for k in node.keywords}
                ok = isinstance(kw.get("trust_env"), ast.Constant) and kw["trust_env"].value is False
                assert ok, f"{rel}:{node.lineno} builds httpx.{what} without trust_env=False"
                builders[rel] = builders.get(rel, 0) + 1
    assert builders == {"llm/ollama.py": 1, "llm/vllm_client.py": 1}, builders


# --------------------------------------------------------------------------- #
#  R771: the daemon this app starts listens where the app talks to it, and nowhere else
# --------------------------------------------------------------------------- #
@pytest.fixture
def fake_ollama(tmp_path, monkeypatch):
    b = tmp_path / ("ollama.exe" if sys.platform == "win32" else "ollama")
    b.write_text("#!/bin/sh\nsleep 300\n", encoding="utf-8")
    b.chmod(b.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    assert shutil.which("ollama") is not None
    return b


@pytest.fixture
def spawn_env(monkeypatch, fake_ollama):
    """The environment each ``ollama serve`` would have been started with; nothing is run."""
    envs: list[dict] = []

    def _popen(argv, **kw):
        envs.append(dict(kw.get("env") or {}))
        return None

    monkeypatch.setattr(subprocess, "Popen", _popen)
    monkeypatch.setattr(life, "is_running", lambda **kw: False)
    monkeypatch.setattr(life, "_proc", None)
    return envs


@pytest.mark.parametrize(
    ("url", "bind"),
    [
        ("http://127.0.0.1:11434", "127.0.0.1:11434"),
        ("http://127.0.0.1:12345/", "127.0.0.1:12345"),
        ("http://localhost:11434", "localhost:11434"),
        ("http://[::1]:11434", "[::1]:11434"),
        ("http://127.0.0.1", "127.0.0.1:80"),  # the port the client itself would use
        # Alias names go as their literal address: the daemon resolving one could reach DNS.
        ("http://localhost.localdomain:11434", "127.0.0.1:11434"),
        ("http://ip6-localhost:11434", "[::1]:11434"),
    ],
)
def test_the_daemon_listens_on_the_configured_loopback_address(url, bind, monkeypatch, spawn_env):
    monkeypatch.setenv("OO_OLLAMA_URL", url)
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11434")  # inherited: would put the daemon on the local network
    life.start(wait=False)
    assert [e.get("OLLAMA_HOST") for e in spawn_env] == [bind]


def test_the_default_address_binds_loopback_even_with_no_setting(monkeypatch, spawn_env):
    monkeypatch.delenv("OO_OLLAMA_URL", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0")
    life.start(wait=False)
    assert spawn_env[0]["OLLAMA_HOST"] == "127.0.0.1:11434"


@pytest.mark.parametrize(
    ("url", "said"),
    [
        ("http://127.0.0.1:99999", "port"),
        ("http://127.0.0.1:port", "port"),
        ("http://127.0.0.1:0", "port 0"),  # a random port the app never finds: every Launch would orphan a daemon
        ("https://127.0.0.1:11434", "http://"),  # Ollama serves no TLS
    ],
)
def test_an_address_the_daemon_cannot_serve_starts_nothing(url, said, monkeypatch, spawn_env):
    monkeypatch.setenv("OO_OLLAMA_URL", url)
    with pytest.raises(life.OllamaLifecycleError, match=said):
        life.start(wait=False)
    assert spawn_env == []


def test_a_remote_address_starts_nothing(monkeypatch, spawn_env):
    """R771 joins row 234: no spawn at all for an address that is not on this computer."""
    monkeypatch.setenv("OO_OLLAMA_URL", "http://203.0.113.7:11434")
    with pytest.raises(life.OllamaLifecycleError, match="must be loopback"):
        life.start(wait=False)
    assert spawn_env == []


def test_a_running_daemon_is_never_touched(monkeypatch, spawn_env):
    """A daemon that already answers is not ours to rebind: nothing is spawned and nothing is changed."""
    monkeypatch.setattr(life, "is_running", lambda **kw: True)
    out = life.start(wait=False)
    assert out["started"] is False and spawn_env == []


def test_an_inherited_origins_setting_never_reaches_the_daemon(monkeypatch, spawn_env):
    """OLLAMA_ORIGINS=* would let any web page in the browser call the daemon and read its answers."""
    monkeypatch.setenv("OLLAMA_ORIGINS", "*")
    life.start(wait=False)
    assert "OLLAMA_ORIGINS" not in spawn_env[0]
