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


def test_warm_cache_populates_the_keys_the_endpoints_use(monkeypatch):
    ins._read_cache._cache.clear()
    monkeypatch.setattr(ins.q, "trending_windows", lambda db, **kw: {"windows": []})
    monkeypatch.setattr(ins.q, "top_terms", lambda db, **kw: {"terms": []})

    res = ins.warm_cache(db=object())
    assert len(res["warmed"]) == 3
    # The EXACT key the Home "Trending now" panel requests is now a cache hit.
    home_key = ins._ckey("trending-windows", country=None, kind=None, limit=10, series_top=5)
    assert ins._read_cache.get(home_key) is not None
    # A second warm within the TTL recomputes nothing (all keys already fresh).
    assert ins.warm_cache(db=object())["warmed"] == []
