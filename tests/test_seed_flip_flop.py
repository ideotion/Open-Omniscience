"""The two seeds no longer undo each other, and what they erased comes back (R152; the seed flip-flop of 2026-10-17).

The legal catalogue's FEED-LESS entry for a host the news catalogue also lists was taken as a correction of the news
row: the legal seed wrote its empty ``rss_url`` and ``region`` over the row's and rewrote the baseline, the default seed
then read that as a correction in the other direction, and so on every boot. Seven news feeds were erased for good
(an empty live value reads as a gap, which nothing refills). Each test below is red without the rule it pins.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Source
from src.ingest.seed_sources import (
    CATALOGUE_OWNED_FIELDS,
    _norm,
    _to_source_kwargs,
    repair_erased_feeds,
    seed_sources,
)

DOMAIN = "au.example"
FEED = f"https://{DOMAIN}/en/rss"


@pytest.fixture()
def s():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    yield session
    session.close()


def _news(**kw):
    return {"name": "African Union News", "domain": DOMAIN, "rss_url": FEED, "region": "africa",
            "country": "int", "source_type": "news", "_provenance": "curated", **kw}


def _legal(**kw):
    return {"name": "African Union", "domain": DOMAIN, "country": "int", "source_type": "law",
            "_provenance": "legal", **kw}


def _row(s):
    return s.query(Source).filter(Source.domain == DOMAIN).order_by(Source.id).first()


def _erase(s, entry=None):
    """The state the flip-flop left: feed and region gone, the legal entry's name, the baseline the legal seed wrote."""
    row = _row(s)
    shipped = {f: _norm(_to_source_kwargs(entry or _legal()).get(f)) for f in CATALOGUE_OWNED_FIELDS}
    row.rss_url, row.region, row.name = None, None, "African Union"
    row.catalog_baseline = json.dumps(shipped, sort_keys=True)
    s.commit()
    assert _row(s).feed_key == ""


def test_the_legal_seed_does_not_take_a_news_rows_feed_and_a_second_round_applies_nothing(s):
    seed_sources(s, [_news()])
    for _ in range(3):  # the legal seed hands the syncer only its own catalogue's entry
        result = seed_sources(s, [_legal()])
        assert result["corrections"]["applied"] == 0 and result["corrections"]["kept"] == 0
        assert result["corrections"]["foreign_catalogue"] == 1
    row = _row(s)
    assert row.rss_url == FEED and row.region == "africa" and row.name == "African Union News"


def test_an_entry_of_the_rows_own_catalogue_still_corrects_it(s):
    seed_sources(s, [_news()])
    result = seed_sources(s, [_news(name="African Union (news)")])
    assert result["corrections"]["applied"] == 1 and result["corrections"]["foreign_catalogue"] == 0
    assert _row(s).name == "African Union (news)"


def test_a_row_without_a_via_marker_is_corrected_as_before(s):
    plain = {"name": "Plain", "domain": DOMAIN, "rss_url": FEED}
    seed_sources(s, [plain])
    assert not [t for t in (_row(s).tags or "").split(",") if t.startswith("via:")]
    result = seed_sources(s, [{**plain, "name": "Plain, renamed", "_provenance": "legal"}])
    assert result["corrections"]["applied"] == 1 and result["corrections"]["foreign_catalogue"] == 0
    assert _row(s).name == "Plain, renamed"


def test_an_erased_feed_and_region_come_back_from_the_rows_own_catalogue(s):
    seed_sources(s, [_news()])
    _erase(s)
    result = seed_sources(s, [_news(), _legal()])
    repair = result["feed_repair"]
    assert repair["restored"] == 1 and repair["not_restored"] == 0
    assert repair["restored_rows"][0]["domain"] == DOMAIN
    assert repair["restored_rows"][0]["fields"] == ["region", "rss_url"]
    assert "legal: African Union" in repair["restored_rows"][0]["explained_by"]
    row = _row(s)
    assert row.rss_url == FEED and row.region == "africa" and row.feed_key == f"f:{DOMAIN}/en/rss"
    assert s.query(Source).count() == 1                    # the news entry paired with the row, no second row
    assert row.name == "African Union News"                # the swapped name returned through the ordinary sync
    again = seed_sources(s, [_news(), _legal()])
    assert again["feed_repair"]["restored"] == 0 and again["corrections"]["applied"] == 0   # idempotent


def test_only_the_region_is_restored_when_the_feed_is_still_there(s):
    seed_sources(s, [_news()])
    _erase(s)
    _row(s).rss_url = FEED
    s.commit()
    repair = repair_erased_feeds(s, [_news(), _legal()])
    assert repair["restored"] == 1 and repair["restored_rows"][0]["fields"] == ["region"]


