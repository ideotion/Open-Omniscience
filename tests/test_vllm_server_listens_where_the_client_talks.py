"""Row 247: a vLLM server this app starts listens on the loopback address ``OO_VLLM_URL`` names, read when asked.

``vllm_lifecycle.start()`` passed ``server_argv`` no host or port, so the server listened on the fixed 127.0.0.1 and
``default_vllm_port()`` whatever ``OO_VLLM_URL`` said: an address on another port, or on ``[::1]``, started a server the
client never reached. And ``base_url()`` read the import-time ``DEFAULT_VLLM_URL``, so a later ``OO_VLLM_PORT`` was
unseen by the probe while the client saw it. Now the server listens exactly where ``base_url()`` points, and an address
the server cannot serve (another computer, an unreadable port, port 0, https) starts nothing -- R771's rules for Ollama.
"""

from __future__ import annotations

import pytest

from src.llm import vllm_lifecycle as V

_REAL_PORT_OCCUPANT = V.port_occupant  # taken before the autouse fixture stubs it


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_VLLM_VENV_DIR", str(tmp_path / "vllm_venv"))
    monkeypatch.setattr(V, "data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(V, "port_occupant", lambda **kw: {"state": "free", "port": 0, "detail": "stubbed: free"})
    V._proc = None
    V._history_disabled = False
    V._history_disabled_reason = None
    yield
    V._proc = None
    V._history_disabled = False
    V._history_disabled_reason = None


@pytest.fixture
def spawned(monkeypatch):
    """Every command line ``start()`` would have run; nothing is run."""
    V.venv_python().parent.mkdir(parents=True, exist_ok=True)
    V.venv_python().write_text("#!/bin/sh\n", encoding="utf-8", newline="\n")
    V._write_marker("0.25.1")
    monkeypatch.setattr("src.llm.backend.detect_gpu", lambda: {"available": True, "vram_mb": 8192})
    monkeypatch.setattr(V, "is_running", lambda **kw: False)
    argvs: list[list[str]] = []

    class _Proc:
        def poll(self):
            return None

    def popen(argv, **kw):
        argvs.append(list(argv))
        return _Proc()

    return argvs, popen


def _flag(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


@pytest.mark.parametrize(
    ("url", "host", "port"),
    [
        ("http://127.0.0.1:8123", "127.0.0.1", 8123),
        ("http://127.0.0.1:8123/", "127.0.0.1", 8123),
        ("http://localhost:9001", "localhost", 9001),
        ("http://[::1]:9002", "::1", 9002),
        ("http://127.0.0.1", "127.0.0.1", 80),  # the port the client itself uses
    ],
)
def test_the_server_listens_on_the_configured_loopback_address(url, host, port, monkeypatch, spawned):
    argvs, popen = spawned
    monkeypatch.setenv("OO_VLLM_URL", url)
    assert V.bind_address() == (host, port)
    V.start("my/model", popen=popen)
    assert len(argvs) == 1
    assert (_flag(argvs[0], "--host"), _flag(argvs[0], "--port")) == (host, str(port))


def test_with_no_setting_the_server_listens_where_the_default_client_talks(monkeypatch, spawned):
    from src.llm.vllm_client import default_vllm_port

    argvs, popen = spawned
    monkeypatch.delenv("OO_VLLM_URL", raising=False)
    V.start("my/model", popen=popen)
    assert (_flag(argvs[0], "--host"), _flag(argvs[0], "--port")) == ("127.0.0.1", str(default_vllm_port()))


def test_the_address_is_read_when_asked_not_frozen_at_import(monkeypatch):
    monkeypatch.delenv("OO_VLLM_URL", raising=False)
    monkeypatch.setenv("OO_VLLM_PORT", "8765")
    assert V.base_url() == "http://127.0.0.1:8765"
    assert V.bind_address() == ("127.0.0.1", 8765)


@pytest.mark.parametrize(
    ("url", "said"),
    [
        ("http://203.0.113.7:8001", "must be loopback"),  # another computer (R762)
        ("http://vllm.example.com:8001", "must be loopback"),
        ("http://127.0.0.1:99999", "port"),
        ("http://127.0.0.1:port", "port"),
        ("http://127.0.0.1:0", "port 0"),  # a random port the app never finds
        ("https://127.0.0.1:8001", "http://"),  # started without TLS
        ("http://0.0.0.0:8001", "must be loopback"),  # every interface: never "local"
        ("http://[::]:8001", "must be loopback"),
        ("http://[::1%25lo]:8001", "zone"),  # no server binds a scoped address as written
        ("http://[::1:8001", "OO_VLLM_URL"),  # a broken IPv6 address: a sentence, never a ValueError
        ("http://ip6-localhost:9004", "::1"),  # R767: an alias is refused, naming the literal to use instead
        ("http://localhost.localdomain:9003", "127.0.0.1"),
    ],
)
def test_an_address_the_server_cannot_serve_starts_nothing(url, said, monkeypatch, spawned):
    argvs, popen = spawned

    def must_not_clear(*a, **k):
        raise AssertionError("the GPU was cleared for a server that will not start")

    monkeypatch.setattr(V, "clear_gpu_for_vllm", must_not_clear)
    monkeypatch.setenv("OO_VLLM_URL", url)
    with pytest.raises(V.VllmLifecycleError, match=said):
        V.start("my/model", popen=popen)
    assert argvs == []


def test_a_refusal_never_quotes_sign_in_details(monkeypatch):
    monkeypatch.setenv("OO_VLLM_URL", "http://alice:s3cretpw@203.0.113.7:8001")
    with pytest.raises(V.VllmLifecycleError) as exc:
        V.bind_address()
    assert "s3cretpw" not in str(exc.value) and "alice" not in str(exc.value)


def _listener(family: int, host: str):
    import socket

    s = socket.socket(family)
    s.bind((host, 0))
    # A backlog with room: the probe's own HTTP check connects first and is never accepted, and with a
    # backlog of 1 macOS then refused the raw probe's connect, so a listener read as "free" (CI, macOS).
    s.listen(64)
    return s


@pytest.mark.parametrize(("v6", "host", "shown"), [(True, "::1", "[::1]"), (False, "127.0.0.1", "127.0.0.1")])
def test_the_status_probe_looks_where_the_server_listens(monkeypatch, v6, host, shown):
    """The probe and the server agree: an IPv6 literal is probed with an IPv6 socket, so a listener there is seen."""
    import socket

    if v6 and not socket.has_ipv6:
        pytest.skip("no IPv6 on this machine")
    try:
        srv = _listener(socket.AF_INET6 if v6 else socket.AF_INET, host)
    except OSError:
        pytest.skip(f"{host} cannot be bound here")
    with srv:
        port = srv.getsockname()[1]
        monkeypatch.setenv("OO_VLLM_URL", f"http://{shown}:{port}")
        # This test is about the RAW probe; the HTTP check before it would only fill the queue.
        monkeypatch.setattr("src.llm.vllm_client.VllmClient.is_available", lambda self: False)
        assert V.bind_address() == (host, port)
        occ = _REAL_PORT_OCCUPANT(timeout=1.0)
    assert occ["port"] == port and occ["state"] == "foreign", occ


def _record_probe(monkeypatch) -> list[tuple]:
    """The raw probe's (host, port), through R767's ``connect_ex_loopback``; nothing is connected."""
    import src.llm.loopback as L

    seen: list[tuple] = []

    def probe(host, port, *, timeout):
        seen.append((host, port))
        return 111

    monkeypatch.setattr(L, "connect_ex_loopback", probe)
    return seen


def test_an_address_with_no_port_is_probed_on_the_port_the_server_uses(monkeypatch):
    seen = _record_probe(monkeypatch)
    monkeypatch.setenv("OO_VLLM_URL", "http://127.0.0.1")
    occ = _REAL_PORT_OCCUPANT(timeout=0.2)
    assert occ["port"] == 80 == V.bind_address()[1]
    assert seen == [("127.0.0.1", 80)]


@pytest.mark.parametrize("url", ["http://[::1]:9002", "http://127.0.0.1:9002", "http://localhost:9005"])
def test_the_probe_looks_at_the_address_the_server_listens_on(url, monkeypatch):
    """The raw probe is handed exactly the (host, port) the server is started on (``bind_address``): ``::1`` without
    its brackets, so the socket family follows the address."""
    seen = _record_probe(monkeypatch)
    monkeypatch.setenv("OO_VLLM_URL", url)
    _REAL_PORT_OCCUPANT(timeout=0.2)
    assert seen == [V.bind_address()]


@pytest.mark.parametrize("url", ["http://127.0.0.1:0", "http://[::1:8001", "http://[::1%25lo]:8001"])
def test_the_probe_answers_an_address_it_cannot_use_without_contacting_anything(url, monkeypatch):
    """Port 0 is never probed as 80; a broken or scoped IPv6 address is a sentence, never a ValueError or a connect."""
    import socket

    def no_socket(*a, **k):
        raise AssertionError("a socket was opened for an address the server could not listen on")

    monkeypatch.setattr(socket, "socket", no_socket)
    monkeypatch.setattr(socket, "create_connection", no_socket)
    monkeypatch.setenv("OO_VLLM_URL", url)
    occ = _REAL_PORT_OCCUPANT(timeout=0.2)
    assert occ["state"] in {"unknown", "refused"} and occ["port"] == 0 and occ["detail"], occ


def test_a_start_reads_the_address_once(monkeypatch, spawned):
    """The bind, the occupancy check and the answer name ONE address, even if the setting changes during the start."""
    argvs, popen = spawned
    urls = iter(["http://127.0.0.1:9101", "http://127.0.0.1:9999", "http://127.0.0.1:9999", "http://127.0.0.1:9999"])
    monkeypatch.setattr(V, "base_url", lambda: next(urls))
    probed: list[str | None] = []
    monkeypatch.setattr(V, "port_occupant", lambda **kw: probed.append(kw.get("url")) or {"state": "free", "port": 0, "detail": ""})
    out = V.start("my/model", popen=popen)
    assert _flag(argvs[0], "--port") == "9101"
    assert probed == ["http://127.0.0.1:9101"]
    assert "9101" in out["base_url"]
