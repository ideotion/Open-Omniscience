"""Article counts per source, read from indexes alone (field test 2026-11-14, row 59).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS MODULE EXISTS. Two Home and Insights reads counted articles per source with a join the
planner served by reading every article ROW: ``queries.source_type_facets`` (``/api/insights/
source-types``) and the content-type and tag options of ``/api/insights/latest``. A row read on
this table is the article's whole record, its text included, and on the encrypted store every page
of it goes through the codec. ``quarantined`` and ``created_at`` sit after ``content`` in the
record, so a row whose text spills also walks its overflow pages. On the field instances both routes
answered 503 after the 60 s statement deadline for about an hour after every unlock (report 4.2,
16.4), before the in-memory rollups were rebuilt.

Measured on a 150,000-article, 1.03 GB plaintext store (16 KiB pages, 300 sources, created_at spread
over 90 days, half the rows ``quarantined`` NULL and half 0), bytes read through ``read()`` by one
connection with an 8 MB page cache and no mmap (``/proc/self/io`` rchar). The count statements alone:

    the all-time count per source type          2,628.6 MB, 533 ms  ->  2.5 MB, 42 ms
    the 30-day count per source (latest facets)     812.0 MB, 190 ms  ->  3.6 MB, 53 ms

and the two route functions whole, old tree against this one (``source_type_facets``; ``latest_articles``
with its defaults, whose bounded candidate read is unchanged):

    source_type_facets     2,628 MB, 527 ms    ->  2.5 MB, 21 ms
    latest_articles        1,576 MB, 1,069 ms  ->  12.6 MB, 579 ms

Same counts in every case. The plaintext times flatter the old plans: they are page-cache reads,
where the field store pays a decrypt and an HMAC per page and often a cold disk.

THE PLANS, and why each is forced with ``INDEXED BY``. Without statistics the planner takes
``idx_article_source_id`` for the GROUP BY and then reads the row for the filter column.

  * all time, quarantined left out: ``idx_article_feed_scan (quarantined, source_id, id)`` carries
    every column the count needs, so the scan is ``SCAN articles USING COVERING INDEX``.
  * a ``created_at`` window: no index carries both ``created_at`` and ``source_id``. The ids in the
    window come from ``idx_article_created_at`` (index only, it carries the rowid), and the
    ``source_id`` of each from ``idx_article_source_id`` (index only too); SQLite joins the two
    with an IN list and a bloom filter. Both are index scans, and neither touches a row.

A store missing one of these indexes (``idx_article_feed_scan`` is a boot self-heal, see
``maintenance.HOT_INDEXES``) would fail the prepare, so the schema is asked first and such a store
runs the old plan, slower, with the same counts. An error of the statement itself, a deadline among
them, is raised as it was: retrying a deadlined scan with the slower plan would spend the deadline
twice.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.orm import Session

# All time, quarantined articles left out: one covering-index scan.
_ALL_TIME_UNQUARANTINED = (
    "SELECT source_id, count(*) FROM articles INDEXED BY idx_article_feed_scan "
    "WHERE quarantined IS NOT 1 GROUP BY source_id"
)

# A created_at window, every article counted (the latest facets never filtered on quarantine).
_SINCE = (
    "SELECT source_id, count(*) FROM articles INDEXED BY idx_article_source_id "
    "WHERE id IN (SELECT id FROM articles INDEXED BY idx_article_created_at WHERE created_at >= :since) "
    "GROUP BY source_id"
)


def _have(session: Session, *names: str) -> bool:
    """Whether every one of ``names`` is an index of this store (one read of the schema table).

    Asked BEFORE the statement rather than learned from its failure: a driver error's words are never read
    (the sink sweep's rule), and a failed scan must never be retried with the slower plan."""
    if session.get_bind().dialect.name != "sqlite":  # INDEXED BY and sqlite_master are SQLite's
        return False
    found = session.execute(
        text("SELECT count(*) FROM sqlite_master WHERE type = 'index' AND name IN :names").bindparams(
            bindparam("names", expanding=True)
        ),
        {"names": list(names)},
    ).scalar()
    return int(found or 0) == len(names)


def _counts(rows) -> dict[int, int]:
    return {int(sid): int(n) for sid, n in rows if sid is not None}


def unquarantined_counts_by_source(session: Session) -> dict[int, int]:
    """``{source_id: articles}`` over the whole corpus, quarantined articles left out (``IS NOT 1``,
    so NULL counts as not quarantined, as everywhere else)."""
    if _have(session, "idx_article_feed_scan"):
        return _counts(session.execute(text(_ALL_TIME_UNQUARANTINED)).all())
    return _counts(session.execute(_fallback_unquarantined()).all())


def counts_by_source_since(session: Session, since: datetime) -> dict[int, int]:
    """``{source_id: articles}`` for articles with ``created_at >= since``, every article counted.

    ``since`` is bound through the column's own DateTime type, so it is compared against the same
    stored text form the ORM filter ``Article.created_at >= since`` compares against."""
    from src.database.models import Article

    if _have(session, "idx_article_source_id", "idx_article_created_at"):
        param = bindparam("since", since, type_=Article.__table__.c.created_at.type)
        return _counts(session.execute(text(_SINCE).bindparams(param)).all())
    return _counts(session.execute(_fallback_since(since)).all())


# The fallbacks are built by the ORM, so another dialect gets its own spelling (``IS NOT true`` on PostgreSQL, where
# ``IS NOT 1`` is a syntax error). On SQLite they compile to the plans the old joins ran, which the tests pin as the slow
# twin of the forced ones.
def _fallback_unquarantined():
    from src.database.models import Article

    return (
        select(Article.source_id, func.count())
        .where(Article.quarantined.isnot(True))
        .group_by(Article.source_id)
    )


def _fallback_since(since: datetime):
    from src.database.models import Article

    return select(Article.source_id, func.count()).where(Article.created_at >= since).group_by(Article.source_id)
