"""Audit finding 2026-07-17: several downstream analytics functions
(corpus_keywords, corpus_www, corpus_sentiment, corpus_sources,
corpus_facet_article_ids, who_aggregate, where_aggregate -- src/analytics/queries.py)
filter with an UNCHUNKED ``X.article_id.in_(article_ids)``. The corpus-* endpoints
accept ``cap`` up to 5000 (some up to 20000) -- well past SQLite's historical ~999
bound-variable ceiling. A Home card carrying an explicit, large ``article_ids`` set
(diet_self_audit/capacity_implausible can now carry up to 2000, per an earlier fix
this same audit session) or a plain search with a high ``cap`` would make the
downstream query raise "OperationalError: too many SQL variables" instead of an
honest result. ``_resolve_corpus`` -- the ONE shared resolver every corpus-*
endpoint funnels through -- now clamps ``cap`` to a SQLite-safe bound regardless of
what the caller requested.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from src.api.insights import _SQLITE_SAFE_IN_CAP, _resolve_corpus


def test_explicit_article_ids_are_clamped_to_the_sqlite_safe_cap_even_with_a_higher_requested_cap():
    many_ids = ",".join(str(i) for i in range(1, 2001))  # 2000 explicit ids
    ids, total = _resolve_corpus(
        None, many_ids, query=None, source=None, start_date=None, end_date=None,
        language=None, tags=None, cap=2000,  # the endpoint's own declared le=5000 range
    )
    assert len(ids) == _SQLITE_SAFE_IN_CAP
    assert len(ids) <= 900  # the value used everywhere else in the codebase for this bound
    assert total == 2000  # the TRUE requested size is still disclosed (capped = total > len(ids))
    assert ids == list(range(1, _SQLITE_SAFE_IN_CAP + 1))  # order-preserving, first N kept


def test_explicit_article_ids_under_the_safe_cap_are_unaffected():
    few_ids = "5,3,9,3,1"  # includes a duplicate, deliberately unsorted
    ids, total = _resolve_corpus(
        None, few_ids, query=None, source=None, start_date=None, end_date=None,
        language=None, tags=None, cap=900,
    )
    assert ids == [5, 3, 9, 1]  # deduped, order-preserving, nothing clamped
    assert total == 4


def test_sqlite_safe_cap_constant_matches_the_repo_wide_convention():
    assert _SQLITE_SAFE_IN_CAP == 900
