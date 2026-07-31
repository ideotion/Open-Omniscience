"""
vLLM sampling-option mapping: Ollama-style ``options`` -> OpenAI-compatible body.

Before 2026-07-31 ``VllmClient.generate`` accepted ``options`` purely for signature
parity with ``OllamaClient.generate`` and dropped it -- so a caller asking for
``temperature: 0`` silently got the server's default sampling on the GPU backend.
No test could catch it, because catching it needed a running vLLM server.

The mapping is therefore a PURE function, and these tests exercise it directly plus
assert that the request body actually carries the mapped fields (via a stub
transport, so still no server).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import httpx
import pytest

from src.llm.vllm_client import VllmClient, openai_sampling_params

# -- the pure mapping ------------------------------------------------------- #


def test_temperature_zero_survives_the_falsiness_trap():
    """0 is the value a determinism-seeking caller cares most about.

    A naive ``if value:`` filter would drop exactly this one.
    """
    params, dropped = openai_sampling_params({"temperature": 0})
    assert params == {"temperature": 0}
    assert dropped == []


def test_every_exact_equivalent_is_mapped():
    params, dropped = openai_sampling_params(
        {
            "temperature": 0.2,
            "top_p": 0.9,
            "seed": 42,
            "stop": ["\n\n"],
            "presence_penalty": 0.1,
            "frequency_penalty": 0.3,
        }
    )
    assert params == {
        "temperature": 0.2,
        "top_p": 0.9,
        "seed": 42,
        "stop": ["\n\n"],
        "presence_penalty": 0.1,
        "frequency_penalty": 0.3,
    }
    assert dropped == []


def test_num_predict_becomes_max_tokens_but_negatives_are_dropped():
    """Ollama overloads negatives (-1 unlimited, -2 fill context).

    Omitting max_tokens IS "no explicit bound", which is what -1 means -- sending
    ``max_tokens: -1`` would be a bogus bound the caller never asked for.
    """
    params, dropped = openai_sampling_params({"num_predict": 256})
    assert params == {"max_tokens": 256}
    assert dropped == []

    for sentinel in (-1, -2):
        params, dropped = openai_sampling_params({"num_predict": sentinel})
        assert params == {}, f"num_predict={sentinel} must not become a max_tokens bound"
        assert dropped == ["num_predict"]


def test_non_equivalent_knobs_are_dropped_and_reported_never_approximated():
    """repeat_penalty must NOT be silently mapped onto frequency_penalty.

    They use different formulations and ranges; approximating one as the other
    would change sampling in a way the caller did not request.
    """
    params, dropped = openai_sampling_params(
        {"temperature": 0, "repeat_penalty": 1.1, "num_ctx": 8192, "mirostat": 2}
    )
    assert params == {"temperature": 0}, "only the exact equivalent may be sent"
    assert "frequency_penalty" not in params
    assert sorted(dropped) == ["mirostat", "num_ctx", "repeat_penalty"]


def test_vllm_only_extensions_are_dropped_not_smuggled_in():
    """top_k is outside the OpenAI chat-completions spec; a strict server 400s."""
    params, dropped = openai_sampling_params({"top_k": 40, "repetition_penalty": 1.05})
    assert params == {}
    assert sorted(dropped) == ["repetition_penalty", "top_k"]


@pytest.mark.parametrize("empty", [None, {}])
def test_absent_options_send_nothing(empty):
    assert openai_sampling_params(empty) == ({}, [])


def test_explicit_none_is_unset_not_a_value():
    params, dropped = openai_sampling_params({"temperature": None, "top_p": 0.5})
    assert params == {"top_p": 0.5}
    assert dropped == []


# -- the request body actually carries them --------------------------------- #


def _stub_client(captured: dict) -> VllmClient:
    """A VllmClient whose transport records the request body instead of sending it."""

    def _handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "m",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    c = VllmClient(base_url="http://127.0.0.1:8000")
    c._client = httpx.Client(
        transport=httpx.MockTransport(_handler), base_url="http://127.0.0.1:8000"
    )
    return c


def test_generate_puts_temperature_in_the_request_body():
    """The end-to-end property the old code broke: the knob reaches the wire."""
    captured: dict = {}
    client = _stub_client(captured)
    client.generate("hello", model="m", options={"temperature": 0, "seed": 7})
    assert captured.get("temperature") == 0, f"temperature absent from body: {captured}"
    assert captured.get("seed") == 7


def test_generate_without_options_sends_no_sampling_fields():
    """Byte-compatible with the previous body when no options are passed."""
    captured: dict = {}
    client = _stub_client(captured)
    client.generate("hello", model="m")
    assert set(captured) == {"model", "messages", "stream"}
