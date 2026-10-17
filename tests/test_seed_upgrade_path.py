"""An install that booted the flip-flopping seeder comes back to a fresh install's state, and what that cannot know is pinned (R152).

``tests/test_seed_flip_flop.py`` pins each rule on its own. This is the upgrade as an operator lives it: the damage below is
MEASURED, copied from a database main's own seeder (the default seed then the legal seed, twice) wrote on 2026-10-17, for
the nine hosts both catalogues list. Booting the current seeder on it must (a) restore the seven erased feeds, (b) report no
operator edit where nobody made one, and (c) land on a fresh install's rows, baselines included. Then the limits, as tests:
an operator's own edit survives the repair, a feed an operator cleared on an undamaged row is never refilled, and the one
state the repair cannot tell from the damage (a feed an operator re-added and cleared again BEFORE upgrading) gets the
catalogue's feed back. Each is red without the rule it names (the repair reverted; the sync fixes reverted).
"""

from __future__ import annotations

import json
import shutil

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Source
from src.ingest.seed_sources import seed_default_sources
from src.law.catalog import seed_legal_sources

_FIELDS = ("domain", "name", "source_type", "rss_url", "country", "language", "region", "catalog_baseline")


def _bl(country, language, name, source_type):
    return json.dumps({"country": country, "language": language, "name": name, "region": None, "rss_url": None,
                       "source_type": source_type}, sort_keys=True)


# (name, source_type, rss_url, country, language, region, baseline) as main left them after two boots.
DAMAGE = {
    "asean.org": ("ASEAN", "news", None, "int", None, None, _bl("int", None, "ASEAN", "law")),
    "au.int": ("African Union", "news", None, "int", None, None, _bl("int", None, "African Union", "law")),
    "congress.gov": ("US Congress (congress.gov)", "news", None, "us", "en", "global",
                     _bl("us", "en", "US Congress (congress.gov)", "law")),
    "epo.org": ("European Patent Office (EPO)", "news", "", "eu", "en", "global",
                _bl("eu", "en", "European Patent Office (EPO)", "ip")),
    "gov.uk": ("UK IPO", "news", None, "gb", "en", "global", _bl("gb", "en", "UK IPO", "ip")),
    "icc-cpi.int": ("International Criminal Court", "case_law", None, "int", None, None,
                    _bl("int", None, "International Criminal Court", "case_law")),
    "icj-cij.org": ("International Court of Justice", "case_law", None, "int", None, None,
                    _bl("int", None, "International Court of Justice", "case_law")),
    "oas.org": ("Organization of American States", "news", None, "int", None, None,
                _bl("int", None, "Organization of American States", "law")),
    "uspto.gov": ("USPTO (US Patent & Trademark Office)", "news", "", "us", "en", "global",
                  _bl("us", "en", "USPTO (US Patent & Trademark Office)", "ip")),
}
ERASED_FEEDS = ("asean.org", "au.int", "congress.gov", "gov.uk", "icc-cpi.int", "icj-cij.org", "oas.org")


def _boot(session):
    """The production order (``src/api/main.py``): the default seed, then the legal seed."""
    default = seed_default_sources(session)
    legal = seed_legal_sources(session)
    return default, legal


def _snapshot(session):
    return {r.id: {f: getattr(r, f) for f in _FIELDS} for r in session.query(Source).order_by(Source.id)}


def _first(session, domain):
    return session.query(Source).filter(Source.domain == domain).order_by(Source.id).first()


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    """A database one boot of the current seeder wrote, and its rows: what a fresh install looks like."""
    path = tmp_path_factory.mktemp("seed-upgrade") / "template.db"
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as session:
        _boot(session)
        rows = _snapshot(session)
    engine.dispose()
    return path, rows


@pytest.fixture()
def installed(template, tmp_path):
    """A copy of the fresh database, opened for one scenario."""
    path = tmp_path / "scenario.db"
    shutil.copy(template[0], path)
    engine = create_engine(f"sqlite:///{path}", future=True)
    session = sessionmaker(bind=engine, future=True)()
    yield session, template[1]
    session.close()
    engine.dispose()


