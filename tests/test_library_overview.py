"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

GET /api/library/overview -- the central Library DASHBOARD roll-up (field remark 16).
Honest COUNTS + on-disk byte SIZES only, NEVER a score; tables/managers absent from a
build degrade to null / unavailable rather than crashing; freshness is disclosed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def _no_score(obj) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert "score" not in str(k).lower(), f"a composite score leaked: {k}"
            _no_score(v)
    elif isinstance(obj, list):
        for v in obj:
            _no_score(v)


def test_library_overview_shape_and_honesty(client):
    r = client.get("/api/library/overview")
    assert r.status_code == 200
    d = r.json()

    # the four sections + the disclosed freshness window.
    for k in ("corpus", "downloaded", "derived", "database_file"):
        assert k in d, f"missing section {k}"
    assert "computed_at" in d and int(d["cache_ttl_s"]) >= 1

    # the RAW / downloaded layers (counts or null; download sizes via the managers).
    dl = d["downloaded"]
    for k in ("wikipedia", "maps", "markets", "laws", "statistics", "models"):
        assert k in dl, f"missing downloaded layer {k}"
    assert "dumps" in dl["wikipedia"] and "count" in dl["wikipedia"]["dumps"]
    assert "osm_regions" in dl["maps"] and "total_bytes" in dl["maps"]["osm_regions"]
    assert "total_bytes" in dl["models"]

    # the DERIVED / extrapolated AI layer, BY KIND (summaries / translations / synthesis,
    # AI keywords) — clearly separate from the corpus, never the trusted index.
    der = d["derived"]
    assert "article_analyses" in der and "by_kind" in der["article_analyses"]
    assert "ai_keywords" in der and "by_kind" in der["ai_keywords"]

    # counts only — NO composite score anywhere in the whole payload.
    _no_score(d)
