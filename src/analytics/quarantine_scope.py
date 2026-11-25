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

import contextlib
import threading
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


#: R832 (row 421): the imported articles the re-index has not finished, as ONE reason beside "not screened". An article of a
#: ``merged`` import (``merged_rows``) still owes the re-index while either analysis stamp of the current engine is missing (the
#: same test as the backlog, ``src/backup/merge.py`` ``_BACKLOG_SQL``). An article that is quarantined (a stand-in is) or still
#: queued for screening is counted under that reason, never also here, so the reasons never name one article twice: the
#: screening wins, because an aggregate leaves a queued article out whatever its analysis holds. Query time only: nothing is
#: written. The queue subquery is index-only (the queue's primary key). The article itself is joined: ``merged_rows`` has no
#: cascade, so an imported article deleted while its import is still ``merged`` keeps its row there, and it is not an article
#: the corpus holds (the re-index counts it as absent, ``_BATCH_ABSENT_SQL``), so it is never counted here.
_NOT_ANALYSED_FROM = (
    " FROM merge_batches b"
    " JOIN merged_rows m ON m.batch_id = b.id AND m.table_name = 'articles'"
    " JOIN articles a ON a.id = m.row_id"
    " LEFT JOIN article_index_stamps st ON st.article_id = m.row_id AND st.engine IN (:engine, :kw_legacy)"
    " LEFT JOIN article_www_stamps ws ON ws.article_id = m.row_id AND ws.engine = :www_engine"
    " WHERE b.status = :s AND (st.article_id IS NULL OR ws.article_id IS NULL)"
    " AND a.quarantined IS NOT 1"
    " AND m.row_id NOT IN (SELECT article_id FROM screening_pending)"
)
_NOT_ANALYSED_SQL = "SELECT COUNT(DISTINCT m.row_id)" + _NOT_ANALYSED_FROM
#: Whether any import is still listed as merged: one probe, so a corpus with no import in flight pays nothing more.
_ANY_MERGED_SQL = "SELECT 1 FROM merge_batches WHERE status = :s LIMIT 1"
#: How long the whole-store count is reused by the surfaces that poll it (as the backlog's own cache, ``api/jobs.py``).
_NOT_ANALYSED_TTL_S = 30.0
_not_analysed_cache: dict[str, Any] = {"at": None, "value": None, "store": None, "failed": False}
#: One whole-store count at a time: two polls that both miss the cache would otherwise each scan every merged row at once.
_not_analysed_lock = threading.Lock()


def _not_analysed_params() -> dict[str, str]:
    """The stamp identities the backlog reads (an identity that cannot be computed equals no stamp, so every article of a merged
    import counts as owed: overstated, never hidden), and the ``merged`` status."""
    from src.backup.merge import _STATUS_MERGED, _backlog_engines, _backlog_www_engine

    engine, legacy = _backlog_engines()
    return {"engine": engine, "kw_legacy": legacy, "www_engine": _backlog_www_engine(), "s": _STATUS_MERGED}


def not_analysed_count(session: Session) -> int:
    """How many articles of the corpus the re-index has not finished (R832), disjoint from the quarantined and the not-screened
    ones. Raises when the store cannot be read (the caller says nothing then, never 0). Reused for ``_NOT_ANALYSED_TTL_S``,
    and so is a failure: a read that failed is not tried again by every poll inside that time (it raises again, never 0)."""
    import time

    from sqlalchemy import text

    try:  # the store it was read from: a cached count is never served for another one (a swap, a second engine)
        bind = session.get_bind()
        store = (id(bind), str(getattr(bind, "url", "")))
    except Exception:  # noqa: BLE001 - no store to name: never served from the cache
        store = None

    def _cached() -> int | None:
        at = _not_analysed_cache["at"]
        if store is None or at is None or time.monotonic() - at > _NOT_ANALYSED_TTL_S or _not_analysed_cache["store"] != store:
            return None
        if _not_analysed_cache["failed"]:
            raise RuntimeError("the not-analysed count could not be read")
        return None if _not_analysed_cache["value"] is None else int(_not_analysed_cache["value"])

    hit = _cached()
    if hit is not None:
        return hit
    with _not_analysed_lock:
        hit = _cached()  # another poll may have filled it while this one waited
        if hit is not None:
            return hit
        try:
            params = _not_analysed_params()
            if session.execute(text(_ANY_MERGED_SQL), {"s": params["s"]}).first() is None:
                n = 0
            else:
                n = int(session.execute(text(_NOT_ANALYSED_SQL), params).scalar() or 0)
        except Exception:
            if store is not None:
                _not_analysed_cache.update(at=time.monotonic(), value=None, store=store, failed=True)
            raise
        if store is not None:
            _not_analysed_cache.update(at=time.monotonic(), value=n, store=store, failed=False)
        return n


