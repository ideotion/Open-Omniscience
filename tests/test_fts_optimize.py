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


def _segments(s) -> int:
    from sqlalchemy import text as _t

    return int(s.execute(_t("SELECT count(DISTINCT segid) FROM article_fts_idx")).scalar() or 0)


def _many_segments(n_batches=30):
    eng = _engine()
    ensure_fts(eng)
    Session = sessionmaker(bind=eng, future=True)
    with Session() as s:
        from sqlalchemy import text as _t

        s.execute(_t("INSERT INTO article_fts(article_fts, rank) VALUES ('automerge', 0)"))
        s.add(Source(name="S", domain="x.test"))
        s.commit()
        for b in range(n_batches):  # one commit per batch: one new segment each, automerge off
            for i in range(5):
                k = b * 5 + i
                s.add(Article(url=f"u{k}", canonical_url=f"u{k}", source_id=1, title=f"T{k}",
                              content=f"inflation report {k} word{k}", hash=f"h{k}", language="en"))
            s.commit()
    return Session


def test_the_bounded_merge_leaves_a_handful_of_segments_and_search_unchanged():
    """The 2026-11-15 change: bounded incremental 'merge' steps instead of one 'optimize' that held the writer gate for
    half an hour on a field import."""
    from src.database.fts import merge_fts_segments

    Session = _many_segments()
    with Session() as s:
        before = _segments(s)
        assert before > 6
        assert merge_fts_segments(s, budget_s=60) is True
        assert _segments(s) <= 6
        assert len(search_ids(s, "inflation") or []) == 150


def test_writes_between_merge_steps_never_fragment_the_index():
    """The regression a review measured on the first cut (negative counts, 2026-11-15): an article written between
    steps abandoned the partial merge, and the segment count grew without bound (4 to 122 segments here, in 300 steps
    of 4 pages with one article after each). The incremental steps stay a handful under the same interleaving."""
    import random
    import string

    import src.database.fts as fts_mod
    from src.database.fts import merge_fts_segments

    rnd = random.Random(3)

    def doc():
        return "inflation " + " ".join("".join(rnd.choices(string.ascii_lowercase, k=6)) for _ in range(40))

    eng = _engine()
    ensure_fts(eng)
    Session = sessionmaker(bind=eng, future=True)
    with Session() as s:
        s.add(Source(name="S", domain="x.test"))
        s.commit()
        k = 0
        for _b in range(40):
            for _i in range(10):
                k += 1
                s.add(Article(url=f"u{k}", canonical_url=f"u{k}", source_id=1, title="t", content=doc(),
                              hash=f"h{k}", language="en"))
            s.commit()
        old = fts_mod._FTS_MERGE_STEP_PAGES
        fts_mod._FTS_MERGE_STEP_PAGES = 4
        try:
            for _j in range(300):  # one small step, then one article: a collector writing beside the merge
                merge_fts_segments(s, budget_s=60, max_steps=1)
                k += 1
                s.add(Article(url=f"u{k}", canonical_url=f"u{k}", source_id=1, title="t", content=doc(),
                              hash=f"h{k}", language="en"))
                s.commit()
        finally:
            fts_mod._FTS_MERGE_STEP_PAGES = old
        assert _segments(s) <= 20
        assert len(search_ids(s, "inflation") or []) == 700


def test_the_bounded_merge_stops_when_asked_and_does_nothing_on_a_zero_budget():
    from src.database.fts import merge_fts_segments

    Session = _many_segments()
    with Session() as s:
        before = _segments(s)
        assert merge_fts_segments(s, budget_s=0) is False
        assert merge_fts_segments(s, budget_s=60, should_stop=lambda: True) is False
        assert _segments(s) == before