def _damage(session):
    for domain, (name, stype, feed, country, language, region, baseline) in DAMAGE.items():
        row = _first(session, domain)
        row.name, row.source_type, row.rss_url, row.country, row.language, row.region = (
            name, stype, feed, country, language, region)
        row.catalog_baseline = baseline
    session.commit()


def test_the_upgrade_lands_on_a_fresh_installs_rows_and_reports_no_edit_nobody_made(installed):
    session, fresh = installed
    _damage(session)
    assert any(_snapshot(session)[i] != fresh[i] for i in fresh)          # the damage is real before the boots
    first_default, first_legal = _boot(session)
    assert first_default["feed_repair"]["restored"] == 7 and first_default["feed_repair"]["not_restored"] == 0
    assert first_default["corrections"]["kept"] == 0 and first_legal["corrections"]["kept"] == 0
    second_default, second_legal = _boot(session)
    assert second_default["feed_repair"]["restored"] == 0
    assert second_default["corrections"]["kept"] == 0 and second_legal["corrections"]["kept"] == 0
    assert second_default["corrections"]["applied"] == 0 and second_legal["corrections"]["applied"] == 0
    assert _snapshot(session) == fresh                                    # every row, baselines included
    for domain in ERASED_FEEDS:
        assert _first(session, domain).rss_url == fresh[_first(session, domain).id]["rss_url"] not in (None, "")


def test_an_operators_own_edit_survives_the_repair_and_is_the_only_edit_listed(installed):
    """V1 a feed re-added on au.int, V2 a renamed gov.uk, V3 an operator region on asean.org (its feed is still restored)."""
    session, fresh = installed
    _damage(session)
    _first(session, "au.int").rss_url = "https://example.org/my.xml"
    _first(session, "gov.uk").name = "My UK page"
    _first(session, "asean.org").region = "asia"
    session.commit()
    default, _legal = _boot(session)
    assert _first(session, "au.int").rss_url == "https://example.org/my.xml"
    assert _first(session, "gov.uk").name == "My UK page"
    assert _first(session, "asean.org").region == "asia"
    assert _first(session, "asean.org").rss_url == fresh[_first(session, "asean.org").id]["rss_url"]
    fields = {r["domain"]: set(r["fields"]) for r in default["feed_repair"]["restored_rows"]}
    assert set(fields) == set(ERASED_FEEDS) and "rss_url" not in fields["au.int"]   # the operator's feed is not restored over
    assert "region" not in fields["asean.org"]                                      # nor the operator's region
    listed = {(c["domain"], c["field"]) for c in default["corrections"]["conflicts"]}
    assert ("gov.uk", "name") in listed                                    # the real edit is named...
    assert listed <= {("gov.uk", "name"), ("au.int", "rss_url"), ("asean.org", "region")}   # ...beside no false one
    assert default["corrections"]["kept"] == len(listed)


def test_a_feed_an_operator_cleared_on_an_undamaged_row_is_never_refilled(installed):
    session, fresh = installed
    _damage(session)
    row = _first(session, "reuters.com")
    assert row.rss_url                                                    # a single-entry row with a feed
    row.rss_url = None
    session.commit()
    default, _legal = _boot(session)
    assert session.get(Source, row.id).rss_url in (None, "")
    assert default["feed_repair"]["operator_cleared"] >= 1


def test_the_one_state_the_repair_cannot_tell_from_the_damage_gets_the_catalogues_feed_back(installed):
    """KNOWN LIMIT (OPEN_QUEUE, R152 item 9a), by construction rather than a bug: an operator who re-added a feed to one of
    the seven and cleared it again before upgrading leaves the same row as the damage (an empty feed, a baseline naming
    none), so the repair restores the catalogue's feed. Pinned so the day this stops being true is a decision, not a drift."""
    session, fresh = installed
    _damage(session)
    row = _first(session, "au.int")
    row.rss_url = "https://example.org/my.xml"
    session.commit()
    row.rss_url = None                                                    # re-added, then cleared again
    session.commit()
    default, _legal = _boot(session)
    assert "au.int" in {r["domain"] for r in default["feed_repair"]["restored_rows"]}
    assert _first(session, "au.int").rss_url == fresh[row.id]["rss_url"]
