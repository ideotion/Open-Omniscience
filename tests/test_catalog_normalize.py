"""
Tests for catalog normalisation + Wikidata query building/parsing.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

All pure / network-free: the WDQS response is a fixture, so parsing, domain
reduction, social-host exclusion and dedup are pinned without any live calls.
"""

from __future__ import annotations

from src.catalog.normalize import (
    dedup_entries,
    is_social,
    registrable_domain,
    to_entry,
)
from src.catalog.wikidata import build_query, parse_results


def test_registrable_domain_variants():
    assert registrable_domain("https://www.example.com/path?q=1") == "example.com"
    assert registrable_domain("http://news.example.co.uk:8080/") == "news.example.co.uk"
    assert registrable_domain("example.org") == "example.org"
    assert registrable_domain("") is None
    assert registrable_domain(None) is None


def test_is_social_matches_subdomains():
    assert is_social("twitter.com")
    assert is_social("m.facebook.com")
    assert is_social("x.com")
    assert not is_social("example.com")
    assert not is_social(None)


def test_to_entry_drops_social_and_empty():
    assert to_entry(name="X", url="https://x.com/feed") is None      # social
    assert to_entry(name="", url="https://example.com") is None       # no name
    assert to_entry(name="Paper", url="not a url at all") is None or \
        to_entry(name="Paper", url="not a url at all")["domain"]      # garbage host tolerated/None


def test_to_entry_shape_and_tags():
    e = to_entry(name="Le Example", url="https://www.le-example.fr/",
                 country="FR", language="FR", source_type="news", tags=["world"])
    assert e["domain"] == "le-example.fr"
    assert e["country"] == "fr"       # lowercased 2-letter
    assert e["language"] == "fr"
    assert "news" in e["tags"] and "world" in e["tags"]


def test_dedup_within_batch_and_against_existing():
    entries = [
        {"domain": "a.test"}, {"domain": "a.test"},   # in-batch dup
        {"domain": "b.test"}, {"domain": "c.test"},
    ]
    res = dedup_entries(entries, existing_domains={"c.test"})
    kept = {e["domain"] for e in res["kept"]}
    assert kept == {"a.test", "b.test"}
    assert res["skipped_existing"] == 1
    assert res["skipped_dupes"] == 1


def test_build_query_contains_country_and_types():
    q = build_query("fr", ["Q11032", "Q192283"], label_lang="fr")
    assert '"FR"' in q                     # ISO code uppercased
    assert "wd:Q11032" in q and "wd:Q192283" in q
    assert "P856" in q                     # requires an official website
    assert 'wikibase:language "fr,en"' in q


def test_parse_results_from_fixture():
    payload = {"results": {"bindings": [
        {"itemLabel": {"value": "Example Times"},
         "website": {"value": "https://www.exampletimes.fr/"},
         "lang": {"value": "fr"}},
        {"itemLabel": {"value": "Social Feed"},          # social -> dropped
         "website": {"value": "https://twitter.com/x"}},
        {"itemLabel": {"value": "No Site"}},             # no website -> dropped
    ]}}
    entries = parse_results(payload, country_code="fr", source_type="news")
    assert len(entries) == 1
    e = entries[0]
    assert e["domain"] == "exampletimes.fr"
    assert e["country"] == "fr" and e["source_type"] == "news"
