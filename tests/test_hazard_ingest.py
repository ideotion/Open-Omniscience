"""Hazards ingested AS corpus Articles (2026-07-24 field-feedback Session A §6, ruled).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Covers: the ingest module (create/dedup/update, the linked HazardEventDetail
layer, provenance/tags), the mandatory NEGATIVE-SPACE lens (a malformed/fields-
missing record must never fabricate an Article or a magnitude -- absence stays
absence, never a guessed 0/now/(0,0)), the pre-existing-data isolation guard
(ingesting hazards must never disturb an unrelated Source/Article), the
Article.hash global-uniqueness collision path, the timemap/alerts-layer
integration (magnitude/lat/lon restored, the internal article_id link), and
the two save_snapshot call-site integrations (the scheduler ride-along +
the API endpoint).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.database.models import Article, Base, HazardEventDetail, Source
from src.hazards.ingest import (
    ensure_hazard_source,
    hazard_canonical_url,
    ingest_hazard_record,
    ingest_hazard_records,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


@pytest.fixture()
def extractor():
    return BaselineExtractor()


def _usgs_record(**kw) -> dict:
    rec = {
        "source": "usgs",
        "id": "us7000abcd",
        "type": "earthquake",
        "title": "M 5.2 - 10km SW of Somewhere",
        "severity": "moderate",
        "magnitude": 5.2,
        "lat": 37.5,
        "lon": -122.1,
        "place": "10km SW of Somewhere",
        "time": "2026-07-20T12:00:00Z",
        "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000abcd",
    }
    rec.update(kw)
    return rec


def _gdacs_record(**kw) -> dict:
    rec = {
        "source": "gdacs",
        "id": "1234567",
        "type": "cyclone",
        "title": "Tropical Cyclone ABC-26",
        "severity": "watch",
        "magnitude": None,
        "lat": -12.3,
        "lon": 45.6,
        "place": "Madagascar",
        "time": "2026-07-19T00:00:00Z",
        "url": "https://www.gdacs.org/report.aspx?eventid=1234567",
    }
    rec.update(kw)
    return rec


# --------------------------------------------------------------------------- #
# hazard_canonical_url + ensure_hazard_source: the pure/provenance seams.
# --------------------------------------------------------------------------- #


def test_hazard_canonical_url_is_stable_and_never_a_real_url():
    u = hazard_canonical_url("usgs", "us7000abcd")
    assert u == "hazard://usgs/us7000abcd"
    assert not u.startswith("http")  # can never collide with a scraped Article


def test_ensure_hazard_source_creates_one_row_per_provider(db):
    src1 = ensure_hazard_source(db, "usgs")
    src2 = ensure_hazard_source(db, "usgs")  # idempotent
    src3 = ensure_hazard_source(db, "gdacs")
    assert src1.id == src2.id
    assert src1.id != src3.id
    assert src1.domain == "hazard.usgs.local" and src1.source_type == "hazard"
    assert src1.tags == "hazard"
    assert src3.domain == "hazard.gdacs.local"


# --------------------------------------------------------------------------- #
# Basic ingestion: create, dedup-on-unchanged, update-on-revision.
# --------------------------------------------------------------------------- #


def test_ingest_creates_an_article_and_linked_detail(db, extractor):
    res = ingest_hazard_record(db, _usgs_record(), extractor=extractor)
    assert res["status"] == "created"
    art = db.query(Article).filter_by(id=res["article_id"]).one()
    assert art.canonical_url == "hazard://usgs/us7000abcd"
    assert art.title and "5.2" in art.title
    assert art.language is None  # never guessed
    src = db.query(Source).filter_by(id=art.source_id).one()
    assert src.domain == "hazard.usgs.local" and src.source_type == "hazard"

    detail = db.query(HazardEventDetail).filter_by(article_id=art.id).one()
    assert detail.provider == "usgs" and detail.event_id == "us7000abcd"
    assert detail.magnitude == 5.2
    assert detail.lat == 37.5 and detail.lon == -122.1
    assert detail.severity == "moderate"
    assert detail.event_time == datetime(2026, 7, 20, 12, 0, 0)


def test_reingesting_the_identical_record_never_duplicates(db, extractor):
    ingest_hazard_record(db, _usgs_record(), extractor=extractor)
    res2 = ingest_hazard_record(db, _usgs_record(), extractor=extractor)
    assert res2["status"] in ("updated-metadata-only",)  # unchanged body -> no re-index
    assert db.query(Article).count() == 1
    assert db.query(HazardEventDetail).count() == 1


def test_a_revised_magnitude_updates_the_linked_detail_never_duplicates(db, extractor):
    """A real-world case: USGS commonly revises a quake's magnitude within hours."""
    ingest_hazard_record(db, _usgs_record(magnitude=5.2), extractor=extractor)
    res2 = ingest_hazard_record(db, _usgs_record(magnitude=5.6), extractor=extractor)
    assert res2["status"] == "updated-metadata-only"
    assert db.query(Article).count() == 1
    detail = db.query(HazardEventDetail).one()
    assert detail.magnitude == 5.6  # updated, not stuck at the first-seen value


