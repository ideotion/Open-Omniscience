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
from src.safety.fetcher import RedirectRefused


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


def test_a_source_whose_lookup_wikidata_redirected_off_its_host_is_counted_and_named(db):
    """A refused redirect used to vanish into ``except Exception: continue``: the pass said "0 typed" exactly as it does when Wikidata
    has no match. It is counted now, with the class name (never a URL) beside the tally, and the batch carries on past it."""
    db.add(Source(name="Reuters", domain="reuters.com", source_type="news"))
    db.add(Source(name="Redirected", domain="redirected.example", source_type="news"))
    db.commit()
    good = _getter_for("Q192283x", ["Q192283"], ["https://reuters.com/"])

    def getter(url: str):
        if "Redirected" in url:
            raise RedirectRefused("request refused: the host is not one this client talks to")
        return good(url)

    res = apply_source_types(db, get=getter)
    assert res == {"scanned": 2, "sources_typed": 1, "sources_refused": 1, "refusal": "RedirectRefused"}
    assert "http" not in str(res) and "talks" not in str(res), "the result names the class and carries no address or message"


def test_a_pass_with_no_refusal_carries_a_zero_and_no_refusal_name(db):
    db.add(Source(name="Reuters", domain="reuters.com", source_type="news"))
    db.commit()
    res = apply_source_types(db, get=_getter_for("Q192283x", ["Q192283"], ["https://reuters.com/"]))
    assert res["sources_refused"] == 0 and "refusal" not in res


def test_any_other_failure_of_a_source_is_still_skipped_and_is_not_called_a_refusal(db):
    db.add(Source(name="Reuters", domain="reuters.com", source_type="news"))
    db.commit()

    def getter(url: str):
        raise RuntimeError("Wikidata answered with nonsense")

    res = apply_source_types(db, get=getter)
    assert res == {"scanned": 1, "sources_typed": 0, "sources_refused": 0}
