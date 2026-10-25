"""
Stored sources named by a bare Wikidata Q-id (qualification lane, 2026-10-25): a local, read-only
report. It fetches nothing, renames nothing and marks nothing; naming the label stays the separate
consented POST /api/sources/resolve-qid-names.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics import quarantine_job as qj
from src.database.models import Article, Base, Source


@pytest.fixture
def world():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, autoflush=False)
    with Session() as s:
        raw = Source(name="Q11858063", domain="ilkka-pohjalainen.fi", enabled=True)
        raw2 = Source(name=" q42 ", domain="example.org", enabled=False)  # whitespace and case tolerated
        named = Source(name="Ilkka-Pohjalainen", domain="ilkka.fi", enabled=True)
        lookalike = Source(name="Q Magazine", domain="q.example", enabled=True)  # not an identifier
        s.add_all([raw, raw2, named, lookalike])
        s.commit()
        for i, src in enumerate([raw, raw, raw, raw2, named]):
            url = f"https://x.example/{i}"
            s.add(Article(url=url, canonical_url=url, source_id=src.id, content="text", hash=f"h{i}",
                          word_count=1, language="fi", title=f"T{i}"))
        s.commit()
    return Session


def _client(monkeypatch, world):
    from src.api.quarantine import router

    monkeypatch.setattr(qj, "_default_session", lambda: world())
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_only_sources_whose_whole_name_is_a_qid_are_listed_with_their_article_counts(world, monkeypatch):
    body = _client(monkeypatch, world).get("/api/quarantine/raw-id-sources").json()
    assert body["examined"] == 4 and body["raw_id_sources"] == 2
    by_name = {r["name"]: r for r in body["rows"]}
    assert set(by_name) == {"Q11858063", " q42 "}
    assert by_name["Q11858063"]["articles"] == 3 and by_name[" q42 "]["articles"] == 1
    assert by_name[" q42 "]["enabled"] is False
    assert body["articles_in_shown"] == 4


def test_a_limit_shows_fewer_rows_but_still_counts_every_flagged_source(world, monkeypatch):
    body = _client(monkeypatch, world).get("/api/quarantine/raw-id-sources", params={"limit": 1}).json()
    assert body["raw_id_sources"] == 2 and body["shown"] == 1 and len(body["rows"]) == 1


def test_it_renames_and_marks_nothing_and_makes_no_request(world, monkeypatch):
    import socket

    def _no_network(*a, **k):
        raise AssertionError("the report must not touch the network")

    monkeypatch.setattr(socket, "getaddrinfo", _no_network)
    _client(monkeypatch, world).get("/api/quarantine/raw-id-sources")
    with world() as s:
        assert {r[0] for r in s.query(Source.name)} == {"Q11858063", " q42 ", "Ilkka-Pohjalainen", "Q Magazine"}
        assert s.query(Article).filter(Article.quarantined.is_(True)).count() == 0


def test_the_route_is_a_get_that_does_not_shadow_the_action_route():
    from src.api.quarantine import router

    methods = {(r.path, tuple(sorted(r.methods))) for r in router.routes}
    assert ("/api/quarantine/raw-id-sources", ("GET",)) in methods