def test_a_feed_the_operator_cleared_is_never_refilled(s):
    seed_sources(s, [_news()])
    _row(s).rss_url = None                                 # an operator edit: the baseline still names the feed
    s.commit()
    result = seed_sources(s, [_news(), _legal()])
    assert result["feed_repair"]["restored"] == 0 and result["feed_repair"]["operator_cleared"] == 1
    assert _row(s).rss_url is None


def test_an_empty_value_nothing_explains_is_listed_not_restored(s):
    seed_sources(s, [_news()])
    _erase(s, entry=_legal(name="Something Else"))         # the baseline is no feed-less entry's record
    repair = repair_erased_feeds(s, [_news(), _legal()])
    assert repair["restored"] == 0 and repair["not_restored"] == 1
    assert "explains" in repair["not_restored_rows"][0]["reason"]
    assert _row(s).rss_url is None


def test_a_feed_another_row_of_the_domain_already_carries_is_not_restored(s):
    seed_sources(s, [_news()])
    _erase(s)
    s.add(Source(name="African Union EN", domain=DOMAIN, rss_url=FEED))
    s.commit()
    repair = repair_erased_feeds(s, [_news(), _legal()])
    assert repair["restored"] == 0 and repair["not_restored"] == 1
    assert "already carries that feed" in repair["not_restored_rows"][0]["reason"]
    assert _row(s).rss_url is None


def test_the_same_name_in_both_catalogues_proves_nothing_alone(s):
    seed_sources(s, [_news(name="African Union")])
    row = _row(s)
    row.rss_url = None
    row.catalog_baseline = json.dumps({"name": "African Union", "country": "xx", "rss_url": None}, sort_keys=True)
    s.commit()
    repair = repair_erased_feeds(s, [_news(name="African Union"), _legal()])
    assert repair["restored"] == 0 and repair["not_restored"] == 1


def test_the_real_default_and_legal_seeds_leave_each_other_alone_and_no_news_feed_is_erased(s):
    """The production sequence (``src/api/main.py``: default seed, then legal seed), on the shipped catalogues."""
    from src.ingest.seed_sources import seed_default_sources
    from src.law.catalog import seed_legal_sources

    seed_default_sources(s)
    seed_legal_sources(s)
    with_feed = {r.domain for r in s.query(Source).filter(Source.rss_url.isnot(None), Source.rss_url != "")}
    for _ in range(2):
        first = seed_default_sources(s)
        second = seed_legal_sources(s)
        assert first["corrections"]["applied"] == 0 and first["corrections"]["kept"] == 0
        assert second["corrections"]["applied"] == 0 and second["corrections"]["kept"] == 0
        assert first["feed_repair"]["restored"] == 0
    assert {r.domain for r in s.query(Source).filter(Source.rss_url.isnot(None), Source.rss_url != "")} == with_feed
    for domain in ("au.int", "oas.org", "gov.uk"):
        assert s.query(Source).filter(Source.domain == domain, Source.rss_url.isnot(None), Source.rss_url != "").count() >= 1


def test_a_name_match_with_a_row_another_catalogue_made_is_not_a_corrected_feed(s):
    """The legal seed sees only legal entries, so every news row of the domain is a leftover in it. A legal entry that
    shares a news row's NAME but carries another feed (a gazette feed) is a second description, not that row's correction."""
    def entry(name, feed, prov):
        return {"name": name, "domain": "d.example", "rss_url": f"https://d.example/{feed}.xml", "_provenance": prov}

    main = [entry("D News", "f1", "curated"), entry("D Other", "f2", "curated")]
    legal = [entry("D News", "f3", "legal")]
    for _ in range(3):
        seed_sources(s, main)
        seed_sources(s, legal)
    assert sorted(r.rss_url for r in s.query(Source)) == [
        "https://d.example/f1.xml", "https://d.example/f2.xml", "https://d.example/f3.xml",
    ]


def test_a_merge_that_only_records_offered_tags_is_committed_by_the_seeder(s):
    """``get_db`` callers (POST /sources/seed-defaults, POST /law/seed) never commit: the seeder has to."""
    entries = [{"name": "O", "domain": "o.example", "rss_url": "https://o.example/a.xml", "tags": ["politics"]},
               {"name": "O", "domain": "o.example", "tags": ["politics"]}]
    seed_sources(s, entries)
    row = _row_of(s, "o.example")
    base = json.loads(row.catalog_baseline)
    base.pop("merged_tags", None)
    row.catalog_baseline = json.dumps(base, sort_keys=True)
    s.commit()
    seed_sources(s, entries)
    s.rollback()
    assert "politics" in json.loads(_row_of(s, "o.example").catalog_baseline).get("merged_tags", [])


def _row_of(s, domain):
    return s.query(Source).filter(Source.domain == domain).order_by(Source.id).first()
