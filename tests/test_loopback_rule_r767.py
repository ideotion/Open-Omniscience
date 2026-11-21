"""R767 (row 235): the local AI talks only to a loopback literal or exactly ``localhost``, and ``localhost``'s
answer is itself checked on the socket.

* ``ip6-localhost``, ``ip6-loopback`` and ``localhost.localdomain`` are refused, and the refusal names the literal.
* Inside :func:`loopback_only`, a connect to a non-loopback ADDRESS is refused before the real socket call, even
  when the name was ``localhost`` (a resolver that answers ``localhost`` with a public address).
* A connect handed a NAME inside the scope is refused: it would resolve in C, out of sight.
* Outside the scope nothing changes (the check is inert).
"""

from __future__ import annotations

import socket
from pathlib import Path

import httpx
import pytest

from src.ingest import airplane as ap
from src.ingest.loopback_scope import (
    LoopbackConnectRefused,
    check_loopback_connect,
    in_scope,
    loopback_only,
)
from src.llm import loopback as L

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = "203.0.113.7"


@pytest.fixture(autouse=True)
def _online():
    """Kill switch OFF, so the airplane gate cannot be what refuses: the loopback check must."""
    from src.ingest import activate_kill_switch, clear_kill_switch, kill_switch_active

    was = kill_switch_active()
    clear_kill_switch()
    yield
    (activate_kill_switch if was else clear_kill_switch)()


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:11434", "http://127.5.6.7:8000", "http://[::1]:8000", "http://localhost:8000", "http://LOCALHOST/"],
)
def test_loopback_literals_and_localhost_are_accepted(url):
    assert L.is_loopback_url(url)
    assert L.loopback_refusal(url, setting="OO_OLLAMA_URL") is None
    assert L.alias_literal(url) is None


@pytest.mark.parametrize(
    ("alias", "literal"),
    [("ip6-localhost", "[::1]"), ("ip6-loopback", "[::1]"), ("localhost.localdomain", "127.0.0.1"),
     ("LOCALHOST.LOCALDOMAIN", "127.0.0.1")],
)
def test_aliases_are_refused_and_the_refusal_names_the_literal(alias, literal):
    url = f"http://{alias}:8000"
    assert not L.is_loopback_url(url)
    why = L.loopback_refusal(url, setting="OO_VLLM_URL")
    assert why and "OO_VLLM_URL" in why and f"Use {literal} instead" in why and "hosts file" in why
    assert L.alias_literal(url) == literal


@pytest.mark.parametrize(
    "url",
    ["http://example.com", "http://localhost.example.com", "http://127.0.0.1.evil.example", f"http://{PUBLIC}",
     "http://0.0.0.0", "http://[::]", "not a url", ""],
)
def test_everything_else_is_refused_with_the_general_reason(url):
    why = L.loopback_refusal(url, setting="OO_OLLAMA_URL")
    assert why and "must be loopback" in why


def test_the_clients_refuse_an_alias_before_any_request():
    from src.llm.ollama import LLMError, OllamaClient
    from src.llm.vllm_client import VllmClient

    with pytest.raises(LLMError, match=r"Use \[::1\] instead"):
        VllmClient(base_url="http://ip6-localhost:8000")
    with pytest.raises(LLMError, match="Use 127.0.0.1 instead"):
        OllamaClient(base_url="http://localhost.localdomain:11434")


# --- the socket-level check -------------------------------------------------------------------------------------


def test_the_check_is_inert_outside_the_scope():
    assert not in_scope()
    check_loopback_connect((PUBLIC, 80))
    check_loopback_connect(("example.com", 80))


@pytest.mark.parametrize("address", [(PUBLIC, 80), ("10.0.0.1", 80), ("::ffff:203.0.113.7", 80, 0, 0), ("example.com", 80),
                                     ("localhost", 80), ("ip6-localhost", 80), (None, 80), 12345,
                                     ("127.0.0.1%evil.example", 80), ("[127.0.0.1]", 80)])
def test_inside_the_scope_only_a_loopback_address_passes(address):
    with loopback_only():
        assert in_scope()
        with pytest.raises(LoopbackConnectRefused):
            check_loopback_connect(address)
        check_loopback_connect(("127.0.0.1", 80))
        check_loopback_connect(("::1", 80, 0, 0))
    assert not in_scope()


@pytest.mark.parametrize("url", ["http://127.0.0.1%25evil.example:11434", "http://[127.0.0.1]:8000"])
def test_a_literal_with_a_suffix_is_a_name_not_a_literal(url):
    assert not L.is_loopback_url(url)


def test_inside_the_scope_nothing_but_this_computer_is_looked_up(monkeypatch):
    asked: list[object] = []
    real = ap._orig_getaddrinfo
    ap.ensure_loopback_guard_installed()
    monkeypatch.setattr(ap, "_orig_getaddrinfo", lambda host, *a, **k: asked.append(host) or real(host, *a, **k))
    with loopback_only():
        for name in ("example.com", "localhost.localdomain", PUBLIC, "127.0.0.1%x"):
            with pytest.raises(LoopbackConnectRefused):
                socket.getaddrinfo(name, 80)
        socket.getaddrinfo("localhost", 80)
        socket.getaddrinfo("127.0.0.1", 80)
    assert asked == ["localhost", "127.0.0.1"], "a refused name never reached the resolver"
    socket.getaddrinfo("127.0.0.1", 80)  # outside the scope: unchanged


