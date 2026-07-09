"""A6 riders: poll-cache serve isolation + per-level degraded-graph wording (#591 nits).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from src.analytics import poll_cache
from src.api.insights import _graph_degraded


def test_poll_cache_serve_is_isolated_from_a_mutating_caller():
    """A served alert payload is a DEEP COPY — a caller that mutates a NESTED object in one
    serve must NOT corrupt the cached payload that later serves reuse (the shallow-merge
    ``{**payload, …}`` only copied the top level)."""
    payload = {"tiers": {"urgent": [{"place": "X", "n": 2}]}, "convergences": [{"id": 1}]}
    original = {"tiers": {"urgent": [{"place": "X", "n": 2}]}, "convergences": [{"id": 1}]}

    a = poll_cache._decorate(payload, built_at=1000.0, cached=True, now=1000.0)
    # Mutate nested structures in the first served result.
    a["tiers"]["urgent"].append({"place": "Y", "n": 9})
    a["tiers"]["urgent"][0]["n"] = 999
    a["convergences"].clear()

    # The source payload is untouched, and a subsequent serve reflects the ORIGINAL data.
    assert payload == original, "a mutating caller corrupted the cached payload"
    b = poll_cache._decorate(payload, built_at=1000.0, cached=True, now=1000.0)
    assert b["tiers"]["urgent"] == [{"place": "X", "n": 2}]
    assert b["convergences"] == [{"id": 1}]
    # The disclosure is still attached (no score).
    assert b["cached"] is True and "as_of" in b and "cache_note" in b
    assert not any("score" in k for k in b)


def test_degraded_graph_mirrors_the_real_per_level_method():
    """A family/supergroup timeout must not be handed the keyword co-occurrence wording."""

    class _Exc(Exception):
        pass

    kw = _graph_degraded(_Exc(), level="keyword", term="trump")
    assert kw["method"].startswith("PMI/co-occurrence")
    assert "Association is not causation" in kw["caveat"]
    assert "narrow the term" in kw["caveat"].lower()  # the actionable message still rides

    fam = _graph_degraded(_Exc(), level="family")
    assert fam["method"] == "shared-article overlap between keyword FAMILIES (top members each)"
    assert fam["caveat"].startswith("Families group surface forms")
    assert "PMI" not in fam["method"]

    sg = _graph_degraded(_Exc(), level="supergroup")
    assert sg["method"].startswith("shared-article overlap between SUPER-GROUPS")
    assert "Super-groups are the user's own curation" in sg["caveat"]

    art = _graph_degraded(_Exc(), level="article", n_articles=5)
    assert art["level"] == "article" and art["n_articles"] == 5
    assert "concept map" in art["caveat"].lower()

    for out in (kw, fam, sg, art):
        assert out["nodes"] == [] and out["edges"] == [] and out["degraded"] is True
