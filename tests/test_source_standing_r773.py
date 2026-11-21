"""R773 (row 39): no count the user sees calls an unchecked candidate a source.

A source is a row the app collected from, or one collection may take now (enabled AND
qualified). A candidate not yet checked is any other row still waiting for its first verdict.
The field's 25,000 disabled Wikidata finds were being counted as country coverage.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.api.insights import _count_sources_not_candidates
from src.catalog.source_standing import (
    CANDIDATE_LINE,
    counted_by_country,
    standing_totals,
)
from src.database.models import Article, Base, Source

ROOT = Path(__file__).resolve().parent.parent
LANGS = ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh")


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng, tables=[Source.__table__, Article.__table__])
    with Session(eng) as s:
        yield s


def _src(db, sid, *, country, enabled, status, articles=0):
    db.add(Source(id=sid, name=f"S{sid}", domain=f"s{sid}.example", country=country,
                  enabled=enabled, status=status))
    db.flush()
    for i in range(articles):
        db.add(Article(url=f"https://s{sid}.example/{i}", canonical_url=f"https://s{sid}.example/{i}",
                       source_id=sid, title="t", content="x", hash=f"{sid:030d}{i:034d}"))
    db.commit()


def _world(db):
    _src(db, 1, country="FI", enabled=True, status="qualified")                  # collectable now
    _src(db, 2, country="FI", enabled=False, status="disqualified", articles=2)  # collected from before
    _src(db, 3, country="FI", enabled=False, status="unqualified")               # a discovery find
    _src(db, 4, country="JP", enabled=False, status="unqualified")               # only candidates here
    _src(db, 5, country="JP", enabled=True, status="unqualified")                # seeded, not judged yet
    _src(db, 6, country="JP", enabled=False, status="disqualified")              # judged and refused
    _src(db, 7, country=None, enabled=None, status="qualified")                  # NULL enabled reads enabled


def test_a_source_is_collected_from_or_collectable_and_a_candidate_is_unjudged(db):
    _world(db)
    sources, candidates = counted_by_country(db)
    assert sources == {"fi": 2, "": 1}
    assert candidates == {"fi": 1, "jp": 2}
    totals = standing_totals(db)
    assert totals == {"sources": 3, "candidates_not_checked": 3, "other": 1}
    assert sum(totals.values()) == 7, "the three parts partition the table"


def test_the_map_counts_sources_and_puts_candidates_beside_them(db):
    _world(db)
    # What the rollup or the live query hands the endpoint: the flat count per country.
    data = {
        "by_country": [
            {"country": "fi", "sources": 3, "articles": 2, "keywords": 0, "sentiment": None, "sentiment_n": 0},
            {"country": "jp", "sources": 3, "articles": 0, "keywords": 0, "sentiment": None, "sentiment_n": 0},
        ],
        "unlocated": {"sources": 1, "articles": 0, "keywords": 0, "by_language": {}},
        "total_sources": 7,
    }
    _count_sources_not_candidates(db, data)
    rows = {r["country"]: r for r in data["by_country"]}
    assert (rows["fi"]["sources"], rows["fi"]["candidates"]) == (2, 1)
    assert (rows["jp"]["sources"], rows["jp"]["candidates"]) == (0, 2), "candidates never cover a country"
    assert data["total_sources"] == 3 and data["candidates_not_checked"] == 3
    assert data["unlocated"]["sources"] == 1 and data["candidate_line"] == CANDIDATE_LINE
    assert [r["country"] for r in data["by_country"]] == ["fi", "jp"]


def test_the_country_breakdown_and_coverage_name_candidates_apart():
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.database.session import init_db

    init_db()
    with TestClient(app) as client:
        cov = client.get("/api/database/coverage").json()
        countries = client.get("/api/database/countries").json()
    assert {"sources", "candidates_not_checked", "candidate_line"} <= set(cov)
    assert "candidates_not_checked" in countries
    assert all("candidates" in c for c in countries["countries"])
    # A country is covered only by a source.
    assert countries["covered"] == sum(
        1 for c in countries["countries"] if c["code"] != "(none)" and c["sources"] > 0)


def test_the_panels_show_the_candidate_figure_and_line():
    js = (ROOT / "src/static/app-sources.js").read_text(encoding="utf-8")
    assert "c.candidates_not_checked" in js and "c.candidate_line" in js
    assert "<th>Candidates not yet checked</th>" in js
    simple = (ROOT / "src/static/simple/simple.js").read_text(encoding="utf-8")
    assert "d.candidates_not_checked" in simple and "c.candidates_not_checked" in simple
    # The simple Today figure never falls back to the flat row count.
    assert "c.sources_qualified : c.sources)" not in simple
    # "N more countries have sources" counts countries with a source, not ones with only candidates.
    assert re.search(r"var waiting = all\.filter\(.*c\.sources > 0", simple)


@pytest.mark.parametrize("lang", LANGS)
def test_the_candidate_line_ships_in_every_language(lang):
    main = json.loads((ROOT / f"src/static/locales/{lang}.json").read_text(encoding="utf-8"))
    simple = json.loads((ROOT / f"src/static/simple/locales/{lang}.json").read_text(encoding="utf-8"))["strings"]
    for table in (main, simple):
        assert table.get(CANDIDATE_LINE) and table.get("candidates not yet checked")
    assert main.get("Candidates not yet checked")
    if lang != "en":
        assert main[CANDIDATE_LINE] != CANDIDATE_LINE
