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

    def list_installed(self):
        if not self._available:
            raise LLMUnavailable("Ollama not reachable (fake)")
        return ["llama3.2:3b"]

    def list_installed_detailed(self):
        if not self._available:
            raise LLMUnavailable("Ollama not reachable (fake)")
        return [{"tag": "llama3.2:3b", "size_gb": 2.0, "modified": "2026-06-01T00:00:00Z"}]

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


# --- corpus synthesis (0.0.8 part 2, WP4 / RM-12) ----------------------------- #


def test_synthesize_carries_member_provenance_and_stores_per_member():
    fake = _FakeOllama()
    _override(fake)
    ids = [_seed_article() for _ in range(3)]
    with TestClient(app) as client:
        r = client.post("/api/llm/synthesize", json={"article_ids": ids})
        assert r.status_code == 200
        body = r.json()
        assert body["member_ids"] == sorted(ids)
        assert body["member_count"] == 3
        assert body["prompt_version"] == "synthesis-v1"
        assert "never a verdict" in body["caveat"] or "asserts nothing" in body["caveat"]
        # exactly ONE generation call (bounded fan-out by construction)
        assert len(fake.calls) == 1
        prompt = fake.calls[0][0]
        assert "[1]" in prompt and "[3]" in prompt  # numbered excerpts
    from src.database.models import ArticleAnalysis
    from src.database.session import session_scope

    with session_scope() as s:
        stored = (
            s.query(ArticleAnalysis)
            .filter(ArticleAnalysis.kind == "synthesis",
                    ArticleAnalysis.article_id.in_(ids))
            .all()
        )
        assert len(stored) == 3  # provenance stored per member


def test_synthesize_caps_explicit_ids_at_20():
    _override(_FakeOllama())
    with TestClient(app) as client:
        r = client.post("/api/llm/synthesize", json={"article_ids": list(range(1, 22))})
        assert r.status_code == 400
        assert "At most 20" in r.json()["detail"]


def test_synthesize_503_when_ollama_down():
    _override(_FakeOllama(available=False))
    art = _seed_article()
    with TestClient(app) as client:
        r = client.post("/api/llm/synthesize", json={"article_ids": [art]})
        assert r.status_code == 503


def test_synthesize_requires_a_selection():
    _override(_FakeOllama())
    with TestClient(app) as client:
        assert client.post("/api/llm/synthesize", json={}).status_code == 400


# --- model catalog honesty (0.0.8 part 2: model-list freshness + picker) ------ #


def test_models_endpoint_carries_as_of_and_hardware_fit():
    _override(_FakeOllama(available=True))
    with TestClient(app) as client:
        r = client.get("/api/llm/models")
        assert r.status_code == 200
        body = r.json()
        assert body["catalog_as_of"]  # the suggested list is date-stamped
        assert body["installed"] and body["installed"][0]["tag"] == "llama3.2:3b"
        # every catalog entry is annotated with a hardware-fit hint
        assert all("fit" in m for m in body["catalog"])
        assert {m["fit"] for m in body["catalog"]} <= {"fits", "tight", "too_large", "unknown"}
