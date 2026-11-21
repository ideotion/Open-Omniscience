"""Row 234: an ``OO_OLLAMA_URL`` on another computer is refused with its reason, and no local daemon is spawned for it.

Before: ``ollama_lifecycle.is_running`` and ``backend._ollama_available`` swallowed the loopback refusal, so a remote
address read as "Ollama is NOT reachable" (a stopped daemon), ``can_launch`` stayed True, and the Launch button ran
``ollama serve`` here -- a local process the app would never talk to. Now the SAME rule every local-AI call obeys
(``src.llm.ollama._loopback_refusal``, which ``_require_loopback`` raises; R762 for vLLM) is said where the state is
reported, ``can_launch`` is False, and ``start()`` raises the refusal before the binary is even looked up.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import src.llm.backend as backend_mod
import src.llm.ollama_lifecycle as life

ROOT = Path(__file__).resolve().parents[1]
# A public address, a name, an empty setting, and a malformed one (urlparse raises on an unclosed "["): all fail closed.
REMOTE_URLS = ("http://203.0.113.7:11434", "http://ollama.example.com:11434", "", "http://[::1")
REFUSED_UI = (
    "This Ollama address is not on this computer, so the app does not contact it and does not start Ollama for it. "
    "The local AI only talks to this computer: set OO_OLLAMA_URL to 127.0.0.1, localhost or ::1."
)


@pytest.fixture(autouse=True)
def _online():
    """The kill switch OFF, so the airplane socket guard cannot be what stops a connect: the lifecycle must."""
    from src.ingest import activate_kill_switch, clear_kill_switch, kill_switch_active

    was = kill_switch_active()
    clear_kill_switch()
    yield
    if was:
        activate_kill_switch()
    else:
        clear_kill_switch()


@pytest.fixture
def fake_ollama(tmp_path, monkeypatch):
    """A real executable 'ollama' on PATH, so the binary check passes and only the address can refuse."""
    b = tmp_path / ("ollama.exe" if sys.platform == "win32" else "ollama")
    b.write_text("#!/bin/sh\nsleep 300\n", encoding="utf-8")
    b.chmod(b.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    assert shutil.which("ollama") is not None
    return b


@pytest.fixture
def network_calls(monkeypatch):
    """Every resolution and connect THIS test's thread makes, recorded; a remote one is refused here so a regression cannot
    egress. Another thread's (a background job an earlier test left running in this worker) is passed through unrecorded:
    the code under test is synchronous, and counting a stranger's socket would make the test fail for the wrong reason."""
    calls: list[tuple[str, object]] = []
    real_getaddrinfo = socket.getaddrinfo
    real_create = socket.create_connection
    real_connect = socket.socket.connect
    mine = threading.get_ident()

    def _is_local(host) -> bool:
        return str(host) in {"127.0.0.1", "::1", "localhost"}

    def getaddrinfo(host, *a, **k):
        if threading.get_ident() != mine:
            return real_getaddrinfo(host, *a, **k)
        calls.append(("getaddrinfo", host))
        if not _is_local(host):
            raise socket.gaierror("test: remote lookup refused")
        return real_getaddrinfo(host, *a, **k)

    def create_connection(address, *a, **k):
        if threading.get_ident() != mine:
            return real_create(address, *a, **k)
        calls.append(("create_connection", address))
        if not _is_local(address[0]):
            raise ConnectionRefusedError("test: remote connect refused")
        return real_create(address, *a, **k)

    def connect(self, address):
        if threading.get_ident() != mine:
            return real_connect(self, address)
        calls.append(("connect", address))
        if isinstance(address, tuple) and not _is_local(address[0]):
            raise ConnectionRefusedError("test: remote connect refused")
        return real_connect(self, address)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(socket.socket, "connect", connect)
    return calls


@pytest.fixture
def spawned(monkeypatch):
    """Every Popen, recorded and never run."""
    seen: list[tuple] = []

    def _popen(*a, **k):
        seen.append(a)
        raise AssertionError("test: nothing may be spawned for a refused address")

    monkeypatch.setattr(subprocess, "Popen", _popen)
    monkeypatch.setattr(life, "_proc", None)
    return seen


def _remote(monkeypatch, url: str) -> None:
    monkeypatch.setenv("OO_OLLAMA_URL", url)


