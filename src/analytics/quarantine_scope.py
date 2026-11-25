"""The one quarantine filter the keyword aggregates and the language series share (R101).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R101 (ruled 2026-09-30, the question ``D22`` / ``PRH-06``): an article the app quarantined as "not an
article" leaves the keyword figures, the per-language series and the equilibrium lever, in ONE slice,
so no call answers differently depending on which store served it. Every one of those readers takes
its filter from here, so they cannot drift apart:

* :func:`not_quarantined` is the SQL condition, written as ``<id> NOT IN (SELECT id FROM articles WHERE
  quarantined IS 1)``. That shape is deliberate: the subquery is answered from ``idx_article_quarantined``
  alone (SQLite carries the rowid in every index), so a reader that is index-only today stays
  index-only. A join to ``articles`` on ``quarantined`` would drag each article row through the SQLCipher
  codec, the recorded perf trap the language series and the mention scans were built to avoid.
* :func:`quarantined_article_ids` is the same set, read once, for the DuckDB rollup build, which filters
  rows as it stages them rather than asking SQLite again for every batch.

``quarantined`` NULL ("never judged") counts as not quarantined, as it does for every other reader.
Stand-in articles are quarantined (``src/database/stand_in.py``), so they leave these figures too.

R827 R10 / R830 (row 408 PR 3): the slice grows by one population, the imported articles the junk screening has not
reached yet (``screening_pending``, :class:`src.database.models.ScreeningPending`). They stay readable and searchable,
but an aggregate cannot yet know whether they are articles at all, so every aggregate that leaves quarantined articles
out leaves them out too, through :func:`not_counted` / :data:`NOT_COUNTED_SQL` / :func:`not_counted_article_ids`, and
says how many with :func:`not_counted_tally`. The quarantine-only forms stay for the readers whose subject IS the stamp
(the keyword counters, which the screening keeps as it always has, and the R101 transition). The pending subquery is
answered from the table's own primary key, so it costs one small index read like the quarantine one.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import Article

#: The same condition as raw SQL, for the readers that write their statements as text (``article_id`` is the
#: mention's column). Index-only: the subquery is answered from ``idx_article_quarantined`` alone, never an article row.
NOT_QUARANTINED_SQL = " AND article_id NOT IN (SELECT id FROM articles WHERE quarantined IS 1)"


#: :data:`NOT_QUARANTINED_SQL` plus the articles still queued for screening (R830): the slice every aggregate takes.
NOT_COUNTED_SQL = NOT_QUARANTINED_SQL + " AND article_id NOT IN (SELECT article_id FROM screening_pending)"  # nosec B608 # two module constants, never input


def quarantined_ids_select():
    """``SELECT id FROM articles WHERE quarantined IS 1``: the subquery every filter here uses."""
    return select(Article.id).where(Article.quarantined.is_(True))


def not_quarantined(article_id_column: Any):
    """The condition that keeps a row whose article is NOT quarantined. ``article_id_column`` is the
    column holding the article id: ``Article.id`` itself, or a mention's ``article_id``."""
    return article_id_column.not_in(quarantined_ids_select())


def quarantined_article_ids(session: Session) -> frozenset[int]:
    """Every quarantined article's id, read once (an index-only scan of ``idx_article_quarantined``)."""
    return frozenset(int(i) for (i,) in session.execute(quarantined_ids_select()))


def pending_ids_select():
    """``SELECT article_id FROM screening_pending``: the imported articles the screening has not reached (R830)."""
    from src.database.models import ScreeningPending

    return select(ScreeningPending.article_id)


def not_counted(article_id_column: Any):
    """The condition that keeps a row whose article an aggregate counts: not quarantined and not still queued for
    screening (R830). Same argument as :func:`not_quarantined`."""
    return article_id_column.not_in(quarantined_ids_select()) & article_id_column.not_in(pending_ids_select())


