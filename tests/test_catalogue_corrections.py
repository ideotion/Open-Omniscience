"""A CORRECTION in the shipped catalogue must reach a row the operator never touched, and must
never overwrite one they did -- the three-way merge (maintainer-ruled 2026-09-11).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

THE SHAPE OF THE PROBLEM, which is why these tests are behavioural rather than structural.
``seed_sources`` skips a domain it already holds and ``reconcile_source_metadata`` fills only
EMPTY fields, so a corrected feed URL never reached an existing install -- measured. But the
naive repair (overwrite from the catalogue) silently reverts an operator's own edit, which is
strictly worse than the bug. Both halves therefore need pinning, and neither is visible in the
code of one function: the first is "does the fix arrive", the second is "does my edit survive".
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Source
from src.ingest.seed_sources import (
    CATALOGUE_OWNED_FIELDS,
    seed_sources,
    sync_catalogue_corrections,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _entry(domain="ex.example", **kw):
    e = {"name": "Example", "domain": domain, "rss_url": f"https://{domain}/feed",
         "country": "fr", "language": "fr", "region": "europe", "source_type": "news",
         "tags": ["news"], "enabled": True, "priority": 3, "rate_limit_ms": 2000}
    e.update(kw)
    return e


def _install(session, entries):
    """An install that seeded these entries and has since recorded its baseline (one boot)."""
    for e in entries:
        e.setdefault("_provenance", "curated")
    seed_sources(session, entries)          # seed_sources already runs the sync
    return session.query(Source).filter_by(domain=entries[0]["domain"]).one()


def test_a_corrected_feed_url_reaches_a_row_the_operator_never_touched(session):
    """The case that motivated the whole thing. Measured before it shipped: the row kept the
    stale URL through any number of re-seeds, and export/import was the only remedy."""
    row = _install(session, [_entry()])
    assert row.rss_url == "https://ex.example/feed"

    fixed = _entry(rss_url="https://ex.example/rss.xml")   # the catalogue corrects it
    result = sync_catalogue_corrections(session, [fixed])
    session.refresh(row)

    assert row.rss_url == "https://ex.example/rss.xml"
    assert result["applied"] == 1 and result["kept"] == 0


def test_an_operator_edit_is_kept_and_reported_never_overwritten(session):
    """The half that makes the other half safe. A re-seed silently reverting a hand-set value
    is, in reconcile_source_metadata's own words, a data-loss bug wearing a maintenance task's
    clothes -- so the divergence is REPORTED by domain and field instead."""
    row = _install(session, [_entry()])
    row.rss_url = "https://ex.example/my-own-feed"          # the operator edits it in the UI
    session.commit()

    fixed = _entry(rss_url="https://ex.example/rss.xml")    # and the catalogue corrects it too
    result = sync_catalogue_corrections(session, [fixed])
    session.refresh(row)

    assert row.rss_url == "https://ex.example/my-own-feed"  # theirs stands
    assert result["applied"] == 0 and result["kept"] == 1
    (conflict,) = result["conflicts"]
    assert conflict == {"domain": "ex.example", "field": "rss_url",
                        "kept": "https://ex.example/my-own-feed",
                        "catalogue": "https://ex.example/rss.xml"}


def test_a_row_with_no_baseline_adopts_the_catalogue_and_changes_nothing(session):
    """Every row predating the column is in this position. We cannot tell an operator's edit
    from a shipped value without a baseline, so the first boot RECORDS where things stand --
    guessing is exactly what the column exists to avoid."""
    row = _install(session, [_entry()])
    row.rss_url = "https://ex.example/whatever-this-is"
    row.catalog_baseline = None                            # as if the row predates the column
    session.commit()

    result = sync_catalogue_corrections(session, [_entry(rss_url="https://ex.example/rss.xml")])
    session.refresh(row)

    assert row.rss_url == "https://ex.example/whatever-this-is"   # untouched, on purpose
    assert result["adopted"] == 1 and result["applied"] == 0 and result["kept"] == 0
    # ...and the baseline now reflects the catalogue, so the NEXT correction does flow.
    assert json.loads(row.catalog_baseline)["rss_url"] == "https://ex.example/rss.xml"
    again = sync_catalogue_corrections(session, [_entry(rss_url="https://ex.example/v3")])
    session.refresh(row)
    assert again["kept"] == 1 and row.rss_url == "https://ex.example/whatever-this-is"


def test_a_steady_catalogue_writes_nothing_and_a_conflict_is_reported_only_once(session):
    """Two properties that keep this cheap and quiet: an unchanged catalogue costs comparisons
    and no writes, and a kept edit does not nag on every boot for the life of the install."""
    row = _install(session, [_entry()])
    assert sync_catalogue_corrections(session, [_entry()]) ["applied"] == 0

    row.rss_url = "https://ex.example/mine"
    session.commit()
    fixed = _entry(rss_url="https://ex.example/rss.xml")
    assert sync_catalogue_corrections(session, [fixed])["kept"] == 1
    assert sync_catalogue_corrections(session, [fixed])["kept"] == 0   # reported once
    session.refresh(row)
    assert row.rss_url == "https://ex.example/mine"                    # still theirs


def test_an_empty_field_is_a_gap_not_an_edit_so_the_two_mechanisms_never_fight(session):
    """reconcile_source_metadata owns empties; this owns corrections. Without the rule, a field
    reconcile had just filled would read as an operator edit on the very same boot."""
    row = _install(session, [_entry()])
    row.country = None
    session.commit()

    result = sync_catalogue_corrections(session, [_entry(country="es")])
    session.refresh(row)
    assert result["kept"] == 0 and result["applied"] == 0   # not claimed as an edit
    assert row.country is None                              # and not filled here either


def test_the_operators_own_knobs_are_never_catalogue_owned(session):
    """enabled / priority / rate_limit_ms are what the UI exists to set. A catalogue that
    disagrees with the operator about them is not a correction, it is a reversion."""
    for knob in ("enabled", "priority", "rate_limit_ms", "reliability_score", "tags"):
        assert knob not in CATALOGUE_OWNED_FIELDS

    row = _install(session, [_entry()])
    row.enabled, row.priority, row.rate_limit_ms = False, 1, 9000
    session.commit()
    sync_catalogue_corrections(session, [_entry(enabled=True, priority=3, rate_limit_ms=2000)])
    session.refresh(row)
    assert (row.enabled, row.priority, row.rate_limit_ms) == (False, 1, 9000)


def test_every_owned_field_actually_carries_a_correction(session):
    """Anti-vacuity: a field listed as owned but never compared would pass every test above."""
    row = _install(session, [_entry()])
    corrected = _entry(rss_url="https://ex.example/v2", name="Example Daily", country="es",
                       language="es", region="asia", source_type="magazine")
    result = sync_catalogue_corrections(session, [corrected])
    session.refresh(row)
    assert result["applied"] == len(CATALOGUE_OWNED_FIELDS), result
    for field in CATALOGUE_OWNED_FIELDS:
        assert str(getattr(row, field)).lower() == str(corrected[field]).lower(), field


# ---- what Q's trace of the "kept 9 / kept 10" report found (2026-10-17): none of the nine was an operator edit ----------

def _set_baseline(row, **fields):
    base = json.loads(row.catalog_baseline)
    base.update(fields)
    row.catalog_baseline = json.dumps(base, sort_keys=True)


def test_a_field_reconcile_just_filled_with_the_catalogues_own_value_is_not_reported_as_an_edit(session):
    """Shape A: the gap was filled earlier in the SAME call with exactly what the catalogue ships now, so there is nothing to
    apply and nothing to keep. It used to be listed as an operator edit (live 'fr' != baseline None), and nine false ones
    pushed a real one out of the eight listed examples."""
    row = _install(session, [_entry()])
    row.language = None
    _set_baseline(row, language=None)
    session.commit()

    result = seed_sources(session, [_entry(_provenance="curated")])["corrections"]
    session.refresh(row)
    assert row.language == "fr"
    assert result["kept"] == 0 and result["conflicts"] == [] and result["advanced"] >= 1
    assert json.loads(row.catalog_baseline)["language"] == "fr"        # the baseline moved: no second report either


def test_a_baseline_taken_from_another_catalogue_against_the_column_default_is_not_an_edit(session):
    """Shape B: the news entry ships no source_type, the row holds the column default 'news' (nobody chose it) and the
    baseline holds the OTHER catalogue's 'law'. It is not an operator edit: the baseline moves, the row is unchanged."""
    entry = _entry()
    entry.pop("source_type")
    row = _install(session, [entry])
    row.source_type = "news"
    _set_baseline(row, source_type="law")
    session.commit()

    result = sync_catalogue_corrections(session, [entry])
    session.refresh(row)
    assert row.source_type == "news"
    assert result["kept"] == 0 and result["conflicts"] == [] and result["advanced"] == 1 and result["dropped"] == 0
    assert json.loads(row.catalog_baseline)["source_type"] is None
    assert sync_catalogue_corrections(session, [entry])["advanced"] == 0     # reported once