@pytest.mark.parametrize("url", REMOTE_URLS)
def test_start_refuses_a_remote_address_and_spawns_nothing(url, monkeypatch, fake_ollama, spawned, network_calls):
    _remote(monkeypatch, url)
    with pytest.raises(life.OllamaLifecycleError) as exc:
        life.start()
    assert "OO_OLLAMA_URL must be loopback" in str(exc.value)
    assert spawned == [] and network_calls == []


def test_the_refusal_comes_before_the_binary_check(monkeypatch, tmp_path, spawned):
    """With no binary AND a remote address, the address is the reason given: installing Ollama would not help."""
    monkeypatch.setenv("PATH", str(tmp_path))
    _remote(monkeypatch, REMOTE_URLS[0])
    with pytest.raises(life.OllamaLifecycleError, match="must be loopback"):
        life.start()


@pytest.mark.parametrize("url", REMOTE_URLS)
def test_state_says_why_and_offers_no_launch(url, monkeypatch, fake_ollama, network_calls):
    _remote(monkeypatch, url)
    st = life.state()
    assert st["installed"] is True and st["running"] is False
    assert st["refused"] and "OO_OLLAMA_URL must be loopback" in st["refused"]
    assert st["can_launch"] is False
    assert network_calls == []


def test_release_vram_names_the_refusal(monkeypatch, fake_ollama, network_calls):
    _remote(monkeypatch, REMOTE_URLS[1])
    out = life.release_vram()
    assert out["attempted"] is False and "must be loopback" in out["reason"]
    assert network_calls == []


