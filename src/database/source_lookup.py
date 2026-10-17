"""One place that answers "which source is this domain" (row J, S05-10).

A domain may carry several sources once a source is identified by ``(domain, feed_key)``. Every lookup
that used ``filter_by(domain=...).first()`` returned "the" source only because ``domain`` was UNIQUE; with
the composite key the same call is a coin toss -- and not even rowid order, since the query now rides the
composite index. These helpers pin the answer: **the lowest ``id``**. The row an install already has was
created first, so on an unmigrated store every lookup answers exactly as it did before; a feed added later
is reachable by its own key and never displaces it.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.database.models import Source


def source_for_domain(session: Session, domain: str | None) -> Source | None:
    """The oldest source of ``domain`` (lowest id), or ``None``. An empty domain matches nothing."""
    if not domain:
        return None
    return session.query(Source).filter(Source.domain == domain).order_by(Source.id).first()


def sources_for_domain(session: Session, domain: str | None) -> list[Source]:
    """Every source of ``domain``, oldest first. For callers that must act on all of an outlet's feeds."""
    if not domain:
        return []
    return session.query(Source).filter(Source.domain == domain).order_by(Source.id).all()
