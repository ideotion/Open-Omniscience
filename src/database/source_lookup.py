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

from src.database.feed_key import feed_key
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


def domain_keyed(session: Session) -> bool:
    """Is the store still keyed on the domain alone (the rebuild has not reached it)? Then it cannot hold a second feed of a
    domain, and an add or an import of one reads as the domain's existing row, exactly as it did before row J (a second INSERT
    would be an IntegrityError that ``POST /sources`` turns into a 500)."""
    from src.database.source_identity import composite_key_active

    return not composite_key_active(session.connection())


def source_for_feed(session: Session, domain: str | None, rss_url: str | None) -> Source | None:
    """The source with exactly this ``(domain, feed)``, or ``None``. For an explicit ADD: a second feed of a registered
    domain is not "already there", it is a sibling, so only the identical feed counts as a duplicate."""
    if not domain:
        return None
    if domain_keyed(session):
        return source_for_domain(session, domain)
    return (
        session.query(Source)
        .filter(Source.domain == domain, Source.feed_key == feed_key(rss_url))
        .order_by(Source.id)
        .first()
    )


def match_import(rows: list[tuple[int, str]], fk: str, batch_records: int = 1, legacy: bool = False) -> int | None:
    """Which of a domain's ``(id, feed_key)`` rows an imported record is -- an EDIT, never an add: the identical feed;
    else the domain's only row, when this import carries ONE record for the domain (a changed feed URL is the same source,
    as the seeder and the restore merge read it -- ``merge._same_source`` applies the same one-to-one fallback only when
    both sides hold exactly one); else, for a record with no feed, the oldest row. ``None`` means a feed this domain does
    not hold yet: a sibling. ``batch_records`` is how many records of this domain the import carries: with several, a feed
    the store lacks is a new sibling, never an overwrite of the one row it happens to hold. ``legacy``: a store still keyed
    on the domain alone can only edit its row."""
    if legacy and rows:
        return rows[0][0]
    for sid, key in rows:
        if (key or "") == fk:
            return sid
    if len(rows) == 1 and batch_records <= 1:
        return rows[0][0]
    if not fk and rows:
        return rows[0][0]
    return None


def source_for_import(session: Session, domain: str | None, rss_url: str | None, batch_records: int = 1) -> Source | None:
    """The source an imported record (YAML, CSV) updates, per :func:`match_import`, or ``None`` when it is a new feed."""
    rows = sources_for_domain(session, domain)
    sid = match_import(
        [(r.id, r.feed_key or "") for r in rows], feed_key(rss_url), batch_records, legacy=domain_keyed(session)
    )
    return next((r for r in rows if r.id == sid), None) if sid is not None else None
