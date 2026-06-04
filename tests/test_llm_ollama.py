"""
Tests for the Ollama LLM client + API (Action Plan Phase 2).

No real Ollama is needed: httpx is driven through a MockTransport, and the API is
exercised with the client dependency overridden. Proves:
  * loud degradation -- Ollama down => LLMUnavailable / HTTP 503 (never a fake result);
  * a missing model => LLMUnavailable with a 'ollama pull' hint;
  * generation parses the response;
  * summarizing a stored article persists an ArticleAnalysis WITH provenance.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.llm import get_llm_client
from src.api.main import app
from src.database.models import Article, ArticleAnalysis, Base, Source
from src.database.session import get_db
from src.llm.ollama import LLMUnavailable, OllamaClient


def _client_with(handler) -> OllamaClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="http://testollama")
    return OllamaClient(client=http, base_url="http://testollama")


# --------------------------------------------------------------------------- #
# client unit tests
# --------------------------------------------------------------------------- #

def test_unavailable_when_ollama_down():
    def handler(request):
        raise httpx.ConnectError("connection refused")
    client = _client_with(handler)
    assert client.is_available() is False
    with pytest.raises(LLMUnavailable):
        client.list_installed()


def test_list_installed_parses_tags():
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "llama3.2:3b"}, {"name": "gemma2:2b"}]})
    client = _client_with(handler)
    assert client.list_installed() == ["llama3.2:3b", "gemma2:2b"]


def test_generate_parses_response():
    def handler(request):
        assert request.url.path == "/api/generate"
        return httpx.Response(200, json={"response": "  a summary.  ", "eval_count": 7})
    client = _client_with(handler)
    out = client.generate("hi", model="llama3.2:3b")
    assert out.text == "a summary."
    assert out.model == "llama3.2:3b"


def test_missing_model_raises_with_hint():
    def handler(request):
        return httpx.Response(404, json={"error": "model not found"})
    client = _client_with(handler)
    with pytest.raises(LLMUnavailable) as exc:
        client.generate("hi", model="nope:1b")
    assert "ollama pull nope:1b" in str(exc.value)


# --------------------------------------------------------------------------- #
# API tests
# --------------------------------------------------------------------------- #

@pytest.fixture()
def client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'llm.db'}", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="S", domain="s.example"))
        s.flush()
        s.add(Article(url="https://s.example/a", canonical_url="https://s.example/a",
                      source_id=1, title="Town budget", content="The town approved its budget.",
                      hash="a".ljust(64, "0")))
        s.commit()

    def _db():
        db = Sess()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as c:
        yield c, _client_with
    app.dependency_overrides.clear()


def test_health_reports_unavailable_gracefully(client):
    c, mk = client
    def down(request):
        raise httpx.ConnectError("refused")
    app.dependency_overrides[get_llm_client] = lambda: mk(down)
    r = c.get("/api/llm/health")
    assert r.status_code == 200
    assert r.json()["available"] is False


def test_generate_503_when_down(client):
    c, mk = client
    def down(request):
        raise httpx.ConnectError("refused")
    app.dependency_overrides[get_llm_client] = lambda: mk(down)
    r = c.post("/api/llm/generate", json={"prompt": "hi"})
    assert r.status_code == 503


def test_summarize_persists_with_provenance(client):
    c, mk = client
    def ok(request):
        return httpx.Response(200, json={"response": "The town approved its budget for the year."})
    app.dependency_overrides[get_llm_client] = lambda: mk(ok)
    r = c.post("/api/llm/articles/1/summarize", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "summary"
    assert body["model"]  # provenance: which model
    assert body["prompt_version"] == "summary-v1"  # provenance: prompt version
    assert body["created_at"]  # provenance: when
    assert "budget" in body["result"].lower()


def test_summarize_unknown_article_404(client):
    c, mk = client
    app.dependency_overrides[get_llm_client] = lambda: mk(lambda r: httpx.Response(200, json={"response": "x"}))
    assert c.post("/api/llm/articles/999/summarize", json={}).status_code == 404
