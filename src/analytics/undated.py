"""How many of a chart's articles have no date of their own, and how many of those carry the feed's (row 459, R853).

Open Omniscience - Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two kinds of article time series exist, and an article whose page gave no publication date reaches them differently:

* ``KIND_COLLECTION`` (the keyword-index series: ``/api/insights/trend``, the corpus-algebra trend, the trending cards).
  The index stamps every article ``observed_on = (published_at or created_at).date()`` (``src/analytics/store.py``), so an
  article with no date of its own is drawn at the day the app COLLECTED it, a date that is not the article's.
* ``KIND_LEFT_OUT`` / ``KIND_LEFT_OUT_FIGURE`` (the series read straight off ``published_at``: the price correlation and
  the daily-volume anomalies). An article with no date of its own is simply not in them.

R853 (the ruling on row 459): each such chart states, under it, how many of ITS articles are in that position (``n``) and
how many of those carry a date the source's feed gave the item (``feed_dated``, row 457's ``feed_entry_published_at``),
counted over exactly what the chart shows: the same filters, window and article set, never a corpus-wide figure under a
filtered chart. Nothing plotted changes; this only says what the picture already holds.

The blocks are read the way the rest of the keyword aggregates are, so the cost stays where it was measured:

* ``n`` is decided from ``idx_article_published_at`` alone. ``published_at IS NULL`` is a seek in that index and the index
  carries the rowid, so ``<id> IN (SELECT id FROM articles WHERE published_at IS NULL)`` never brings an article row
  through the SQLCipher codec (``published_at`` sits after ``content`` in the record, so a row read would walk the
  content's overflow pages: the recorded codec trap, ``src/analytics/quarantine_scope.py``).
* ``feed_dated`` has no index and needs the row, so it is read only while ``n`` is at most :data:`FEED_COUNT_CAP`. Over
  that it is ``None`` with ``feed_dated_reason = "over_cap"``, which the chart words as "not counted", never as 0.
* Any read that fails gives ``n = None`` ("not counted"): a count that could not be taken is said, never guessed.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select

from src.database.maintenance import StatementTimeout
from src.database.models import Article
from src.monitoring.secret_scrub import log_failure

logger = logging.getLogger(__name__)

KIND_COLLECTION = "collection"  # drawn at the collection date
KIND_LEFT_OUT = "left_out"  # left out of the chart
KIND_LEFT_OUT_FIGURE = "left_out_figure"  # left out of a figure computed from a daily series (the correlation)
KINDS = (KIND_COLLECTION, KIND_LEFT_OUT, KIND_LEFT_OUT_FIGURE)

#: The most undated articles whose feed date is read row by row (see the module docstring).
FEED_COUNT_CAP = 2000

#: Bound-variable chunk for explicit id lists, the same bound ``src/analytics/queries.py`` uses (``_IN_CHUNK``).
_CHUNK = 900

#: The sentence the chart line carries on hover, per kind (English here; the page keys and translates it).
METHOD = {
    KIND_COLLECTION: (
        "The app dates each article by the date its page gives. An article whose page gave none is drawn at the day "
        "the app collected it, which is not the day it was published. This counts those articles among the ones this "
        "chart shows, and how many of them carry a date the source's feed gave the item."
    ),
    KIND_LEFT_OUT: (
        "This chart dates each article by the date its page gives, so an article whose page gave none is not in it. "
        "This counts those articles under the same filters, and how many of them carry a date the source's feed gave "
        "the item."
    ),
    KIND_LEFT_OUT_FIGURE: (
        "This figure dates each article by the date its page gives, so an article whose page gave none is not in it. "
        "This counts those articles under the same filters, and how many of them carry a date the source's feed gave "
        "the item."
    ),
}


def undated_ids_select():
    """``SELECT id FROM articles WHERE published_at IS NULL``: answered from ``idx_article_published_at`` alone."""
    return select(Article.id).where(Article.published_at.is_(None))


def _block(kind: str, n: int | None, feed_dated: int | None, reason: str | None) -> dict[str, Any]:
    return {"kind": kind, "n": n, "feed_dated": feed_dated, "feed_dated_reason": reason, "method": METHOD[kind]}


def not_counted_block(kind: str) -> dict[str, Any]:
    """The block for a chart whose count could not be taken: says so, never 0."""
    return _block(kind, None, None, "not_counted")


def _feed_dated(session, ids: list[int]) -> int:
    total = 0
    for i in range(0, len(ids), _CHUNK):
        chunk = ids[i : i + _CHUNK]
        total += int(
            session.query(func.count(Article.id))
            .filter(Article.id.in_(chunk), Article.feed_entry_published_at.isnot(None))
            .scalar()
            or 0
        )
    return total


def _from_undated_ids(session, kind: str, ids: list[int], *, over_cap_n: int | None = None) -> dict[str, Any]:
    if over_cap_n is not None:
        return _block(kind, over_cap_n, None, "over_cap")
    return _block(kind, len(ids), _feed_dated(session, ids) if ids else 0, None)


def undated_in_select(session, id_select, *, kind: str) -> dict[str, Any]:
    """The block for a chart whose article set is ``id_select``, a SELECT of ONE article-id column carrying every filter
    the chart's own query applies (keyword, window, country, quarantine and screening slice)."""
    try:
        sub = id_select.subquery()
        col = list(sub.c)[0]
        undated = select(col).where(col.in_(undated_ids_select())).distinct()
        ids = [int(r[0]) for r in session.execute(undated.limit(FEED_COUNT_CAP + 1))]
        if len(ids) > FEED_COUNT_CAP:
            n = int(session.execute(select(func.count()).select_from(undated.subquery())).scalar() or 0)
            return _from_undated_ids(session, kind, [], over_cap_n=n)
        return _from_undated_ids(session, kind, ids)
    except StatementTimeout:  # the request's deadline is the caller's to handle, never a "not counted" to cache
        raise
    except Exception as exc:  # noqa: BLE001 - a count that cannot be taken is "not counted", never a broken chart
        log_failure(logger, "undated count failed", exc, level=logging.WARNING)
        return not_counted_block(kind)


