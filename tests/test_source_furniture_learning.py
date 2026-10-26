"""
Per-source learned furniture (qualification lane, 2026-10-26): a local, read-only list of short lines
that repeat across one source's bodies, for a person to read. It marks and strips nothing.
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
from src.ingest.furniture import learn_repeated_lines


def _bodies(n, template):
    return [template.format(i=i) for i in range(n)]


def test_a_short_line_in_most_bodies_is_a_candidate_and_unique_text_is_not():
    texts = _bodies(10, "Meny\nUnique story number {i} with its own words that never repeats here.\nLogga in")
    out = learn_repeated_lines(texts)
    lines = {r["line"]: r for r in out["candidates"]}
    assert out["examined"] == 10
    assert set(lines) == {"Meny", "Logga in"}
    assert lines["Meny"]["articles"] == 10 and lines["Meny"]["share"] == 1.0


def test_a_line_counts_once_per_body_even_when_it_repeats_inside_one():
    texts = ["Annons\nAnnons\nAnnons\nStory " + str(i) for i in range(5)]
    out = learn_repeated_lines(texts)
    assert out["candidates"][0]["articles"] == 5 and out["candidates"][0]["known"] is True


def test_a_long_repeated_paragraph_is_not_listed_and_few_articles_are_not_enough():
    long_line = " ".join(["word"] * 30)
    assert learn_repeated_lines([long_line + f"\nX{i}" for i in range(10)])["candidates"] == []
    assert learn_repeated_lines(["Meny\nA", "Meny\nB"])["candidates"] == []  # 2 < min_articles


def test_empty_bodies_do_not_count_toward_the_share():
    out = learn_repeated_lines(["Meny\nA", "Meny\nB", "Meny\nC", None, "", "  "])
    assert out["examined"] == 3 and out["candidates"][0]["share"] == 1.0


@pytest.fixture
def world():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, autoflush=False)
    with Session() as s:
        a = Source(name="A", domain="a.example", enabled=True)
        b = Source(name="B", domain="b.example", enabled=True)
        s.add_all([a, b])
        s.commit()
        for i in range(12):
            url = f"https://a.example/{i}"
            s.add(Article(url=url, canonical_url=url, source_id=a.id, hash=f"a{i}", word_count=5,
                          language="sv", title=f"T{i}", content=f"Meny\nStory {i} is its own text.\nAnnons"))
        for i in range(3):
            url = f"https://b.example/{i}"
            s.add(Article(url=url, canonical_url=url, source_id=b.id, hash=f"b{i}", word_count=5,
                          language="sv", title=f"U{i}", content=f"Other {i}"))
        s.commit()
    return Session


def _client(monkeypatch, world):
    from src.api.quarantine import router

    monkeypatch.setattr(qj, "_default_session", lambda: world())
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_the_endpoint_lists_this_sources_repeats_only_and_says_how_it_chose(world, monkeypatch):
    c = _client(monkeypatch, world)
    body = c.get("/api/quarantine/source-furniture", params={"source_id": 1}).json()
    assert body["sampled"] == 12 and body["articles_in_source"] == 12
    assert {r["line"] for r in body["candidates"]} == {"Meny", "Annons"}
    assert "newest" in body["method"] and "nothing marked" in body["method"]
    other = c.get("/api/quarantine/source-furniture", params={"source_id": 2}).json()
    assert other["candidates"] == []


def test_unknown_source_is_404_and_bounds_are_422(world, monkeypatch):
    c = _client(monkeypatch, world)
    assert c.get("/api/quarantine/source-furniture", params={"source_id": 99}).status_code == 404
    assert c.get("/api/quarantine/source-furniture", params={"source_id": 1, "sample": 5}).status_code == 422
    assert c.get("/api/quarantine/source-furniture", params={"source_id": 1, "min_share": 0}).status_code == 422


def test_it_marks_nothing_and_strips_nothing(world, monkeypatch):
    _client(monkeypatch, world).get("/api/quarantine/source-furniture", params={"source_id": 1})
    with world() as s:
        assert s.query(Article).filter(Article.quarantined.is_(True)).count() == 0
        assert s.query(Article).filter(Article.content.like("%Annons%")).count() == 12


def test_a_line_exactly_at_min_share_is_listed_despite_float_error():
    # 0.07 * 100 == 7.000000000000001: the line in exactly 7 of 100 bodies must still be listed
    texts = [f"Meny\nA{i}" for i in range(7)] + [f"B{i}" for i in range(93)]
    out = learn_repeated_lines(texts, min_share=0.07)
    assert [r["line"] for r in out["candidates"]] == ["Meny"] and out["candidates"][0]["articles"] == 7
