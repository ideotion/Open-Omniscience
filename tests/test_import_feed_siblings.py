"""An import reads a feed the store lacks as a SIBLING, never as an edit of the one row it holds (row J, J3).

The independent read of J3 found two ways a multi-feed outlet collapsed to one row on import (CSV and YAML), and a legacy
store raising an IntegrityError where it used to return the existing row. Real sessions, the real importers.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.csv_io import parse_sources_csv, upsert_sources, write_csv
from src.database.models import Base, Source
from src.database.source_manager import SourceManager

EN, AR, FA = ("https://outlet.example/%s.xml" % x for x in ("en", "ar", "fa"))


@pytest.fixture()
def s():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    yield session
    session.close()


def _sheet(*feeds, domain="outlet.example"):
    rows = [{"name": f"Outlet {f.rsplit('/', 1)[1][:2]}", "domain": domain, "rss_url": f} for f in feeds]
    parsed, errors = parse_sources_csv(write_csv(rows))
    assert errors == []
    return parsed


def _feeds(s):
    return sorted(r.rss_url for r in s.query(Source))


def test_a_csv_of_a_multi_feed_outlet_the_store_does_not_hold_creates_every_feed(s):
    res = upsert_sources(s, _sheet(EN, AR, FA))
    assert res["errors"] == [] and res["created"] == 3
    assert _feeds(s) == sorted([EN, AR, FA])


def test_a_csv_that_repeats_one_row_for_a_new_domain_updates_it_instead_of_failing(s):
    res = upsert_sources(s, _sheet(EN, EN))
    assert res["errors"] == [] and (res["created"], res["updated"]) == (1, 1)
    assert _feeds(s) == [EN]


@pytest.mark.parametrize("order", [(EN, AR), (AR, EN)])
def test_a_csv_of_two_feeds_into_a_store_holding_one_keeps_both(s, order):
    SourceManager(s).create_source("Outlet en", "outlet.example", rss_url=EN)
    res = upsert_sources(s, _sheet(*order))
    assert res["errors"] == [] and (res["created"], res["updated"]) == (1, 1)
    assert _feeds(s) == sorted([EN, AR])


def test_a_csv_with_one_record_still_reads_a_changed_feed_as_the_same_source(s):
    SourceManager(s).create_source("Outlet en", "outlet.example", rss_url=EN)
    res = upsert_sources(s, _sheet("https://outlet.example/en-v2.xml"))
    assert (res["created"], res["updated"]) == (0, 1)
    assert _feeds(s) == ["https://outlet.example/en-v2.xml"]


def test_a_csv_that_repeats_one_corrected_row_still_corrects_the_row_it_is_not_a_sibling(s):
    SourceManager(s).create_source("Outlet en", "outlet.example", rss_url=EN)
    new = "https://outlet.example/en-v2.xml"
    res = upsert_sources(s, _sheet(new, new))
    assert res["errors"] == [] and res["created"] == 0 and res["updated"] == 2
    assert _feeds(s) == [new]


def test_a_yaml_that_repeats_one_corrected_row_still_corrects_the_row(s, tmp_path):
    import yaml

    SourceManager(s).create_source("Outlet en", "outlet.example", rss_url=EN)
    new = "https://outlet.example/en-v2.xml"
    p = tmp_path / "x.yml"
    p.write_text(yaml.safe_dump({"sources": [{"name": "Outlet en", "domain": "outlet.example", "rss_url": new}] * 2}))
    SourceManager(s).import_sources_from_yaml(str(p))
    assert _feeds(s) == [new]


def test_a_yaml_of_two_feeds_into_a_store_holding_one_keeps_both(s, tmp_path):
    import yaml

    m = SourceManager(s)
    m.create_source("Outlet en", "outlet.example", rss_url=EN)
    p = tmp_path / "x.yml"
    p.write_text(yaml.safe_dump({"sources": [
        {"name": "Outlet en", "domain": "outlet.example", "rss_url": EN},
        {"name": "Outlet ar", "domain": "outlet.example", "rss_url": AR}]}))
    out = m.import_sources_from_yaml(str(p))
    assert (out["added"], out["updated"]) == (1, 1)
    assert _feeds(s) == sorted([EN, AR])


def _legacy_session(tmp_path):
    from src.database.source_identity import add_feed_key_column
    from tests.test_source_composite_key import _legacy_engine

    eng = _legacy_engine(tmp_path)
    with eng.begin() as c:
        add_feed_key_column(c)
    return sessionmaker(bind=eng, future=True)()


def test_on_a_store_still_keyed_on_the_domain_a_second_feed_reads_as_the_existing_row(tmp_path):
    from src.database.source_identity import composite_key_active

    s = _legacy_session(tmp_path)
    assert not composite_key_active(s.connection())
    m = SourceManager(s)
    first = m.create_source("O en", "o.example", rss_url="https://o.example/en.xml")
    again = m.create_source("O fa", "o.example", rss_url="https://o.example/fa.xml")  # was an IntegrityError / a 500
    assert again.id == first.id
    res = upsert_sources(s, _sheet("https://o.example/ar.xml", "https://o.example/fa.xml", domain="o.example"))
    assert res["created"] == 0 and res["errors"] == []  # edits of the one row, as before row J
    assert s.query(Source).count() == 1
