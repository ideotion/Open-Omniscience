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
    ],
)
def test_the_daemon_listens_on_the_configured_loopback_address(url, bind, monkeypatch, spawn_env):
    monkeypatch.setenv("OO_OLLAMA_URL", url)
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11434")  # inherited: would put the daemon on the local network
    life.start(wait=False)
    assert [e.get("OLLAMA_HOST") for e in spawn_env] == [bind]


@pytest.mark.parametrize("url", ["http://localhost.localdomain:11434", "http://ip6-localhost:11434"])
def test_an_alias_address_starts_no_daemon_at_all(url, monkeypatch, spawn_env):
    """R767: the aliases are refused by the loopback rule itself, so no daemon is started for one (earlier, R771 bound it
    to the literal); the refusal names the literal to use instead."""
    monkeypatch.setenv("OO_OLLAMA_URL", url)
    with pytest.raises(life.OllamaLifecycleError, match="instead"):
        life.start(wait=False)
    assert spawn_env == []


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



_LOOPBACK_TRANSPORT_CLASS = ("llm/loopback.py", "LoopbackTransport")


def _is_the_loopback_transport(keyword) -> bool:
    """``transport=_loopback_transport()`` exactly: R767's loopback-only scope, built with no argument (no proxy, no mount)."""
    import ast

    v = keyword.value
    return (
        keyword.arg == "transport" and isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
        and v.func.id == "_loopback_transport" and not v.args and not v.keywords
    )


def _sweep_evasions(root) -> None:
    """Fails on any way round the keyword sweep above in ``root``: a client built through an alias, a subclass or
    ``getattr``, or given its own proxy, mounts or transport (security read of R770)."""
    import ast

    builders = {"Client", "AsyncClient"}
    routes = {"proxy", "proxies", "mounts", "transport"}
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "httpx" not in text:
            continue
        tree = ast.parse(text)
        names = {"httpx"}
        direct: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.asname or a.name for a in node.names if a.name.split(".")[0] == "httpx"}
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "httpx":
                direct |= {(a.asname or a.name): a.name for a in node.names}
        rel = path.relative_to(root).as_posix()

        def httpx_name(n: ast.AST, names=names, direct=direct) -> str | None:
            if isinstance(n, ast.Attribute):
                base = n.value
                while isinstance(base, ast.Attribute):  # httpx._client.Client
                    base = base.value
                if isinstance(base, ast.Name) and base.id in names:
                    return n.attr
            if isinstance(n, ast.Name) and n.id in direct:
                return direct[n.id]
            return None

        called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        annotations: list[ast.AST] = []  # a type annotation names the class without building one
        for n in ast.walk(tree):
            if (isinstance(n, ast.arg) and n.annotation is not None) or isinstance(n, ast.AnnAssign):
                annotations.append(n.annotation)
            elif isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.returns is not None:
                annotations.append(n.returns)
        called |= {id(sub) for a in annotations for sub in ast.walk(a)}
        for node in ast.walk(tree):
            what = httpx_name(node)
            if what in builders:
                assert id(node) in called, f"{rel}:{node.lineno} refers to httpx.{what} without calling it (an alias)"
            if isinstance(node, ast.ClassDef):
                # The one named exception (R767): the loopback-only transport, which adds a scope and no route of its own
                # (test_the_loopback_transport_is_the_one_exception_and_carries_no_proxy pins that).
                if (rel, node.name) == _LOOPBACK_TRANSPORT_CLASS:
                    continue
                assert not any(httpx_name(b) for b in node.bases), f"{rel}:{node.lineno} subclasses an httpx class"
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Name) and f.id == "getattr" and node.args:
                first = node.args[0]
                assert not (isinstance(first, ast.Name) and first.id in names), (
                    f"{rel}:{node.lineno} reaches into httpx through getattr"
                )
            inner = httpx_name(f)
            assert inner not in {"HTTPTransport", "AsyncHTTPTransport", "Proxy"}, (
                f"{rel}:{node.lineno} builds httpx.{inner}, which can carry a proxy"
            )
            if inner in builders:
                given = {k.arg for k in node.keywords if not _is_the_loopback_transport(k)} & routes
                assert not given, f"{rel}:{node.lineno} gives httpx.{inner} its own route: {sorted(given)}"


def test_the_sweep_also_refuses_the_ways_round_it():
    from pathlib import Path

    _sweep_evasions(Path(__file__).resolve().parents[1] / "src")


