"""
Tests for the in-app Wikidata source_type enrichment (guarded, injected getter).

The reconciliation/domain-gate logic is covered in tests/test_wikidata_enrich.py;
here we cover the DB-writing apply + the airplane up-front refusal. In-memory
SQLite -> runs in CI.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.wikidata_apply import apply_source_types
from src.database.models import Base, Source
from src.ingest import activate_kill_switch, clear_kill_switch


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return json.loads(json.dumps(self._payload))


def _getter_for(qid, p31, websites):
    search = {"search": [{"id": qid}]}
    ent = {
        "entities": {
            qid: {
                "claims": {
                    "P31": [{"mainsnak": {"datavalue": {"value": {"id": q}}}} for q in p31],
                    "P856": [{"mainsnak": {"datavalue": {"value": w}}} for w in websites],
                }
            }
        }
    }

    def getter(url: str):
        return _Resp(search if "wbsearchentities" in url else ent)

    return getter


def test_sets_source_type_when_domain_matches(db):
    db.add(Source(name="Reuters", domain="reuters.com", source_type="news"))
    db.commit()
    getter = _getter_for("Q192283x", ["Q192283"], ["https://reuters.com/"])
    res = apply_source_types(db, get=getter)
    assert res["sources_typed"] == 1
    assert db.query(Source).one().source_type == "wire-agency"


def test_wrong_entity_domain_leaves_source_untouched(db):
    db.add(Source(name="Reuters", domain="reuters.com", source_type="news"))
    db.commit()
    # the search lands on an entity whose website is a different domain -> no change
    getter = _getter_for("Qwrong", ["Q11032"], ["https://some-other.com/"])
    res = apply_source_types(db, get=getter)
    assert res["sources_typed"] == 0
    assert db.query(Source).one().source_type == "news"


def test_curated_non_default_type_is_never_touched(db):
    db.add(Source(name="Nature", domain="nature.com", source_type="scientific"))
    db.commit()
    getter = _getter_for("Qx", ["Q5633421"], ["https://nature.com/"])
    res = apply_source_types(db, get=getter)
    assert res["scanned"] == 0  # filter excludes non-default types
    assert db.query(Source).one().source_type == "scientific"


def test_refuses_up_front_under_airplane_mode(db):
    db.add(Source(name="Reuters", domain="reuters.com", source_type="news"))
    db.commit()
    called = {"n": 0}

    def getter(url):  # must never be reached
        called["n"] += 1
        return _Resp({})

    activate_kill_switch()
    try:
        with pytest.raises(RuntimeError, match="airplane"):
            apply_source_types(db, get=getter)
    finally:
        clear_kill_switch()
    assert called["n"] == 0  # no socket attempted offline
