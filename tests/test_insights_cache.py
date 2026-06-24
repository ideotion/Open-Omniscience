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


def test_slow_per_keyword_endpoints_run_under_a_statement_deadline():
    """Remark 8 (field test 2026-06-24): the heaviest per-keyword reads (associations,
    the keyword/article graph, framing) must run under a statement DEADLINE so a
    runaway whole-corpus aggregation on a large encrypted corpus ends in a typed 503,
    never an infinite "Loading…". The deadline is layered on the existing TTL cache
    (it runs INSIDE the compute, so only on a cache miss)."""
    import pathlib

    src = pathlib.Path(ins.__file__).read_text("utf-8")
    # associations + BOTH graph paths (article-set + layered) route through the helper.
    assert src.count("_deadlined(") >= 3, "associations + both graph paths need the deadline"
    assert "statement_deadline" in src and "StatementTimeout" in src

    # Read framing.py as a sibling file rather than importing it — importing pulls in
    # vaderSentiment (the [analysis] extra), absent in the core-only CI lane.
    fsrc = pathlib.Path(ins.__file__).with_name("framing.py").read_text("utf-8")
    assert "statement_deadline(" in fsrc and "status_code=503" in fsrc


def test_statement_timeout_maps_to_an_honest_503(monkeypatch):
    """A StatementTimeout raised while computing a per-keyword payload becomes an
    HTTP 503 with the deadline stated — not a 500 and not a hang (remark 8)."""
    from fastapi import HTTPException

    from src.database.maintenance import StatementTimeout

    ins._read_cache._cache.clear()

    def boom(db, term, **kw):
        raise StatementTimeout("statement exceeded the 60s deadline and was aborted")

    monkeypatch.setattr(ins.rm, "associations", boom)
    try:
        ins.insights_associations(term="runaway", db=object())
    except HTTPException as exc:
        assert exc.status_code == 503
        assert "deadline" in exc.detail
    else:
        raise AssertionError("a StatementTimeout must surface as HTTP 503")
