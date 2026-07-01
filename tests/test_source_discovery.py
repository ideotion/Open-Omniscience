"""
Tests for in-app Wikidata source DISCOVERY (injected run_query, no network).

In-memory SQLite -> runs in CI. The pure query/parse/dedup is covered in the
catalog-build tests; here we cover the DB insert (disabled + provenance), dedup
against existing sources, and the airplane up-front refusal.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.discover import discover_sources
from src.database.models import Base, Source
from src.ingest import activate_kill_switch, clear_kill_switch


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _payload(name, website):
    return {"results": {"bindings": [
        {"itemLabel": {"value": name}, "website": {"value": website}},
    ]}}


def _run_query_returning(name, website):
    def run_query(cc, type_qids):  # same hit for every (country x spec)
        return _payload(name, website)

    return run_query


def test_discovers_and_inserts_disabled_source_with_provenance(db):
    rq = _run_query_returning("Kenya Times", "https://kenyatimes.co.ke/")
    res = discover_sources(db, ["ke"], run_query=rq)
    assert res["added"] == 1
    src = db.query(Source).filter_by(domain="kenyatimes.co.ke").one()
    assert src.enabled is False  # review-before-enable
    assert "via:wikidata-discovery" in (src.tags or "")
    assert src.country == "ke"  # ccTLD backfill


def test_deduplicates_against_existing_sources(db):
    db.add(Source(name="Kenya Times", domain="kenyatimes.co.ke", enabled=True))
    db.commit()
    rq = _run_query_returning("Kenya Times", "https://kenyatimes.co.ke/")
    res = discover_sources(db, ["ke"], run_query=rq)
    assert res["added"] == 0
    # the pre-existing (enabled) source is untouched
    assert db.query(Source).filter_by(domain="kenyatimes.co.ke").one().enabled is True


def test_refuses_up_front_under_airplane_mode(db):
    called = {"n": 0}

    def rq(cc, type_qids):
        called["n"] += 1
        return _payload("X", "https://x.ke/")

    activate_kill_switch()
    try:
        with pytest.raises(RuntimeError, match="airplane"):
            discover_sources(db, ["ke"], run_query=rq)
    finally:
        clear_kill_switch()
    assert called["n"] == 0  # no query attempted offline