def test_a_real_operator_edit_is_listed_even_beside_many_false_ones(session):
    """The false kept-conflicts crowded the eight listed examples; with them gone the one real edit is the only entry."""
    rows = []
    for i in range(10):
        row = _install(session, [_entry(domain=f"d{i}.example")])
        row.language = None
        _set_baseline(row, language=None)
        rows.append(row)
    mine = rows[3]
    mine.language = None
    mine.name = "My name for it"
    session.commit()
    entries = [_entry(domain=f"d{i}.example", _provenance="curated", **({"name": "Corrected"} if i == 3 else {}))
               for i in range(10)]
    result = seed_sources(session, entries)["corrections"]
    assert [c["field"] for c in result["conflicts"]] == ["name"] and result["conflicts"][0]["domain"] == "d3.example"


def test_a_catalogue_that_stops_shipping_a_field_never_nulls_the_live_value(session):
    """R100, inferred in the trace and made a test first: the sync wrote ``computed.get(field)`` (None for an entry that
    ships no value) over a live value that equalled the old baseline, so a dropped ``source_type`` (nullable) or a
    feed-less entry would have nulled it. The value stays, the field is counted as dropped, and it is reported once."""
    entry = _entry(source_type="legal")
    row = _install(session, [entry])
    dropped = _entry()
    dropped.pop("source_type")
    dropped.pop("rss_url")
    result = sync_catalogue_corrections(session, [dropped])
    session.refresh(row)
    assert row.source_type == "legal" and row.rss_url == "https://ex.example/feed"
    assert result["applied"] == 0 and result["kept"] == 0 and result["dropped"] == 2
    assert sync_catalogue_corrections(session, [dropped])["dropped"] == 0


