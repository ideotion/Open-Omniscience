"""
Tests for the vLLM OpenAI-compatible client (B1, 2026-07-24 field-feedback
Session B). Mirrors ``test_llm_ollama.py``'s MockTransport pattern exactly --
no real vLLM/GPU needed; a stub OpenAI-compatible server proves the chat-
completions mapping, the ``/v1/models`` list, the usage->GenerationResult
remap, a 404-model case, and kill-switch behaviour on both sides of the
loopback/clearnet distinction.
"""

from __future__ import annotations

import httpx
import pytest

from src.llm.ollama import LLMUnavailable
from src.llm.vllm_client import VllmClient


def _client_with(handler, *, base_url: str = "http://testvllm") -> VllmClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url=base_url)
    return VllmClient(client=http, base_url=base_url)


def test_unavailable_when_vllm_down():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    client = _client_with(handler)
    assert client.is_available() is False
    with pytest.raises(LLMUnavailable):
        client.list_installed()


def test_list_installed_parses_openai_models_shape():
    def handler(request):
        assert request.url.path == "/v1/models"
        return httpx.Response(
            200,
            json={"object": "list", "data": [{"id": "solidrust/Mistral-7B-Instruct-v0.3-AWQ"}]},
        )

    client = _client_with(handler)
    assert client.list_installed() == ["solidrust/Mistral-7B-Instruct-v0.3-AWQ"]


def test_list_installed_detailed_has_no_fabricated_size_or_date():
    def handler(request):
        return httpx.Response(200, json={"data": [{"id": "my-model"}]})

    client = _client_with(handler)
    detailed = client.list_installed_detailed()
    assert detailed == [{"tag": "my-model", "size_gb": None, "modified": None}]


def test_generate_maps_chat_completions_and_usage():
    seen = {}

    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        import json as _json

        body = _json.loads(request.content)
        seen["body"] = body
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "choices": [{"message": {"role": "assistant", "content": "  a summary.  "}}],
                "usage": {"prompt_tokens": 42, "completion_tokens": 9},
            },
        )

    client = _client_with(handler)
    out = client.generate("hi", model="my-model", system="be terse")
    assert out.text == "a summary."
    assert out.model == "my-model"
    assert out.prompt_eval_count == 42
    assert out.eval_count == 9
    # vLLM has no per-call unload/reload analog -- never a fabricated timing.
    assert out.total_duration is None
    assert out.load_duration is None
    # system + user both land as chat messages, in order.
    msgs = seen["body"]["messages"]
    assert msgs[0] == {"role": "system", "content": "be terse"}
    assert msgs[1] == {"role": "user", "content": "hi"}


def test_generate_without_system_omits_the_system_message():
    def handler(request):
        import json as _json

        body = _json.loads(request.content)
        assert len(body["messages"]) == 1
        assert body["messages"][0]["role"] == "user"
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}}
        )

    client = _client_with(handler)
    client.generate("hi", model="my-model")


def test_missing_model_raises_llm_unavailable():
    def handler(request):
        return httpx.Response(404, json={"error": "model not found"})

    client = _client_with(handler)
    with pytest.raises(LLMUnavailable):
        client.generate("hi", model="nope")


def test_keep_alive_and_options_are_accepted_but_have_no_effect():
    """Signature parity with OllamaClient.generate -- vLLM keeps a served model
    resident for the server's whole lifetime, so these are silently ignored
    rather than raising a TypeError (so a caller need not branch by backend)."""

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = _client_with(handler)
    out = client.generate("hi", model="m", keep_alive="30m", options={"temperature": 0})
    assert out.text == "ok"


def test_kill_switch_refuses_a_non_loopback_backend_under_airplane_mode(monkeypatch):
    """Defense in depth: the check is skipped for an injected client's own real
    call (no socket ever opens with MockTransport), but the guard itself must
    still fire for a genuinely non-loopback base_url."""
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: True)

    def handler(request):
        raise AssertionError("must never reach the transport under airplane mode")

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="http://example.com")
    client = VllmClient(client=http, base_url="http://example.com")
    with pytest.raises(LLMUnavailable):
        client.list_installed()


def test_loopback_generate_is_airplane_safe(monkeypatch):
    """A loopback vLLM call is NEVER refused by the kill switch (mirrors Ollama's
    airplane/Ollama gate split, Session A §7) -- inference stays local."""
    monkeypatch.setattr("src.ingest.kill_switch_active", lambda: True)

    def handler(request):
        return httpx.Response(200, json={"data": [{"id": "m"}]})

    # _is_loopback_url only recognises real loopback hosts; use a genuinely
    # loopback base_url to prove the "loopback => airplane-safe" path.
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="http://127.0.0.1:8000")
    loopback_client = VllmClient(client=http, base_url="http://127.0.0.1:8000")
    assert loopback_client.list_installed() == ["m"]


def test_constructing_a_real_client_enforces_loopback():
    """Without an injected client, constructing a VllmClient against a remote
    base_url refuses immediately (mirrors OllamaClient's _require_loopback)."""
    from src.llm.ollama import LLMError

    with pytest.raises(LLMError):
        VllmClient(base_url="http://example.com:8000")
