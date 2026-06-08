"""
The multi-dimensional source profile — measured signals, NO composite score.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

FUTURE_DEVELOPMENTS §6 "C": per source, a panel of *measured* dimensions —
coordination/actor membership, novelty ratio, output-capacity plausibility,
transparency facts, corpus track-record — and **deliberately no single composite
score** (B is forbidden: a 0–100 trust number is false precision over incommensurable
dimensions, Goodhart-gameable, and *will* misclassify small/foreign/new/dissident
sources). The user weights which dimensions matter into *their own* view; this module
only *measures and reports*, each dimension carrying its own method + caveat.

The absence of a composite is enforced by a test (``test_integrity_profile``): the
returned ``dimensions`` mapping must contain no ``*score*``-style aggregate key.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func

from src.database.models import Article, Source
from src.integrity.actors import corpus_actors
from src.signals.novelty import novelty_scores

_PROFILE_DAYS = 30
_MAX_ARTICLES = 2000

# Ownership / control tags we recognise as transparency facts (from the spectrum file).
_OWNERSHIP_TAGS = ("state-media", "public-broadcaster", "wire-agency", "independent")


def source_profile(session, source_name: str, *, days: int = _PROFILE_DAYS) -> dict:
    """A panel of measured signals for one source — no composite, ever."""
    source = session.query(Source).filter(Source.name == source_name).first()
    if source is None:
        # Fall back to matching by domain so the profile works from either handle.
        source = session.query(Source).filter(Source.domain == source_name).first()
    if source is None:
        return {"source": source_name, "found": False}

    cutoff = datetime.now(UTC) - timedelta(days=days)
    arts = (
        session.query(Article)
        .filter(Article.source_id == source.id,
                func.coalesce(Article.published_at, Article.created_at) >= cutoff)
        .order_by(func.coalesce(Article.published_at, Article.created_at).asc())
        .limit(_MAX_ARTICLES)
        .all()
    )

    dimensions: dict[str, dict] = {}

    # -- coordination / actor membership ----------------------------------- #
    actors = corpus_actors(session, days=days)
    membership = [
        {"signature": a.signature, "co_sources": [s for s in a.sources if s != source.name],
         "shared_stories": a.shared_stories}
        for a in actors.actors if source.name in a.sources
    ]
    dimensions["coordination"] = {
        "is_member": bool(membership),
        "actors": membership,
        "method": actors.method,
        "caveat": actors.caveat,
    }

    # -- novelty ratio (originates vs echoes) ------------------------------ #
    # Novelty of this source's pieces against the *whole* recent corpus (oldest-first),
    # so a source that mostly reposts what others already published scores low.
    corpus = (
        session.query(Article.id, Article.source_id, Article.content, Article.title)
        .filter(func.coalesce(Article.published_at, Article.created_at) >= cutoff)
        .order_by(func.coalesce(Article.published_at, Article.created_at).asc())
        .limit(_MAX_ARTICLES)
        .all()
    )
    docs = [(str(aid), (content or title or "")) for aid, _sid, content, title in corpus]
    scores = novelty_scores(docs)
    own_ids = {str(a.id) for a in arts}
    ratios = [scores[i].ratio for i in own_ids if i in scores and scores[i].ratio is not None]
    mean_novelty = sum(ratios) / len(ratios) if ratios else None
    dimensions["novelty"] = {
        "mean_ratio": None if mean_novelty is None else round(mean_novelty, 3),
        "n": len(ratios),
        "method": "mean share of word-shingles new to the corpus across this source's recent articles",
        "caveat": ("Originality vs derivation, not truth or quality. A low ratio means this "
                   "source mostly echoes text already in your corpus — relative to your corpus."),
    }

    # -- output capacity plausibility -------------------------------------- #
    n_arts = len(arts)
    per_day = round(n_arts / days, 2) if days else None
    # Corpus-wide median per-source per-day, for context (not a threshold/verdict).
    totals = dict(
        session.query(Article.source_id, func.count(Article.id))
        .filter(func.coalesce(Article.published_at, Article.created_at) >= cutoff)
        .group_by(Article.source_id).all()
    )
    rates = sorted((c / days) for c in totals.values()) if days else []
    median_rate = rates[len(rates) // 2] if rates else None
    dimensions["output_capacity"] = {
        "articles": n_arts,
        "per_day": per_day,
        "corpus_median_per_day": None if median_rate is None else round(median_rate, 2),
        "method": f"this source's articles/day over {days}d vs the corpus median",
        "caveat": ("High output can be entirely legitimate (a wire agency, a large newsroom). "
                   "This is context for a human question, never a verdict of automation."),
    }

    # -- transparency facts (descriptive, contestable) --------------------- #
    tags = [t.strip() for t in (source.tags or "").split(",") if t.strip()]
    ownership = [t for t in tags if t in _OWNERSHIP_TAGS]
    leaning = [t for t in tags if t.startswith("lean-")]
    dimensions["transparency"] = {
        "country": source.country,
        "language": source.language,
        "ownership_tags": ownership,
        "leaning_tags": leaning,
        "reliability_score": source.reliability_score,  # operator-set metadata, not computed here
        "method": "descriptive tags from the curated catalog / operator edits",
        "caveat": ("Ownership and leaning tags are reputational and CONTESTABLE, editable by you; "
                   "reliability_score is an operator-set field, not a verdict this tool computed. "
                   "These are facts to weigh, not a score."),
    }

    # -- corpus track record ----------------------------------------------- #
    first_seen, last_seen, total = (
        session.query(func.min(Article.created_at), func.max(Article.created_at),
                      func.count(Article.id))
        .filter(Article.source_id == source.id).first()
    )
    dimensions["track_record"] = {
        "total_articles": int(total or 0),
        "first_seen": first_seen.isoformat() if first_seen else None,
        "last_seen": last_seen.isoformat() if last_seen else None,
        "method": "counts over everything this source has contributed to your corpus",
        "caveat": "Reflects your collection, not the source's full output.",
    }

    return {
        "source": source.name,
        "domain": source.domain,
        "found": True,
        "window_days": days,
        "dimensions": dimensions,
        "no_composite_score": True,  # §6: there is deliberately no single trust number here
    }
