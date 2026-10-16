"""The seeder carries out the registration plan against the database (row J, S05-10 J3, R145).

A source is its domain AND its feed: a second feed registers, a feed-less description merges its tags, a corrected feed
URL is the SAME source, an operator's removal of a merged tag stays removed, a different lean is a counted conflict, and a
sibling feed starts from the outlet's measured verdict -- recorded as inherited, never as measured here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.qualification import (
    CURATED_CRITERIA_VERSION,
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
    VERDICT_INHERITED,
)
from src.database.models import Base, Source, SourceQualificationAttempt
from src.ingest.seed_sources import seed_sources


@pytest.fixture()
def s():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    yield session
    session.close()


def _e(name, feed=None, tags=None, domain="outlet.example", **kw):
    out = {"name": name, "domain": domain, **kw}
    if feed:
        out["rss_url"] = f"https://{domain}/{feed}.xml"
    if tags:
        out["tags"] = tags
    return out


def test_a_corrected_feed_url_is_the_same_source_not_a_second_row(s):
    seed_sources(s, [_e("Outlet", "old")])
    result = seed_sources(s, [_e("Outlet", "new")])  # the catalogue fixed the feed: one entry, one row
    assert result["created"] == 0 and s.query(Source).count() == 1
    assert s.query(Source).one().rss_url == "https://outlet.example/new.xml"  # the correction reached the row
    assert s.query(Source).one().feed_key == "f:outlet.example/new.xml"


def test_a_second_feed_of_a_registered_domain_becomes_a_sibling_row(s):
    seed_sources(s, [_e("Outlet EN", "en")])
    result = seed_sources(s, [_e("Outlet EN", "en"), _e("Outlet AR", "ar")])
    assert result["created"] == 1 and result["skipped_existing"] == 1
    assert [r.name for r in s.query(Source).order_by(Source.id)] == ["Outlet EN", "Outlet AR"]


def test_a_merged_tag_is_put_on_once_and_an_operator_removal_stays_removed(s):
    entries = [_e("Outlet", "en"), _e("Outlet", tags=["lean-left", "wire"])]
    seed_sources(s, entries)
    row = s.query(Source).one()
    assert set(row.tags.split(",")) >= {"lean-left", "wire"}
    row.tags = ",".join(t for t in row.tags.split(",") if t != "wire")  # the operator removes a tag
    s.commit()
    seed_sources(s, entries)
    assert "wire" not in s.query(Source).one().tags.split(",")  # not put back by the next boot


def test_a_different_lean_is_a_counted_conflict_and_the_existing_one_stays(s):
    seed_sources(s, [_e("Outlet", "en", tags=["lean-right"])])
    result = seed_sources(s, [_e("Outlet", "en", tags=["lean-right"]), _e("Outlet", tags=["lean-left"], _provenance="spectrum")])
    assert result["tag_merge"]["conflict_count"] == 1
    c = result["tag_merge"]["conflicts"][0]
    assert (c["kept"], c["catalogue"], c["provenance"]) == ("lean-right", "lean-left", "spectrum")
    assert "lean-left" not in s.query(Source).one().tags.split(",")


def test_a_row_with_no_readable_baseline_is_skipped_and_counted_not_guessed(s):
    """The seeder adopts a baseline (sync runs first), so this is the merge step's own refusal."""
    from src.ingest.seed_sources import merge_feedless_tags

    seed_sources(s, [_e("Outlet", "en")])
    row = s.query(Source).one()
    row.catalog_baseline = "{not json"
    s.commit()
    out = merge_feedless_tags(s, [(_e("Outlet", tags=["lean-left"]), row)])
    assert out["skipped_no_baseline"] == 1 and out["tags_merged"] == 0
    assert "lean-left" not in (row.tags or "")


def test_a_feedless_description_of_an_outlet_that_already_has_feed_rows_in_the_database_merges_there(s):
    """The legal seeder passes only legal rows: the outlet's feed rows may already be in the database, not in the input."""
    seed_sources(s, [_e("Outlet EN", "en"), _e("Outlet AR", "ar")])
    result = seed_sources(s, [_e("Outlet", tags=["gazette"])])
    assert result["created"] == 0 and s.query(Source).count() == 2  # no third, feed-less copy of the outlet
    assert "gazette" in s.query(Source).order_by(Source.id).first().tags.split(",")


