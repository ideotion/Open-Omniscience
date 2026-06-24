"""The whole-corpus read cache + background warming (perf, field report 2026-06-18).

top / trending / trending-windows / map GROUP BY over the full mention table per
call (2.7-36 s on the field corpus) and one is POLLED from Home. A short TTL cache
makes repeat calls instant; warm_cache pre-computes the common views after each
scrape so even the first open rarely hits a cold query. Honest: computed_at +
cache_ttl_s + a `cached` flag travel in the payload.

Imports fastapi/sqlalchemy -> runs in CI.
"""

from __future__ import annotations

import src.api.insights as ins


def test_cached_helper_memoizes():
    ins._read_cache._cache.clear()
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return {"v": 1}

    key = ins._ckey("probe", a=1, b="x")
    r1 = ins._cached(key, compute)
    r2 = ins._cached(key, compute)
    assert calls["n"] == 1  # second call served from cache, NOT recomputed
    assert r1["cached"] is False and r2["cached"] is True
    assert "computed_at" in r2 and r2["cache_ttl_s"] == ins._CACHE_TTL_S


def test_distinct_params_are_distinct_cache_entries():
    ins._read_cache._cache.clear()
    calls = {"n": 0}

    def compute():
        calls["n"] += 1
        return {"v": calls["n"]}

    a = ins._cached(ins._ckey("t", limit=10), compute)
    b = ins._cached(ins._ckey("t", limit=20), compute)
    assert calls["n"] == 2 and a["v"] != b["v"]  # different params -> not shared


def test_per_corpus_analysis_endpoints_route_through_cache():
    """Remark 8 (field test 2026-06-24): the analysis window's per-corpus endpoints were
    UNCACHED whole-corpus-scoped aggregations, so every keyword open / subtab switch
    re-paid the search + GROUP BY ("Loading…"). They now route through the shared
    _cached() (the corpus resolve moved INSIDE the compute so a cache hit skips the
    search too), TTL-disclosed like every other cached insights endpoint."""
    import pathlib

    src = pathlib.Path(ins.__file__).read_text("utf-8")
    for name in (
        "corpus-keywords",
        "corpus-www",
        "corpus-sentiment",
        "corpus-sources",
        "corpus-coordination",
    ):
        assert f'_ckey("{name}"' in src, f"{name} must build a cache key for _cached()"


def test_warm_cache_populates_the_keys_the_endpoints_use(monkeypatch):
    ins._read_cache._cache.clear()
    monkeypatch.setattr(ins.q, "trending_windows", lambda db, **kw: {"windows": []})
    monkeypatch.setattr(ins.q, "top_terms", lambda db, **kw: {"terms": []})

    res = ins.warm_cache(db=object())
    assert len(res["warmed"]) == 3
    # The EXACT keys Home + Insights request must each be a cache HIT — including the
    # `tl` param the endpoint always adds (P0-4: the old warm key used limit=10 and
    # omitted tl, so it matched NOTHING the UI asks for and the user paid cold).
    for lim, st in (ins.WARM_TRENDING_HOME, ins.WARM_TRENDING_INSIGHTS):
        key = ins._ckey(
            "trending-windows", country=None, kind=None,
            limit=lim, series_top=st, tl=ins._tlang(None),
        )
        assert ins._read_cache.get(key) is not None, f"warm missed the UI key {lim}/{st}"
    # A second warm within the TTL recomputes nothing (all keys already fresh).
    assert ins.warm_cache(db=object())["warmed"] == []


def test_associations_endpoint_is_cached(monkeypatch):
    # The per-query analysis endpoints (associations / graph) are heavy whole-corpus
    # co-occurrence; caching by their args makes re-opening the same term instant.
    ins._read_cache._cache.clear()
    calls = {"n": 0}

    def fake_assoc(db, term, **kw):
        calls["n"] += 1
        return {"term": term, "neighbours": []}

    monkeypatch.setattr(ins.q, "associations", fake_assoc)
    r1 = ins.insights_associations(term="middle-east", db=object())
    r2 = ins.insights_associations(term="middle-east", db=object())
    assert calls["n"] == 1  # the 2nd call is served from cache
    assert r1["cached"] is False and r2["cached"] is True
    # A different term is a different cache entry (recomputed).
    ins.insights_associations(term="other", db=object())
    assert calls["n"] == 2
