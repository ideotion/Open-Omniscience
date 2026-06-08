"""
The corpus actor graph — coordination over the stored articles.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Thin, bounded adapter from the stored corpus to the pure
:func:`src.signals.coordination.detect_coordination` primitive: pull recent articles,
hand the engine ``{id, source, text, published_at, host}``, get back proposed actors
(coordinated source clusters) with their evidence. No verdict is rendered here — a
proposed actor is a *question with evidence*, applied only if the user chooses.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import func

from src.database.models import Article, Source
from src.signals.coordination import detect_coordination

# Bounds — never an unbounded scan (the bounded-crawler discipline).
_MAX_ARTICLES = 2000


def actor_signature(sources: list[str]) -> str:
    """A stable identity for an actor = hash of its sorted member source names.

    Used to persist a user's collapse decision so it re-applies to the *same* cluster
    on recompute, and changes (inviting re-inspection) if the membership shifts.
    """
    basis = "|".join(sorted(s for s in sources if s)).encode("utf-8")
    return hashlib.sha256(basis).hexdigest()[:16]


def corpus_actors(
    session,
    *,
    days: int = 14,
    threshold: float = 0.6,
    window_hours: float = 48.0,
    min_chars: int = 200,
    limit: int = _MAX_ARTICLES,
):
    """Detect coordinated actors among recently-published articles.

    Returns the :class:`~src.signals.coordination.CoordinationResult`, with a stable
    ``signature`` attached to each actor (for collapse persistence).
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)
    rows = (
        session.query(Article, Source.name, Source.domain)
        .outerjoin(Source, Source.id == Article.source_id)
        .filter(func.coalesce(Article.published_at, Article.created_at) >= cutoff)
        .order_by(Article.id.desc())
        .limit(limit)
        .all()
    )
    documents = []
    for article, source_name, domain in rows:
        text = article.get_content() or article.title or ""
        if len(text) < min_chars:
            continue
        documents.append({
            "id": str(article.id),
            "source": source_name or domain or f"source-{article.source_id}",
            "text": text,
            "published_at": article.published_at or article.created_at,
            "host": domain,
        })

    result = detect_coordination(documents, threshold=threshold, window_hours=window_hours)
    # Attach a stable signature to each proposed actor.
    for actor in result.actors:
        actor.signature = actor_signature(actor.sources)  # type: ignore[attr-defined]
    return result


def actor_view(result) -> list[dict]:
    """Serialise actors with their signature for the API/GUI."""
    out = []
    for actor in result.actors:
        d = actor.to_dict()
        d["signature"] = (actor.signature or actor_signature(actor.sources))
        out.append(d)
    return out