# --- R167: a field the catalogue starts shipping, on a row that holds the column default --------------------------------
def _installed_without_region_and_type(session, domain="ex.example"):
    first = _entry(domain)
    first.pop("region")
    first.pop("source_type")
    row = _install(session, [first])
    assert (row.region, row.source_type) == ("global", "news"), "the row took the column defaults"
    base = json.loads(row.catalog_baseline)
    assert base["region"] is None and base["source_type"] is None, "and the baseline recorded that the catalogue shipped none"
    return row


def test_a_field_the_catalogue_starts_shipping_reaches_a_row_that_holds_the_column_default(session):
    """The Opus read's M1: 1,807 of 5,580 sources.yml entries ship no region and 3,140 no source_type, so those rows hold
    the column default with a baseline of None. When the catalogue fills either, the value fell through to the operator-edit
    list and was never applied (live != baseline None, live != the new value, live != baseline). Red without the R167 clause."""
    row = _installed_without_region_and_type(session)
    result = sync_catalogue_corrections(session, [_entry(region="europe", source_type="legal")])
    session.refresh(row)
    assert (row.region, row.source_type) == ("europe", "legal")
    assert result["applied"] == 2 and result["kept"] == 0 and result["conflicts"] == []
    assert json.loads(row.catalog_baseline)["region"] == "europe"
    assert sync_catalogue_corrections(session, [_entry(region="europe", source_type="legal")])["applied"] == 0


def test_a_value_the_operator_chose_over_the_default_is_still_kept_when_the_catalogue_starts_shipping_one(session):
    row = _installed_without_region_and_type(session)
    row.region = "asia"
    session.commit()
    result = sync_catalogue_corrections(session, [_entry(region="europe", source_type="legal")])
    session.refresh(row)
    assert row.region == "asia" and row.source_type == "legal"
    assert result["kept"] == 1 and result["conflicts"][0]["field"] == "region" and result["applied"] == 1


def test_r167_a_value_typed_exactly_as_the_default_is_taken_for_never_edited_a_known_limit(session):
    """THE ASSUMPTION R167 MAKES, stated as a test so it is not discovered later: nothing in the app records which fields an
    operator edited (the PUT allowlist does not even reach region or source_type, and the only per-row record is
    ``catalog_baseline``), so an operator who set region to exactly ``"global"`` on a row whose baseline is None is
    indistinguishable from one who never touched it, and receives the catalogue's value. The ``now is None`` branch makes the
    same assumption in the other direction. If a per-field edit marker ever exists it must win here, and this test changes."""
    row = _installed_without_region_and_type(session)
    row.region = "global"      # typed by hand, equal to the default
    session.commit()
    sync_catalogue_corrections(session, [_entry(region="europe", source_type="legal")])
    session.refresh(row)
    assert row.region == "europe"


def test_the_catalogue_filling_region_and_type_on_the_real_sources_yml_shape_lists_no_false_edit(session):
    """The shape of the real file, not a toy: entries of configs/sources.yml that ship no region or no source_type are seeded
    as they are (rows hold the defaults), then the catalogue fills every one of them. Zero conflicts, every fill applied."""
    from src.ingest.seed_sources import load_sources_from_yaml

    real = [e for e in load_sources_from_yaml() if not e.get("region") or not e.get("source_type")]
    assert len(real) > 1000, "the real catalogue still ships many entries without a region or a type"
    real = real[:400]
    entries = []
    for e in real:
        e = {k: v for k, v in e.items() if k not in ("region", "source_type")}
        e["_provenance"] = "curated"
        entries.append(e)
    seed_sources(session, entries)
    assert session.query(Source).filter(Source.region == "global", Source.source_type == "news").count() == len(entries)
    filled = [dict(e, region="europe", source_type="legal") for e in entries]
    result = sync_catalogue_corrections(session, filled)
    assert result["kept"] == 0 and result["conflicts"] == []
    assert result["applied"] == 2 * len(entries)
    assert session.query(Source).filter(Source.region == "europe", Source.source_type == "legal").count() == len(entries)

