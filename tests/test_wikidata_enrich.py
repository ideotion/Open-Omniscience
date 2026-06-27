"""Tests for Wikidata source_type reconciliation (pure layer, no network)."""

import json

from src.catalog.wikidata_enrich import (
    entity_domains,
    entity_p31,
    parse_search_qids,
    reconcile,
    wbentities_url,
    wbsearch_url,
)


def _entity(qid, *, p31, websites):
    return {
        "entities": {
            qid: {
                "claims": {
                    "P31": [
                        {"mainsnak": {"datavalue": {"value": {"id": q}}}} for q in p31
                    ],
                    "P856": [
                        {"mainsnak": {"datavalue": {"value": w}}} for w in websites
                    ],
                }
            }
        }
    }


def test_url_builders():
    assert "wbsearchentities" in wbsearch_url("BBC News")
    assert "search=BBC" in wbsearch_url("BBC News")
    assert "wbgetentities" in wbentities_url(["Q9531", "Q11148"])
    assert "Q9531%7CQ11148" in wbentities_url(["Q9531", "Q11148"])  # pipe-joined


def test_parse_search_qids_in_rank_order():
    payload = {"search": [{"id": "Q1"}, {"id": "Q2"}, {}]}
    assert parse_search_qids(payload) == ["Q1", "Q2"]
    assert parse_search_qids({}) == []


def test_entity_domain_and_p31_extraction():
    ent = _entity("Q9531", p31=["Q15265344"], websites=["https://www.bbc.com/news"])["entities"]["Q9531"]
    assert entity_domains(ent) == {"bbc.com"}
    assert entity_p31(ent) == ["Q15265344"]


def test_reconcile_maps_p31_to_source_type_when_domain_matches():
    payload = _entity("Q192283x", p31=["Q192283"], websites=["https://apnews.com/"])
    row = reconcile(payload, "Q192283x", expected_domain="apnews.com")
    assert row["source_type"] == "wire-agency"
    assert row["ownership"] == "wire-agency"
    assert row["domain"] == "apnews.com"
    assert row["note"] == "wikidata:Q192283x"
    assert row["confidence"] == "high"


def test_reconcile_rejects_when_website_does_not_match():
    # The anti-fabrication gate: a name search that lands on the wrong entity
    # (whose website is some other domain) must yield nothing, never a wrong type.
    payload = _entity("Qwrong", p31=["Q11032"], websites=["https://some-other-site.com/"])
    assert reconcile(payload, "Qwrong", expected_domain="example-news.com") is None


def test_reconcile_rejects_unmapped_type_even_if_domain_matches():
    # A real entity that is not a media type we map → leave the source untouched.
    payload = _entity("Qband", p31=["Q215380"], websites=["https://example.com/"])
    assert reconcile(payload, "Qband", expected_domain="example.com") is None


def test_reconcile_handles_missing_website():
    payload = _entity("Qnoweb", p31=["Q11032"], websites=[])
    assert reconcile(payload, "Qnoweb", expected_domain="example.com") is None


def test_enrich_loop_with_injected_getter_is_network_free():
    from scripts.enrich_sources_wikidata import enrich

    search = {"search": [{"id": "Q9531"}]}
    ent = _entity("Q9531", p31=["Q1616075"], websites=["https://www.bbc.co.uk/"])

    def getter(url: str) -> bytes:
        if "wbsearchentities" in url:
            return json.dumps(search).encode()
        return json.dumps(ent).encode()

    rows = enrich(
        [{"name": "BBC", "domain": "bbc.co.uk"}], getter=getter, sleep=0, log=lambda *_: None
    )
    assert len(rows) == 1
    assert rows[0]["source_type"] == "broadcaster"
    assert rows[0]["domain"] == "bbc.co.uk"
