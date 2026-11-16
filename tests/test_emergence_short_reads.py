"""Emergence reads its article counts as short per-day statements (field test 2026-11-14 row 58).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

On a field corpus the detector's one GROUP BY over five weeks of mentions ran 1,239 s while the WAL grew to 2.81 GB: a
running statement is a reader no checkpoint can pass. It now goes through ``windowed_group_counts``. These tests pin
that it does, and that the per-day row counts give the answer ``COUNT(DISTINCT article_id)`` over the window gave.
"""

from __future__ import annotations

import pytest
from sqlalchemy import distinct, func, select

from src.analytics.emergence import find_manufactured_emergence
from src.database import query as query_mod
from src.database.derived_views import KeywordMentionRead
from src.database.stand_in import not_a_stand_in_article_id
from tests.test_concentration_bounded_reads import _random_corpus, db  # noqa: F401  (the fixture)

_ARGS = {"max_prior": 1, "min_recent_articles": 2, "min_sources": 2, "max_candidates": 100_000, "max_items": 100_000}


def _one_group_by(session, *, key, day, rowid, value, lo, hi, keep, where=(), **_):
    """The read as it was: one statement, distinct articles over the whole window."""
    stmt = (
        select(KeywordMentionRead.keyword_id, func.count(distinct(KeywordMentionRead.article_id)))
        .where(day >= lo, day < hi, not_a_stand_in_article_id(KeywordMentionRead.article_id))
        .group_by(KeywordMentionRead.keyword_id)
    )
    return query_mod.grouped_counts(session, stmt, keep)


def test_emergence_reads_through_the_windowed_helper(db, monkeypatch):  # noqa: F811
    _random_corpus(db, 1)
    calls: list[tuple] = []
    real = query_mod.windowed_group_counts

    def spy(session, **kw):
        calls.append((kw["lo"], kw["hi"]))
        return real(session, **kw)

    monkeypatch.setattr(query_mod, "windowed_group_counts", spy)
    find_manufactured_emergence(db, **_ARGS)
    assert calls, "the counts are read day by day, never as one statement over the window"


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_per_day_row_counts_are_the_distinct_article_counts(db, monkeypatch, seed):  # noqa: F811
    _random_corpus(db, seed)
    windowed = find_manufactured_emergence(db, **_ARGS)
    db.rollback()
    monkeypatch.setattr(query_mod, "windowed_group_counts", _one_group_by)
    single = find_manufactured_emergence(db, **_ARGS)
    assert windowed == single
    assert windowed.get("items"), "the corpus has emergent terms, so the comparison is not of two empty answers"
