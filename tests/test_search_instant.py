"""The instant rung's endpoints: first hits from one character, honest about order and coverage.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def seeded(client):
    from src.database.models import Article, Source
    from src.database.session import session_scope

    tag = uuid.uuid4().hex[:10]
    name = f"Instant Gazette {tag}"
    with session_scope() as s:
        src = Source(name=name, domain=f"instantgazette{tag}.example")
        s.add(src)
        s.flush()
        for i in range(14):
            s.add(Article(url=f"https://instantgazette.example/{tag}/{i}", canonical_url=f"https://instantgazette.example/{tag}/{i}",
                          source_id=src.id, title=f"Zorblax report {i}", content=f"body {i}", language="en",
                          hash=f"{tag}{i}".ljust(64, "d"), published_at=datetime.now(UTC)))
        s.add(Article(url=f"https://instantgazette.example/{tag}/q", canonical_url=f"https://instantgazette.example/{tag}/q",
                      source_id=src.id, title="Zorblax quarantined", content="x", language="en", quarantined=True,
                      hash=f"{tag}q".ljust(64, "d")))
    return name


def test_one_character_is_enough_and_the_answer_says_what_it_is(client, seeded):
    r = client.get("/api/search/instant", params={"q": "z", "limit": 5})
    assert r.status_code == 200
    d = r.json()
    assert len(d["hits"]) == 5 and d["more"] is True
    assert d["order"] == "newest-ingested"
    assert "not the best match" in d["caveat"] and d["method"]
    ids = [h["id"] for h in d["hits"]]
    assert ids == sorted(ids, reverse=True)
    assert all(h["source"] == seeded and h["title"].startswith("Zorblax report") for h in d["hits"])  # quarantined left out


def test_narrowing_and_no_match(client, seeded):
    assert len(client.get("/api/search/instant", params={"q": "zorblax report 1"}).json()["hits"]) >= 1
    d = client.get("/api/search/instant", params={"q": "zzzqqq"}).json()
    assert d["hits"] == [] and d["more"] is False


def test_blank_query_is_empty_not_an_error(client, seeded):
    assert client.get("/api/search/instant", params={"q": "  "}).json()["hits"] == []


def test_coverage_is_reported_honestly_until_the_backfill_ran(client, seeded):
    assert client.get("/api/search/instant", params={"q": "z"}).json()["index_complete"] is False
    st = client.get("/api/search/instant/status").json()
    assert st["present"] is True and st["articles"] >= 15


def test_the_build_job_completes_and_marks_the_index_complete(client, seeded):
    from src.api.search_instant import _BUILD_JOB

    r = client.post("/api/search/instant/build")
    assert r.status_code == 200
    _BUILD_JOB.join(30)
    assert client.get("/api/search/instant", params={"q": "z"}).json()["index_complete"] is True
    st = client.get("/api/search/instant/status").json()
    assert st["complete"] is True and st["covered"] == st["articles"]


def test_rebuild_forgets_the_index_and_fills_it_again_from_the_articles(client, seeded):
    from src.api.search_instant import _BUILD_JOB

    client.post("/api/search/instant/build")
    _BUILD_JOB.join(30)
    before = client.get("/api/search/instant/status").json()["covered"]
    assert before >= 15
    assert client.post("/api/search/instant/build", params={"rebuild": "true"}).status_code == 200
    _BUILD_JOB.join(30)
    st = client.get("/api/search/instant/status").json()
    assert st["complete"] is True and st["covered"] == before
    assert len(client.get("/api/search/instant", params={"q": "zorblax"}).json()["hits"]) >= 1
