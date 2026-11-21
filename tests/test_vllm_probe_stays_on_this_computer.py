"""R762: the vLLM status probe never contacts an address on another computer.

``port_occupant()`` runs on every ``GET /api/llm/vllm/status`` (Settings reads it with no click). It used
to build a ``VllmClient``, whose loopback refusal raised and was swallowed, and then fall through to a raw
``connect_ex`` on the ``OO_VLLM_URL`` host: a TCP connection to another computer, past the rule every
other local-AI call obeys. Now the SAME rule (``src.llm.ollama._loopback_refusal``, which ``_require_loopback`` raises) refuses first, the
refusal is the answer with its reason, and nothing is resolved or connected.

The recorder below sees every resolution and connect a probe could make. The control test proves it is
not vacuous: a loopback address IS probed, and the recorder sees that connect.
"""

from __future__ import annotations

import inspect
import json
import socket
from pathlib import Path

import pytest

from src.llm import vllm_lifecycle as V

ROOT = Path(__file__).resolve().parents[1]
REMOTE_URLS = ("http://203.0.113.7:8000", "http://vllm.example.com:8000")
REFUSED_UI = (
    "This vLLM address is not on this computer, so the app does not contact it. The local AI only talks to "
    "this computer: set OO_VLLM_URL to 127.0.0.1, localhost or ::1."
)


@pytest.fixture(autouse=True)
def _online():
    """The kill switch OFF, so the airplane socket guard cannot be what stops the connect: the probe must."""
    from src.ingest import activate_kill_switch, clear_kill_switch, kill_switch_active

    was = kill_switch_active()
    clear_kill_switch()
    yield
    if was:
        activate_kill_switch()
    else:
        clear_kill_switch()


