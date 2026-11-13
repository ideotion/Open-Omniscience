"""An Ollama cloud model is refused before any request names it (R671).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Generation talks to the loopback Ollama daemon and airplane mode lets that through, on the premise that local inference does no network
I/O. A cloud model breaks the premise: the daemon forwards the prompt (corpus text) to ollama.com from its own process, where the
socket guard cannot see it. The rule and where it was read in Ollama's source are in ``src/llm/remote_models.py``.

Every refusal here is proved by the requests the fake daemon RECEIVED: a refused model means no ``/api/generate`` and no ``/api/pull``
ever reached it, not only that an exception was raised.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from src.llm import ollama_lifecycle
from src.llm.ollama import LLMUnavailable, OllamaClient, RemoteModelRefused
from src.llm.remote_models import REFUSAL, is_cloud_name, local_entry

_ROOT = Path(__file__).resolve().parents[1]

# Ollama's own cases (internal/modelref ParseRef / parseSourceSuffix at 5632619) plus the edges of the rule.
_CLOUD = [
    "gpt-oss:20b:cloud", "glm-4.6:cloud", "gpt-oss:120b-cloud", "GPT-OSS:120B-CLOUD", "  qwen3-coder:480b-cloud  ",
    "deepseek-v3.1:671b-cloud", "kimi-k2:1t-Cloud", "gpt-oss:20b:cloud:local", "ns/model:cloud",
]
_LOCAL = [
    "llama3.2:3b", "gemma2:2b", "mistral", "registry.example.com:5000/model", "host:5000/x-cloud", "cloud", "qwen:cloudless",
    "my-cloud-model:7b", "gpt-oss:20b:local", "",
]


@pytest.mark.parametrize("name", _CLOUD)
def test_a_cloud_suffixed_name_is_cloud(name):
    assert is_cloud_name(name)


@pytest.mark.parametrize("name", _LOCAL)
def test_a_local_name_is_not_cloud_by_its_name(name):
    assert not is_cloud_name(name)


def _daemon(tags: list[dict] | None, seen: list[str], *, tags_status: int = 200):
    """A fake daemon: answers /api/tags with ``tags`` and /api/generate with a summary, recording every path it is asked."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/api/tags":
            if tags is None:
                raise httpx.ConnectError("connection refused")
            return httpx.Response(tags_status, json={"models": tags})
        if request.url.path == "/api/generate":
            return httpx.Response(200, json={"response": "a summary.", "eval_count": 1})
        return httpx.Response(200, content=b'{"status":"success"}\n')

    base = "http://127.0.0.1:11434"
    return OllamaClient(client=httpx.Client(transport=httpx.MockTransport(handler), base_url=base), base_url=base)


@pytest.mark.parametrize("name", ["gpt-oss:120b-cloud", "glm-4.6:cloud", "gpt-oss:20b:cloud"])
def test_a_cloud_name_never_reaches_the_daemon(name):
    seen: list[str] = []
    client = _daemon([{"name": name, "remote_host": "https://ollama.com:443"}], seen)
    with pytest.raises(RemoteModelRefused) as exc:
        client.generate("corpus text", model=name)
    assert REFUSAL in str(exc.value)
    assert seen == [], "a cloud name must be refused without asking the daemon anything"


def test_a_local_alias_of_a_cloud_model_is_refused_by_its_remote_fields():
    """``ollama create my-model -f`` with FROM a cloud model: any name, forwarded by the daemon. Only /api/tags tells it apart."""
    seen: list[str] = []
    client = _daemon([{"name": "my-model:latest", "model": "my-model:latest", "remote_model": "gpt-oss:120b",
                       "remote_host": "https://ollama.com:443"}], seen)
    with pytest.raises(RemoteModelRefused):
        client.generate("corpus text", model="my-model")
    assert "/api/generate" not in seen and seen == ["/api/tags"]


