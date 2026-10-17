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


def test_a_disqualified_outlet_hands_its_verdict_to_a_new_sibling_and_says_it_was_inherited(s):
    seed_sources(s, [_e("Outlet EN", "en")])
    _judged(s, "Outlet EN", STATUS_DISQUALIFIED)
    result = seed_sources(s, [_e("Outlet EN", "en"), _e("Outlet AR", "ar")])
    assert result["sibling_verdicts"] == {"inherited": 1, "disqualified": 1, "left_to_own_trial": 0}
    ar = s.query(Source).filter_by(name="Outlet AR").one()
    assert ar.status == STATUS_DISQUALIFIED and ar.qualified_at is None
    kinds = [a.verdict for a in s.query(SourceQualificationAttempt).filter_by(source_id=ar.id)]
    assert kinds == [VERDICT_INHERITED]  # never a 'disqualified' attempt this install did not measure


def test_a_qualified_outlet_hands_nothing_on_the_new_feed_gets_its_own_trial(s):
    """R153: the qualified direction is never handed on, curated stamp or measured."""
    for version in ("oo-criteria-9", CURATED_CRITERIA_VERSION):
        s.query(SourceQualificationAttempt).delete()
        s.query(Source).delete()
        s.commit()
        seed_sources(s, [_e("Outlet EN", "en")])
        _judged(s, "Outlet EN", STATUS_QUALIFIED, version=version)
        result = seed_sources(s, [_e("Outlet EN", "en"), _e("Outlet AR", "ar")])
        assert result["sibling_verdicts"] == {"inherited": 0, "disqualified": 0, "left_to_own_trial": 1}
        ar = s.query(Source).filter_by(name="Outlet AR").one()
        assert ar.status == STATUS_UNQUALIFIED and ar.qualification_criteria_version is None
        assert not s.query(SourceQualificationAttempt).filter_by(source_id=ar.id).count()


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


def test_a_store_still_keyed_on_the_domain_holds_a_second_feed_back_instead_of_failing_the_seed(s, monkeypatch):
    """Opus read, finding 6: the seeder asks whether the store can hold several feeds of a domain. A store whose rebuild
    was refused keeps one feed per domain, and registering a sibling would have broken UNIQUE (domain) for the batch."""
    monkeypatch.setattr("src.ingest.seed_sources.composite_key_active", lambda _conn: False)
    result = seed_sources(s, [_e("Outlet", "en"), _e("Outlet es", "es"), _e("Other", "o", domain="other.example")])
    assert s.query(Source).count() == 2  # the first feed of each domain only
    assert result["created"] == 2 and result["held_back_legacy_key"] == 1


def test_a_tag_both_entries_carry_stays_removed_once_the_operator_removed_it(s):
    """A merged tag the row already had was never recorded, so removing it was undone at the next boot (223 of the 240
    real merges share a tag with their row: news on Reuters). The catalogue's offer is recorded even when nothing is added."""
    entries = [_e("Outlet", "en", tags=["politics"]), _e("Outlet", tags=["politics", "extra"])]
    seed_sources(s, entries)
    row = s.query(Source).one()
    assert split(row.tags) == ["extra", "politics"] or set(split(row.tags)) == {"politics", "extra"}
    row.tags = ",".join(t for t in split(row.tags) if t != "politics")
    s.commit()
    seed_sources(s, entries)
    assert "politics" not in split(s.query(Source).one().tags)


def split(value):
    return [t for t in (value or "").split(",") if t]


def test_the_seeder_reads_a_curated_oldest_row_past_to_a_measured_disqualified_one(s):
    """The restore merge hands a sibling the outlet's MEASURED disqualification even when the oldest row only carries the
    catalogue's stamp; the seeder must not give it nothing (boot would then stamp it qualified and collect it)."""
    seed_sources(s, [_e("Outlet EN", "en"), _e("Outlet DE", "de")])
    _judged(s, "Outlet EN", STATUS_QUALIFIED, version=CURATED_CRITERIA_VERSION)
    _judged(s, "Outlet DE", STATUS_DISQUALIFIED)
    seed_sources(s, [_e("Outlet EN", "en"), _e("Outlet DE", "de"), _e("Outlet AR", "ar")])
    assert s.query(Source).filter_by(name="Outlet AR").one().status == STATUS_DISQUALIFIED


def test_the_stricter_verdict_wins_for_a_new_sibling(s):
    """R150/R153 in the seeder as in the restore: en (oldest) qualified, de disqualified -> the new sibling is disqualified."""
    seed_sources(s, [_e("Outlet EN", "en"), _e("Outlet DE", "de")])
    _judged(s, "Outlet EN", STATUS_QUALIFIED)
    _judged(s, "Outlet DE", STATUS_DISQUALIFIED)
    seed_sources(s, [_e("Outlet EN", "en"), _e("Outlet DE", "de"), _e("Outlet AR", "ar")])
    assert s.query(Source).filter_by(name="Outlet AR").one().status == STATUS_DISQUALIFIED


