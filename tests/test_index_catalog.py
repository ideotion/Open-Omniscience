"""The world-index catalog covers all continents with category facets (continent + tags).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from src.markets.feed_catalog import load_index_feeds


def test_index_catalog_covers_all_continents_with_facets():
    feeds = load_index_feeds()
    assert len(feeds) >= 20, "the catalog should span many world indices"
    continents = {f.continent for f in feeds}
    assert {"Africa", "Asia", "Europe", "North America", "South America", "Oceania"} <= continents
    assert all(f.continent for f in feeds), "every index must carry a continent (category facet)"
    assert all(f.tags for f in feeds), "every index must carry at least one tag"
    d = feeds[0].to_dict()
    assert "continent" in d and "tags" in d, "the API must expose continent + tags to the board"


def test_index_catalog_marks_named_vs_oecd_units():
    by_key = {f.key: f for f in load_index_feeds()}
    assert by_key["idx_sp500"].unit == "pts"  # a named index level (points)
    assert by_key["idx_oecd_zaf"].unit == "idx"  # a normalised OECD share-price index (2015=100)
    assert by_key["idx_oecd_zaf"].continent == "Africa"
