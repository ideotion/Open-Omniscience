"""Installed-vs-running detection, and the Launch control that depends on it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-07-29: "Ollama and vLLM installations should be detectable even when
they have not been started. A 'launch' button would then be made available to the user
to start either service."

vLLM already had this shape. Ollama had neither half: the only predicate in any
availability path was an HTTP probe of the RUNNING daemon, so installed-but-stopped was
indistinguishable from absent — ``backend.py``'s own docstring named the gap — and
nothing in ``src/`` started an Ollama server at all.

The load-bearing case here is the one that used to be unrepresentable: binary present,
daemon down. It is exercised with a REAL executable on a real PATH rather than by
monkeypatching the predicate, because monkeypatching ``is_installed`` would prove only
that the plumbing carries a boolean, not that the detection actually works.
"""

from __future__ import annotations

import os
import stat
import subprocess

import pytest

import src.llm.backend as backend_mod
import src.llm.ollama_lifecycle as life


@pytest.fixture()
def fake_ollama(tmp_path, monkeypatch):
    """A real, executable 'ollama' on a real PATH — so shutil.which genuinely finds it."""
    b = tmp_path / "ollama"
    b.write_text("#!/bin/sh\nsleep 300\n", encoding="utf-8")
    b.chmod(b.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    return b


# --------------------------------------------------------------------------- #
#  detection: installed and running are INDEPENDENT
# --------------------------------------------------------------------------- #
def test_installed_is_true_while_the_daemon_is_down(fake_ollama, monkeypatch):
    """THE case the field report is about. Before this, the app could only ask 'does
    the daemon answer?', so a stopped Ollama reported exactly like an uninstalled one
    and the UI offered no control at all."""
    monkeypatch.setattr(life, "is_running", lambda **kw: False)
    st = life.state()
    assert st["installed"] is True, "the binary is on PATH — that is the INSTALLED fact"
    assert st["running"] is False
    assert st["can_launch"] is True, "installed + stopped is exactly when Launch is honest"
    assert st["path"] == str(fake_ollama)


def test_absent_binary_is_not_launchable(monkeypatch, tmp_path):
    """An empty PATH must yield not-installed, and crucially NOT can_launch — offering
    Launch for software that is not there could only ever fail."""
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(life, "is_running", lambda **kw: False)
    st = life.state()
    assert st["installed"] is False
    assert st["can_launch"] is False
    assert st["path"] is None


def test_a_running_daemon_is_not_launchable(fake_ollama, monkeypatch):
    """Already running ⇒ no Launch button; the control appears only where it does
    something."""
    monkeypatch.setattr(life, "is_running", lambda **kw: True)
    st = life.state()
    assert st["installed"] is True and st["running"] is True
    assert st["can_launch"] is False


def test_a_probe_failure_degrades_to_not_installed_never_raises(monkeypatch):
    def boom():
        raise OSError("PATH unreadable")

    monkeypatch.setattr(life, "binary_path", boom)
    # is_installed calls binary_path; the resolver's wrapper must absorb it.
    assert backend_mod._ollama_installed() is False


# --------------------------------------------------------------------------- #
#  the resolver carries it, in ONE builder
# --------------------------------------------------------------------------- #
def test_resolve_backend_reports_ollama_installed_but_stopped(fake_ollama, monkeypatch):
    monkeypatch.setattr(backend_mod, "_ollama_available", lambda: False)
    monkeypatch.setattr(backend_mod, "_vllm_status", lambda: {"installed": False, "running": False})
    r = backend_mod.resolve_backend()
    assert r["ollama"] == {"installed": True, "running": False, "can_launch": True}
    # ...while the pre-existing flat field keeps its old meaning, so nothing that read
    # it before changes behaviour.
    assert r["ollama_available"] is False
    assert r["no_backend"] is True


def test_every_branch_carries_the_launch_fields(fake_ollama, monkeypatch):
    """The payload is built by ONE helper precisely so a field cannot be present in
    three branches and missing from the fourth. Walk every override to prove it."""
    monkeypatch.setattr(backend_mod, "_ollama_available", lambda: False)
    monkeypatch.setattr(backend_mod, "_vllm_status", lambda: {"installed": True, "running": False})
    for override in (None, "ollama", "vllm", "auto"):
        r = backend_mod.resolve_backend(override=override)
        assert "ollama" in r, f"missing ollama block for override={override!r}"
        assert set(r["ollama"]) == {"installed", "running", "can_launch"}
        assert r["vllm_can_launch"] is True, f"override={override!r}"


def test_vllm_can_launch_tracks_installed_and_not_running(monkeypatch):
    monkeypatch.setattr(backend_mod, "_ollama_available", lambda: False)
    for installed, running, expected in (
        (True, False, True),    # the launchable state
        (True, True, False),    # already up
        (False, False, False),  # nothing to launch
    ):
        monkeypatch.setattr(
            backend_mod, "_vllm_status", lambda i=installed, ru=running: {"installed": i, "running": ru}
        )
        assert backend_mod.resolve_backend()["vllm_can_launch"] is expected, (installed, running)


# --------------------------------------------------------------------------- #
#  launching
# --------------------------------------------------------------------------- #
def test_start_refuses_when_not_installed(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(life.OllamaLifecycleError) as exc:
        life.start()
    assert "not installed" in str(exc.value)


def test_start_is_idempotent_by_probe_and_spawns_nothing(fake_ollama, monkeypatch):
    """The daemon is usually owned by systemd, not by us, so 'already running' must be
    decided by PROBE — an ownership flag would be wrong more often than right. And it
    must not spawn a second server."""
    monkeypatch.setattr(life, "is_running", lambda **kw: True)
    spawned = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: spawned.append(a) or None)
    out = life.start()
    assert out == {"started": False, "reason": "already running", "path": str(fake_ollama)}
    assert spawned == [], "an already-running daemon must not be re-spawned"


def test_start_reports_not_ready_honestly_rather_than_claiming_success(fake_ollama, monkeypatch):
    """A spawned-but-not-yet-answering daemon is the interesting case: reporting
    ready:True would hand the UI a green state the very next call would find
    unreachable."""
    monkeypatch.setattr(life, "is_running", lambda **kw: False)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)
    out = life.start(timeout=0.05)
    assert out["started"] is True
    assert out["ready"] is False, "never a fabricated ready state"
    assert "did not answer" in out["note"]


