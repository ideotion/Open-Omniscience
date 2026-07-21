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
from src.database.models import Article, Base, Source
from src.database.session import get_db
from src.llm.ollama import LLMUnavailable, OllamaClient


def _client_with(handler, *, base_url: str = "http://testollama") -> OllamaClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url=base_url)
    return OllamaClient(client=http, base_url=base_url)


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
        return httpx.Response(
            200, json={"models": [{"name": "llama3.2:3b"}, {"name": "gemma2:2b"}]}
        )

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


def test_pull_streams_progress_objects():
    def handler(request):
        assert request.url.path == "/api/pull"
        body = b'{"status":"pulling manifest"}\n{"status":"downloading","completed":5}\n{"status":"success"}\n'
        return httpx.Response(200, content=body)

    client = _client_with(handler)
    progress = list(client.pull("llama3.2:3b"))
    assert progress[0]["status"] == "pulling manifest"
    assert progress[-1]["status"] == "success"
    assert any(p.get("completed") == 5 for p in progress)


def test_remove_deletes_and_404_is_loud():
    def ok(request):
        assert request.method == "DELETE" and request.url.path == "/api/delete"
        return httpx.Response(200, json={})

    assert _client_with(ok).remove("gemma2:2b") is True

    def missing(request):
        return httpx.Response(404, json={"error": "model not found"})

    with pytest.raises(LLMUnavailable):
        _client_with(missing).remove("nope:1b")


# --------------------------------------------------------------------------- #
# kill switch + loopback constraint (audit PR C — privacy/safety hardening)
# --------------------------------------------------------------------------- #


def test_kill_switch_allows_loopback_generation_and_list():
    """Airplane mode must NOT block LOOPBACK Ollama inference (2026-07-20 field
    report / ruling): the local model does no network I/O of its own, so list and
    generate against a loopback base_url proceed even while the kill switch is
    engaged."""
    from src.ingest import activate_kill_switch, clear_kill_switch

    def handler(request):
        if request.url.path == "/api/generate":
            return httpx.Response(200, json={"response": "a summary.", "eval_count": 3})
        return httpx.Response(200, json={"models": [{"name": "llama3.2:3b"}]})

    client = _client_with(handler, base_url="http://127.0.0.1:11434")
    activate_kill_switch()
    try:
        assert client.list_installed() == ["llama3.2:3b"]
        out = client.generate("hi", model="llama3.2:3b")
        assert out.text == "a summary."
    finally:
        clear_kill_switch()


def test_kill_switch_blocks_non_loopback_base_url_even_for_generate():
    """A non-loopback base_url is still refused under airplane mode, even for
    list/generate -- the loopback allowance is conditioned on the target actually
    being loopback (defense in depth for a misconfigured/injected client)."""
    from src.ingest import activate_kill_switch, clear_kill_switch
    from src.llm.ollama import LLMUnavailable

    called = {"n": 0}

    def handler(request):
        called["n"] += 1
        return httpx.Response(200, json={"models": [{"name": "llama3.2:3b"}]})

    client = _client_with(handler, base_url="http://evil.example")
    activate_kill_switch()
    try:
        with pytest.raises(LLMUnavailable) as exc:
            client.list_installed()
        assert "Turn airplane mode off" in str(exc.value)
        with pytest.raises(LLMUnavailable):
            client.generate("hi", model="llama3.2:3b")
        assert called["n"] == 0, "no Ollama request may be attempted while offline"
    finally:
        clear_kill_switch()
    # Cleared again -> the same client works (the gate is not sticky).
    assert client.list_installed() == ["llama3.2:3b"]


def test_kill_switch_blocks_pull_and_remove():
    """Airplane mode must refuse model pull/remove too — no socket while offline
    (the pull would egress over clearnet, exactly what airplane mode forbids)."""
    from src.ingest import activate_kill_switch, clear_kill_switch

    called = {"n": 0}

    def handler(request):
        called["n"] += 1
        return httpx.Response(200, json={})

    client = _client_with(handler)
    activate_kill_switch()
    try:
        with pytest.raises(LLMUnavailable):
            list(client.pull("llama3.2:3b"))  # generator: kill-switch fires on first iter
        with pytest.raises(LLMUnavailable):
            client.remove("llama3.2:3b")
        assert called["n"] == 0, "no Ollama request may be attempted while offline"
    finally:
        clear_kill_switch()


def test_non_loopback_ollama_url_refused():
    """A non-loopback OO_OLLAMA_URL must fail LOUDLY when WE open the socket —
    the local LLM never talks to a remote host (privacy by construction)."""
    from src.llm.ollama import LLMError, OllamaClient

    for bad in (
        "http://evil.example:11434",
        "http://10.0.0.5:11434",
        "http://[::ffff:8.8.8.8]",
        # Hostname-prefix bypass regression: these merely START WITH "127." as a
        # string but are ordinary DNS names, not loopback addresses -- a naive
        # `.startswith("127.")` check wrongly accepted them (a crafted
        # OO_OLLAMA_URL could then egress to whatever IP the attacker's DNS
        # resolves them to).
        "http://127.0.0.1.evil.example:11434",
        "http://127.evil.com:11434",
        "http://127.0.0.1evil.com:11434",
    ):
        with pytest.raises(LLMError):
            OllamaClient(base_url=bad)  # client=None -> we open the socket -> enforced
    # Loopback forms are accepted.
    for ok in ("http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434"):
        OllamaClient(base_url=ok)


# --------------------------------------------------------------------------- #
# API tests
# --------------------------------------------------------------------------- #


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'llm.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="S", domain="s.example"))
        s.flush()
        s.add(
            Article(
                url="https://s.example/a",
                canonical_url="https://s.example/a",
                source_id=1,
                title="Town budget",
                content="The town approved its budget.",
                hash="a".ljust(64, "0"),
            )
        )
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


def test_pull_endpoint_streams_ndjson(client):
    c, mk = client

    def ok(request):
        assert request.url.path == "/api/pull"
        return httpx.Response(200, content=b'{"status":"pulling"}\n{"status":"success"}\n')

    app.dependency_overrides[get_llm_client] = lambda: mk(ok)
    r = c.post("/api/llm/pull", json={"model": "gemma2:2b"})
    assert r.status_code == 200
    assert "ndjson" in r.headers.get("content-type", "")
    lines = [ln for ln in r.text.splitlines() if ln.strip()]
    assert lines[-1] == '{"status":"success"}'


def test_remove_endpoint_ok(client):
    c, mk = client

    def ok(request):
        return httpx.Response(200, json={})

    app.dependency_overrides[get_llm_client] = lambda: mk(ok)
    r = c.post("/api/llm/remove", json={"model": "gemma2:2b"})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_pull_remove_reject_bad_model_name(client):
    c, mk = client

    def boom(request):  # must never be reached — validation rejects first
        raise AssertionError("no Ollama call for an invalid model name")

    app.dependency_overrides[get_llm_client] = lambda: mk(boom)
    for path in ("/api/llm/pull", "/api/llm/remove"):
        assert c.post(path, json={"model": "../etc/passwd"}).status_code == 400
        assert c.post(path, json={"model": ""}).status_code == 400


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
    assert body["prompt_version"] == "summary-v2"  # provenance: prompt version
    assert body["created_at"]  # provenance: when
    assert "budget" in body["result"].lower()


def test_summarize_unknown_article_404(client):
    c, mk = client
    app.dependency_overrides[get_llm_client] = lambda: mk(
        lambda r: httpx.Response(200, json={"response": "x"})
    )
    assert c.post("/api/llm/articles/999/summarize", json={}).status_code == 404
