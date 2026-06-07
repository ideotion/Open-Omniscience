"""
Tests for the Wikipedia language-edition catalogue + the /languages endpoint.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.wiki.languages import (
    _REGION_RANK,
    _TIER_RANK,
    all_languages,
    get_language,
    is_known,
    languages_by_region,
)


def test_catalogue_is_sane():
    langs = all_languages()
    assert len(langs) >= 40
    codes = [x.code for x in langs]
    assert len(codes) == len(set(codes))          # unique edition codes
    for x in langs:
        assert x.code and x.name and x.autonym
        assert x.tier in _TIER_RANK


def test_sorted_largest_tier_first():
    langs = all_languages()
    ranks = [_TIER_RANK[x.tier] for x in langs]
    assert ranks == sorted(ranks)                 # non-decreasing tier rank
    assert langs[0].tier == "huge"
    assert get_language("EN") is langs[0] or get_language("en").code == "en"


def test_lookup_helpers():
    assert is_known("fr") and is_known("AR")
    assert not is_known("zz")
    assert get_language("zz") is None
    assert get_language("de").autonym == "Deutsch"


def test_every_edition_has_a_known_region():
    for lang in all_languages():
        assert lang.region in _REGION_RANK


def test_grouping_by_continent_is_complete_and_ordered():
    groups = languages_by_region()
    # Every edition appears exactly once across the groups.
    grouped_codes = [lang.code for _region, langs in groups for lang in langs]
    assert sorted(grouped_codes) == sorted(x.code for x in all_languages())
    assert len(grouped_codes) == len(set(grouped_codes))
    # Regions are ordered largest-edition-first (by the curated rank).
    region_ranks = [_REGION_RANK[region] for region, _langs in groups]
    assert region_ranks == sorted(region_ranks)
    # Europe and Asia both carry editions in the curated list.
    region_names = {region for region, _ in groups}
    assert {"Europe", "Asia"} <= region_names
    # Within a region, editions stay ordered largest tier first.
    for _region, langs in groups:
        tier_ranks = [_TIER_RANK[x.tier] for x in langs]
        assert tier_ranks == sorted(tier_ranks)


def test_languages_endpoint():
    from src.api.main import app

    with TestClient(app) as client:
        data = client.get("/api/wiki/languages").json()
    langs = data["languages"]
    assert any(x["code"] == "en" for x in langs)
    first = langs[0]
    assert {"code", "name", "autonym", "tier", "region"} <= set(first)
    # Grouped form is present and covers the same editions.
    groups = data["groups"]
    assert groups and all(g["region"] and g["languages"] for g in groups)
    grouped = [l["code"] for g in groups for l in g["languages"]]
    assert sorted(grouped) == sorted(x["code"] for x in langs)
