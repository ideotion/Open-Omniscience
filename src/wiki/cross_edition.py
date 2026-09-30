"""Q712's analytics 4 and 5, as COUNTS over rows this machine holds. No verdicts, no blends.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q712 = a confirms five analytics in an order: edit velocity, contested pages, newly created
pages (``analytics.py``, 0.4) and then these two (0.5, slice S05-06 S4):

4. **Divergence** -- for ONE Wikidata item, what each language edition holds: does it have a
   page, how large is it, how many changes did this machine record for it in the window.
5. **Attention against press coverage** -- for the pages the source ranked highest on its
   latest published day, the source's own view count beside how many articles of THIS
   corpus mention the title.

EVERY NUMBER IS EITHER THE SOURCE'S, NAMED AS THEIRS, OR A COUNT THIS MODULE MADE. Nothing is
normalised, ranked against a baseline or folded with anything else: a page being twice as
long in one edition is shown as two sizes, not as a ratio, and a page with many views and few
articles is shown as those two numbers, never as a gap, a lead or a score.

WHAT ABSENCE MEANS HERE IS THE HARD PART. An edition with no row for the item has FOUR
distinct causes and they must not read alike: the walk never ran there, the walk is part-way
through it, the walk finished and found no page linked to the item, or the item is not a
valid one. The answer names which, with the walk's own counters, because "not found" from a
walk that has read 3% of an edition is a statement about the walk and not about the edition.
A page the stream does not follow has no recorded changes, which is UNKNOWN and is reported
as ``None``, never as 0 -- a 0 reads as "nobody edited it".

NO PER-PAGE VIEW HISTORY IS STORED. The lane keeps the source's latest published top list per
edition (``wiki.pageviews.top.<edition>``, refreshed daily and overwritten) -- its first
fifty rows with their view counts. So analytic 5 is ONE DAY's cross-section of that top list,
not a series, and says so: a time series would need the list kept daily, which is a storage
decision nobody has made. The coverage it sets beside each page is counted for that same UTC
day and for the seven days ending on it.

READS LOCAL ROWS, TOUCHES NO NETWORK.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text, tuple_

DEFAULT_WINDOW_DAYS: int = 7

#: How many suggested items the picker offers. A bound on a list, never on a count.
CANDIDATES_N: int = 20

#: Rows of the source's top list kept in the key-value store (``service.py``); the most this
#: analytic can read, stated so a caller never infers the cap from a response's length.
TOP_ROWS_STORED: int = 50

#: Seconds the attention read may spend counting press coverage before it stops and says
#: how many rows it skipped. A page whose count was not made is reported as not made.
ATTENTION_DEADLINE_S: float = 8.0

_QID = re.compile(r"^Q[1-9][0-9]{0,11}$")

#: The four reasons an edition has no row, named once so the UI translates tokens, not prose.
STATE_FOUND = "found"
STATE_NOT_WALKED = "walk-never-ran"
STATE_WALK_INCOMPLETE = "walk-incomplete"
STATE_NONE_AFTER_WALK = "none-after-complete-walk"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def normalise_qid(value: Any) -> str | None:
    """``q42`` / `` Q42 `` -> ``Q42``; anything that is not a Wikidata item id -> ``None``."""
    if not isinstance(value, str):
        return None
    v = value.strip().upper()
    return v if _QID.match(v) else None


def _edition_of_external_id(external_id: str) -> tuple[str, int | None]:
    from src.wiki.identity import parse_external_id

    ident = parse_external_id(external_id)
    return ident.wiki, ident.page_id


def divergence_candidates(
    lane: Any, *, window_days: int = DEFAULT_WINDOW_DAYS, now: datetime | None = None,
    top_n: int = CANDIDATES_N,
) -> dict[str, Any]:
    """Wikidata items worth opening: those of the pages this machine recorded most changes for.

    Reads the most-changed followed pages of the window and keeps the ones the walk linked to
    an item, with how many editions the walk has found that item in. A suggestion, in the
    order of the change count the lane made itself; nothing ranks items against each other.
    """
    from src.versioned.models import VersionedChange
    from src.wiki.lane_models import WikiWalkPage

    at = now or _utcnow()
    start = (at - timedelta(days=window_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = lane.execute(
        select(VersionedChange.external_id, func.count(VersionedChange.id))
        .where(VersionedChange.recorded_at >= start, VersionedChange.external_id.is_not(None))
        .group_by(VersionedChange.external_id)
        .order_by(func.count(VersionedChange.id).desc(), VersionedChange.external_id)
        .limit(400)
    ).all()
    pairs: list[tuple[str, int]] = []
    changes: dict[tuple[str, int], int] = {}
    for external_id, n in rows:
        try:
            edition, page_id = _edition_of_external_id(str(external_id))
        except ValueError:
            continue
        if page_id is None:
            continue
        pairs.append((edition, page_id))
        changes[(edition, page_id)] = int(n)
    if not pairs:
        return {"items": [], "n": 0, "window_days": window_days}
    qids: dict[tuple[str, int], str] = {
        (str(e), int(p)): str(q)
        for e, p, q in lane.execute(
            select(WikiWalkPage.edition, WikiWalkPage.page_id, WikiWalkPage.qid).where(
                tuple_(WikiWalkPage.edition, WikiWalkPage.page_id).in_(pairs),
                WikiWalkPage.qid.is_not(None),
            )
        ).all()
    }
    order: list[str] = []
    changed: dict[str, int] = {}
    for pair in pairs:  # already most-changed first
        qid = qids.get(pair)
        if qid is None:
            continue
        if qid not in changed:
            order.append(qid)
        changed[qid] = changed.get(qid, 0) + changes[pair]
    order = order[:top_n]
    editions_found = {
        str(q): int(n)
        for q, n in lane.execute(
            select(WikiWalkPage.qid, func.count(func.distinct(WikiWalkPage.edition)))
            .where(WikiWalkPage.qid.in_(order))
            .group_by(WikiWalkPage.qid)
        ).all()
    } if order else {}
    return {
        "items": [
            {"qid": q, "changes_in_window": changed[q], "editions_found": editions_found.get(q, 0)}
            for q in order
        ],
        "n": len(order),
        "window_days": window_days,
    }


def divergence(
    lane: Any,
    qid: str,
    *,
    editions: tuple[str, ...] | list[str],
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Analytic 4: what each edition holds for ONE Wikidata item, side by side.

    One row per edition the operator follows (and any other edition the walk found the item
    in). Sizes are the editions' own ``info.length`` read by the walk, in bytes of wikitext;
    changes are the lane's own count for a page the stream follows, ``None`` for one it does
    not. The spread is shown as the smallest and the largest size with the editions that hold
    them -- never as a ratio.
    """
    from src.versioned.models import VersionedChange, VersionedEntity
    from src.wiki.identity import external_id_for, legacy_external_id_for
    from src.wiki.lane_models import WikiWalkCursor, WikiWalkPage

    item = normalise_qid(qid)
    if item is None:
        return {"measured": False, "reason": "qid-invalid", "qid": str(qid)[:40]}
    at = now or _utcnow()
    start = (at - timedelta(days=window_days)).replace(hour=0, minute=0, second=0, microsecond=0)

    pages = {
        str(p.edition): p
        for p in lane.execute(select(WikiWalkPage).where(WikiWalkPage.qid == item)).scalars()
    }
    cursors = {str(c.edition): c for c in lane.execute(select(WikiWalkCursor)).scalars()}
    wanted = list(dict.fromkeys([*editions, *sorted(pages)]))

    # Which of the found pages the stream follows, by either identity form (a lane written
    # before Q715 keyed entities on the title).
    ids: dict[str, str] = {}
    legacy: dict[str, str] = {}
    for edition, page in pages.items():
        ids[edition] = external_id_for(edition, int(page.page_id))
        legacy[edition] = legacy_external_id_for(edition, str(page.title))
    names = [*ids.values(), *legacy.values()]
    followed_ids = (
        set(lane.execute(select(VersionedEntity.external_id).where(VersionedEntity.external_id.in_(names))).scalars())
        if names
        else set()
    )
    counts = (
        dict(
            lane.execute(
                select(VersionedChange.external_id, func.count(VersionedChange.id))
                .where(VersionedChange.external_id.in_(names), VersionedChange.recorded_at >= start)
                .group_by(VersionedChange.external_id)
            ).all()
        )
        if names
        else {}
    )

    rows: list[dict[str, Any]] = []
    for edition in wanted:
        cursor = cursors.get(edition)
        walk = (
            {
                "pages_seen": int(cursor.pages_seen or 0),
                "edition_articles": cursor.edition_articles,
                "completed_at": cursor.completed_at.isoformat() if cursor.completed_at else None,
            }
            if cursor is not None
            else None
        )
        page = pages.get(edition)
        if page is not None:
            keys = [k for k in (ids[edition], legacy[edition]) if k in followed_ids]
            rows.append(
                {
                    "edition": edition,
                    "state": STATE_FOUND,
                    "page_id": int(page.page_id),
                    "title": str(page.title),
                    "length_bytes": page.length_bytes,
                    "read_at": page.walked_at.isoformat() if page.walked_at else None,
                    "followed": bool(keys),
                    "changes_in_window": sum(int(counts.get(k, 0)) for k in keys) if keys else None,
                    "walk": walk,
                }
            )
            continue
        if cursor is None:
            state = STATE_NOT_WALKED
        elif cursor.completed_at is None:
            state = STATE_WALK_INCOMPLETE
        else:
            state = STATE_NONE_AFTER_WALK
        rows.append({"edition": edition, "state": state, "walk": walk})

    sized = [r for r in rows if r["state"] == STATE_FOUND and r.get("length_bytes") is not None]
    smallest = min(sized, key=lambda r: (r["length_bytes"], r["edition"]), default=None)
    largest = max(sized, key=lambda r: (r["length_bytes"], r["edition"]), default=None)
    found = sum(1 for r in rows if r["state"] == STATE_FOUND)
    return {
        "measured": found > 0,
        "reason": None if found else "item-not-found",
        "qid": item,
        "window_days": window_days,
        "editions": rows,
        "n_editions": len(rows),
        "n_found": found,
        "n_sized": len(sized),
        "smallest": {"edition": smallest["edition"], "length_bytes": smallest["length_bytes"]} if smallest else None,
        "largest": {"edition": largest["edition"], "length_bytes": largest["length_bytes"]} if largest else None,
        "method": (
            "The page walk's rows that carry the Wikidata item (each edition's own size in bytes "
            "of wikitext, read when the walk reached the page), the walk's own counters for "
            "every edition without one, and the changes this machine recorded in the window "
            "for a page the stream follows. Sizes are shown as they are, each beside its own "
            "edition; nothing is derived from them."
        ),
        "caveat": (
            "A size is read once, when the walk reached the page, so it can be older than the "
            "edit count beside it. A missing edition is a statement about the walk, named in "
            "each row, before it is a statement about Wikipedia. Recorded changes exist only "
            "for pages the stream follows; for the others the count is unknown, not zero. "
            "Editions are separate articles, not translations of one text."
        ),
    }