def test_localhost_by_name_passes_only_where_its_answers_are_checked_next():
    with loopback_only():
        check_loopback_connect(("localhost", 80), name_allowed=True)
        with pytest.raises(LoopbackConnectRefused):
            check_loopback_connect(("localhost.localdomain", 80), name_allowed=True)


def _lying_localhost(monkeypatch):
    """The resolver answers localhost with a public address; returns the list of addresses the REAL connect saw."""
    real_gai = ap._orig_getaddrinfo

    def lying(host, port, *a, **k):
        if str(host).lower() == "localhost":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, port))]
        return real_gai(host, port, *a, **k)

    reached: list[object] = []
    real_connect, real_connect_ex = ap._orig_connect, ap._orig_connect_ex

    def connect(self, address):
        reached.append(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        reached.append(address)
        return real_connect_ex(self, address)

    ap.ensure_loopback_guard_installed()
    monkeypatch.setattr(ap, "_orig_getaddrinfo", lying)
    monkeypatch.setattr(ap, "_orig_connect", connect)
    monkeypatch.setattr(ap, "_orig_connect_ex", connect_ex)
    return reached


def test_a_localhost_answering_a_public_address_is_never_connected(monkeypatch):
    reached = _lying_localhost(monkeypatch)
    with loopback_only(), pytest.raises(OSError):
        socket.create_connection(("localhost", 9), timeout=0.5)
    assert reached == [], "a public answer for localhost reached the real connect"


def test_outside_the_scope_the_same_answer_is_not_this_checks_business(monkeypatch):
    """Control: the refusal above is the scope's, not some other gate's -- outside it the connect is attempted."""
    reached = _lying_localhost(monkeypatch)
    with pytest.raises(OSError):
        socket.create_connection(("localhost", 9), timeout=0.2)
    assert reached and reached[0][0] == PUBLIC


def test_connect_ex_loopback_refuses_a_public_answer_for_localhost(monkeypatch):
    reached = _lying_localhost(monkeypatch)
    assert L.connect_ex_loopback("localhost", 9, timeout=0.5) is None
    assert reached == []


def test_connect_ex_loopback_reaches_a_real_loopback_listener():
    """Control: the probe is not vacuous -- a loopback listener IS found."""
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        # A backlog with room for every probe: nothing accepts here, and on macOS a full loopback backlog answers a
        # connect with EAGAIN (35), which read as "nothing listening" on the CI's second probe.
        srv.listen(16)
        port = srv.getsockname()[1]
        assert L.connect_ex_loopback("127.0.0.1", port, timeout=1.0) == 0
        assert L.connect_ex_loopback("localhost", port, timeout=1.0) == 0


def test_the_local_ai_transport_refuses_a_public_address_before_connecting(monkeypatch):
    reached = _lying_localhost(monkeypatch)
    with httpx.Client(transport=L.LoopbackTransport(), trust_env=False) as client:
        with pytest.raises(httpx.ConnectError):
            client.get(f"http://{PUBLIC}:9/", timeout=0.5)
        with pytest.raises(httpx.ConnectError):
            client.get("http://localhost:9/", timeout=0.5)
    assert reached == [] and not in_scope(), "nothing reached the real connect, and the scope never leaks"


def test_both_clients_use_the_loopback_transport():
    for path in ("src/llm/ollama.py", "src/llm/vllm_client.py"):
        src = (ROOT / path).read_text(encoding="utf-8")
        assert "transport=_loopback_transport()" in src, f"{path} must send every request through the loopback scope"


# --- the vLLM probe and the Settings note -----------------------------------------------------------------------


def test_the_vllm_probe_names_the_literal_for_an_alias(monkeypatch):
    from src.llm import vllm_lifecycle as V

    calls: list[object] = []
    monkeypatch.setattr(socket.socket, "connect_ex", lambda self, a: calls.append(a) or 111)
    monkeypatch.setenv("OO_VLLM_URL", "http://ip6-localhost:8000")
    occ = V.port_occupant(timeout=0.5)
    assert occ["state"] == "refused" and occ["use_instead"] == "[::1]" and "hosts file" in occ["detail"]
    assert calls == [], "an alias is refused before any connect"


ALIAS_UI = (
    "This vLLM address uses a name that is on this computer only if its hosts file says so; otherwise it is looked "
    "up on the internet, so the app does not contact it. Use this address instead:"
)


def test_settings_names_the_literal_in_twelve_languages():
    import json

    js = (ROOT / "src/static/app-ai-tools.js").read_text(encoding="utf-8")
    assert f't("{ALIAS_UI}")' in js and "occ.use_instead" in js
    tables = sorted((ROOT / "src/static/locales").glob("*.json"))
    assert len(tables) == 12
    for path in tables:
        table = json.loads(path.read_text(encoding="utf-8"))
        assert table.get(ALIAS_UI), f"{path.name} lacks the alias sentence"
        if path.stem != "en":
            assert table[ALIAS_UI] != ALIAS_UI, f"{path.name} is untranslated"