@pytest.fixture
def network_calls(monkeypatch):
    """Every resolution and connect, recorded; a remote one is refused here so a regression cannot egress."""
    calls: list[tuple[str, object]] = []
    real_connect_ex = socket.socket.connect_ex
    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo
    real_create = socket.create_connection

    def _is_local(address) -> bool:
        host = address[0] if isinstance(address, tuple) else address
        return str(host) in {"127.0.0.1", "::1", "localhost"}

    def connect_ex(self, address):
        calls.append(("connect_ex", address))
        if not _is_local(address):
            return 111
        return real_connect_ex(self, address)

    def connect(self, address):
        calls.append(("connect", address))
        if not _is_local(address):
            raise ConnectionRefusedError("test: remote connect refused")
        return real_connect(self, address)

    def getaddrinfo(host, *a, **k):
        calls.append(("getaddrinfo", host))
        if not _is_local((host,)):
            raise socket.gaierror("test: remote lookup refused")
        return real_getaddrinfo(host, *a, **k)

    def create_connection(address, *a, **k):
        calls.append(("create_connection", address))
        if not _is_local(address):
            raise ConnectionRefusedError("test: remote connect refused")
        return real_create(address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    return calls


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.parametrize("url", REMOTE_URLS)
def test_a_remote_vllm_address_is_refused_and_never_contacted(monkeypatch, network_calls, url):
    monkeypatch.setenv("OO_VLLM_URL", url)
    occ = V.port_occupant(timeout=1.0)
    assert network_calls == [], f"the probe touched the network for {url}: {network_calls}"
    assert occ["state"] == "refused"
    assert occ["port"] == 8000
    assert "OO_VLLM_URL must be loopback" in occ["detail"]
    host = url.split("//")[1].split(":")[0]
    assert host in occ["detail"], "the reason names the address it refused"


def test_a_loopback_address_is_still_probed_and_the_recorder_sees_it(monkeypatch, network_calls):
    """The control: without it, an empty recorder above could mean the recorder saw nothing at all."""
    port = _free_port()
    monkeypatch.setenv("OO_VLLM_URL", f"http://127.0.0.1:{port}")
    occ = V.port_occupant(timeout=1.0)
    assert occ["state"] == "free"
    assert ("connect_ex", ("127.0.0.1", port)) in network_calls


def test_start_refuses_a_remote_address_without_spawning_or_connecting(monkeypatch, network_calls):
    monkeypatch.setattr("src.llm.backend.detect_gpu", lambda: {"available": True, "vram_mb": 8188})
    monkeypatch.setattr(V, "is_installed", lambda: True)
    monkeypatch.setenv("OO_VLLM_URL", REMOTE_URLS[0])

    def must_not_spawn(*a, **k):
        raise AssertionError("start() spawned a server for an address on another computer")

    def must_not_clear(*a, **k):
        raise AssertionError("start() cleared the GPU for an address on another computer")

    monkeypatch.setattr(V, "clear_gpu_for_vllm", must_not_clear)

    with pytest.raises(V.VllmLifecycleError) as exc:
        V.start("a-model", popen=must_not_spawn)
    assert "OO_VLLM_URL must be loopback" in str(exc.value)
    assert [c for c in network_calls if c[1] and "203.0.113.7" in str(c[1])] == []


def test_status_carries_the_refusal_and_touches_no_remote_host(monkeypatch, network_calls):
    monkeypatch.setattr("src.llm.backend.detect_gpu", lambda: {"available": False})
    monkeypatch.setenv("OO_VLLM_URL", REMOTE_URLS[0])
    st = V.status()
    assert st["port_occupant"]["state"] == "refused"
    assert st["running"] is False
    assert [c for c in network_calls if "203.0.113.7" in str(c[1])] == []


def test_one_shared_loopback_rule_not_a_second_copy():
    """R762: the probe calls the helper VllmClient calls; vllm_lifecycle carries no loopback test of its own."""
    probe = inspect.getsource(V.port_occupant)
    assert "_loopback_refusal(url" in probe
    assert probe.index("_loopback_refusal(url") < probe.index("s.connect_ex("), "the refusal comes before any connect"
    from src.llm import ollama

    raiser = inspect.getsource(ollama._require_loopback)
    assert "_loopback_refusal(url" in raiser and "_is_loopback_url" not in raiser, "the raiser and the probe share one rule"
    lifecycle = (ROOT / "src/llm/vllm_lifecycle.py").read_text(encoding="utf-8")
    for copy in ("is_loopback", "_is_loopback_url", "ip_address("):
        assert copy not in lifecycle, f"a second loopback check ({copy}) would drift from the shared one"
    client = (ROOT / "src/llm/vllm_client.py").read_text(encoding="utf-8")
    assert '_require_loopback(self.base_url, setting="OO_VLLM_URL")' in client


def test_each_refusal_names_its_own_setting():
    from src.llm.ollama import LLMError, OllamaClient
    from src.llm.vllm_client import VllmClient

    with pytest.raises(LLMError, match="OO_VLLM_URL must be loopback"):
        VllmClient(base_url="http://example.com:8000")
    with pytest.raises(LLMError, match="OO_OLLAMA_URL must be loopback"):
        OllamaClient(base_url="http://example.com:11434")


def test_settings_shows_the_refusal_in_twelve_languages():
    js = (ROOT / "src/static/app-ai-tools.js").read_text(encoding="utf-8")
    assert 's.port_occupant.state === "refused"' in js
    assert f't("{REFUSED_UI}")' in js
    assert "</p>` + refusedNote + kindNote + logBlock;" in js, "the note is part of what the box shows"
    for path in sorted((ROOT / "src/static/locales").glob("*.json")):
        table = json.loads(path.read_text(encoding="utf-8"))
        assert table.get(REFUSED_UI), f"{path.name} lacks the refusal sentence"


@pytest.mark.parametrize("url", ("http://127.0.0.1:99999", "http://127.0.0.1:abc"))
def test_a_malformed_port_is_reported_not_raised_and_nothing_is_contacted(monkeypatch, network_calls, url):
    monkeypatch.setenv("OO_VLLM_URL", url)
    occ = V.port_occupant(timeout=1.0)
    assert occ["state"] == "unknown"
    assert occ["port"] == 0
    assert "OO_VLLM_URL" in occ["detail"]
    assert network_calls == []


def test_an_empty_setting_means_the_default_address(monkeypatch):
    from src.llm.vllm_client import DEFAULT_VLLM_URL

    monkeypatch.setenv("OO_VLLM_URL", "")
    assert V.base_url() == DEFAULT_VLLM_URL