def test_a_local_model_runs_and_is_checked_first_even_in_airplane_mode():
    from src.ingest import activate_kill_switch, clear_kill_switch

    seen: list[str] = []
    client = _daemon([{"name": "llama3.2:3b", "model": "llama3.2:3b"}], seen)
    activate_kill_switch()
    try:
        out = client.generate("hi", model="llama3.2:3b")
    finally:
        clear_kill_switch()
    assert out.text == "a summary."
    assert seen == ["/api/tags", "/api/generate"]


@pytest.mark.parametrize("asked,listed", [
    ("mistral", "mistral:latest"), ("library/mistral", "mistral:latest"), ("registry.ollama.ai/library/mistral:latest", "mistral:latest"),
    ("Mistral:Latest", "mistral:latest"),
])
def test_a_local_model_is_found_under_the_spellings_the_daemon_accepts(asked, listed):
    assert local_entry(asked, [{"name": listed}])[0] == "local"


def test_a_model_the_daemon_does_not_list_is_refused_as_not_installed():
    seen: list[str] = []
    with pytest.raises(LLMUnavailable) as exc:
        _daemon([{"name": "gemma2:2b"}], seen).generate("hi", model="nope:1b")
    assert not isinstance(exc.value, RemoteModelRefused)
    assert "ollama pull nope:1b" in str(exc.value)
    assert "/api/generate" not in seen


@pytest.mark.parametrize("status", [None, 500])
def test_an_unreadable_model_list_fails_closed(status):
    seen: list[str] = []
    client = _daemon(None if status is None else [], seen, tags_status=status or 200)
    with pytest.raises(LLMUnavailable):
        client.generate("hi", model="llama3.2:3b")
    assert "/api/generate" not in seen


def test_the_picker_and_the_installed_list_never_show_a_remote_model():
    seen: list[str] = []
    tags = [{"name": "llama3.2:3b", "size": 2 * 1024**3}, {"name": "gpt-oss:120b-cloud", "remote_host": "https://ollama.com:443"},
            {"name": "alias:latest", "remote_model": "glm-4.6"}, {"name": "glm-4.6:cloud"}]
    client = _daemon(tags, seen)
    assert client.list_installed() == ["llama3.2:3b"]
    assert [m["tag"] for m in client.list_installed_detailed()] == ["llama3.2:3b"]


def test_pull_and_unload_never_send_a_cloud_name():
    seen: list[str] = []
    client = _daemon([], seen)
    with pytest.raises(RemoteModelRefused):
        list(client.pull("gpt-oss:120b-cloud"))
    assert client.unload("glm-4.6:cloud") is False
    assert seen == []


def test_the_active_model_setting_refuses_a_cloud_model_and_ignores_a_stored_one(tmp_path, monkeypatch):
    from src.config import app_settings

    path = tmp_path / "app_settings.json"
    monkeypatch.setattr(app_settings, "_settings_path", lambda: path)
    with pytest.raises(app_settings.AppSettingsError) as exc:
        app_settings.save_settings({"llm_model": "gpt-oss:120b-cloud"})
    assert REFUSAL in str(exc.value)
    app_settings.save_settings({"llm_model": "llama3.2:3b"})
    assert app_settings.load_settings().llm_model == "llama3.2:3b"
    # a value stored before the rule (written straight to the file) is not used
    path.write_text(json.dumps({**json.loads(path.read_text(encoding="utf-8")), "llm_model": "glm-4.6:cloud"}), "utf-8")
    assert app_settings.load_settings().llm_model is None


def test_the_custom_download_refuses_a_cloud_model_before_the_airplane_check():
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.ingest import activate_kill_switch, clear_kill_switch

    activate_kill_switch()
    try:
        with TestClient(app) as c:
            r = c.post("/api/llm/models/pull-custom", json={"identifier": "gpt-oss:120b-cloud"})
    finally:
        clear_kill_switch()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["queued"] == [] and body["refused"][0]["reason"] == REFUSAL


