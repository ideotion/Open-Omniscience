"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

HTTP-level tests for the LLM endpoints (finding TEST-05, 0.0.8 WP4). The
existing test_llm_ollama.py covers the OllamaClient itself; these exercise the
FastAPI layer through the documented get_llm_client dependency override --
no Ollama and no network involved.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from src.api.llm import get_llm_client
from src.api.main import app
from src.database.models import Article, Source
from src.database.session import init_db, session_scope
from src.llm.ollama import GenerationResult, LLMUnavailable


class _FakeOllama:
    """Stands in for OllamaClient: deterministic, offline, honest-shaped."""

    def __init__(self, available: bool = True):
        self._available = available
        self.base_url = "http://127.0.0.1:11434"
        self.calls: list[tuple] = []

    def is_available(self) -> bool:
        return self._available

    def list_installed(self) -> list[dict]:
        if not self._available:
            raise LLMUnavailable("Ollama not reachable (fake)")
        return [{"name": "llama3.2:3b", "size": 2_000_000_000}]

    def generate(self, prompt, *, model="llama3.2:3b", system=None, options=None):
        if not self._available:
            raise LLMUnavailable("Ollama not reachable (fake)")
        self.calls.append((prompt, model, system))
        return GenerationResult(model=model, text=f"FAKE[{prompt[:24]}]")


def _override(fake):
    app.dependency_overrides[get_llm_client] = lambda: fake


def teardown_function(_fn):
    app.dependency_overrides.pop(get_llm_client, None)


def _seed_article() -> int:
    init_db()
    with session_scope() as s:
        domain = f"llm-{uuid.uuid4().hex[:8]}.example"
        src = Source(name=f"LLM {domain}", domain=domain, language="en")
        s.add(src)
        s.flush()
        a = Article(
            url=f"https://{domain}/a",
            canonical_url=f"https://{domain}/a",
            source_id=src.id,
            title="An article about rivers",
            content="A long body about rivers and floods. " * 30,
            language="en",
            hash=uuid.uuid4().hex + uuid.uuid4().hex,
        )
        s.add(a)
        s.flush()
        return a.id


def test_health_reports_available_with_models():
    _override(_FakeOllama(available=True))
    with TestClient(app) as client:
        r = client.get("/api/llm/health")
        assert r.status_code == 200
        body = r.json()
        assert body["available"] is True
        assert body["installed_models"]


def test_generate_round_trip():
    fake = _FakeOllama()
    _override(fake)
    with TestClient(app) as client:
        r = client.post("/api/llm/generate", json={"prompt": "say hi"})
        assert r.status_code == 200
        assert r.json()["text"].startswith("FAKE[")
        assert fake.calls  # the prompt actually reached the client


def test_generate_503_when_ollama_down():
    _override(_FakeOllama(available=False))
    with TestClient(app) as client:
        r = client.post("/api/llm/generate", json={"prompt": "say hi"})
        assert r.status_code == 503
        assert "not reachable" in r.json()["detail"].lower()


def test_summarize_stores_provenance_and_404s_on_unknown_article():
    fake = _FakeOllama()
    _override(fake)
    art_id = _seed_article()
    with TestClient(app) as client:
        r = client.post(f"/api/llm/articles/{art_id}/summarize", json={})
        assert r.status_code == 200
        body = r.json()
        assert body["result"].startswith("FAKE[")
        assert body.get("model")  # provenance: which model produced it

        r404 = client.post("/api/llm/articles/99999999/summarize", json={})
        assert r404.status_code == 404


def test_translate_includes_target_language_in_prompt():
    fake = _FakeOllama()
    _override(fake)
    art_id = _seed_article()
    with TestClient(app) as client:
        r = client.post(
            f"/api/llm/articles/{art_id}/translate", json={"target_language": "French"}
        )
        assert r.status_code == 200
        # the prompt the client received must carry the requested language
        assert any("French" in (p or "") + (s or "") for p, _m, s in fake.calls)
