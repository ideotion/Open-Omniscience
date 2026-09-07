"""Catalogue entries a domain-keyed seeder can never register must be COUNTED.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``Source.domain`` is UNIQUE and ``seed_sources`` is create-only, so one registrable
domain holds exactly one feed. The losers were counted in the same ``skipped`` number
as an idempotent re-run, so they were invisible.

TWO FIGURES, BECAUSE THEY ANSWER DIFFERENT QUESTIONS, and pinning only the first was
the first cut's mistake -- it named the number a reader of the catalogue file would
compute, not the number an install reports:

  * ``configs/sources.yml`` alone: 54 domains, 227 entries.
  * what ``seed_default_sources`` actually hands the seeder -- five catalogues
    concatenated: 299 domains, **475 of 3,870 entries**. That is what
    ``POST /api/sources/seed-defaults`` returns on a real boot.

The extra 248 are CROSS-catalogue and they are not the same story: 220 are
``sources_spectrum.yml`` losing to ``sources.yml``, 24 markets, 4 legal. Measured, 192
of the shadowed entries carry a ``lean-*`` tag the surviving sibling does not have --
``cnn.com`` loses ``lean-center-left``, ``dailymail.co.uk`` loses ``lean-right`` -- so
the political-lean catalogue is 79% shadowed by the curated one and that vocabulary
(``src/catalog/taxonomy.py``) reaches the database for barely any outlet that has it.

WHY THIS IS A GUARD AND NOT A DELETION. The shadowed entries are not redundant rows:
``bbc.com`` carries 31 and the 30 that lose are BBC's non-English language services;
``dw.com`` shadows DW Arabic, Deutsch, Español and Brasil. Of the 227 in the curated
file, **75 declare a language and declare a DIFFERENT one than the sibling that
survives** -- for those the corpus loses a language it would otherwise have had from
that outlet. (108 entries "differ" if a missing ``language`` field is counted as a
value; 33 of those are absent-vs-present artifacts on shared-domain journal families,
not lost languages, so 75 is the figure that carries the argument.) Deleting any of it
to make the catalogue "clean" would delete exactly the multilingual breadth the
de-US-centring and language-equilibrium work exists to build, so the repair is a
maintainer ruling about source identity (a domain, or a feed) and this file makes the
number visible until then.

The budgets are MAXIMA that may only fall, with the twin that keeps them honest: a
budget left above the real count is itself a defect, because it hides the next
collision someone adds.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Source
from src.ingest.seed_sources import (
    catalog_domain_collisions,
    load_sources_from_yaml,
    seed_sources,
)

#: Measured 2026-09-07 on configs/sources.yml alone: 54 domains, 227 entries that can
#: never be registered. Lower it when a collision is genuinely resolved; never raise it
#: to admit a new one -- adding a second entry for a domain the catalogue already
#: claims silently discards the new entry, which is the thing this pins.
_COLLIDING_DOMAINS_BUDGET = 54
_SHADOWED_ENTRIES_BUDGET = 227

#: Measured 2026-09-07 on what seed_default_sources really builds. This is the one an
#: install reports, and the one that catches a CROSS-catalogue collision -- invisible
#: to the per-file budget above, and already 248 entries strong.
_BOOT_COLLIDING_DOMAINS_BUDGET = 299
_BOOT_SHADOWED_ENTRIES_BUDGET = 475

#: Shadowed entries that declare a language and declare a DIFFERENT one than the
#: sibling that survives -- the loss that is genuinely a lost language, as opposed to
#: a field one side simply left blank. This is the number the "do not delete" argument
#: rests on; see the test for why the looser 108 does not.
_LANGUAGE_LOSSES = 75

#: Shadowed entries carrying a `lean-*` tag their surviving sibling lacks. The tag
#: never reaches Source.tags for these outlets, so the political-lean vocabulary is
#: mostly absent from the database it was written for.
_LEAN_TAGS_LOST_BUDGET = 192


@pytest.fixture(scope="module")
def catalog() -> list[dict]:
    return load_sources_from_yaml()


@pytest.fixture(scope="module")
def boot_catalog() -> list[dict]:
    """Exactly what ``seed_default_sources`` hands the seeder, captured from the real
    function rather than rebuilt from the same file list. Rebuilding it is how the
    first measurement of this went wrong: a plausible reconstruction merged the
    GENERATED legal catalogue where the shipped path loads only the curated one, and
    reported 494 where the truth is 475."""
    import src.ingest.seed_sources as ss

    captured: list[dict] = []
    real = ss.seed_sources
    ss.seed_sources = lambda _s, sources: captured.extend(sources) or {  # type: ignore[assignment]
        "created": 0, "skipped": 0, "total": 0,
        "skipped_existing": 0, "shadowed": 0, "shadowed_examples": [],
    }
    try:
        ss.seed_default_sources(session=None)  # type: ignore[arg-type]
    finally:
        ss.seed_sources = real  # type: ignore[assignment]
    assert captured, "seed_default_sources handed the seeder nothing"
    return captured


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


def test_the_boot_path_does_not_grow_new_unreachable_entries(boot_catalog):
    """The per-file budget cannot see a CROSS-catalogue collision, and 248 of them
    already exist -- including the whole political-lean catalogue. This pins what an
    install actually loses, which is the number the seeder reports."""
    collisions = catalog_domain_collisions(boot_catalog)
    shadowed = sum(len(v) for v in collisions.values())
    assert len(collisions) == _BOOT_COLLIDING_DOMAINS_BUDGET, (
        f"{len(collisions)} domains carry more than one entry across the catalogues "
        f"seed_default_sources loads (budget {_BOOT_COLLIDING_DOMAINS_BUDGET})."
    )
    assert shadowed == _BOOT_SHADOWED_ENTRIES_BUDGET, (
        f"{shadowed} entries can never be registered on a real boot "
        f"(budget {_BOOT_SHADOWED_ENTRIES_BUDGET})."
    )
    # The per-file figure is a strict subset of it, or one of the two is measuring
    # something other than what it says.
    assert shadowed > _SHADOWED_ENTRIES_BUDGET


def test_the_political_lean_vocabulary_is_the_half_with_a_live_consumer(boot_catalog):
    """`lean-*` is real vocabulary (src/catalog/taxonomy.py), and for these outlets it
    never reaches Source.tags at all. Asserted because it is the part of the loss that
    a reader would otherwise have to take on trust from a docstring."""
    winner: dict[str, dict] = {}
    for entry in boot_catalog:
        winner.setdefault(entry["domain"], entry)
    lost = 0
    for dom, shadowed_entries in catalog_domain_collisions(boot_catalog).items():
        kept = {t for t in (winner[dom].get("tags") or []) if t.startswith("lean-")}
        for e in shadowed_entries:
            if {t for t in (e.get("tags") or []) if t.startswith("lean-")} - kept:
                lost += 1
    assert lost == _LEAN_TAGS_LOST_BUDGET, (
        f"{lost} shadowed entries carry a lean-* tag the surviving sibling lacks "
        f"(recorded {_LEAN_TAGS_LOST_BUDGET})."
    )
    assert lost > 0


def test_the_shadowed_entries_include_real_language_losses(catalog):
    """The reason this is not resolved by deletion, asserted rather than left in prose.

    Counts only pairs where BOTH sides declare a language and the languages DIFFER.
    The looser reading -- treating a missing ``language`` as a value -- gives 108, but
    33 of those are absent-vs-present artifacts on shared-domain journal families
    (Wiley titles, arXiv sections) where nothing bilingual is lost. Filling one of
    those missing fields in is a pure metadata improvement, and it must not be able to
    move a guard about collisions: under the looser count it would have dropped the
    number to 75 and reddened a threshold of 100, which is a guard firing on somebody
    doing the right thing somewhere else.
    """
    collisions = catalog_domain_collisions(catalog)
    winner: dict[str, dict] = {}
    for entry in catalog:
        winner.setdefault(entry["domain"], entry)
    both_declared_and_differ = [
        e
        for dom, lost in collisions.items()
        for e in lost
        if e.get("language")
        and winner[dom].get("language")
        and e["language"] != winner[dom]["language"]
    ]
    assert len(both_declared_and_differ) == _LANGUAGE_LOSSES, (
        f"{len(both_declared_and_differ)} shadowed entries declare a language their "
        f"surviving sibling does not (recorded {_LANGUAGE_LOSSES}). Re-measure and "
        "update deliberately -- this number is the argument against deletion."
    )
    # The specific case the ruling is about, named so a future reader can check it.
    assert any(e.get("name") == "BBC Arabic" for e in collisions.get("bbc.com", []))
    # ... and it is not one stray entry: every bbc.com loser is a non-English service.
    bbc_losers = collisions.get("bbc.com", [])
    assert len(bbc_losers) == 30
    assert all((e.get("language") or "en") != "en" for e in bbc_losers)


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
    assert result["skipped_existing"] == 0
    # And every non-shadowed entry did land. Counted in the DATABASE, not from the
    # function's own counters: `created + skipped_existing + shadowed == total` is an
    # identity of the loop that produces them, so asserting it proves nothing about
    # what was actually written.
    assert session.query(Source).count() == len(catalog) - expected
    assert result["created"] == session.query(Source).count()


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param({"name": "No domain key"}, id="absent"),
        pytest.param({"name": "Null", "domain": None}, id="none"),
        pytest.param({"name": "Empty", "domain": ""}, id="empty"),
    ],
)
def test_the_two_implementations_agree_on_a_malformed_entry(entry, session):
    """The real catalogue is entirely well-formed, which is exactly why the agreement
    test above cannot see this: the fixture matches production in every dimension
    except the one where the two rules used to differ. The report function skipped a
    falsy domain; the seeder read `s["domain"]` (raising on an absent key) and counted
    a second empty one as SHADOWED, then built `Source(domain=None)` against a NOT NULL
    column -- an IntegrityError that would take the whole batch."""
    pair = [dict(entry), dict(entry)]
    assert catalog_domain_collisions(pair) == {}
    result = seed_sources(session, pair)
    assert result["shadowed"] == 0
    assert result["created"] == 0
    assert result["skipped_malformed"] == 2
    assert result["created"] + result["skipped"] == result["total"]
    assert session.query(Source).count() == 0
