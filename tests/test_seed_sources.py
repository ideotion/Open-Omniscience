"""
Tests for source seeding (Action Plan Phase 6.2) -- immediate out-of-box utility.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.database.models import Base, Source
from src.database.session import get_db
from src.ingest.seed_sources import (
    DEFAULT_SOURCES_PATH,
    load_sources_from_yaml,
    seed_default_sources,
    seed_sources,
)

_YAML = """
sources:
  - name: Example One
    domain: one.example
    rss_url: https://one.example/feed.xml
    tags: [a, b]            # list form, as in the real catalog
    reliability_score: 9
    language: en
    country: US
  - name: Example Two
    domain: two.example
    tags: single
  - {}                       # malformed -> skipped
  - name: No Domain          # missing domain -> skipped
"""


def _session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_loader_skips_malformed(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(_YAML, encoding="utf-8")
    rows = load_sources_from_yaml(p)
    assert [r["name"] for r in rows] == ["Example One", "Example Two"]


def test_seed_maps_rich_fields_and_tags_list(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(_YAML, encoding="utf-8")
    rows = load_sources_from_yaml(p)
    s = _session()
    seed_sources(s, rows)
    one = s.query(Source).filter_by(domain="one.example").one()
    assert one.tags == "a,b"  # list joined to CSV
    assert one.reliability_score == 9  # rich field mapped
    # country canonicalised to lowercase ISO-2 (the one conversion layer, 0.09)
    assert one.language == "en" and one.country == "us"
    two = s.query(Source).filter_by(domain="two.example").one()
    assert two.tags == "single"  # scalar tag preserved
    s.close()


def test_seed_is_idempotent(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(_YAML, encoding="utf-8")
    rows = load_sources_from_yaml(p)
    s = _session()
    first = seed_sources(s, rows)
    assert first["created"] == 2 and first["skipped"] == 0
    second = seed_sources(s, rows)
    assert second["created"] == 0 and second["skipped"] == 2
    assert s.query(Source).count() == 2
    s.close()


_COUNTRY_YAML = """
sources:
  - name: Title Paper (France)      # no country field -> read from the title suffix
    domain: title.example
  - name: Explicit (France)         # explicit field outranks the title suffix
    domain: explicit.example
    country: us
  - name: Plain Paper               # no signal but a ccTLD -> ccTLD fallback
    domain: plain.example.de
  - name: Override (France)         # title suffix outranks the ccTLD
    domain: override.example.de
"""


def test_seed_backfills_country_from_title_with_correct_precedence(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(_COUNTRY_YAML, encoding="utf-8")
    s = _session()
    seed_sources(s, load_sources_from_yaml(p))
    by = {row.domain: row.country for row in s.query(Source).all()}
    assert by["title.example"] == "fr"  # backfilled from "(France)"
    assert by["explicit.example"] == "us"  # explicit field wins over the title
    assert by["plain.example.de"] == "de"  # ccTLD fallback (no title signal)
    assert by["override.example.de"] == "fr"  # human title beats the ccTLD guess
    s.close()


def test_default_catalog_is_large_and_valid():
    # The shipped catalog (configs/sources.yml) must parse and be substantial.
    rows = load_sources_from_yaml(DEFAULT_SOURCES_PATH)
    assert len(rows) >= 500
    assert all(r.get("name") and r.get("domain") for r in rows)


def test_catalog_honours_its_own_country_suffix_convention():
    """Every ``Name (Country)`` entry must carry the matching ``country`` field.

    The catalog uses a trailing ``(Country)`` suffix as a human-authored origin
    marker; leaving the structured field blank where the title states the country
    is the provenance gap this guards against (a source the title says is from
    Spain must not be invisible to every geographic view). Regression guard for
    the country-provenance fix.
    """
    from src.catalog.normalize import country_from_title

    rows = load_sources_from_yaml(DEFAULT_SOURCES_PATH)
    missing = [
        r["name"]
        for r in rows
        if (code := country_from_title(r.get("name")))
        and (r.get("country") or "").strip().lower() != code
    ]
    assert not missing, f"{len(missing)} catalog entries name a country but omit it: {missing[:10]}"


def test_seed_default_catalog_dedupes_by_domain():
    s = _session()
    result = seed_default_sources(s)
    # 1900+ entries with some duplicate domains -> created == unique domains.
    assert result["created"] >= 500
    assert s.query(Source).count() == result["created"]
    assert result["created"] + result["skipped"] == result["total"]
    s.close()


@pytest.fixture()
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'seed.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)

    def _db():
        db = Sess()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_seed_defaults_endpoint(client):
    r = client.post("/api/sources/seed-defaults")
    assert r.status_code == 200, r.text
    assert r.json()["seeded"]["created"] >= 3
    # they now appear in the source list
    sources = client.get("/api/sources").json()
    assert len(sources) >= 3
    # idempotent
    r2 = client.post("/api/sources/seed-defaults")
    assert r2.json()["seeded"]["created"] == 0
