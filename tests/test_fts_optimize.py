"""FTS5 'optimize' + planner tuning pass (keyword-engine Phase 1.4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

optimize_after_bulk merges the external-content FTS index segments a bulk article load
churns (FTS5 'optimize', distinct from PRAGMA optimize) + refreshes the planner stats
after a big keyword-table churn. Gated, SQLite-only, best-effort — a tuning failure
never breaks the caller, and search stays correct after the merge.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.fts import ensure_fts, optimize_after_bulk, search_ids
from src.database.models import Article, Base, Source


def _engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(eng)
    return eng


def _seed(Session, n):
    with Session() as s:
        s.add(Source(name="S", domain="x.test"))
        s.commit()
        for i in range(n):
            s.add(
                Article(
                    url=f"u{i}",
                    canonical_url=f"u{i}",
                    source_id=1,
                    title=f"Story {i}",
                    content=f"election inflation economy report number {i}",
                    hash=f"h{i}",
                    language="en",
                )
            )
        s.commit()


def test_optimize_after_bulk_runs_and_keeps_fts_queryable():
    eng = _engine()
    ensure_fts(eng)  # create the FTS table + triggers
    Session = sessionmaker(bind=eng, future=True)
    _seed(Session, 5)  # the AFTER INSERT trigger populates the FTS
    with Session() as s:
        # FTS finds all 5 before the merge (sanity)
        assert len(search_ids(s, "inflation") or []) == 5
        out = optimize_after_bulk(s)
        assert out["fts"] is True and out["planner"] is True
        # the merge does not corrupt the index — search is still exact
        assert len(search_ids(s, "inflation") or []) == 5
        assert len(search_ids(s, "election") or []) == 5


def test_optimize_after_bulk_is_best_effort_without_fts():
    """No FTS table (a store that never built one) — the FTS step degrades to False,
    the planner step still runs; never a crash."""
    eng = _engine()  # NO ensure_fts
    Session = sessionmaker(bind=eng, future=True)
    _seed(Session, 2)
    with Session() as s:
        out = optimize_after_bulk(s)
        assert out["fts"] is False  # graceful: no FTS table to optimize
        assert out["planner"] is True  # planner optimize needs no FTS