def not_counted_article_ids(session: Session) -> frozenset[int]:
    """Every article an aggregate leaves out (quarantined or still queued for screening), read once, for the DuckDB
    rollup builds."""
    return quarantined_article_ids(session) | frozenset(int(i) for (i,) in session.execute(pending_ids_select()))


def not_counted_tally(session: Session) -> dict[str, int]:
    """How many articles the aggregates leave out for a reason that will pass: ``not_screened`` (queued for the junk
    screening, R830). A surface says "N articles not screened yet" while it is above 0 and nothing at 0. Never raises:
    a store that cannot be read says nothing it cannot back (an empty dict)."""
    from sqlalchemy import func

    from src.database.models import ScreeningPending

    try:
        n = int(session.execute(select(func.count()).select_from(ScreeningPending)).scalar() or 0)
    except Exception:  # noqa: BLE001 - an unreadable count is not a zero: say nothing
        return {}
    return {"not_screened": n}


def pending_keyword_contributions(session: Session, keyword_ids: Any = None) -> dict[int, tuple[int, int]]:
    """``keyword id -> (mentions, articles)`` that the articles still queued for screening put into the maintained keyword
    counters (R830). The counters are kept as the screening has always kept them, so they include an unscreened article
    until it is judged; a reader that serves the counters as an aggregate subtracts this at query time, which reads only
    the queued articles' own mention rows (through the index on ``article_id``). A quarantined article left the counters
    when it was stamped, so it is not subtracted twice. ``keyword_ids`` narrows the read. Empty when nothing is queued."""
    from sqlalchemy import func

    from src.database.derived_views import KeywordMentionRead

    q = select(
        KeywordMentionRead.keyword_id,
        func.sum(KeywordMentionRead.count),
        func.count(func.distinct(KeywordMentionRead.article_id)),
    ).where(
        KeywordMentionRead.article_id.in_(pending_ids_select()),
        KeywordMentionRead.article_id.not_in(quarantined_ids_select()),
    )
    if keyword_ids is not None:
        ids = sorted({int(i) for i in keyword_ids})
        if not ids:
            return {}
        out: dict[int, tuple[int, int]] = {}
        for i in range(0, len(ids), 900):
            for kid, men, arts in session.execute(
                q.where(KeywordMentionRead.keyword_id.in_(ids[i : i + 900])).group_by(KeywordMentionRead.keyword_id)
            ):
                out[int(kid)] = (int(men or 0), int(arts or 0))
        return out
    return {
        int(kid): (int(men or 0), int(arts or 0))
        for kid, men, arts in session.execute(q.group_by(KeywordMentionRead.keyword_id))
    }


def any_pending(session: Session) -> bool:
    """Whether any article is still queued for screening (one primary-key probe). A store that cannot say reads as
    False, so a reader that cannot ask keeps its old answer."""
    try:
        return session.execute(pending_ids_select().limit(1)).first() is not None
    except Exception:  # noqa: BLE001 - a store without the table has nothing queued
        return False


def split_not_screened(session: Session, ids: list[int]) -> tuple[list[int], int]:
    """``(counted, n)`` for a search-fed aggregate (R830 group D): the ids an aggregate counts, in their order, and how
    many of ``ids`` are still queued for screening. The list of results keeps every id; only the figure built over
    them leaves the queued ones out and says how many with "N of these results not counted yet". One primary-key read
    of the queue for the ids given (they are already bounded to the safe IN size by the caller); nothing queued, or a
    store without the queue, costs one probe and returns ``ids`` whole."""
    if not ids or not any_pending(session):
        return list(ids), 0
    from src.database.models import ScreeningPending

    queued: set[int] = set()
    for i in range(0, len(ids), 900):
        queued.update(
            int(a)
            for (a,) in session.execute(
                select(ScreeningPending.article_id).where(ScreeningPending.article_id.in_(ids[i : i + 900]))
            )
        )
    if not queued:
        return list(ids), 0
    return [i for i in ids if i not in queued], len({i for i in ids if i in queued})
