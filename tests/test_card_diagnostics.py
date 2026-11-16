"""Home-card click diagnostics (maintainer field report 2026-06-22): records what
clicking each Lead loads — its EXACT corpus (hard-linked) or a fuzzy text search that
LOSES it (search-fallback mismatch, the source-laundering bug). Pure classification,
exercised with synthetic cards + a stubbed FTS so it needs no corpus.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from src.briefing import card_diagnostics as cd


def test_card_seed_query_replicates_the_frontend():
    # quoted term in the title wins
    assert cd.card_seed_query({"title": 'Rising: “climate finance” this week'}) == "climate finance"
    # else the card key
    assert cd.card_seed_query({"title": "Source laundering", "key": "enable-javascript.com"}) == "enable-javascript.com"
    # else the title with quotes stripped
    assert cd.card_seed_query({"title": "Reading diet"}) == "Reading diet"


def _run(monkeypatch, cards, fts):
    monkeypatch.setattr(
        cd, "card_click_diagnostics", cd.card_click_diagnostics
    )  # keep the real fn

    import src.briefing.service as service
    import src.database.fts as fts_mod

    # S2.3: the diagnostic READS the Home cache and never recomputes — forcing a
    # refresh made this read-only report REWRITE the live feed. So the seam the
    # fixture stubs is the cache read, not get_briefing.
    monkeypatch.setattr(
        service, "_read_cache",
        lambda: {"generated_at": "2026-01-01T00:00:00+00:00", "cards": cards},
    )
    # **k so the double tracks the real signature: search_ids grew an
    # `exclude_quarantined` keyword (the diagnostic passes it, so that clicking a card
    # and this count measure the SAME set). A positional-only double silently
    # TypeErrors on the next such parameter instead of exercising it.
    monkeypatch.setattr(
        fts_mod, "search_ids", lambda session, q, **k: list(range(fts.get(q, 0)))
    )
    return cd.card_click_diagnostics(session=None)


def test_hard_linked_card_opens_its_exact_set(monkeypatch):
    cards = [{"type": "convergence", "title": "Paris", "bucket": "investigate",
              "id": "c1", "n": 5, "article_ids": [1, 2, 3, 4, 5], "key": ""}]
    log = _run(monkeypatch, cards, {})
    rec = log["cards"][0]
    assert rec["hard_linked"] is True and rec["mismatch"] is False
    assert rec["click"] == {"mode": "exact", "opens": "openAnalysisForIds", "loads_n": 5}
    assert log["summary"]["hard_linked"] == 1 and log["summary"]["mismatched"] == 0


def test_source_laundering_search_fallback_is_flagged_a_mismatch(monkeypatch):
    # the maintainer's case: card about 314 articles, but clicking searches the origin
    # domain and loads 27000 -> the exact corpus is LOST.
    cards = [{"type": "source_laundering", "title": "Source laundering", "bucket": "overtold",
              "id": "c2", "n": 314, "article_ids": [], "key": "enable-javascript.com"}]
    log = _run(monkeypatch, cards, {"enable-javascript.com": 27000})
    rec = log["cards"][0]
    assert rec["hard_linked"] is False
    assert rec["click"]["mode"] == "search" and rec["click"]["loads_n"] == 27000
    assert rec["mismatch"] is True
    assert "LOST" in rec["verdict"]
    assert log["summary"]["search_fallback"] == 1 and log["summary"]["mismatched"] == 1
    assert log["by_type"]["source_laundering"]["mismatched"] == 1


def test_search_fallback_that_roughly_matches_is_not_a_mismatch(monkeypatch):
    cards = [{"type": "rising_topic", "title": 'Rising: “inflation”', "bucket": "watch",
              "id": "c3", "n": 40, "article_ids": [], "key": "inflation"}]
    log = _run(monkeypatch, cards, {"inflation": 42})
    rec = log["cards"][0]
    assert rec["hard_linked"] is False and rec["mismatch"] is False  # 42 ~ 40
    assert rec["seed_query"] == "inflation"
    assert log["summary"]["mismatched"] == 0


def test_zero_result_search_fallback_is_a_mismatch(monkeypatch):
    cards = [{"type": "x", "title": "Topic", "bucket": "watch", "id": "c4", "n": 12,
              "article_ids": [], "key": "no-such-term"}]
    log = _run(monkeypatch, cards, {"no-such-term": 0})
    assert log["cards"][0]["mismatch"] is True  # loads 0 -> corpus lost


def test_an_absent_cache_says_so_instead_of_reporting_zero_cards(monkeypatch):
    """"0 cards" from an absent cache and "0 cards" from a Home that genuinely has
    none are opposite facts. The summary alone cannot tell them apart, so the basis
    must."""
    import src.briefing.service as service

    monkeypatch.setattr(service, "_read_cache", lambda: None)
    log = cd.card_click_diagnostics(session=None)
    assert log["summary"]["total"] == 0
    assert log["cache_present"] is False
    assert "no Home cache" in log["basis"]


def test_a_present_cache_names_when_it_was_generated(monkeypatch):
    """The twin: a real cache must report as one, or the honest-absence branch would
    swallow every genuine read."""
    import src.briefing.service as service

    monkeypatch.setattr(
        service, "_read_cache",
        lambda: {"generated_at": "2026-01-02T03:04:05+00:00", "cards": []},
    )
    log = cd.card_click_diagnostics(session=None)
    assert log["cache_present"] is True
    assert "2026-01-02T03:04:05+00:00" in log["basis"]


def test_the_source_candidates_card_opens_the_candidates_not_a_search(monkeypatch):
    """Field test 2026-11-14 row 64: the card counts ~300 CANDIDATES, and the text search of its key loaded 0 articles.
    Its button now opens Settings -> Advanced -> Sources, so it is a view, never a search-fallback mismatch."""
    from pathlib import Path

    cards = [{"type": "recipe_source_candidates", "title": "300 source candidates await your review",
              "bucket": "context", "id": "c9", "n": 300, "key": "source-candidates"}]
    log = _run(monkeypatch, cards, {"source-candidates": 0})
    rec = log["cards"][0]
    assert rec["click"]["mode"] == "view" and rec["mismatch"] is False
    assert log["summary"]["mismatched"] == 0 and log["summary"]["view"] == 1
    js = Path("src/static/app-home.js").read_text(encoding="utf-8")
    assert 'c.type !== "recipe_source_candidates"' in js and "showTab('sources')" in js
    # Both renderers take the one helper: the Leads carousel painted its own "Open corpus" text search for this card
    # after the flip card was fixed, so a single grep for the flip card's string passed with the bug still there.
    assert js.count("cardOpensElsewhere(c, ") == 3, "the definition, the flip card and the carousel must both ask cardOpensElsewhere"
    carousel = js[js.index("function _carPaint()"):]
    carousel = carousel[: carousel.index("\n    }\n")]
    assert "cardOpensElsewhere(c, " in carousel
