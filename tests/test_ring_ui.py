"""The /api/insights/rings endpoint that feeds the super-ring picker (Step 4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from src.api.insights import list_rings


def test_list_rings_returns_curated_rings():
    r = list_rings()
    assert r["count"] >= 1
    ids = {x["id"] for x in r["rings"]}
    assert {"election", "government", "inflation"} <= ids  # curated + the Step-3 expansion
    election = next(x for x in r["rings"] if x["id"] == "election")
    assert "en:election" in election["members"]
    assert "en" in election["languages"] and election["size"] >= 2
    # sorted by language breadth then id (a stable, honest order — no score)
    breadth = [len(x["languages"]) for x in r["rings"]]
    assert breadth == sorted(breadth, reverse=True)
