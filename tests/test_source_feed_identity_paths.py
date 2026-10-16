"""Adding and importing sources treats a source as (domain, feed) (row J, S05-10 J3).

Matching on the domain alone made a sheet that exports thirty feeds of one outlet overwrite the first row thirty
times, and made "add this feed" answer "already there" for any second feed of a registered domain.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.csv_io import parse_sources_csv, upsert_sources, write_csv
from src.database.models import Base, Source
from src.database.source_lookup import match_import
from src.database.source_manager import SourceManager


@pytest.fixture()
def s():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    yield session
    session.close()


def test_match_import_reads_an_edit_never_an_add():
    rows = [(1, "f:a/en"), (2, "f:a/ar")]
    assert match_import(rows, "f:a/ar") == 2  # the identical feed
    assert match_import(rows, "f:a/fa") is None  # a feed the domain does not hold: a sibling
    assert match_import(rows, "") == 1  # a record with no feed edits the oldest
    assert match_import([(7, "f:a/en")], "f:a/changed") == 7  # one row: a changed feed URL is the same source
    assert match_import([], "f:a/en") is None


def test_adding_a_second_feed_creates_a_sibling_and_the_same_feed_is_a_duplicate(s):
    m = SourceManager(s)
    a = m.create_source("Outlet EN", "outlet.example", rss_url="https://outlet.example/en.xml")
    b = m.create_source("Outlet AR", "outlet.example", rss_url="https://outlet.example/ar.xml")
    again = m.create_source("Outlet EN again", "outlet.example", rss_url="https://outlet.example/en.xml")
    assert a.id != b.id and again.id == a.id and s.query(Source).count() == 2


def test_a_discovered_feed_fills_the_feedless_row_and_a_different_feed_is_a_sibling(s):
    m = SourceManager(s)
    m.create_source("Outlet", "outlet.example")
    out = m.add_discovered_sources([{"domain": "outlet.example", "rss_url": "https://outlet.example/en.xml"}])
    assert s.query(Source).count() == 1 and out[0].rss_url == "https://outlet.example/en.xml"
    m.add_discovered_sources([{"domain": "outlet.example", "rss_url": "https://outlet.example/ar.xml"}])
    assert s.query(Source).count() == 2


def test_a_csv_round_trip_of_a_multi_feed_outlet_overwrites_nothing(s):
    m = SourceManager(s)
    for lang in ("en", "ar", "fa"):
        m.create_source(f"Outlet {lang}", "outlet.example", rss_url=f"https://outlet.example/{lang}.xml")
    rows = [{"name": r.name, "domain": r.domain, "rss_url": r.rss_url} for r in s.query(Source).order_by(Source.id)]
    parsed, errors = parse_sources_csv(write_csv(rows))
    assert errors == []
    result = upsert_sources(s, parsed)
    assert (result["created"], result["updated"]) == (0, 3)
    assert [(r.name, r.rss_url) for r in s.query(Source).order_by(Source.id)] == [
        ("Outlet en", "https://outlet.example/en.xml"),
        ("Outlet ar", "https://outlet.example/ar.xml"),
        ("Outlet fa", "https://outlet.example/fa.xml"),
    ]  # the first row still holds the first feed


def test_a_csv_row_with_a_new_feed_of_a_multi_feed_outlet_creates_a_sibling(s):
    m = SourceManager(s)
    for lang in ("en", "ar"):
        m.create_source(f"Outlet {lang}", "outlet.example", rss_url=f"https://outlet.example/{lang}.xml")
    parsed, _ = parse_sources_csv(write_csv([{"name": "Outlet fa", "domain": "outlet.example",
                                              "rss_url": "https://outlet.example/fa.xml"}]))
    result = upsert_sources(s, parsed)
    assert (result["created"], result["updated"]) == (1, 0) and s.query(Source).count() == 3


def test_a_yaml_round_trip_of_a_multi_feed_outlet_overwrites_nothing(s, tmp_path):
    m = SourceManager(s)
    for lang in ("en", "ar"):
        m.create_source(f"Outlet {lang}", "outlet.example", rss_url=f"https://outlet.example/{lang}.xml")
    path = tmp_path / "sources.yml"
    m.export_sources_to_yaml(str(path))
    result = m.import_sources_from_yaml(str(path))
    assert result == {"added": 0, "updated": 2, "skipped": 0}
    assert [r.name for r in s.query(Source).order_by(Source.id)] == ["Outlet en", "Outlet ar"]
