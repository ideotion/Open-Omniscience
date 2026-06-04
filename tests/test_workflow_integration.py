"""
Full investigative-workflow integration test.

One test exercises the whole product spine end to end through the HTTP API, the
way an investigator actually uses it, as a regression guard and living example:

    add source -> ethical ingest (RSS) -> Boolean search -> local-LLM summarize
    -> import commodity prices -> honest correlation -> signed evidence bundle
    -> independent verification -> source health.

The network (article fetch) and the LLM are faked; everything else is real.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.ingestion import get_fetcher
from src.api.llm import get_llm_client
from src.api.main import app
from src.database.fts import ensure_fts
from src.database.models import Base, Source
from src.database.session import get_db
from src.ingest import EthicalFetcher
from src.llm.ollama import OllamaClient
from src.reporting.evidence import verify_bundle


def _html(title, body):
    return (f"<html><head><title>{title}</title></head><body><article><h1>{title}</h1>"
            f"<p>{(body + ' ') * 30}</p></article></body></html>")


class _Resp:
    def __init__(self, status_code=200, text="", content_type="text/html"):
        self.status_code = status_code
        self.text = text
        self.content = text.encode()
        self.headers = {"Content-Type": content_type}
        self.url = "http://feed"


class _NetSession:
    def __init__(self, routes):
        self.headers = {}
        self._routes = routes

    def get(self, url, timeout=None, allow_redirects=True):
        return self._routes.get(url) or _Resp(status_code=404, text="nf")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))  # evidence signing key under tmp
    engine = create_engine(f"sqlite:///{tmp_path / 'wf.db'}", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    ensure_fts(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="Fixture", domain="127.0.0.1",
                     rss_url="http://127.0.0.1/feed.xml", language="en"))
        s.commit()

    feed = ("""<?xml version="1.0"?><rss version="2.0"><channel>
      <item><title>Neodymium supply shock</title><link>http://127.0.0.1/a1</link></item>
    </channel></rss>""")
    routes = {
        "http://127.0.0.1/robots.txt": _Resp(404, ""),
        "http://127.0.0.1/feed.xml": _Resp(200, feed, "application/rss+xml"),
        "http://127.0.0.1/a1": _Resp(200, _html(
            "Neodymium supply shock", "Rare earth neodymium prices surged amid export limits.")),
    }
    fetcher = EthicalFetcher(min_interval_s=0.0, session=_NetSession(routes))

    def _llm_handler(request):
        return httpx.Response(200, json={"response": "Neodymium prices surged after export limits."})
    llm = OllamaClient(client=httpx.Client(transport=httpx.MockTransport(_llm_handler),
                                           base_url="http://t"), base_url="http://t")

    def _db():
        db = Sess()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_fetcher] = lambda: fetcher
    app.dependency_overrides[get_llm_client] = lambda: llm
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_full_investigative_workflow(client):
    # 1. Ingest the source's RSS feed (ethical fetch -> extract -> store).
    r = client.post("/api/sources/1/ingest")
    assert r.json()["tally"]["stored"] == 1

    # 2. Find it via Boolean full-text search.
    r = client.get("/api/articles", params={"query": "neodymium AND export"})
    assert r.json()["total"] == 1
    article_id = r.json()["results"][0]["id"]

    # 3. Summarize it with the (faked) local LLM; result persisted with provenance.
    r = client.post(f"/api/llm/articles/{article_id}/summarize", json={})
    assert r.status_code == 200
    assert r.json()["prompt_version"] == "summary-v1"

    # 4. Import commodity prices and correlate with the news (real scipy stats).
    pts = [{"observed_on": f"2026-01-0{d}", "price": 100 + d} for d in range(1, 6)]
    client.post("/api/commodities/Nd/prices", json={"points": pts})
    r = client.get("/api/commodities/Nd/correlation", params={"query": "neodymium"})
    body = r.json()
    assert "caveat" in body and "causation" in body["caveat"].lower()

    # 5. Export a signed evidence bundle for the finding and verify it independently.
    r = client.post("/api/reports/evidence", json={"query": "neodymium", "case_name": "REE"})
    bundle = r.json()
    assert bundle["manifest"]["item_count"] == 1
    ok, reason = verify_bundle(bundle)
    assert ok, reason

    # 6. Source health is a real check (the fetcher returns 200 for the feed).
    r = client.get("/api/monitoring/health")
    assert r.json()["summary"].get("up") == 1
