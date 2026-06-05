"""
Tests for the world-awareness features: local translation + honest framing.

Translation uses the mocked Ollama client (no real model); framing uses real
VADER sentiment + keyword extraction on fixtures and asserts it surfaces SIGNALS
without ever emitting a bias verdict.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.llm import get_llm_client
from src.api.main import app
from src.awareness.framing import compare_framing
from src.database.fts import ensure_fts
from src.database.models import Article, ArticleAnalysis, Base, Source
from src.database.session import get_db
from src.llm.ollama import OllamaClient


# --------------------------------------------------------------------------- #
# framing (pure function)
# --------------------------------------------------------------------------- #

def test_framing_surfaces_tone_and_terms_no_verdict():
    data = {
        "Outlet A": [{"title": "Reform praised", "content": "The landmark reform was praised as a historic success and a triumph.", "url": "a1", "published_at": None}],
        "Outlet B": [{"title": "Reform slammed", "content": "The disastrous reform was slammed as a corrupt failure and a scandal.", "url": "b1", "published_at": None}],
    }
    res = compare_framing(data)
    assert res["sources_compared"] == 2
    by = {f["source"]: f for f in res["framing"]}
    # real, opposite tone signals
    assert by["Outlet A"]["avg_tone"] > 0
    assert by["Outlet B"]["avg_tone"] < 0
    assert by["Outlet A"]["tone_label"] == "positive"
    assert by["Outlet B"]["tone_label"] == "negative"
    assert by["Outlet A"]["top_terms"]
    # honesty: no fabricated bias score/field anywhere -- only measurable signals,
    # and the caveat explicitly disclaims a verdict.
    for f in res["framing"]:
        assert not any("bias" in k or "score" in k for k in f)
    assert "signals" in res["caveat"].lower()
    assert "not a judgement" in res["caveat"].lower()


def test_framing_empty_source_skipped():
    res = compare_framing({"A": [], "B": [{"title": "x", "content": "good news great", "url": "u", "published_at": None}]})
    assert res["sources_compared"] == 1


# --------------------------------------------------------------------------- #
# API: translation + framing
# --------------------------------------------------------------------------- #

@pytest.fixture()
def client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'a.db'}", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    ensure_fts(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        a = Source(name="Le Monde", domain="lemonde.fr", language="fr")
        b = Source(name="Guardian", domain="theguardian.com", language="en")
        s.add_all([a, b]); s.flush()
        s.add_all([
            Article(url="https://lemonde.fr/1", canonical_url="https://lemonde.fr/1", source_id=a.id,
                    title="Élection", content="le scandale de corruption a indigné les électeurs",
                    hash="1".rjust(64, "0"), language="fr"),
            Article(url="https://theguardian.com/2", canonical_url="https://theguardian.com/2", source_id=b.id,
                    title="Election reform", content="the reform was welcomed as a positive step forward",
                    hash="2".rjust(64, "0"), language="en"),
        ])
        s.commit()

    def _db():
        db = Sess()
        try:
            yield db
        finally:
            db.close()

    def _fake_llm():
        def handler(request):
            return httpx.Response(200, json={"response": "Election: the corruption scandal outraged voters."})
        http = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://t")
        return OllamaClient(client=http, base_url="http://t")

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_llm_client] = _fake_llm
    with TestClient(app) as c:
        yield c, Sess
    app.dependency_overrides.clear()


def test_translate_persists_with_provenance(client):
    c, Sess = client
    r = c.post("/api/llm/articles/1/translate", json={"target_language": "English"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "translation"
    assert body["source_language"] == "fr"
    assert body["target_language"] == "English"
    assert body["prompt_version"].startswith("translate-v1")
    assert "corruption" in body["result"].lower()
    with Sess() as s:
        assert s.query(ArticleAnalysis).filter_by(kind="translation").count() == 1


def test_translate_unknown_article_404(client):
    c, _ = client
    assert c.post("/api/llm/articles/999/translate", json={}).status_code == 404


def test_framing_endpoint_groups_by_source(client):
    c, _ = client
    r = c.get("/api/framing")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sources_compared"] == 2
    sources = {f["source"] for f in body["framing"]}
    assert sources == {"Le Monde", "Guardian"}
    assert "signals" in body["caveat"].lower()