def test_start_reports_ready_once_the_daemon_answers(fake_ollama, monkeypatch):
    calls = {"n": 0}

    def _running(**kw):
        calls["n"] += 1
        return calls["n"] > 1  # down at the idempotency check, up on the first poll

    monkeypatch.setattr(life, "is_running", _running)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)
    out = life.start(timeout=5)
    assert out == {"started": True, "ready": True, "path": str(fake_ollama)}


def test_start_spawns_a_fixed_argv_with_no_shell(fake_ollama, monkeypatch):
    """Fixed argv from shutil.which, never a shell string — the same discipline the
    verified-binary installer uses."""
    monkeypatch.setattr(life, "is_running", lambda **kw: False)
    seen = {}

    def _popen(argv, **kw):
        seen["argv"] = argv
        seen["kw"] = kw
        return None

    monkeypatch.setattr(subprocess, "Popen", _popen)
    life.start(wait=False)
    assert seen["argv"] == [str(fake_ollama), "serve"]
    assert "shell" not in seen["kw"], "never a shell"
    assert seen["kw"]["stdout"] is subprocess.DEVNULL
    assert seen["kw"]["stderr"] is subprocess.DEVNULL, (
        "an unread pipe fills its buffer and wedges the daemon"
    )


def test_stopping_ollama_only_ever_reaches_a_daemon_this_app_spawned(monkeypatch):
    """The deliberate asymmetry with vLLM, now pinned as BEHAVIOUR rather than absence.

    This test used to assert ``not hasattr(life, "stop")`` and carried its own
    instruction for the day one arrived: "it must only ever kill a process this app
    itself spawned — update this test deliberately, never by reflex". A stop() arrived
    on 2026-08-10, because the automated bench has to hand one GPU between two
    backends, and this is that deliberate update.

    Asserting the absence of a function proved nothing about behaviour; asserting that
    NO SIGNAL IS SENT to a daemon we did not spawn proves the thing the ruling is
    actually about. The reason still holds for such a daemon — it is usually a system
    service shared with everything else on the machine — so the refusal is the feature.
    """
    signalled: list = []
    monkeypatch.setattr(life, "_proc", None)
    monkeypatch.setattr(life, "is_running", lambda **_kw: True)
    monkeypatch.setattr("os.kill", lambda *a, **kw: signalled.append(a))

    out = life.stop()

    assert signalled == [], "a daemon this app did not spawn was signalled"
    assert out["stopped"] is False and out["owned"] is False
    assert "not ours to do" in out["reason"]
    assert "release_vram" in out["reason"], (
        "the refusal must name what DOES free the card, or it is a dead end"
    )