def test_a_corrected_feed_url_on_an_outlet_with_several_feeds_is_the_same_source(s):
    """Measured by the independent read: 'en' fixed to 'en-v2' on a two-feed outlet made a THIRD row and left the dead
    feed polled. The row whose recorded baseline carries that entry's name is the same source."""
    seed_sources(s, [_e("O en", "en"), _e("O ar", "ar")])
    result = seed_sources(s, [_e("O en", "en-v2"), _e("O ar", "ar")])
    assert result["created"] == 0 and s.query(Source).count() == 2
    assert sorted(r.rss_url for r in s.query(Source)) == ["https://outlet.example/ar.xml", "https://outlet.example/en-v2.xml"]


# --- the report adds up, and a refused conflicting lean is loud once (OPEN_QUEUE row J item 6 (a), (d)) ---
def _accounted(result):
    return result["created"] + result["skipped"] == result["total"] and result["skipped"] == (
        result["skipped_existing"] + result["merged"] + result["shadowed"]
        + result["skipped_malformed"] + result["held_back_legacy_key"]
    )


def test_every_entry_lands_in_exactly_one_counter(s):
    first = [
        _e("Outlet EN", "en"), _e("Outlet AR", "ar"),
        _e("Outlet", tags=["lean-left"]),                    # feed-less: merges onto the feed row in the same list
        _e("Outlet EN", "en"),                               # the same feed named twice: its tags merge (R145 amendment)
        _e("Bare", domain="bare.example"), _e("Bare", domain="bare.example"),   # a feed-less duplicate: unregistered
        {"domain": "nameless.example"},                      # no name
        {"name": "No domain"},                               # no domain
    ]
    r1 = seed_sources(s, first)
    assert _accounted(r1) and r1["merged"] == 2 and r1["skipped_malformed"] == 2 and r1["shadowed"] == 1
    # the legal-only call: the outlet's feed rows are in the database, not in the input (``extra_merges``)
    r2 = seed_sources(s, [_e("Outlet", tags=["wire"]), _e("Other", "x", domain="other.example")])
    assert _accounted(r2) and r2["merged"] == 1 and r2["created"] == 1
    r3 = seed_sources(s, first)
    assert _accounted(r3) and r3["created"] == 0


def test_a_store_that_cannot_hold_a_second_feed_still_accounts_for_every_entry(s, monkeypatch):
    seed_sources(s, [_e("Outlet EN", "en")])
    monkeypatch.setattr("src.ingest.seed_sources.composite_key_active", lambda _c: False)
    r = seed_sources(s, [_e("Outlet EN", "en"), _e("Outlet AR", "ar")])
    assert r["held_back_legacy_key"] == 1 and _accounted(r)


def test_a_refused_lean_is_listed_once_with_its_reason_and_only_counted_afterwards(s):
    entries = [_e("Outlet", "en", tags=["lean-right"]), _e("Outlet", tags=["lean-left"], _provenance="spectrum")]
    first = seed_sources(s, entries)["tag_merge"]
    assert first["conflict_count"] == 1 and first["refused_standing"] == 0
    refused = json.loads(s.query(Source).one().catalog_baseline)["refused_tags"]
    assert refused["lean-left"]["kept"] == "lean-right" and refused["lean-left"]["provenance"] == "spectrum"
    again = seed_sources(s, entries)["tag_merge"]
    assert again["conflict_count"] == 0 and again["conflicts"] == [] and again["refused_standing"] == 1
    assert "lean-left" not in s.query(Source).one().tags.split(",")


def test_a_refusal_lapses_when_the_kept_lean_is_removed_and_a_sync_keeps_the_record(s):
    row_entry = _e("Outlet", "en", tags=["lean-right", "wire"])    # a second tag: an EMPTY tag list is a gap reconcile refills
    spectrum = _e("Outlet", tags=["lean-left"], _provenance="spectrum")
    seed_sources(s, [row_entry, spectrum])
    assert "refused_tags" in json.loads(s.query(Source).one().catalog_baseline)
    renamed = seed_sources(s, [dict(row_entry, name="Outlet (renamed)"), spectrum])   # a correction rewrite must not forget it
    assert renamed["corrections"]["applied"] == 1
    assert renamed["tag_merge"]["conflict_count"] == 0 and renamed["tag_merge"]["refused_standing"] == 1
    assert "refused_tags" in json.loads(s.query(Source).one().catalog_baseline)
    row = s.query(Source).one()
    row.tags = ",".join(t for t in row.tags.split(",") if t != "lean-right")   # the operator removes the kept lean
    s.commit()
    out = seed_sources(s, [dict(row_entry, name="Outlet (renamed)"), spectrum])["tag_merge"]
    assert out["tags_merged"] == 1 and "lean-left" in s.query(Source).one().tags.split(",")
    assert "refused_tags" not in json.loads(s.query(Source).one().catalog_baseline)