def test_a_loopback_address_is_not_refused_and_stays_launchable(monkeypatch, fake_ollama):
    """The control: the refusal is not vacuous -- a loopback address passes and can be launched."""
    monkeypatch.setenv("OO_OLLAMA_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr(life, "is_running", lambda **kw: False)
    assert life.refusal() is None
    st = life.state()
    assert st["refused"] is None and st["can_launch"] is True


def test_the_lifecycle_judges_the_address_the_client_uses(monkeypatch):
    """One address, one rule: the lifecycle refuses exactly when ``OllamaClient`` would."""
    from src.llm.ollama import LLMError, OllamaClient

    for url in (*REMOTE_URLS, "http://127.0.0.1:11434", "http://localhost:11434/"):
        monkeypatch.setenv("OO_OLLAMA_URL", url)
        try:
            OllamaClient(timeout=0.1)._client.close()
            client_refuses = False
        except LLMError:
            client_refuses = True
        assert (life.refusal() is not None) is client_refuses, url
    monkeypatch.delenv("OO_OLLAMA_URL")
    assert life.refusal() is None


@pytest.mark.parametrize("override", [None, "ollama", "vllm"])
def test_resolve_backend_names_the_refusal_not_a_down_daemon(override, monkeypatch, fake_ollama, network_calls):
    _remote(monkeypatch, REMOTE_URLS[0])
    monkeypatch.setattr(backend_mod, "_vllm_status", lambda: {"installed": False, "running": False})
    monkeypatch.setattr(backend_mod, "_stored_backend_override", lambda: None)
    monkeypatch.delenv("OO_LLM_BACKEND", raising=False)
    res = backend_mod.resolve_backend(override=override)
    assert res["ollama"]["refused"] and res["ollama"]["can_launch"] is False
    if override != "vllm":
        assert "Ollama is NOT contacted" in res["reason"] and "must be loopback" in res["reason"]
        assert "NOT reachable" not in res["reason"]
    assert res["ollama_available"] is False
    assert network_calls == []


def test_resolve_backend_keeps_the_old_wording_for_a_stopped_local_daemon(monkeypatch, fake_ollama):
    monkeypatch.setenv("OO_OLLAMA_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr(backend_mod, "_ollama_available", lambda: False)
    monkeypatch.setattr(backend_mod, "_vllm_status", lambda: {"installed": False, "running": False})
    monkeypatch.setattr(backend_mod, "_stored_backend_override", lambda: None)
    monkeypatch.delenv("OO_LLM_BACKEND", raising=False)
    res = backend_mod.resolve_backend()
    assert "Ollama is NOT reachable" in res["reason"]
    assert res["ollama"]["refused"] is None and res["ollama"]["can_launch"] is True


def test_the_launch_endpoint_answers_409_with_the_reason(monkeypatch, fake_ollama, spawned):
    from fastapi import HTTPException

    from src.api.llm import ollama_start

    _remote(monkeypatch, REMOTE_URLS[0])
    with pytest.raises(HTTPException) as exc:
        ollama_start()
    assert exc.value.status_code == 409
    assert "must be loopback" in json.dumps(exc.value.detail)
    assert spawned == []


def test_settings_says_it_in_every_language():
    js = (ROOT / "src/static/app-ai-tools.js").read_text(encoding="utf-8")
    assert "oll.refused" in js and json.dumps(REFUSED_UI)[1:-1] in js
    for path in sorted((ROOT / "src/static/locales").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get(REFUSED_UI), path.name
        assert "OO_OLLAMA_URL" in data[REFUSED_UI], path.name


def test_sign_in_details_in_the_address_are_never_quoted(monkeypatch):
    """urlparse can take part of the userinfo for the host (an unencoded "/" ends the authority), so none of it is shown."""
    for url in ("http://sk-SECRET123/x@evil.example:11434", "http://user:pw@evil.example:11434"):
        _remote(monkeypatch, url)
        said = life.refusal()
        assert said and "sign-in details (not shown)" in said
        assert "secret" not in said.lower() and "pw" not in said and "evil" not in said


def test_activation_blocks_on_the_refusal_and_offers_no_start(monkeypatch, fake_ollama, spawned):
    from src.llm import activation

    _remote(monkeypatch, REMOTE_URLS[0])
    cands = activation._candidates()
    assert cands["ollama"]["refused"]
    plan = activation._plan_for("ollama", "test", cands, None)
    assert plan["can_start"] is False and "must be loopback" in plan["blocker"]


def test_the_gpu_handover_refuses_before_releasing_anything(monkeypatch, spawned):
    from src.llm import arbitration

    released: list[str] = []
    monkeypatch.setattr(arbitration, "release_backend", lambda b: released.append(b) or {"backend": b})
    monkeypatch.setattr(arbitration, "free_vram_mb", lambda: None)
    _remote(monkeypatch, REMOTE_URLS[0])
    out = arbitration.hand_gpu_to("ollama")
    assert released == [] and out["ready"] is False
    assert "must be loopback" in out["reason"]


def test_stop_and_release_name_the_refusal(monkeypatch, fake_ollama, network_calls):
    from src.api.llm import ollama_release

    monkeypatch.setattr(life, "_proc", None)  # not one this app spawned (another test may leave a handle behind)
    _remote(monkeypatch, REMOTE_URLS[0])
    out = life.stop()
    assert out["stopped"] is False and "must be loopback" in out["reason"]
    rel = ollama_release()
    assert rel["attempted"] is False and "must be loopback" in rel["reason"] and not rel.get("deferred")
    assert network_calls == []


def test_with_no_binary_the_address_is_still_the_reason_given(monkeypatch, tmp_path, network_calls):
    """Second security read of row 234: release_vram and the bench's wake named "not installed" before the refusal."""
    from src.ai_layer import model_bench

    monkeypatch.setenv("PATH", str(tmp_path))  # no ollama binary anywhere
    monkeypatch.delenv("OO_LLM_AUTOSTART", raising=False)
    _remote(monkeypatch, REMOTE_URLS[0])
    out = life.release_vram()
    assert out["attempted"] is False and "must be loopback" in out["reason"]
    woke = model_bench._default_wake("ollama")
    assert woke["woken"] is False and "must be loopback" in woke["reason"]
    assert network_calls == []


def test_the_gpu_handover_refuses_without_a_start_too(monkeypatch, spawned):
    from src.llm import arbitration

    released: list[str] = []
    monkeypatch.setattr(arbitration, "release_backend", lambda b: released.append(b) or {"backend": b})
    monkeypatch.setattr(arbitration, "free_vram_mb", lambda: None)
    _remote(monkeypatch, REMOTE_URLS[0])
    out = arbitration.hand_gpu_to("ollama", start=False)
    assert released == [] and out["ready"] is False and "must be loopback" in out["reason"]
