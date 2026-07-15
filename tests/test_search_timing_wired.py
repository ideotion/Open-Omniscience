"""
S5 — instrument_search wired into the live /api/articles FTS path.

Proves a real text search through ``_query_articles`` records a per-phase breakdown into the
search-timing reservoir (so ``GET /api/diagnostics/search-timing`` is no longer empty-honest
forever), with ZERO change to what the search returns. Runs against a real in-memory FTS corpus.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.fts import ensure_fts
from src.database.models import Article, Base, Source

main = pytest.importorskip("src.api.main")  # CI/venv with crypto; skips on a bare sandbox
from src.monitoring import search_timing  # noqa: E402


def _session():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(eng)
    ensure_fts(eng)
    s = sessionmaker(bind=eng, future=True)()
    s.add(Source(name="S", domain="x.test"))
    s.flush()
    for i, (t, c) in enumerate([
        ("Inflation report", "coverage of inflation and markets and trade policy"),
        ("Markets update", "a longer body mentioning inflation once here today"),
        ("Weather note", "sunshine and rain across the region this week"),
    ]):
        s.add(Article(url=f"u{i}", canonical_url=f"u{i}", source_id=1, title=t, content=c,
                      hash=f"h{i}", language="en", created_at=datetime.now(UTC)))
    s.commit()
    return s


def _q(s, query):
    return main._query_articles(
        s, query=query, source=None, start_date=None, end_date=None, language=None,
        tags=None, limit=50, offset=0,
    )


def test_text_search_records_per_phase_timing_without_changing_results():
    s = _session()
    search_timing._reset_for_tests()
    # correctness: the search still returns exactly the matching articles.
    articles, total = _q(s, "inflation")
    titles = {a.title for a in articles}
    assert total == 2 and titles == {"Inflation report", "Markets update"}
    _q(s, "inflation")
    _q(s, "markets")  # a few searches -> a populated reservoir

    report = search_timing.search_timing_report()
    # non-empty aggregate with the fts / load phases we marked + a measured dominant phase.
    assert report["searches"] >= 3, report
    assert "fts" in report["phases"] and "load" in report["phases"], report["phases"]
    assert report["dominant_phase"] in ("fts", "resolve", "load")


def test_browse_without_a_query_records_nothing():
    s = _session()
    search_timing._reset_for_tests()
    articles, total = _q(s, None)  # a browse, not a search
    assert total == 3  # all three, recency order
    report = search_timing.search_timing_report()
    assert report["searches"] == 0  # a browse is not a search — nothing recorded