@pytest.mark.parametrize(
    "code",
    [
        "import httpx\nC = httpx.Client\nc = C(trust_env=False)\n",
        "import httpx\ndef f(c: httpx.Client = httpx.Client) -> None:\n    pass\n",  # a default, not an annotation
        "from httpx import Client\nC = Client\n",
        "import httpx\nclass C(httpx.Client):\n    pass\n",
        "import httpx\nc = getattr(httpx, 'Client')()\n",
        "import httpx\nc = httpx._client.Client\n",
        "import httpx\nt = httpx.HTTPTransport(proxy='http://p')\n",
        "import httpx\nc = httpx.Client(trust_env=False, proxy='http://p')\n",
        "import httpx as h\nc = h.Client(trust_env=False, mounts={})\n",
    ],
)
def test_the_sweep_catches_each_way_round_it(code, tmp_path):
    """The control: each evasion, planted in a scratch tree, is caught."""
    (tmp_path / "m.py").write_text(code, encoding="utf-8")
    with pytest.raises(AssertionError):
        _sweep_evasions(tmp_path)


def test_a_daemon_that_already_answers_is_reported_running_whatever_a_new_one_would_need(monkeypatch, spawn_env):
    """Security read of R771: an https address in front of a running daemon read as an error, not "already running"."""
    monkeypatch.setenv("OO_OLLAMA_URL", "https://127.0.0.1:11434")
    monkeypatch.setattr(life, "is_running", lambda **kw: True)
    out = life.start(wait=False)
    assert out["started"] is False and out["reason"] == "already running" and spawn_env == []


@pytest.mark.parametrize("url", ["https://127.0.0.1:11434", "http://127.0.0.1:0", "http://127.0.0.1:99999"])
def test_the_gpu_handover_refuses_an_address_start_would_refuse_before_releasing_anything(url, monkeypatch, spawn_env):
    """Security read of R771: these pass the loopback rule, so the handover released vLLM and THEN start() refused."""
    from src.llm import arbitration

    released: list[str] = []
    monkeypatch.setattr(arbitration, "release_backend", lambda b: released.append(b) or {"backend": b})
    monkeypatch.setattr(arbitration, "free_vram_mb", lambda: None)
    monkeypatch.setenv("OO_OLLAMA_URL", url)
    out = arbitration.hand_gpu_to("ollama")
    assert released == [] and out["ready"] is False and out["reason"] and spawn_env == []


def test_a_handover_without_a_start_reports_no_start(monkeypatch):
    from src.llm import arbitration

    monkeypatch.setattr(arbitration, "release_backend", lambda b: {"backend": b})
    monkeypatch.setattr(arbitration, "free_vram_mb", lambda: None)
    monkeypatch.setenv("OO_OLLAMA_URL", "http://203.0.113.7:11434")
    out = arbitration.hand_gpu_to("ollama", start=False)
    assert out["started"] is None and "must be loopback" in out["reason"]


def test_a_daemon_asked_for_a_low_port_that_never_answers_says_why(monkeypatch, spawn_env):
    """An address with no port means port 80, which an unprivileged daemon cannot listen on: the note says so."""
    monkeypatch.setenv("OO_OLLAMA_URL", "http://127.0.0.1")
    out = life.start(wait=True, timeout=0)
    assert out["ready"] is False and "port 80" in out["note"] and "11434" in out["note"]
    monkeypatch.setenv("OO_OLLAMA_URL", "http://127.0.0.1:12345")
    assert "administrator" not in life.start(wait=True, timeout=0)["note"]


def test_the_loopback_transport_is_the_one_exception_and_carries_no_proxy(monkeypatch):
    """R767's transport is the sweep's one exception, so it must stay a plain direct connection pool: built with no
    argument, no __init__ of its own, and no proxy even when the environment names one."""
    import inspect

    import httpcore

    from src.llm import loopback, ollama

    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("ALL_PROXY", "http://proxy.invalid:3128")
    assert "__init__" not in vars(loopback.LoopbackTransport)
    t = ollama._loopback_transport()
    assert type(t) is loopback.LoopbackTransport
    assert type(t._pool) is httpcore.ConnectionPool, "a proxy pool would be an HTTPProxy or SOCKSProxy"
    assert "return LoopbackTransport()" in inspect.getsource(ollama._loopback_transport)

