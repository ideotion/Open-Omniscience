"""
The first AI WRITER: LLM keyword extraction into the SEPARATE AI store.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Proves the end-to-end path — read articles from the main corpus, extract terms with
the local model, write them ONLY to the AI store — and the maintainer-ruled
separation: the trusted, rule-based keyword index in the MAIN database is never
written by this path. No Ollama and no network: the LLM client is a deterministic
stub (the documented get_llm_client override).
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from src.ai_layer import store as ai_store
from src.ai_layer.extract import EXTRACT_PROMPT_VERSION, extract_terms, parse_terms
from src.ai_layer.jobs import ArticleWork, extract_for_articles
from src.api.llm import get_llm_client
from src.api.main import app
from src.database.models import Article, KeywordMention, Source
from src.database.session import init_db, session_scope
from src.llm.ollama import GenerationResult, LLMError, LLMUnavailable


class _FakeOllama:
    """Deterministic, offline stand-in for OllamaClient. ``text`` is the canned model
    output each generate() returns; set ``fail``/``unavailable`` to exercise errors."""

    def __init__(self, text: str = "", *, unavailable: bool = False, fail: bool = False):
        self.base_url = "http://127.0.0.1:11434"
        self._text = text
        self._unavailable = unavailable
        self._fail = fail
        self.calls: list[tuple] = []

    def generate(self, prompt, *, model="m", system=None, options=None, keep_alive=None):
        self.calls.append((prompt, model, system))
        if self._unavailable:
            raise LLMUnavailable("Ollama not reachable (fake)")
        if self._fail:
            raise LLMError("model error (fake)")
        return GenerationResult(model=model, text=self._text)


@pytest.fixture
def ai_store_tmp(tmp_path, monkeypatch):
    """Point the AI store at a throwaway file and reset the cached engine around it."""
    from src.ai_layer import db as aidb

    monkeypatch.setenv("OO_AI_DB_PATH", str(tmp_path / "ai_layer.db"))
    aidb._reset_for_tests()
    yield
    aidb._reset_for_tests()


# --- pure extraction units --------------------------------------------------- #


def test_parse_terms_cleans_markers_dedups_and_bounds():
    raw = (
        "1. Sanctions\n"
        "- oil\n"
        "* OIL\n"            # case-insensitive duplicate of "oil" -> dropped
        "• Central Bank\n"
        '"Ukraine"\n'         # surrounding quotes stripped
        "\n"                   # blank -> dropped
        + ("x" * 90) + "\n"    # too long (a sentence, not a keyword) -> dropped
        + "Nile\nElbe\nRhine\n"
    )
    terms = parse_terms(raw, max_terms=5)
    assert terms == ["Sanctions", "oil", "Central Bank", "Ukraine", "Nile"]  # capped at 5
    assert parse_terms("", max_terms=10) == []
    assert parse_terms(None, max_terms=10) == []


def test_extract_terms_uses_the_client_and_parses():
    fake = _FakeOllama(text="rivers\nfloods\n- Nile\n1. Nile")
    terms = extract_terms(fake, "Title", "Some body text", model="m", max_terms=10)
    assert terms == ["rivers", "floods", "Nile"]  # dup "Nile" collapsed
    # empty content -> no model call, no terms
    assert extract_terms(fake, "T", "   ", model="m") == []
    assert len(fake.calls) == 1


# --- the batch job writes the AI store (and never the main one) -------------- #


def test_extract_for_articles_writes_ai_store_only(ai_store_tmp):
    from src.ai_layer import db as aidb

    aidb.init_ai_db()
    fake = _FakeOllama(text="sanctions\nUkraine\noil")
    work = [ArticleWork(1, "T1", "body one", "en"), ArticleWork(2, "T2", "body two", "fr")]
    events = list(extract_for_articles(work, fake, model="llama3.2:3b", max_terms=10))

    assert events[0]["event"] == "start" and events[0]["total"] == 2
    done = events[-1]
    assert done["event"] == "done" and done["aborted"] is False
    assert done["stored"] == 2 and done["terms"] == 6  # 3 terms x 2 articles

    with aidb.ai_session_scope() as s:
        rows1 = ai_store.keywords_for_article(s, 1)
        assert [r.term for r in rows1] == ["Ukraine", "oil", "sanctions"]
        assert all(r.model == "llama3.2:3b" and r.confirmed is False for r in rows1)
        assert all(r.prompt_version == EXTRACT_PROMPT_VERSION for r in rows1)
        assert ai_store.keywords_for_article(s, 2)[0].language == "fr"


def test_extract_for_articles_skips_already_extracted(ai_store_tmp):
    from src.ai_layer import db as aidb

    aidb.init_ai_db()
    fake = _FakeOllama(text="alpha\nbeta")
    work = [ArticleWork(9, "T", "body", "en")]
    list(extract_for_articles(work, fake, model="m"))  # first run stores
    events = list(extract_for_articles(work, fake, model="m"))  # second run skips
    done = events[-1]
    assert done["stored"] == 0 and done["skipped"] == 1
    assert len(fake.calls) == 1  # the skipped article never hit the model again


def test_extract_for_articles_aborts_when_model_unavailable(ai_store_tmp):
    from src.ai_layer import db as aidb

    aidb.init_ai_db()
    fake = _FakeOllama(unavailable=True)
    work = [ArticleWork(1, "T", "body", "en")]
    events = list(extract_for_articles(work, fake, model="m"))
    done = events[-1]
    assert done["event"] == "done" and done["aborted"] is True and done["stored"] == 0


# --- HTTP: wiring + read/confirm + the feature-level separation proof -------- #


def _seed_article() -> int:
    init_db()
    with session_scope() as s:
        domain = f"ai-{uuid.uuid4().hex[:8]}.example"
        src = Source(name=f"AI {domain}", domain=domain, language="en")
        s.add(src)
        s.flush()
        a = Article(
            url=f"https://{domain}/a",
            canonical_url=f"https://{domain}/a",
            source_id=src.id,
            title="An article about rivers",
            content="A long body about rivers, floods and the Nile. " * 20,
            language="en",
            hash=uuid.uuid4().hex + uuid.uuid4().hex,
        )
        s.add(a)
        s.flush()
        return a.id


def teardown_function(_fn):
    app.dependency_overrides.pop(get_llm_client, None)


def test_extract_endpoint_then_read_and_confirm(ai_store_tmp):
    aid = _seed_article()
    app.dependency_overrides[get_llm_client] = lambda: _FakeOllama(
        text="rivers\nfloods\n- Nile"
    )
    client = TestClient(app)

    # extract → NDJSON stream
    r = client.post("/api/ai/keywords/extract", json={"article_ids": [aid]})
    assert r.status_code == 200
    events = [json.loads(line) for line in r.text.splitlines() if line.strip()]
    assert events[0]["event"] == "start"
    assert events[-1] == {
        "event": "done", "total": 1, "stored": 1, "skipped": 0, "failed": 0,
        "terms": 3, "aborted": False,
    }

    # read the lens
    got = client.get(f"/api/ai/articles/{aid}/keywords")
    assert got.status_code == 200
    body = got.json()
    assert {k["term"] for k in body["keywords"]} == {"rivers", "floods", "Nile"}
    assert body["count"] == 3 and all(not k["confirmed"] for k in body["keywords"])

    # the MAIN, rule-based keyword index was NOT written for this article
    with session_scope() as s:
        assert s.query(KeywordMention).filter_by(article_id=aid).count() == 0

    # confirm-within-the-lens
    kid = body["keywords"][0]["id"]
    cr = client.post("/api/ai/keywords/confirm", json={"id": kid, "confirmed": True})
    assert cr.status_code == 200 and cr.json()["ok"] is True
    confirmed = client.get(f"/api/ai/articles/{aid}/keywords?confirmed_only=true").json()
    assert confirmed["count"] == 1


def test_read_lens_is_side_effect_free_when_store_absent(ai_store_tmp):
    """A read before any AI feature ran returns an empty lens WITHOUT creating the
    store file (no empty encrypted file for users who never use AI)."""
    from src.ai_layer.db import ai_db_path

    client = TestClient(app)
    r = client.get("/api/ai/articles/123456/keywords")
    assert r.status_code == 200 and r.json()["count"] == 0
    assert not ai_db_path().exists()