def test_a_daemon_the_app_starts_has_cloud_turned_off(monkeypatch):
    captured: dict = {}

    class _P:
        pid = 1

        def poll(self):
            return None

    def fake_popen(argv, **kw):
        captured.update(kw)
        return _P()

    monkeypatch.setattr(ollama_lifecycle, "binary_path", lambda: "/usr/bin/ollama")
    monkeypatch.setattr(ollama_lifecycle, "is_running", lambda **k: False)
    monkeypatch.setattr(ollama_lifecycle.subprocess, "Popen", fake_popen)
    monkeypatch.setenv("OLLAMA_NO_CLOUD", "0")
    ollama_lifecycle.start(wait=False)
    assert captured["env"]["OLLAMA_NO_CLOUD"] == "1"


def test_the_refusal_is_keyed_in_every_locale_and_the_ui_mirrors_the_rule():
    for f in sorted((_ROOT / "src/static/locales").glob("*.json")):
        assert REFUSAL in json.loads(f.read_text(encoding="utf-8")), f.name
    js = (_ROOT / "src/static/app-settings.js").read_text(encoding="utf-8")
    assert "function _ooIsCloudModel(" in js
    assert js.index("_ooIsCloudModel(tag)") < js.index('ensureAiEgress(t("Download a model you named')


# -- hardening from the two security reads -------------------------------------------------------------------------------------- #


@pytest.mark.parametrize("models", [
    [{"name": "x:1b"}, {"name": "x:1b", "remote_host": "https://ollama.com:443"}],   # one remote entry is enough, whatever the order
    [{"name": "x:1b", "remote_host": 0}],                                              # present and not empty reads as remote
    [{"name": "x:1b", "remote_model": []}],
])
def test_a_remote_mark_of_any_kind_refuses(models):
    assert local_entry("x:1b", models)[0] == "cloud"


def test_fields_of_odd_types_are_read_as_text_not_raised():
    assert local_entry("5", [{"name": 5}])[0] == "local"
    assert local_entry("llama3.2:3b", [{"name": "llama3.2:3b", "model": 7}])[0] == "local"
    assert not is_cloud_name(5)  # type: ignore[arg-type]


@pytest.mark.parametrize("body", [b"[1, 2]", b'"text"', b'{"models": {"llama3.2:3b": {}}}', b"not json"])
def test_an_odd_model_list_body_fails_closed_as_unavailable(body):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, content=body) if request.url.path == "/api/tags" else httpx.Response(200, json={"response": "x"})

    base = "http://127.0.0.1:11434"
    client = OllamaClient(client=httpx.Client(transport=httpx.MockTransport(handler), base_url=base), base_url=base)
    with pytest.raises(LLMUnavailable):
        client.generate("corpus text", model="llama3.2:3b")
    assert seen == ["/api/tags"]


def test_unload_never_sends_a_remote_alias_or_an_unlisted_name():
    seen: list[str] = []
    client = _daemon([{"name": "alias:latest", "remote_model": "glm-4.6", "remote_host": "https://ollama.com:443"},
                      {"name": "llama3.2:3b"}], seen)
    assert client.unload("alias") is False and seen == ["/api/tags"]
    assert client.unload("nope:1b") is False and seen == ["/api/tags"] * 2
    assert client.unload("llama3.2:3b") is True and seen[-1] == "/api/generate"


def test_pull_names_the_cloud_refusal_even_in_airplane_mode():
    from src.ingest import activate_kill_switch, clear_kill_switch

    seen: list[str] = []
    activate_kill_switch()
    try:
        with pytest.raises(RemoteModelRefused):
            list(_daemon([], seen).pull("glm-4.6:cloud"))
    finally:
        clear_kill_switch()
    assert seen == []


def test_the_vllm_client_refuses_a_cloud_name_with_no_request():
    """A loopback vLLM URL can point at Ollama's own OpenAI-compatible endpoint, which forwards a cloud name too."""
    from src.llm.vllm_client import VllmClient

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    base = "http://127.0.0.1:11434"
    client = VllmClient(client=httpx.Client(transport=httpx.MockTransport(handler), base_url=base), base_url=base)
    with pytest.raises(RemoteModelRefused):
        client.generate("corpus text", model="gpt-oss:120b-cloud")
    assert seen == []
