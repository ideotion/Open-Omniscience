"""A source already in the database used to stop learning.

`seed_sources` skipped a domain it already held and never looked at the row again, so a
source registered before the catalogue knew its country -- or before the title-suffix and
ccTLD fallbacks existed -- kept an empty field forever, however many times the catalogue
was re-seeded. `tests/test_seed_sources.py::test_seed_is_idempotent` pinned exactly that
create-only behaviour, so it read as settled rather than as a gap.

The metadata is descriptive (filtering and provenance, never a score), and an absent
country is precisely why a source lands in "unlocated" on the coverage map.

THE SAFETY ARGUMENT IS THE NULL-ONLY RULE, and it is what these tests are mostly about: a
field is written only when the local value is EMPTY. A non-empty local value is left alone
whatever put it there, because the operator may have set it by hand and a re-seed silently
reverting that would be a data-loss bug wearing a maintenance task's clothes.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Source
from src.ingest.seed_sources import reconcile_source_metadata, seed_sources


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _catalog():
    return [
        {"name": "Le Monde", "domain": "lemonde.fr", "tags": ["news", "fr"],
         "country": "FR", "language": "fr", "_provenance": "worldnews"},
    ]


def test_an_existing_row_with_empty_fields_learns_from_the_catalogue():
    s = _session()
    s.add(Source(name="Le Monde", domain="lemonde.fr"))
    s.commit()

    out = reconcile_source_metadata(s, _catalog())
    assert out["checked"] == 1
    assert out["country_filled"] == 1 and out["language_filled"] == 1 and out["tags_filled"] == 1

    row = s.query(Source).filter_by(domain="lemonde.fr").one()
    assert row.country == "fr"
    assert row.language == "fr"
    assert "news" in (row.tags or "")


def test_a_field_that_already_has_a_value_is_never_overwritten():
    """The operator's value wins over the catalogue's, always. This is the rule that
    makes a re-seed safe to run on a live install."""
    s = _session()
    s.add(Source(name="Le Monde", domain="lemonde.fr", country="be", language="nl", tags="mine"))
    s.commit()

    out = reconcile_source_metadata(s, _catalog())
    assert out == {"checked": 1, "country_filled": 0, "language_filled": 0, "tags_filled": 0}

    row = s.query(Source).filter_by(domain="lemonde.fr").one()
    assert (row.country, row.language, row.tags) == ("be", "nl", "mine"), (
        "a re-seed must never revert what an operator set"
    )


def test_it_fills_only_the_empty_fields_of_a_partially_filled_row():
    s = _session()
    s.add(Source(name="Le Monde", domain="lemonde.fr", country="be"))
    s.commit()

    out = reconcile_source_metadata(s, _catalog())
    assert out["country_filled"] == 0, "the set country stays"
    assert out["language_filled"] == 1, "the empty language is filled"

    row = s.query(Source).filter_by(domain="lemonde.fr").one()
    assert row.country == "be" and row.language == "fr"


def test_the_provenance_tag_is_not_copied_onto_a_row_it_did_not_create():
    """`via:<origin>` records where a row CAME FROM. Reconciling an existing row did not
    create it, so copying that marker would assert an origin this row may not have -- a
    hand-registered source coming out claiming it arrived via a catalogue."""
    s = _session()
    s.add(Source(name="Le Monde", domain="lemonde.fr"))
    s.commit()
    reconcile_source_metadata(s, _catalog())

    tags = s.query(Source).filter_by(domain="lemonde.fr").one().tags or ""
    assert "news" in tags, "the descriptive tags ARE facts about the source; fill them"
    assert "via:" not in tags, "the provenance marker is a fact about the ROW; do not"


def test_it_is_idempotent_a_second_run_fills_nothing():
    s = _session()
    s.add(Source(name="Le Monde", domain="lemonde.fr"))
    s.commit()
    first = reconcile_source_metadata(s, _catalog())
    second = reconcile_source_metadata(s, _catalog())
    assert first["country_filled"] == 1
    assert second == {"checked": 1, "country_filled": 0, "language_filled": 0, "tags_filled": 0}


def test_the_fallback_ladder_is_the_create_path_s_own_not_a_second_copy():
    """No explicit country or language in the entry: the value must come from the SAME
    title-suffix / ccTLD ladder `_to_source_kwargs` uses on creation. A divergent second
    implementation here is how two rows for the same domain end up disagreeing."""
    s = _session()
    s.add(Source(name="Der Spiegel", domain="spiegel.de"))
    s.commit()
    reconcile_source_metadata(s, [{"name": "Der Spiegel", "domain": "spiegel.de"}])

    row = s.query(Source).filter_by(domain="spiegel.de").one()
    assert row.country == "de", "the ccTLD fallback must apply here exactly as on create"


def test_a_domain_the_database_does_not_hold_is_not_created_here():
    """Reconciliation fills; it does not register. Creating is `seed_sources`' job, and a
    function that quietly did both would make the create counts wrong."""
    s = _session()
    out = reconcile_source_metadata(s, _catalog())
    assert out["checked"] == 0
    assert s.query(Source).count() == 0


def test_seeding_reconciles_so_every_caller_gets_it():
    """Wired inside `seed_sources`, so the endpoint and both boot-time seeds inherit it
    without a second call site anyone can forget."""
    s = _session()
    s.add(Source(name="Le Monde", domain="lemonde.fr"))
    s.commit()

    out = seed_sources(s, _catalog())
    assert out["created"] == 0 and out["skipped_existing"] == 1
    assert out["reconciled"]["country_filled"] == 1

    row = s.query(Source).filter_by(domain="lemonde.fr").one()
    assert row.country == "fr"


def test_a_malformed_or_duplicate_catalogue_entry_cannot_reach_a_row():
    """First-entry-wins, the same rule `seed_sources` uses for shadowing -- so the two can
    never disagree about which sibling a domain's metadata comes from."""
    s = _session()
    s.add(Source(name="Le Monde", domain="lemonde.fr"))
    s.commit()
    reconcile_source_metadata(s, [
        {},                                              # malformed
        {"name": "No Domain"},                           # no domain
        {"name": "Le Monde", "domain": "lemonde.fr", "country": "FR"},
        {"name": "Impostor", "domain": "lemonde.fr", "country": "JP"},   # shadowed sibling
    ])
    assert s.query(Source).filter_by(domain="lemonde.fr").one().country == "fr"