def undated_in_ids(session, article_ids: Iterable[int], *, kind: str) -> dict[str, Any]:
    """The block for a chart drawn from an explicit article-id list (already sliced the way the chart is)."""
    try:
        wanted = sorted({int(i) for i in article_ids})
        found: list[int] = []
        for i in range(0, len(wanted), _CHUNK):
            chunk = wanted[i : i + _CHUNK]
            found.extend(
                int(r[0])
                for r in session.execute(
                    select(Article.id).where(Article.id.in_(chunk), Article.id.in_(undated_ids_select()))
                )
            )
        if len(found) > FEED_COUNT_CAP:
            return _from_undated_ids(session, kind, [], over_cap_n=len(found))
        return _from_undated_ids(session, kind, found)
    except StatementTimeout:  # the request's deadline is the caller's to handle, never a "not counted" to cache
        raise
    except Exception as exc:  # noqa: BLE001 - see undated_in_select
        log_failure(logger, "undated count failed", exc, level=logging.WARNING)
        return not_counted_block(kind)


def _feed_dated_ids(session, ids: list[int]) -> set[int]:
    found: set[int] = set()
    for i in range(0, len(ids), _CHUNK):
        chunk = ids[i : i + _CHUNK]
        found.update(
            int(r[0])
            for r in session.execute(
                select(Article.id).where(Article.id.in_(chunk), Article.feed_entry_published_at.isnot(None))
            )
        )
    return found


def undated_by_bucket(session, date_id_select, *, kind: str, bucket_key) -> dict[str, Any]:
    """The block for a chart drawn from ``date_id_select`` (a SELECT of ``(observed_on, article_id)`` carrying every
    filter the chart applies), plus ``by_bucket``: ``[{date, n, feed_dated}]`` per chart bucket (``bucket_key(day)``
    gives the chart's own key), so a chart the reader narrows to a time range can state the count for that range alone.
    ``by_bucket`` is present only while the whole set is within :data:`FEED_COUNT_CAP`; past it the block carries ``n``
    over the whole series and no per-bucket split (the page then says the range is not counted)."""
    try:
        sub = date_id_select.subquery()
        day_col, id_col = list(sub.c)[:2]
        undated = select(day_col, id_col).where(id_col.in_(undated_ids_select())).distinct()
        rows = session.execute(undated.limit(FEED_COUNT_CAP + 1)).all()
        ids = sorted({int(a) for _, a in rows})
        if len(rows) > FEED_COUNT_CAP:
            n = int(
                session.execute(select(func.count(func.distinct(undated.subquery().c[1])))).scalar() or 0
            )
            return _block(kind, n, None, "over_cap")
        feed = _feed_dated_ids(session, ids)
        per: dict[str, tuple[set[int], set[int]]] = {}
        for day, aid in rows:
            key = bucket_key(day)
            got = per.setdefault(key, (set(), set()))
            got[0].add(int(aid))
            if int(aid) in feed:
                got[1].add(int(aid))
        out = _block(kind, len(ids), len(feed), None)
        out["by_bucket"] = [{"date": k, "n": len(a), "feed_dated": len(f)} for k, (a, f) in sorted(per.items())]
        return out
    except StatementTimeout:  # the request's deadline is the caller's to handle, never a "not counted" to cache
        raise
    except Exception as exc:  # noqa: BLE001 - see undated_in_select
        log_failure(logger, "undated count failed", exc, level=logging.WARNING)
        return not_counted_block(kind)


def undated_pairs(session, pair_select, *, limit: int) -> list[tuple[int, int]] | None:
    """``(group, article_id)`` pairs of a two-column SELECT whose article is undated, or None past ``limit`` pairs or on
    a failed read. For the trending cards, where one window read serves every term on it."""
    try:
        sub = pair_select.subquery()
        group_col, id_col = list(sub.c)[:2]
        rows = session.execute(
            select(group_col, id_col).where(id_col.in_(undated_ids_select())).distinct().limit(limit + 1)
        ).all()
    except StatementTimeout:  # the request's deadline is the caller's to handle, never a "not counted" to cache
        raise
    except Exception as exc:  # noqa: BLE001 - see undated_in_select
        log_failure(logger, "undated pair read failed", exc, level=logging.WARNING)
        return None
    if len(rows) > limit:
        return None
    return [(int(g), int(a)) for g, a in rows]


def block_for_undated_set(session, kind: str, undated_ids: set[int]) -> dict[str, Any]:
    """The block for a set of undated article ids already found (the trending cards' per-term sets)."""
    try:
        if len(undated_ids) > FEED_COUNT_CAP:
            return _from_undated_ids(session, kind, [], over_cap_n=len(undated_ids))
        return _from_undated_ids(session, kind, sorted(undated_ids))
    except StatementTimeout:  # the request's deadline is the caller's to handle, never a "not counted" to cache
        raise
    except Exception as exc:  # noqa: BLE001 - see undated_in_select
        log_failure(logger, "undated feed count failed", exc, level=logging.WARNING)
        return not_counted_block(kind)