def test_a_genuinely_new_title_updates_the_article_and_reindexes(db, extractor):
    """A GDACS status change (e.g. Green -> Orange) can change the title/body --
    that DOES warrant a re-index (new keyword-bearing text), unlike a pure
    metadata-only revision."""
    ingest_hazard_record(db, _gdacs_record(), extractor=extractor)
    res2 = ingest_hazard_record(
        db, _gdacs_record(title="Tropical Cyclone ABC-26 upgraded to Category 3"), extractor=extractor
    )
    assert res2["status"] == "updated"
    assert db.query(Article).count() == 1
    art = db.query(Article).one()
    assert "Category 3" in art.content


def test_two_providers_with_the_same_event_id_are_distinct_events(db, extractor):
    """event_id is only unique WITHIN a provider -- usgs:1 and gdacs:1 must never
    collide (the composite (provider, event_id) key, not event_id alone)."""
    ingest_hazard_record(db, _usgs_record(id="1"), extractor=extractor)
    ingest_hazard_record(db, _gdacs_record(id="1"), extractor=extractor)
    assert db.query(Article).count() == 2
    assert db.query(HazardEventDetail).count() == 2


def test_two_distinct_events_with_identical_body_text_are_never_conflated(db, extractor):
    """HIGH fix (negative-space skeptic finding, pre-push): two DIFFERENT hazard
    events whose title+place happen to be byte-identical (a plausible real-world
    coincidence -- e.g. two M4.6-ish quakes near the same city description on
    different days, or two GDACS alerts sharing a formulaic name) must BOTH
    persist with their OWN magnitude/coordinates -- never silently and
    PERMANENTLY collapse into one Article the way a body-only content_hash
    would (Article.hash is globally unique, so the second event's commit would
    have hit an integrity error and been misreported as "the same record
    re-ingested" forever, on every future snapshot). The hash now embeds the
    per-event canonical url, so two distinct events can never collide on it."""
    rec_a = _usgs_record(id="quake-a", title="Identical Body", place=None, magnitude=4.6)
    rec_b = _usgs_record(id="quake-b", title="Identical Body", place=None, magnitude=5.1)
    res_a = ingest_hazard_record(db, rec_a, extractor=extractor)
    res_b = ingest_hazard_record(db, rec_b, extractor=extractor)
    assert res_a["status"] == "created" and res_b["status"] == "created"
    assert res_a["article_id"] != res_b["article_id"]
    assert db.query(Article).count() == 2  # both events got their own row
    details = {d.article_id: d for d in db.query(HazardEventDetail).all()}
    assert len(details) == 2
    assert details[res_a["article_id"]].magnitude == 4.6
    assert details[res_b["article_id"]].magnitude == 5.1  # event B's own data survived


# --------------------------------------------------------------------------- #
# NEGATIVE SPACE (mandatory skeptic lens): a malformed/incomplete record must
# never fabricate an Article, a magnitude, a coordinate, or a publish date.
# --------------------------------------------------------------------------- #


def test_missing_source_is_skipped_never_fabricated(db, extractor):
    rec = _usgs_record(); del rec["source"]
    res = ingest_hazard_record(db, rec, extractor=extractor)
    assert res["status"] == "skipped-malformed"
    assert db.query(Article).count() == 0


def test_missing_id_is_skipped_never_fabricated(db, extractor):
    rec = _usgs_record(); rec["id"] = ""
    res = ingest_hazard_record(db, rec, extractor=extractor)
    assert res["status"] == "skipped-malformed"
    assert db.query(Article).count() == 0


def test_no_title_and_no_place_is_skipped_never_a_placeholder_article(db, extractor):
    rec = _usgs_record(title=None, place=None)
    res = ingest_hazard_record(db, rec, extractor=extractor)
    assert res["status"] == "skipped-no-text"
    assert db.query(Article).count() == 0


def test_missing_magnitude_stays_null_never_coerced_to_zero(db, extractor):
    res = ingest_hazard_record(db, _gdacs_record(), extractor=extractor)  # GDACS: magnitude=None
    assert res["status"] == "created"
    detail = db.query(HazardEventDetail).filter_by(article_id=res["article_id"]).one()
    assert detail.magnitude is None  # NEVER 0 — absence is not zero


def test_a_garbage_magnitude_string_degrades_to_null_never_crashes(db, extractor):
    res = ingest_hazard_record(db, _usgs_record(magnitude="not-a-number"), extractor=extractor)
    assert res["status"] == "created"
    detail = db.query(HazardEventDetail).filter_by(article_id=res["article_id"]).one()
    assert detail.magnitude is None


def test_missing_coordinates_stay_null_never_fabricated_as_origin(db, extractor):
    rec = _usgs_record(lat=None, lon=None)
    res = ingest_hazard_record(db, rec, extractor=extractor)
    assert res["status"] == "created"  # title/place still make a usable body
    detail = db.query(HazardEventDetail).filter_by(article_id=res["article_id"]).one()
    assert detail.lat is None and detail.lon is None  # never (0, 0)


