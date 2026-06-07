"""
Tests for the Wikipedia language-edition catalogue + the /languages endpoint.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.wiki.languages import _TIER_RANK, all_languages, get_language, is_known


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


def test_languages_endpoint():
    from src.api.main import app

    with TestClient(app) as client:
        data = client.get("/api/wiki/languages").json()
    langs = data["languages"]
    assert any(x["code"] == "en" for x in langs)
    first = langs[0]
    assert {"code", "name", "autonym", "tier"} <= set(first)
