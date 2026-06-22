"""
Tests for the filterable/sortable source list (/api/catalog/sources).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Source


def _client(tmp_path):
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 's.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add_all(
            [
                Source(
                    name="Alpha",
                    domain="alpha.test",
                    country="FR",
                    language="fr",
                    source_type="news",
                    tags="politics,world",
                    enabled=True,
                ),
                Source(
                    name="Beta",
                    domain="beta.test",
                    country="us",
                    language="en",
                    source_type="financial",
                    tags="markets",
                    enabled=False,
                ),
                Source(
                    name="Gamma",
                    domain="gamma.test",
                    country="fr",
                    language="fr",
                    source_type="news",
                    tags="climate",
                    enabled=True,
                ),
            ]
        )
        s.commit()

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    return app, TestClient(app)


def test_filter_by_country_and_tag(tmp_path):
    app, client = _client(tmp_path)
    try:
        with client:
            byc = client.get("/api/catalog/sources?country=fr").json()
            assert byc["total"] == 2 and {s["domain"] for s in byc["sources"]} == {
                "alpha.test",
                "gamma.test",
            }
            bytag = client.get("/api/catalog/sources?tag=climate").json()
            assert {s["domain"] for s in bytag["sources"]} == {"gamma.test"}
            bytype = client.get("/api/catalog/sources?source_type=financial").json()
            assert {s["domain"] for s in bytype["sources"]} == {"beta.test"}
            dis = client.get("/api/catalog/sources?enabled=false").json()
            assert {s["domain"] for s in dis["sources"]} == {"beta.test"}
    finally:
        app.dependency_overrides.clear()


def test_multi_select_filters_or_within_and_across(tmp_path):
    """#23: comma-separated values OR within a filter, AND across filters."""
    app, client = _client(tmp_path)
    try:
        with client:
            # WITHIN language = OR: fr OR en -> all three sources
            r = client.get("/api/catalog/sources?language=fr,en").json()
            assert {s["domain"] for s in r["sources"]} == {"alpha.test", "beta.test", "gamma.test"}
            # ACROSS filters = AND: (fr OR en) AND type=news -> beta (financial) drops out
            r = client.get("/api/catalog/sources?language=fr,en&source_type=news").json()
            assert {s["domain"] for s in r["sources"]} == {"alpha.test", "gamma.test"}
            # country multi-select still normalises each value (FR/us mixed-case)
            r = client.get("/api/catalog/sources?country=FR,US").json()
            assert {s["domain"] for s in r["sources"]} == {"alpha.test", "beta.test", "gamma.test"}
    finally:
        app.dependency_overrides.clear()


def test_tag_mode_any_vs_all(tmp_path):
    app, client = _client(tmp_path)
    try:
        with client:
            # any (default): politics OR climate
            r = client.get("/api/catalog/sources?tag=politics,climate").json()
            assert {s["domain"] for s in r["sources"]} == {"alpha.test", "gamma.test"}
            # all: must carry BOTH politics AND world -> only alpha
            r = client.get("/api/catalog/sources?tag=politics,world&tag_mode=all").json()
            assert {s["domain"] for s in r["sources"]} == {"alpha.test"}
    finally:
        app.dependency_overrides.clear()


def test_sort_and_search(tmp_path):
    app, client = _client(tmp_path)
    try:
        with client:
            asc = client.get("/api/catalog/sources?sort=name&order=asc").json()
            names = [s["name"] for s in asc["sources"]]
            assert names == sorted(names)
            srch = client.get("/api/catalog/sources?q=gam").json()
            assert {s["domain"] for s in srch["sources"]} == {"gamma.test"}
            # rows carry the fields the Sources table needs.
            row = asc["sources"][0]
            assert {
                "id",
                "name",
                "domain",
                "country",
                "language",
                "source_type",
                "article_count",
                "tags",
                "enabled",
            } <= set(row)
    finally:
        app.dependency_overrides.clear()