def count_not_analysed(session: Session, ids: Any) -> int | None:
    """How many of ``ids`` the re-index has not finished (R832), for a figure built over a search's results: the figure counts
    them, but maybe only in part, so it says how many beside "N of these results not counted yet". Pass the ids the figure
    COUNTS (after :func:`split_not_screened`); a queued or quarantined id is never counted here either. One probe when no
    import is in flight; otherwise lookups by ``ix_merged_rows_lookup``, 900 ids at a time. None when it cannot be read."""
    from sqlalchemy import text

    ids = sorted({int(i) for i in (ids or [])})
    if not ids:
        return 0
    try:
        params = _not_analysed_params()
        if session.execute(text(_ANY_MERGED_SQL), {"s": params["s"]}).first() is None:
            return 0
        n = 0
        for i in range(0, len(ids), 900):
            chunk = ids[i : i + 900]
            marks = ", ".join(f":i{k}" for k in range(len(chunk)))
            stmt = _NOT_ANALYSED_SQL + f" AND m.row_id IN ({marks})"  # nosec B608 # bound parameter names only, never input
            n += int(session.execute(text(stmt), {**params, **{f"i{k}": v for k, v in enumerate(chunk)}}).scalar() or 0)
        return n
    except Exception:  # noqa: BLE001 - an unreadable count is not a zero: the figure says nothing
        return None


def with_not_analysed(payload: dict, session: Session, counted_ids: Any) -> dict:
    """Set ``payload["not_analysed_yet"]`` for a figure built from the analysis (keywords, places, people, dates, sentiment)
    over ``counted_ids`` (R832): how many of them the re-index has not finished, so the figure may count them only in part.
    Left out when it cannot be read (never 0 for "unknown"). Returns ``payload``."""
    n = count_not_analysed(session, counted_ids)
    if n is not None:
        payload["not_analysed_yet"] = n
    return payload


def not_counted_tally(session: Session) -> dict[str, int]:
    """How many articles the aggregates leave out, or count only in part, for a reason that will pass: ``not_screened``
    (queued for the junk screening, R830) and ``not_analysed`` (the re-index has not finished them, R832; never also counted
    as not screened or quarantined). A surface says "N articles not screened yet" / "N articles not analysed yet" while
    each is above 0 and nothing at 0. Never raises: each count that cannot be read is absent on its own (an empty dict when
    neither can)."""
    from sqlalchemy import func

    from src.database.models import ScreeningPending

    out: dict[str, int] = {}
    # A queued article that is already quarantined (a restore can bring one) is counted as quarantined, never
    # also as "not screened yet", so a breakdown never names one article twice. An unreadable count is not a zero.
    with contextlib.suppress(Exception):
        out["not_screened"] = int(session.execute(
            select(func.count()).select_from(ScreeningPending).where(not_quarantined(ScreeningPending.article_id))
        ).scalar() or 0)
    # R832: the second reason, disjoint from the first (``not_analysed_count``); absent when it cannot be read, never 0.
    with contextlib.suppress(Exception):
        out["not_analysed"] = not_analysed_count(session)
    return out


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
