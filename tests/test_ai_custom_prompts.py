"""
User-defined AI extractors (maintainer ask 2026-06-18): a managed list of custom prompts,
each producing TYPED AI metadata — AiKeyword rows of its ``output_kind``, the unified,
prompt-related store. CRUD + an on-demand run; the trusted rule-based index is never
written. No Ollama/network — the LLM client is a deterministic stub.
"""

from __future__ import annotations

import json
import uuid

from fastapi.testclient import TestClient

from src.api.llm import get_llm_client
from src.api.main import app
from src.database.models import Article, KeywordMention, Source
from src.database.session import init_db, session_scope
from src.llm.ollama import GenerationResult, LLMUnavailable


class _FakeOllama:
    def __init__(self, text: str = "", *, unavailable: bool = False):
        self.base_url = "http://127.0.0.1:11434"
        self._text = text
        self._unavailable = unavailable
        self.calls: list[tuple] = []

    def generate(self, prompt, *, model="m", system=None, options=None, keep_alive=None):
        self.calls.append((prompt, model, system))
        if self._unavailable:
            raise LLMUnavailable("offline (fake)")
        return GenerationResult(model=model, text=self._text)


def _seed_article() -> int:
    init_db()
    with session_scope() as s:
        domain = f"cp-{uuid.uuid4().hex[:8]}.example"
        src = Source(name=f"CP {domain}", domain=domain, language="en")
        s.add(src)
        s.flush()
        a = Article(
            url=f"https://{domain}/a", canonical_url=f"https://{domain}/a",
            source_id=src.id, title="Budget article",
            content="The agency spent five million and two billion last year. " * 10,
            language="en", hash=uuid.uuid4().hex + uuid.uuid4().hex,
        )
        s.add(a)
        s.flush()
        return a.id


def _client() -> TestClient:
    init_db()  # ensure ai_custom_prompt + ai_keyword exist in the (conftest plaintext) store
    return TestClient(app)


def teardown_function(_fn):
    app.dependency_overrides.pop(get_llm_client, None)


def test_custom_prompt_crud():
    c = _client()
    r = c.post("/api/ai/prompts", json={
        "label": "Monetary figures", "output_kind": "figure",
        "prompt_text": "List every monetary figure mentioned, one per line.",
        "run_on_ingest": False,
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert r.json()["output_kind"] == "figure"

    listed = c.get("/api/ai/prompts").json()["prompts"]
    assert any(p["id"] == pid and p["label"] == "Monetary figures" for p in listed)

    u = c.put(f"/api/ai/prompts/{pid}", json={
        "label": "Figures", "output_kind": "figure",
        "prompt_text": "List monetary figures.", "run_on_ingest": True, "enabled": True,
    })
    assert u.status_code == 200 and u.json()["run_on_ingest"] is True and u.json()["label"] == "Figures"

    d = c.delete(f"/api/ai/prompts/{pid}")
    assert d.status_code == 200 and d.json()["deleted"] is True
    assert all(p["id"] != pid for p in c.get("/api/ai/prompts").json()["prompts"])
    assert c.delete(f"/api/ai/prompts/{pid}").status_code == 404  # already gone


def test_custom_prompt_validation():
    c = _client()
    assert c.post("/api/ai/prompts", json={
        "label": "X", "output_kind": "Not A Kind!", "prompt_text": "do it"}).status_code == 422
    assert c.post("/api/ai/prompts", json={
        "label": "", "output_kind": "figure", "prompt_text": "do it"}).status_code == 422


def test_run_custom_prompt_writes_typed_ai_metadata_only():
    aid = _seed_article()
    c = _client()
    pid = c.post("/api/ai/prompts", json={
        "label": "Figures", "output_kind": "figure",
        "prompt_text": "List monetary figures, one per line."}).json()["id"]

    fake = _FakeOllama(text="five million\ntwo billion")
    app.dependency_overrides[get_llm_client] = lambda: fake
    r = c.post(f"/api/ai/prompts/{pid}/run", json={"article_ids": [aid]})
    assert r.status_code == 200
    events = [json.loads(line) for line in r.text.splitlines() if line.strip()]
    done = events[-1]
    assert done["event"] == "done" and done["stored"] == 1 and done["terms"] == 2

    # the custom system prompt was actually passed to the model (call = (prompt, model, system))
    assert any("List monetary figures" in (call[2] or "") for call in fake.calls)

    # stored as AI metadata of kind "figure", provenance custom:<id>, unconfirmed
    got = c.get(f"/api/ai/articles/{aid}/keywords?kind=figure").json()
    assert {k["term"] for k in got["keywords"]} == {"five million", "two billion"}
    assert all(k["prompt_version"] == f"custom:{pid}" and not k["confirmed"] for k in got["keywords"])

    # the trusted rule-based index was NOT written for this article
    with session_scope() as s:
        assert s.query(KeywordMention).filter_by(article_id=aid).count() == 0


def test_run_unknown_prompt_is_404():
    c = _client()
    assert c.post("/api/ai/prompts/999999/run", json={"article_ids": [1]}).status_code == 404