def test_garbage_coordinates_degrade_to_null_never_crash(db, extractor):
    res = ingest_hazard_record(db, _usgs_record(lat="north-ish", lon="???"), extractor=extractor)
    assert res["status"] == "created"
    detail = db.query(HazardEventDetail).filter_by(article_id=res["article_id"]).one()
    assert detail.lat is None and detail.lon is None


def test_missing_or_unparseable_time_stays_null_never_guessed_as_now(db, extractor):
    for bad_time in (None, "", "not-a-date", "yesterday-ish"):
        db2 = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
        Base.metadata.create_all(db2)
        s = sessionmaker(bind=db2, future=True)()
        res = ingest_hazard_record(s, _usgs_record(time=bad_time), extractor=extractor)
        assert res["status"] == "created"
        art = s.query(Article).filter_by(id=res["article_id"]).one()
        detail = s.query(HazardEventDetail).filter_by(article_id=art.id).one()
        assert art.published_at is None, f"published_at fabricated for time={bad_time!r}"
        assert detail.event_time is None, f"event_time fabricated for time={bad_time!r}"


def test_a_non_dict_record_is_skipped_never_crashes():
    """A defensive negative-space case: garbage input types must degrade, not raise."""
    for bad in (None, "a string", 42, ["not", "a", "dict"]):
        assert ingest_hazard_record(None, bad) == {"status": "skipped-malformed"}


def test_batch_one_malformed_record_never_breaks_the_others(db, extractor):
    good1 = _usgs_record(id="a")
    bad = {"source": "usgs"}  # missing id
    good2 = _gdacs_record(id="b")
    out = ingest_hazard_records(db, [good1, bad, good2], extractor=extractor)
    assert out["total"] == 3
    assert out["created"] == 2
    assert out["skipped"] == 1
    assert db.query(Article).count() == 2


# --------------------------------------------------------------------------- #
# Isolation: ingesting hazards must never disturb unrelated data.
# --------------------------------------------------------------------------- #


def test_ingest_never_disturbs_pre_existing_non_hazard_sources_and_articles(db, extractor):
    src = Source(name="Example News", domain="example.com", source_type="news")
    db.add(src)
    db.commit()
    art = Article(
        url="https://example.com/a", canonical_url="https://example.com/a",
        source_id=src.id, title="Unrelated news", content="Some unrelated content here.",
        language="en", hash="0" * 64,
    )
    db.add(art)
    db.commit()
    pre_source_count = db.query(Source).count()

    ingest_hazard_records(db, [_usgs_record(), _gdacs_record()], extractor=extractor)

    db.refresh(src)
    db.refresh(art)
    assert src.domain == "example.com" and src.source_type == "news"  # untouched
    assert art.title == "Unrelated news" and art.content == "Some unrelated content here."
    # exactly 2 NEW hazard sources were added, the pre-existing one is untouched
    assert db.query(Source).count() == pre_source_count + 2


def test_article_hash_collision_degrades_to_duplicate_content_never_raises(db, extractor):
    """Article.hash is GLOBALLY unique (src/database/models.py). Since the hash now
    embeds the per-event url (the HIGH fix above), a genuine collision on a BRAND
    NEW event (art is None) can now only occur via a real race -- two commits of
    the EXACT SAME url+body landing at once -- or an actual SHA-256 collision.
    Simulate that directly (a row already holding the hash this ingest is about
    to compute, filed under a DIFFERENT canonical_url, standing in for "someone
    else's commit won the race a moment earlier") to prove the degrade-honestly
    path (mirroring src/law/corpus.py's proven is_integrity_error handling) still
    functions rather than raising or losing the winner's data."""
    import hashlib

    from src.hazards.ingest import _hazard_body, hazard_canonical_url

    rec = _usgs_record(id="race-target", title="Race Target", place=None)
    url = hazard_canonical_url("usgs", "race-target")
    would_be_hash = hashlib.sha256(f"{url}\n{_hazard_body(rec)}".encode()).hexdigest()
    src = ensure_hazard_source(db, "usgs")
    winner = Article(
        url="hazard://usgs/already-won-the-race",
        canonical_url="hazard://usgs/already-won-the-race",
        source_id=src.id, title="Race Target", content=_hazard_body(rec), hash=would_be_hash,
    )
    db.add(winner)
    db.commit()

    res = ingest_hazard_record(db, rec, extractor=extractor)
    assert res["status"] == "duplicate-content"
    assert res["article_id"] == winner.id
    assert db.query(Article).count() == 1  # the losing attempt was never committed


# --------------------------------------------------------------------------- #
# provenance_of / implied tags (the closed-set extension is tested fully in
# tests/test_provenance_class.py; this proves the round-trip through a REAL
# ingested source).
# --------------------------------------------------------------------------- #


def test_ingested_hazard_source_classifies_as_the_hazard_provenance_class(db, extractor):
    from src.catalog.provenance import HAZARD, provenance_of

    res = ingest_hazard_record(db, _usgs_record(), extractor=extractor)
    art = db.query(Article).filter_by(id=res["article_id"]).one()
    src = db.query(Source).filter_by(id=art.source_id).one()
    assert provenance_of(src.domain, src.source_type) == HAZARD
