"""
End-to-end: drive ingestion through the API, then find the result via search.

This is the working-prototype loop (Phase 1 Definition of Done): add a source ->
POST ingest (ethical fetch -> extract -> dedup -> store) -> GET search returns it.
HTTP layer is real (TestClient); the network is faked; the DB is isolated.
"""

from __future__ import annotations

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.ingestion import get_fetcher
from src.api.main import app
from src.database.fts import ensure_fts
from src.database.models import Base, Source
from src.database.session import get_db
from src.ingest import EthicalFetcher


class _Resp:
    def __init__(self, status_code=200, text="", content_type="text/html", url=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode()
        self.headers = {"Content-Type": content_type}
        self.url = url


class _Session:
    def __init__(self, routes):
        self.headers = {}
        self._routes = routes

    def get(self, url, timeout=None, allow_redirects=True):
        if url in self._routes:
            kw = dict(self._routes[url])
            return _Resp(url=url, **kw)
        return _Resp(status_code=404, text="nf", url=url)


def _html(title, body):
    return (f"<html><head><title>{title}</title></head><body><article><h1>{title}</h1>"
            f"<p>{(body + ' ') * 30}</p></article></body></html>")


@pytest.fixture()
def client(tmp_path):
    # A file DB (not :memory:) so every connection sees the same schema/data.
    engine = create_engine(f"sqlite:///{tmp_path / 'ing.db'}", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    ensure_fts(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="Example", domain="example.com", language="en"))
        s.commit()

    routes = {
        "https://example.com/robots.txt": dict(status_code=404, text=""),
        "https://example.com/story":
            dict(text=_html("Corruption Exposed", "An investigation into public funds.")),
    }
    fetcher = EthicalFetcher(min_interval_s=0.0, session=_Session(routes))

    def _db():
        db = Sess()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_fetcher] = lambda: fetcher
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_ingest_then_search_roundtrip(client):
    # 1. Ingest a single URL.
    r = client.post("/api/ingest", json={"source_id": 1, "url": "https://example.com/story"})
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "stored"
    article_id = r.json()["article_id"]
    assert article_id

    # 2. It is now findable via Boolean full-text search.
    r = client.get("/api/articles", params={"query": "corruption AND funds"})
    data = r.json()
    assert data["total"] == 1
    assert data["results"][0]["title"] == "Corruption Exposed"

    # 3. Re-ingesting the same URL is a no-op duplicate.
    r = client.post("/api/ingest", json={"source_id": 1, "url": "https://example.com/story"})
    assert r.json()["result"] == "duplicate"


def test_ingest_unknown_source_404(client):
    r = client.post("/api/ingest", json={"source_id": 999, "url": "https://example.com/story"})
    assert r.status_code == 404


def test_ingest_source_without_rss_400(client):
    r = client.post("/api/sources/1/ingest")
    assert r.status_code == 400
