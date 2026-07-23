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


def test_guarded_run_query_carries_http_status_on_a_non_json_response(monkeypatch):
    """S5 item 4 (field-feedback 2026-07-23): a non-JSON WDQS response body (a
    rate-limit page, an error page, a truncated response) used to surface as a
    bare "Expecting value: line 1 column 1 (char 0)" parse exception, giving no
    way to tell a 429 rate-limit from a genuinely broken query. The production
    transport (_guarded_run_query) must now carry the real HTTP status + a short
    body snippet — observability only, generate_catalog's own record-and-skip
    control flow is unchanged."""
    import json

    from src.catalog.discover import _guarded_run_query

    class _FakeResp:
        status_code = 429
        text = "<html>rate limit exceeded, try again later</html>"

        def json(self):
            raise json.JSONDecodeError("Expecting value", self.text, 0)

    class _FakeSession:
        def get(self, url, timeout=None):  # noqa: ARG002
            return _FakeResp()

    monkeypatch.setattr("src.safety.fetcher.guarded_session", lambda **_kw: _FakeSession())

    run_query = _guarded_run_query({"label_lang": "en", "limit": 50})
    with pytest.raises(RuntimeError) as exc_info:
        run_query("gb", ["Q1"])
    msg = str(exc_info.value)
    assert "429" in msg
    assert "rate limit" in msg


def test_generate_catalog_records_the_enriched_error_and_keeps_going():
    """The enriched message flows through generate_catalog's existing
    record-and-skip path unchanged (no retry-policy change)."""
    from src.catalog.build import generate_catalog

    def rq(cc, type_qids):  # noqa: ARG001
        if cc == "gb":
            raise RuntimeError("non-JSON response (HTTP 429): '<html>rate limited</html>'")
        return _payload("Kenya Times", "https://kenyatimes.co.ke/")

    res = generate_catalog(rq, ["gb", "ke"], [{"type_qids": ["Q1"], "source_type": "news"}])
    assert any("gb/news" in e and "429" in e for e in res["stats"]["errors"])
    assert res["stats"]["countries_queried"] == 2  # gb's failure never aborted ke
