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


def test_oecd_share_price_ids_use_the_fred_two_letter_iso_code():
    """Regression guard for field-test 2026-07-08 Item 1 (the ISO-3->ISO-2 bug).

    FRED's OECD MEI share-price family is ``SPASTT01<CC>M661N`` where <CC> is the
    TWO-letter ISO country code. An earlier catalog used three-letter codes
    (SPASTT01DEUM661N) that do not exist on FRED, so every OECD index 404'd and
    its continent showed empty on the board. Pin the 2-letter convention so a
    regression to 3-letter fails LOUDLY here instead of silently in the field.
    """
    import re

    oecd = [f for f in load_index_feeds() if "oecd" in (f.tags or [])]
    assert oecd, "the catalog should carry OECD share-price indices"
    pat = re.compile(r"^SPASTT01[A-Z]{2}M661N$")
    for f in oecd:
        assert pat.match(f.symbol), (
            f"OECD feed {f.key} has symbol {f.symbol!r}; FRED needs a 2-letter "
            f"ISO code (SPASTT01<CC>M661N), not 3-letter"
        )
        # the id that is fetched must be the pinned symbol (no drift between the two)
        assert f.symbol in (f.url or ""), (
            f"OECD feed {f.key} url {f.url!r} does not carry its symbol {f.symbol!r}"
        )
