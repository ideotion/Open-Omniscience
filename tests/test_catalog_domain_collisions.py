"""Catalogue entries a domain-keyed seeder can never register must be COUNTED.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``Source.domain`` is UNIQUE and ``seed_sources`` is create-only, so one registrable
domain holds exactly one feed. ``configs/sources.yml`` describes several feeds per
domain in 54 places, and the losers were counted in the same ``skipped`` number as an
idempotent re-run -- so 227 of 3,429 entries have never been registered on any install,
invisibly.

WHY THIS IS A GUARD AND NOT A DELETION. The shadowed entries are not redundant rows:
``bbc.com`` carries 31 and the 30 that lose are BBC's non-English language services;
``dw.com`` shadows DW Arabic, Deutsch, Español and Brasil. Measured over all 227, **108
are in a different language than the surviving sibling** -- for those, the corpus loses
a language it would otherwise have had from that outlet. Deleting them to make the
catalogue "clean" would delete exactly the multilingual breadth the de-US-centring and
language-equilibrium work exists to build, so the repair is a maintainer ruling about
source identity (a domain, or a feed) and this file makes the number visible until then.

The budget is a MAXIMUM that may only fall, with the twin that keeps it honest: a
budget left above the real count is itself a defect, because it hides the next
collision someone adds.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base
from src.ingest.seed_sources import (
    catalog_domain_collisions,
    load_sources_from_yaml,
    seed_sources,
)

#: Measured on configs/sources.yml, 2026-09-07: 54 domains, 227 entries that can never
#: be registered. Lower it when a collision is genuinely resolved; never raise it to
#: admit a new one -- adding a second entry for a domain the catalogue already claims
#: silently discards the new entry, which is the thing this pins.
_COLLIDING_DOMAINS_BUDGET = 54
_SHADOWED_ENTRIES_BUDGET = 227


@pytest.fixture(scope="module")
def catalog() -> list[dict]:
    return load_sources_from_yaml()


@pytest.fixture()
def session():
    """An isolated in-memory corpus -- the seeder is the only writer here."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    try:
        yield s
    finally:
        s.close()


def test_the_curated_catalog_does_not_grow_new_unreachable_entries(catalog):
    collisions = catalog_domain_collisions(catalog)
    shadowed = sum(len(v) for v in collisions.values())
    assert len(collisions) <= _COLLIDING_DOMAINS_BUDGET, (
        f"{len(collisions)} domains now carry more than one catalogue entry "
        f"(budget {_COLLIDING_DOMAINS_BUDGET}). A second entry for a domain the "
        "catalogue already claims is silently discarded by the seeder."
    )
    assert shadowed <= _SHADOWED_ENTRIES_BUDGET, (
        f"{shadowed} catalogue entries can never be registered "
        f"(budget {_SHADOWED_ENTRIES_BUDGET})."
    )


def test_the_budget_is_not_left_above_the_real_count(catalog):
    """A ratchet left slack is a ratchet that cannot fire."""
    collisions = catalog_domain_collisions(catalog)
    assert len(collisions) == _COLLIDING_DOMAINS_BUDGET
    assert sum(len(v) for v in collisions.values()) == _SHADOWED_ENTRIES_BUDGET


def test_the_loss_is_disproportionately_non_english(catalog):
    """The reason this is not resolved by deletion, asserted rather than asserted-in-prose."""
    collisions = catalog_domain_collisions(catalog)
    winner = {}
    for entry in catalog:
        winner.setdefault(entry["domain"], entry)
    differing = [
        e
        for dom, lost in collisions.items()
        for e in lost
        if (e.get("language") or "?") != (winner[dom].get("language") or "?")
    ]
    assert len(differing) >= 100, (
        "the shadowed entries were expected to be dominated by other-language editions "
        f"of the surviving sibling; got {len(differing)}"
    )
    # The specific case the ruling is about, named so a future reader can check it.
    assert any(e.get("name") == "BBC Arabic" for e in collisions.get("bbc.com", []))


# --------------------------------------------------------------------------- #
#  The seeder tells the two skip reasons apart
# --------------------------------------------------------------------------- #
_TWO_FEEDS = [
    {"name": "Outlet EN", "domain": "outlet.example", "language": "en"},
    {"name": "Outlet AR", "domain": "outlet.example", "language": "ar"},
]


def test_a_shadowed_entry_is_reported_apart_from_an_idempotent_skip(session):
    first = seed_sources(session, _TWO_FEEDS)
    assert first["created"] == 1
    # The second feed lost to its own sibling, not to a pre-existing database row.
    assert first["shadowed"] == 1
    assert first["skipped_existing"] == 0
    assert first["shadowed_examples"] == [{"name": "Outlet AR", "domain": "outlet.example"}]
    # `skipped` keeps its old meaning (the sum), so existing callers read unchanged.
    assert first["skipped"] == 1
    assert first["created"] + first["skipped"] == first["total"]


def test_an_idempotent_re_run_reports_no_shadowing(session):
    """The negative twin. A count that called every skip 'shadowed' would satisfy the
    test above while turning a healthy re-seed into a permanent catalogue defect."""
    seed_sources(session, _TWO_FEEDS)
    second = seed_sources(session, _TWO_FEEDS)
    assert second["created"] == 0
    assert second["skipped"] == 2
    # One row already existed (idempotent); the sibling is still shadowed by it.
    assert second["skipped_existing"] == 1
    assert second["shadowed"] == 1


def test_a_collision_free_catalog_reports_nothing(session):
    """A catalogue with no collisions must report an empty loss, not an empty-ish one."""
    clean = [
        {"name": "A", "domain": "a.example", "language": "en"},
        {"name": "B", "domain": "b.example", "language": "fr"},
    ]
    assert catalog_domain_collisions(clean) == {}
    result = seed_sources(session, clean)
    assert result["created"] == 2
    assert result["shadowed"] == 0
    assert result["shadowed_examples"] == []


def test_the_seeder_and_the_report_agree_on_the_real_catalog(catalog, session):
    """One rule, two implementations: the loop that decides what lands and the
    function that reports what cannot must never drift. Asserted on the real
    catalogue rather than a fixture, because that is where a drift would matter."""
    result = seed_sources(session, catalog)
    expected = sum(len(v) for v in catalog_domain_collisions(catalog).values())
    assert result["shadowed"] == expected == _SHADOWED_ENTRIES_BUDGET
    # And every non-shadowed entry did land: nothing else is silently lost.
    assert result["created"] == len(catalog) - expected
    assert result["skipped_existing"] == 0
