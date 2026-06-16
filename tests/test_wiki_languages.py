"""
Tests for the Wikipedia language-edition catalogue + the /languages endpoint.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.wiki.languages import (
    _KNOWN_REGIONS,
    _TIER_RANK,
    UI_LOCALE_CODES,
    all_languages,
    app_languages_ui_first,
    get_language,
    is_known,
    languages_ui_first,
)


def test_catalogue_is_sane():
    langs = all_languages()
    assert len(langs) >= 40
    codes = [x.code for x in langs]
    assert len(codes) == len(set(codes))  # unique edition codes
    for x in langs:
        assert x.code and x.name and x.autonym
        assert x.tier in _TIER_RANK


def test_sorted_largest_tier_first():
    langs = all_languages()
    ranks = [_TIER_RANK[x.tier] for x in langs]
    assert ranks == sorted(ranks)  # non-decreasing tier rank
    assert langs[0].tier == "huge"
    assert get_language("EN") is langs[0] or get_language("en").code == "en"


def test_lookup_helpers():
    assert is_known("fr") and is_known("AR")
    assert not is_known("zz")
    assert get_language("zz") is None
    assert get_language("de").autonym == "Deutsch"


def test_every_edition_has_a_known_region():
    # ``region`` is retained as descriptive metadata only (the picker no longer
    # groups by continent — invariant #1, amended 2026-06-16).
    for lang in all_languages():
        assert lang.region in _KNOWN_REGIONS


def test_flat_ui_first_list_is_complete_and_ordered():
    # Invariant #1 (amended 2026-06-16): the picker is ONE flat list, ordered
    # UI-locales-first then largest-tier-first — no continent grouping.
    flat = languages_ui_first()
    # Same editions as the curated catalogue, each exactly once.
    assert sorted(x.code for x in flat) == sorted(x.code for x in all_languages())
    assert len({x.code for x in flat}) == len(flat)
    # UI-locale editions come first (a single contiguous block at the front).
    ui_flags = [x.code in UI_LOCALE_CODES for x in flat]
    n_ui = sum(ui_flags)
    assert n_ui == len(UI_LOCALE_CODES)
    assert ui_flags[:n_ui] == [True] * n_ui  # all UI locales lead, none trail
    # Within each block (UI / non-UI) editions stay ordered largest tier first.
    ui_ranks = [_TIER_RANK[x.tier] for x in flat[:n_ui]]
    rest_ranks = [_TIER_RANK[x.tier] for x in flat[n_ui:]]
    assert ui_ranks == sorted(ui_ranks)
    assert rest_ranks == sorted(rest_ranks)
    # The very first edition is a UI locale in the largest tier (within-tier the
    # tiebreak is English name, so the exact head is deterministic but unasserted).
    assert flat[0].code in UI_LOCALE_CODES
    assert flat[0].tier == "huge"
    assert "en" in {x.code for x in flat[:n_ui]}


def test_app_scope_is_ui_first_subset():
    app_flat = app_languages_ui_first()
    codes = [x.code for x in app_flat]
    assert "en" in codes and "fr" in codes
    # The app scope is a subset of the full flat list, in the same relative order.
    full_order = [x.code for x in languages_ui_first()]
    assert codes == [c for c in full_order if c in set(codes)]


def test_languages_endpoint():
    from src.api.main import app

    with TestClient(app) as client:
        data = client.get("/api/wiki/languages").json()
        dumps = client.get("/api/wiki/languages?scope=dumps").json()
    langs = data["languages"]
    assert any(x["code"] == "en" for x in langs)
    first = langs[0]
    assert {"code", "name", "autonym", "tier", "region"} <= set(first)
    # Invariant #1 (amended 2026-06-16): the by-continent groups are GONE — the
    # endpoint emits ONE flat list, UI-locales first.
    assert "groups" not in data
    assert first["code"] in UI_LOCALE_CODES  # a UI locale leads the flat list
    # The flat list matches the catalogue ordering exactly.
    assert [x["code"] for x in langs] == [x.code for x in languages_ui_first()]
    # Dumps scope narrows to the app's languages and also carries no groups.
    assert "groups" not in dumps
    assert [x["code"] for x in dumps["languages"]] == [
        x.code for x in app_languages_ui_first()
    ]
