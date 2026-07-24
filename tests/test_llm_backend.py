"""
Tests for the dual-backend LLM resolution (B1, 2026-07-24 field-feedback
Session B, RULED A12: vLLM on GPU machines, Ollama KEPT for the CPU-only
fleet). Backend resolution never touches a real GPU/vLLM/Ollama process --
every probe is monkeypatched.
"""

from __future__ import annotations

import pytest

from src.llm import backend as B
from src.llm.ollama import OllamaClient
from src.llm.vllm_client import VllmClient


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    B._reset_clients_for_tests()
    monkeypatch.delenv("OO_LLM_BACKEND", raising=False)
    yield
    B._reset_clients_for_tests()


def _stub(monkeypatch, *, gpu, vllm_installed, vllm_running, ollama_ok=True):
    monkeypatch.setattr(B, "detect_gpu", lambda: gpu)
    monkeypatch.setattr(
        B, "_vllm_status", lambda: {"installed": vllm_installed, "running": vllm_running}
    )
    monkeypatch.setattr(B, "_ollama_available", lambda: ollama_ok)


# --------------------------------------------------------------------------- #
# LlmBackend Protocol conformance -- both real clients satisfy it structurally.
# --------------------------------------------------------------------------- #
def test_ollama_and_vllm_clients_satisfy_the_protocol_structurally():
    # runtime_checkable Protocol.__instancecheck__ only checks METHOD PRESENCE
    # (not signatures) -- both clients define generate/list_installed/
    # is_available/close, so isinstance() against the Protocol holds.
    ollama = OllamaClient.__new__(OllamaClient)  # no __init__ (avoid real construction)
    vllm = VllmClient.__new__(VllmClient)
    assert isinstance(ollama, B.LlmBackend)
    assert isinstance(vllm, B.LlmBackend)


# --------------------------------------------------------------------------- #
# resolve_backend() -- the decision matrix
# --------------------------------------------------------------------------- #
def test_cpu_only_machine_uses_ollama(monkeypatch):
    _stub(monkeypatch, gpu={"available": False}, vllm_installed=False, vllm_running=False)
    r = B.resolve_backend()
    assert r["backend"] == "ollama"
    assert "no GPU" in r["reason"]


def test_gpu_but_vllm_not_installed_uses_ollama(monkeypatch):
    _stub(monkeypatch, gpu={"available": True, "vram_mb": 8192}, vllm_installed=False, vllm_running=False)
    r = B.resolve_backend()
    assert r["backend"] == "ollama"
    assert "not installed" in r["reason"]


def test_gpu_and_vllm_installed_but_not_running_uses_ollama_meanwhile(monkeypatch):
    _stub(monkeypatch, gpu={"available": True}, vllm_installed=True, vllm_running=False)
    r = B.resolve_backend()
    assert r["backend"] == "ollama"
    assert "not running" in r["reason"]


def test_gpu_installed_and_running_prefers_vllm(monkeypatch):
    _stub(monkeypatch, gpu={"available": True, "vram_mb": 8192}, vllm_installed=True, vllm_running=True)
    r = B.resolve_backend()
    assert r["backend"] == "vllm"
    assert "concurrency" in r["reason"]


def test_explicit_override_ollama_wins_even_with_vllm_ready(monkeypatch):
    _stub(monkeypatch, gpu={"available": True}, vllm_installed=True, vllm_running=True)
    r = B.resolve_backend(override="ollama")
    assert r["backend"] == "ollama"
    assert r["override"] == "ollama"


def test_explicit_override_vllm_wins_even_on_cpu_only(monkeypatch):
    _stub(monkeypatch, gpu={"available": False}, vllm_installed=False, vllm_running=False)
    r = B.resolve_backend(override="vllm")
    assert r["backend"] == "vllm"


def test_env_override_is_honoured_when_no_explicit_override(monkeypatch):
    _stub(monkeypatch, gpu={"available": False}, vllm_installed=False, vllm_running=False)
    monkeypatch.setenv("OO_LLM_BACKEND", "vllm")
    r = B.resolve_backend()
    assert r["backend"] == "vllm"


def test_explicit_override_beats_the_env_var(monkeypatch):
    _stub(monkeypatch, gpu={"available": True}, vllm_installed=True, vllm_running=True)
    monkeypatch.setenv("OO_LLM_BACKEND", "vllm")
    r = B.resolve_backend(override="ollama")
    assert r["backend"] == "ollama"


def test_an_invalid_override_falls_back_to_auto(monkeypatch):
    _stub(monkeypatch, gpu={"available": False}, vllm_installed=False, vllm_running=False)
    r = B.resolve_backend(override="not-a-real-backend")
    assert r["backend"] == "ollama"  # auto behaviour, not an error


# --------------------------------------------------------------------------- #
# get_client() -- one instance per KIND, re-resolved each call
# --------------------------------------------------------------------------- #
def test_get_client_returns_ollama_by_default(monkeypatch):
    _stub(monkeypatch, gpu={"available": False}, vllm_installed=False, vllm_running=False)
    c = B.get_client()
    assert isinstance(c, OllamaClient)


def test_get_client_caches_one_instance_per_kind(monkeypatch):
    _stub(monkeypatch, gpu={"available": False}, vllm_installed=False, vllm_running=False)
    c1 = B.get_client()
    c2 = B.get_client()
    assert c1 is c2


def test_get_client_switches_kind_when_the_decision_changes(monkeypatch):
    _stub(monkeypatch, gpu={"available": False}, vllm_installed=False, vllm_running=False)
    ollama_client = B.get_client()
    assert isinstance(ollama_client, OllamaClient)
    _stub(monkeypatch, gpu={"available": True}, vllm_installed=True, vllm_running=True)
    vllm_client = B.get_client()
    assert isinstance(vllm_client, VllmClient)
    # switching back reuses the SAME cached Ollama instance (never rebuilt).
    _stub(monkeypatch, gpu={"available": False}, vllm_installed=False, vllm_running=False)
    assert B.get_client() is ollama_client


def test_detect_gpu_degrades_honestly_when_nvidia_smi_is_absent(monkeypatch):
    def _raise(*a, **kw):
        raise FileNotFoundError("no nvidia-smi")

    monkeypatch.setattr(B.subprocess, "run", _raise)
    r = B.detect_gpu()
    assert r["available"] is False
    assert "reason" in r
