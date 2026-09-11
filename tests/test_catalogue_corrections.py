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
