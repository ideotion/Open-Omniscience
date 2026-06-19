"""EIA (U.S. Energy Information Administration) — maintainer request 2026-06-18: EIA must be
in the source layers and its energy data ingested by default. This pins the two additions:

  (1) EIA is in the raw-data official-statistics agency directory (so it is catalogued
      alongside BLS/Census etc.; a stanced source, stated as a caveat, no verdict — #50);
  (2) the no-key EIA energy FEED expansion (petroleum products redistributed by FRED as
      key-free CSV) is present in the commodity feed catalog, which the markets pass
      auto-imports — so the data is ingested by default with no API key.

The EIA news RSS source (eia.gov/feed, enabled) and the original WTI/Brent/Henry Hub feeds
are covered by configs/sources.yml and the pre-existing energy feeds respectively.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from src.markets.feed_catalog import load_feeds
from src.stats.agencies import get_agency, list_agencies

# The no-key EIA petroleum-product series added in the expansion.
_NEW_ENERGY_KEYS = ("gasoline_regular", "diesel", "heating_oil", "propane", "jet_fuel")


def test_eia_is_in_the_official_statistics_directory():
    """EIA is catalogued in the raw-data agency directory as a US national producer."""
    eia = get_agency("us-eia")
    assert eia is not None, "EIA must be in the official-statistics agency directory"
    assert eia.country == "US" and eia.scope == "national"
    assert eia.acronym == "EIA"
    # An official producer is a stanced source, stated as a caveat — never a per-source
    # "controversial" verdict (ruling #50) and never a credibility score.
    d = eia.to_dict()
    assert "controversial" not in d
    assert not any("score" in k for k in d), "no composite score on an agency entry"
    assert eia in list_agencies()


def test_eia_energy_feeds_are_present_no_key_and_default_ingested():
    """The expanded EIA energy products are in the feed catalog as key-free FRED CSV — the
    markets pass imports the catalog automatically, so they ingest by default (no API key)."""
    feeds = {f.key: f for f in load_feeds()}
    for key in _NEW_ENERGY_KEYS:
        assert key in feeds, f"missing EIA energy feed {key!r}"
        f = feeds[key]
        assert f.category == "energy"
        assert f.market == "EIA/FRED", f"{key} must be labelled EIA/FRED provenance"
        # key-free CSV download (no api.eia.gov key); a wrong id fails loudly, never fabricates
        assert "fred.stlouisfed.org" in f.url and "id=" in f.url
        assert "api.eia.gov" not in f.url and "api_key" not in f.url
    # the original energy series are untouched
    assert {"wti_crude", "brent_crude", "natural_gas"} <= set(feeds)