def _judged(s, name, status, version="oo-criteria-9"):
    row = s.query(Source).filter_by(name=name).one()
    row.status = status
    row.qualified_at = datetime(2026, 9, 1, tzinfo=UTC) if status == STATUS_QUALIFIED else None
    row.qualification_criteria_version = version if status == STATUS_QUALIFIED else None
    s.commit()
    return row


def test_a_new_sibling_inherits_the_outlets_measured_verdict_and_says_it_was_inherited(s):
    seed_sources(s, [_e("Outlet EN", "en")])
    _judged(s, "Outlet EN", STATUS_QUALIFIED)
    result = seed_sources(s, [_e("Outlet EN", "en"), _e("Outlet AR", "ar")])
    assert result["sibling_verdicts"]["inherited"] == 1
    ar = s.query(Source).filter_by(name="Outlet AR").one()
    assert ar.status == STATUS_QUALIFIED and ar.qualification_criteria_version == "oo-criteria-9"
    kinds = [a.verdict for a in s.query(SourceQualificationAttempt).filter_by(source_id=ar.id)]
    assert kinds == [VERDICT_INHERITED]  # never a 'qualified' attempt this install did not measure


def test_a_disqualified_outlet_hands_its_verdict_to_a_new_sibling_too(s):
    seed_sources(s, [_e("Outlet EN", "en")])
    _judged(s, "Outlet EN", STATUS_DISQUALIFIED)
    seed_sources(s, [_e("Outlet EN", "en"), _e("Outlet AR", "ar")])
    assert s.query(Source).filter_by(name="Outlet AR").one().status == STATUS_DISQUALIFIED


def test_a_curated_stamp_is_not_a_verdict_to_hand_on(s):
    seed_sources(s, [_e("Outlet EN", "en")])
    _judged(s, "Outlet EN", STATUS_QUALIFIED, version=CURATED_CRITERIA_VERSION)
    result = seed_sources(s, [_e("Outlet EN", "en"), _e("Outlet AR", "ar")])
    assert result["sibling_verdicts"] == {"inherited": 0, "qualified": 0, "disqualified": 0, "skipped_curated_stamp": 1}
    assert s.query(Source).filter_by(name="Outlet AR").one().status == STATUS_UNQUALIFIED


def test_a_fresh_install_gives_no_sibling_a_verdict_it_does_not_have(s):
    result = seed_sources(s, [_e("Outlet EN", "en"), _e("Outlet AR", "ar")])
    assert result["sibling_verdicts"]["inherited"] == 0
    assert {r.status for r in s.query(Source)} == {STATUS_UNQUALIFIED}


def test_the_baseline_carries_the_merged_tags_through_a_correction(s):
    seed_sources(s, [_e("Outlet", "en", tags=["a"]), _e("Outlet", tags=["lean-left"])])
    assert json.loads(s.query(Source).one().catalog_baseline)["merged_tags"] == ["lean-left"]
    seed_sources(s, [_e("Outlet", "en", tags=["a"], country="fr"), _e("Outlet", tags=["lean-left"])])
    base = json.loads(s.query(Source).one().catalog_baseline)
    assert base["merged_tags"] == ["lean-left"]  # a sync rewrite does not forget what was merged


def test_the_same_feed_named_by_a_second_catalogue_is_one_row_and_its_tags_merge(s):
    """The spectrum catalogue's CNN beside the curated one: one source described twice, never two rows, never a lost lean."""
    entries = [_e("CNN", "rss", tags=["news"]), _e("CNN", "rss", tags=["lean-center-left"], _provenance="spectrum")]
    result = seed_sources(s, entries)
    assert result["created"] == 1 and result["merged"] == 1 and result["shadowed"] == 0
    assert "lean-center-left" in s.query(Source).one().tags.split(",")
