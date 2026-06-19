"""
The A1 read-model seam — the ONE boundary for whole-corpus aggregate reads.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why this module exists
----------------------
The heavy, whole-corpus aggregations (most-mentioned terms, rising terms across
windows, co-occurrence / mind-map graphs, per-country source coverage) are the
queries that froze the UI on a decade-scale corpus (field report 2026-06-18: a
``GROUP BY`` over the 800k+-row mentions table). The data-architecture plan
(maintainer ruling 2026-06-19) answers that with a *derived columnar read-model*
(Slice 4) — but ONLY if those reads all flow through a single, documented seam, so
the columnar store can be plugged in **without touching a single endpoint**.

This module IS that seam. Today (v1) every function delegates straight to
``src.analytics.queries`` so behavior is **byte-identical** — the endpoints already
route through here, the live query is still the source of truth. Slice 4 changes the
*implementation* inside these functions (read the columnar store; fall back to the
live query when it is cold/missing — slower, never wrong); the endpoint code, the
response shapes, and the honesty envelopes do not move.

Invariants this seam must keep (Slice 4 and beyond)
---------------------------------------------------
* **Same results.** A columnar answer must equal the live-query answer for any
  consistent corpus; a cold/missing derived store falls back to the live query.
* **Canonical store stays the source of truth.** The derived store is a disposable
  accelerator; correctness never *depends* on it.
* **Honesty envelope preserved.** Where a payload carries a freshness/basis
  disclosure (Slice 1/2), it travels through here unchanged.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.analytics import queries as _live

# The set of whole-corpus aggregate reads that route through this seam. Slice 4 reads
# these from the derived columnar store; v1 is a transparent delegation. Each wrapper
# forwards its arguments verbatim so the contract cannot drift from the live query
# (the tests compare outputs to prove the delegation is byte-identical).


def top_terms(session: Session, *args, **kwargs) -> dict:
    """Most-mentioned keywords (corpus-wide or windowed). See queries.top_terms."""
    return _live.top_terms(session, *args, **kwargs)


def trending(session: Session, *args, **kwargs) -> dict:
    """Rising keywords by the transparent recent-vs-prior ratio. See queries.trending."""
    return _live.trending(session, *args, **kwargs)


def trending_windows(session: Session, *args, **kwargs) -> dict:
    """Rising keywords across the three preset windows. See queries.trending_windows."""
    return _live.trending_windows(session, *args, **kwargs)


def associations(session: Session, *args, **kwargs) -> dict:
    """Keyword co-occurrence / PMI. See queries.associations."""
    return _live.associations(session, *args, **kwargs)


def layered_graph(session: Session, *args, **kwargs) -> dict:
    """The term/level mind-map graph. See queries.layered_graph."""
    return _live.layered_graph(session, *args, **kwargs)


def article_graph(session: Session, *args, **kwargs) -> dict:
    """The exact-article-set mind-map graph. See queries.article_graph."""
    return _live.article_graph(session, *args, **kwargs)


def source_country_counts(session: Session, *args, **kwargs) -> dict:
    """Per-country source / article / keyword / tone coverage (map). See queries."""
    return _live.source_country_counts(session, *args, **kwargs)
