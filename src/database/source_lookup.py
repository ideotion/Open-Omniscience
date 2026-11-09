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

from src.database.feed_key import domain_keys, feed_key, legacy_feed_key, lookup_key, read_feed_key
from src.database.models import Source

#: The words an add says (a log line) and an edit answers (a 409) when the domain already holds the feed: one sentence for both.
FEED_HELD = "Source with domain {domain} and this feed already exists"


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
    fk = feed_key(rss_url)
    old = legacy_feed_key(rss_url)
    legacy: list[Source] | None = None
    if old != fk:
        # R634: a URL with a userinfo whose pre-R628 key a row still holds is THAT row (one feed stored twice before R628 keeps
        # both rows, and the credentialed one keeps its key), not its plain twin. Read among the domain's keys that hold an "@",
        # compared here, so the login is never a parameter of the query.
        legacy = _keys_with_an_at(session, domain)
        row = next((r for r in legacy if r.feed_key == old), None)
        if row is not None:
            return row
    row = (
        session.query(Source)
        .filter(Source.domain == domain, Source.feed_key == fk)
        .order_by(Source.id)
        .first()
    )
    if row is None and fk:
        # A key stored before R628 kept the feed URL's userinfo and holds an "@": read as its feed's key today
        # (``read_feed_key``), so adding the same feed again is not a second row. Only on a miss, and only the domain's
        # keys that hold an "@".
        rows = legacy if legacy is not None else _keys_with_an_at(session, domain)
        row = next((r for r in rows if read_feed_key(r.feed_key, r.rss_url) == fk), None)
    return row


def _keys_with_an_at(session: Session, domain: str) -> list[Source]:
    """The domain's sources whose stored key holds an "@" (a key stored before R628, or a feed whose path holds one), oldest first:
    one query on the domain's index."""
    return session.query(Source).filter(Source.domain == domain, Source.feed_key.contains("@")).order_by(Source.id).all()


def match_import(
    rows: list[tuple[int, str]], fk: str, batch_records: int = 1, legacy: bool = False, reads: list[tuple[int, str]] | None = None
) -> int | None:
    """Which of a domain's ``(id, feed_key)`` rows an imported record is -- an EDIT, never an add: the identical feed;
    else the domain's only row, when this import carries ONE record for the domain (a changed feed URL is the same source,
    as the seeder and the restore merge read it -- ``merge._same_source`` applies the same one-to-one fallback only when
    both sides hold exactly one); else, for a record with no feed, the oldest row. ``None`` means a feed this domain does
    not hold yet: a sibling. ``batch_records`` is how many records of this domain the import carries: with several, a feed
    the store lacks is a new sibling, never an overwrite of the one row it happens to hold. ``legacy``: a store still keyed
    on the domain alone can only edit its row. ``reads`` (the R628 reads, independent S3): each row's stored key read as its
    feed's key today (:func:`import_reads`), tried after the identical key, so an import finds the row an add finds
    (:func:`source_for_feed`'s fallback): a two-logins pair keeps both keys, and the plain URL or a third login is the oldest of
    the two, never a third row."""
    if legacy and rows:
        return rows[0][0]
    for sid, key in rows:
        if (key or "") == fk:
            return sid
    if fk:
        for sid, key in reads or ():
            if key == fk:
                return sid
    if len(rows) == 1 and batch_records <= 1:
        return rows[0][0]
    if not fk and rows:
        return rows[0][0]
    return None


def import_rows(rows: list[tuple[int, str | None, str | None]]) -> list[tuple[int, str]]:
    """``(id, key)`` for :func:`match_import` from one domain's ``(id, feed_key, rss_url)`` rows: each stored key read as the key its
    row would be written with today (``domain_keys``: R628's reading of a key stored before it, and R634's kept key of a feed
    stored twice)."""
    return list(zip((sid for sid, _k, _u in rows), domain_keys([(k, u) for _sid, k, u in rows]), strict=True))


def import_reads(rows: list[tuple[int, str | None, str | None]]) -> list[tuple[int, str]]:
    """``(id, key)`` for :func:`match_import`'s ``reads``: each row whose stored key holds an "@", read as its feed's key today
    (``read_feed_key``, as :func:`source_for_feed` reads it on a miss), oldest first."""
    return [(sid, read_feed_key(k, u)) for sid, k, u in rows if "@" in (k or "")]


def source_for_import(session: Session, domain: str | None, rss_url: str | None, batch_records: int = 1) -> Source | None:
    """The source an imported record (YAML, CSV) updates, per :func:`match_import`, or ``None`` when it is a new feed."""
    rows = sources_for_domain(session, domain)
    stored: list[tuple[int, str | None, str | None]] = [(r.id, r.feed_key, r.rss_url) for r in rows]
    keyed = import_rows(stored)
    sid = match_import(
        keyed, lookup_key(rss_url, {k for _sid, k in keyed}), batch_records,
        legacy=domain_keyed(session), reads=import_reads(stored),
    )
    return next((r for r in rows if r.id == sid), None) if sid is not None else None


def _other_rows(session: Session, row: Source, domain: str | None) -> list[Source]:
    """The domain's other sources, oldest first: one query on the domain's index, never the URL or a key as a parameter."""
    if not domain:
        return []
    return session.query(Source).filter(Source.domain == domain, Source.id != row.id).order_by(Source.id).all()


def url_held_by_another(session: Session, row: Source, domain: str | None, rss_url: str | None) -> Source | None:
    """The other source of ``domain`` whose ``rss_url`` is exactly the one an edit gives ``row``, or ``None`` (the R628 reads,
    nit c): the plain row of a pair edited to its twin's URL derives a key the twin does not store (it keeps its own), so the
    unique index lets two rows hold one URL. Compared in Python."""
    if not rss_url:
        return None
    return next((o for o in _other_rows(session, row, domain) if o.rss_url == rss_url), None)


def feed_held_by_another(session: Session, row: Source, domain: str | None, rss_url: str | None) -> Source | None:
    """The other source of ``domain`` that stores the key an edit of ``row`` onto ``domain`` and ``rss_url`` would write
    (``source_key_to_write``, the before_update event's own reading), or ``None`` (the R628 reads, independent S2): read back
    from the store after the unique index refused the edit, so the refusal is named for the row that holds the feed and never
    from the driver's text. A new login on the kept row of a plain+login pair derives the plain row's key. Compared in Python."""
    from src.database.models import source_key_to_write

    others = _other_rows(session, row, domain)
    if not others:
        return None
    key = source_key_to_write(session, row.id, domain, row.feed_key, rss_url)
    return next((o for o in others if (o.feed_key or "") == key), None)
