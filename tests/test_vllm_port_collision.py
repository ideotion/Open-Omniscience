"""vLLM's port must never be the app's own (field report 2026-08-02).

"Installing vLLM on a new machine fails." The install had in fact SUCCEEDED --
the journal shipped days earlier said so outright: outcome=installed, exit 0,
resolver=uv, fallback_fired=False, 2943 s. What failed was the SERVER, and the
cause was a flat default:

    vllm_lifecycle.DEFAULT_PORT = 8000        # vLLM
    main.py:2412  os.getenv("OO_PORT", "8000")  # the app itself

Both wanted 127.0.0.1:8000. Two consequences, both reproduced before the fix:

  * `vllm serve` could never bind -- OSError(98) Address already in use. No
    machine that completed an install could ever start the server. It stayed
    latent only because, until that machine, none had.
  * The health probe then asked the APP whether it was vLLM. The app has no
    /v1/models route, so it answered 404 -- 270 times in one session in the
    field bundle -- and is_running() reported "vLLM is down" when the truth was
    "vLLM cannot live here".

Deriving from OO_PORT rather than hardcoding 8001 is the point: a collision
cannot be reintroduced by moving the app.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

import http.server
import re
import socket
import threading
from pathlib import Path

import pytest

from src.llm import vllm_lifecycle as V
from src.llm.vllm_client import default_vllm_port, default_vllm_url

_ROOT = Path(__file__).resolve().parents[1]


def _retire(s: http.server.HTTPServer) -> None:
    """Stop a test server AND release its port.

    Both calls, and ``server_close`` is the load-bearing one. ``shutdown()`` stops the
    serve_forever loop and leaves the LISTENING SOCKET BOUND -- verified directly: after
    ``shutdown()`` alone the port still accepts connections, and only ``server_close()``
    refuses them. Without it this fixture held vLLM's OWN port for the whole remaining
    pytest process, and every later test that called ``start()`` was refused with
    "port 8001 is already taken by another server". That refusal was correct: production
    code was reading a genuinely occupied port. The defect was here.

    A named helper rather than two lines inline, so the pairing is something a test can
    hold onto -- see ``test_retiring_a_test_server_frees_its_port``."""
    s.shutdown()
    s.server_close()


@pytest.fixture
def server_on():
    """A non-vLLM HTTP server, i.e. what the app looks like to the probe."""
    servers = []

    def _start(port: int):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not Found")

            def log_message(self, *a):
                pass

        s = http.server.HTTPServer(("127.0.0.1", port), H)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        servers.append(s)
        return s

    yield _start
    for s in servers:
        _retire(s)


def _app_default_port() -> int:
    """The app's own default, read from its source rather than duplicated here --
    if main.py ever changes it, this test must move with it, not silently pass."""
    src = (_ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    m = re.search(r'os\.getenv\(\s*["\']OO_PORT["\']\s*,\s*["\'](\d+)["\']\s*\)', src)
    assert m, "could not find the app's OO_PORT default in main.py"
    return int(m.group(1))


def test_vllm_port_is_never_the_apps_port(monkeypatch):
    monkeypatch.delenv("OO_VLLM_PORT", raising=False)
    monkeypatch.delenv("OO_PORT", raising=False)
    assert default_vllm_port() != _app_default_port()


@pytest.mark.parametrize("app_port", ["8000", "9000", "1234"])
def test_the_derivation_follows_the_app_and_never_collides(monkeypatch, app_port):
    """Hardcoding 8001 would re-collide the moment the operator moved the app."""
    monkeypatch.delenv("OO_VLLM_PORT", raising=False)
    monkeypatch.setenv("OO_PORT", app_port)
    assert default_vllm_port() != int(app_port)
    assert str(default_vllm_port()) in default_vllm_url()


def test_an_explicit_override_still_wins(monkeypatch):
    monkeypatch.setenv("OO_PORT", "8000")
    monkeypatch.setenv("OO_VLLM_PORT", "8123")
    assert default_vllm_port() == 8123


def test_a_malformed_override_does_not_reinstate_the_collision(monkeypatch):
    """Falling back to a flat 8000 on bad input would restore the exact bug."""
    monkeypatch.setenv("OO_PORT", "8000")
    for bad in ("", "0", "-1", "99999", "eight thousand"):
        monkeypatch.setenv("OO_VLLM_PORT", bad)
        assert default_vllm_port() != 8000, f"{bad!r} collapsed back onto the app's port"


def test_server_argv_carries_the_derived_port_not_the_apps(monkeypatch):
    monkeypatch.delenv("OO_VLLM_PORT", raising=False)
    monkeypatch.setenv("OO_PORT", "8000")
    argv = V.server_argv("a-model")
    assert "--port" in argv
    assert argv[argv.index("--port") + 1] == str(default_vllm_port())
    assert "8000" not in argv


# --------------------------------------------------------------------------- #
# port_occupant(): "down" and "occupied" are different diagnoses.
# --------------------------------------------------------------------------- #
def test_a_free_port_reads_as_not_started_not_as_broken(monkeypatch):
    monkeypatch.delenv("OO_VLLM_URL", raising=False)
    occ = V.port_occupant(timeout=1.0)
    assert occ["state"] == "free"
    assert occ["port"] == default_vllm_port()


def test_a_foreign_server_is_named_rather_than_reported_as_vllm_being_down(
    monkeypatch, server_on
):
    """The whole field defect: something answered, and we called it 'vLLM down'."""
    monkeypatch.delenv("OO_VLLM_URL", raising=False)
    server_on(default_vllm_port())
    occ = V.port_occupant(timeout=1.0)
    assert occ["state"] == "foreign"
    assert "not vLLM" in occ["detail"]
    # is_running() stays False -- correct, but now it is no longer the ONLY signal.
    assert V.is_running(timeout=1.0) is False


def test_start_refuses_a_doomed_launch_instead_of_spawning_into_a_taken_port(
    monkeypatch, server_on
):
    monkeypatch.delenv("OO_VLLM_URL", raising=False)
    monkeypatch.setattr("src.llm.backend.detect_gpu", lambda: {"available": True, "vram_mb": 8188})
    # Past the is-it-installed gate: that check is CORRECTLY first (no point
    # naming a port problem on a machine with no vLLM), but the subject here is
    # the port refusal, which only the installed case reaches.
    monkeypatch.setattr(V, "is_installed", lambda: True)
    server_on(default_vllm_port())

    def must_not_spawn(*a, **k):
        raise AssertionError("start() spawned a server that could never bind")

    with pytest.raises(V.VllmLifecycleError) as exc:
        V.start("a-model", popen=must_not_spawn)
    assert "already taken" in str(exc.value)


def test_status_surfaces_who_is_on_the_port(monkeypatch):
    monkeypatch.setattr("src.llm.backend.detect_gpu", lambda: {"available": False})
    st = V.status()
    assert "port_occupant" in st
    assert st["port_occupant"]["state"] in {"vllm", "foreign", "free", "unknown"}



# --------------------------------------------------------------------------- #
# The fixture's own hygiene (2026-08-06). A leaked listening socket does not fail
# HERE -- it fails in some other file, twenty minutes into the suite, as a source
# defect that is not one. So pin it where it can be read.
# --------------------------------------------------------------------------- #
def _accepts(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def test_retiring_a_test_server_frees_its_port():
    """Drives the real teardown helper the fixture uses.

    Deleting ``server_close()`` from ``_retire`` fails this immediately, which is the
    whole point: the leak it prevents is otherwise invisible until an unrelated test
    calls ``start()`` and is refused."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(404)
            self.end_headers()

        def log_message(self, *a):
            pass

    s = http.server.HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    assert _accepts(port), "the server must really be up, or this proves nothing"
    _retire(s)
    assert not _accepts(port), (
        "the port is still bound after teardown -- shutdown() alone leaks it, and the "
        "next test to want this port is refused by production code that is right"
    )