def _press_count(corpus: Any, match: str, start: datetime, end: datetime) -> int:
    """Articles of the press corpus matching ``match`` and published in ``[start, end)``.

    The corpus's own Wikipedia-sourced articles are left out (a page's own text is not
    coverage of it), and so are articles the app judged not-an-article. An article with no
    publication date is not counted in either window: the date is the only thing placing it
    on the day.
    """
    row = corpus.execute(
        text(
            "SELECT count(*) FROM article_fts f JOIN articles a ON a.id = f.rowid "
            "WHERE article_fts MATCH :q AND a.published_at >= :s AND a.published_at < :e "
            "AND a.source_id NOT IN (SELECT id FROM sources WHERE domain LIKE '%.wikipedia.org') "
            "AND a.quarantined IS NOT 1"
        ),
        {"q": match, "s": start, "e": end},
    ).scalar()
    return int(row or 0)


def attention(
    corpus: Any,
    *,
    edition: str,
    top_n: int = TOP_ROWS_STORED,
    deadline_s: float = ATTENTION_DEADLINE_S,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Analytic 5: the source's most-viewed pages of its latest day beside this corpus's coverage.

    For each of the top rows (the source's rank and view count, as the source gave them) the
    number of press-corpus articles mentioning the title as a phrase, published on that UTC
    day and in the seven days ending on it. Two numbers in two units, side by side; co-occurrence,
    never causation, and never a gap between them.
    """
    from src.config.kv_store import kv_get_json
    from src.database.fts import build_match
    from src.database.fts_norm import query_variants
    from src.wiki.hotset import pageview_kv_key

    blob = kv_get_json(pageview_kv_key(edition)) or {}
    rows = [r for r in (blob.get("rows") or []) if isinstance(r, dict) and r.get("title")]
    try:
        day = datetime.strptime(str(blob.get("day")), "%Y-%m-%d").replace(tzinfo=None)
    except ValueError:
        day = None
    if not rows or day is None:
        return {"measured": False, "reason": "no-top-list-yet", "edition": edition}
    start7 = day - timedelta(days=6)
    end = day + timedelta(days=1)
    started = monotonic()
    out: list[dict[str, Any]] = []
    skipped = 0
    for r in rows[:top_n]:
        title = str(r["title"]).replace('"', " ").strip()
        counted: dict[str, Any] = {"press_day": None, "press_7d": None}
        match = build_match(f'"{title}"', variants=query_variants) if title else None
        if match is not None and monotonic() - started <= deadline_s:
            counted = {
                "press_day": _press_count(corpus, match, day, end),
                "press_7d": _press_count(corpus, match, start7, end),
            }
        else:
            skipped += 1
        out.append(
            {"rank": r.get("rank"), "title": str(r["title"]), "views": r.get("views"), **counted}
        )
    return {
        "measured": True,
        "edition": edition,
        "day": day.date().isoformat(),
        "rows": out,
        "n": len(out),
        "n_top_list": blob.get("n"),
        "rows_stored": TOP_ROWS_STORED,
        "skipped": skipped,
        "method": (
            "The source's own top-viewed list for its latest published UTC day (rank and view "
            "count as the source gave them; only the first fifty rows are stored), and for each "
            "title the number of press-corpus articles mentioning it as a phrase, published on "
            "that day and in the seven days ending on it. Wikipedia-sourced and quarantined "
            "articles are not counted."
        ),
        "caveat": (
            "One day's cross-section, not a series: the list is overwritten each day and no "
            "per-page view history is kept. Views count people opening a page; the article "
            "counts are this machine's corpus only, which is what it collected and not the "
            "press. A title can be ambiguous, renamed, or written differently in another "
            "language, and an undated article is in neither count. The two numbers sit side "
            "by side and are never combined or compared."
        ),
    }
