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
#: How many of the window's most-changed pages the suggestions read; the payload says so.
CANDIDATE_ROWS_READ: int = 400

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


def _parse(external_id: str) -> Any:
    from src.wiki.identity import parse_external_id

    return parse_external_id(external_id)


def divergence_candidates(
    lane: Any, *, window_days: int = DEFAULT_WINDOW_DAYS, now: datetime | None = None,
    top_n: int = CANDIDATES_N,
) -> dict[str, Any]:
    """Wikidata items worth opening: those of the pages this machine recorded most changes for.

    Reads the window's ``CANDIDATE_ROWS_READ`` most-changed pages (the payload says so: an item
    whose pages fall below that line is undercounted or absent) and keeps the ones the walk
    linked to an item, with how many editions the walk has found that item in. A title-keyed
    row (before Q715, or an event with no page id) is resolved through the walk's own
    (edition, title). A suggestion, in the order of the change count the lane made itself;
    nothing ranks items against each other.
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
        .limit(CANDIDATE_ROWS_READ)
    ).all()
    pairs: list[tuple[str, int]] = []
    changes: dict[tuple[str, int], int] = {}
    legacy: dict[tuple[str, str], int] = {}  # (edition, title) -> changes: rows written before Q715
    for external_id, n in rows:
        try:
            ident = _parse(str(external_id))
        except ValueError:
            continue
        if ident.page_id is not None:
            pair = (ident.wiki, int(ident.page_id))
            pairs.append(pair)
            changes[pair] = changes.get(pair, 0) + int(n)
        elif ident.title:
            legacy[(ident.wiki, ident.title)] = int(n)
    if legacy:
        # A title-keyed row names its page only through the walk's own (edition, title).
        for e, p, t in lane.execute(
            select(WikiWalkPage.edition, WikiWalkPage.page_id, WikiWalkPage.title).where(
                tuple_(WikiWalkPage.edition, WikiWalkPage.title).in_(list(legacy))
            )
        ).all():
            pair = (str(e), int(p))
            if pair not in changes:
                pairs.append(pair)
            changes[pair] = changes.get(pair, 0) + legacy[(str(e), str(t))]
    if not pairs:
        return {"items": [], "n": 0, "window_days": window_days, "read_top": CANDIDATE_ROWS_READ}
    qids: dict[tuple[str, int], str] = {
        (str(e), int(p)): str(q)
        for e, p, q in lane.execute(
            select(WikiWalkPage.edition, WikiWalkPage.page_id, WikiWalkPage.qid).where(
                tuple_(WikiWalkPage.edition, WikiWalkPage.page_id).in_(pairs),
                WikiWalkPage.qid.is_not(None),
            )
        ).all()
    }
    pairs.sort(key=lambda pr: (-changes[pr], pr))  # most-changed first, deterministic on ties
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
        "read_top": CANDIDATE_ROWS_READ,
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
    changes are the lane's own count of what the live stream recorded for the page in the
    window, ``None`` (unknown, not 0) for an edition the stream has recorded nothing for. The spread is shown as the smallest and the largest size with the editions that hold
    them -- never as a ratio.
    """
    from src.versioned.models import VersionedChange
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

    # The stream records EVERY change it is sent for a followed edition, with or without a
    # followed-page entity, under the id form (or, before Q715 and for an event with no page
    # id, the title form). So a page's change count is known whenever the stream has recorded
    # anything for its edition; a recorded zero is then a real zero.
    ids: dict[str, str] = {}
    legacy: dict[str, str] = {}
    for edition, page in pages.items():
        ids[edition] = external_id_for(edition, int(page.page_id))
        legacy[edition] = legacy_external_id_for(edition, str(page.title))
    names = [*ids.values(), *legacy.values()]
    stream_seen = {
        str(f).removeprefix("stream:")
        for f in lane.execute(
            select(VersionedChange.feed).where(VersionedChange.feed.in_([f"stream:{e}" for e in pages])).distinct()
        ).scalars()
    } if pages else set()
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
            recorded = edition in stream_seen
            rows.append(
                {
                    "edition": edition,
                    "state": STATE_FOUND,
                    "page_id": int(page.page_id),
                    "title": str(page.title),
                    "length_bytes": page.length_bytes,
                    "read_at": page.walked_at.isoformat() if page.walked_at else None,
                    "stream_recorded": recorded,
                    "changes_in_window": (
                        int(counts.get(ids[edition], 0)) + int(counts.get(legacy[edition], 0)) if recorded else None
                    ),
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
            "for the page. Sizes are shown as they are, each beside its own "
            "edition; nothing is derived from them."
        ),
        "caveat": (
            "A size is read once, when the walk reached the page, so it can be older than the "
            "edit count beside it. A missing edition is a statement about the walk, named in "
            "each row, before it is a statement about Wikipedia. Changes are the ones the live "
            "stream recorded on this machine; for an edition it has recorded nothing for, the "
            "count is unknown, not zero. "
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
            "AND a.source_id NOT IN (SELECT id FROM sources WHERE lower(domain) = 'wikipedia.org' OR lower(domain) LIKE '%.wikipedia.org') "
            "AND a.quarantined IS NOT 1"
        ),
        {"q": match, "s": start.isoformat(" "), "e": end.isoformat(" ")},
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
    skipped = 0      # the deadline ran out before this row
    unsearchable = 0  # the title has no words the index can match (a bare "-"): not a timeout
    for r in rows[:top_n]:
        title = str(r["title"]).replace('"', " ").strip()
        counted: dict[str, Any] = {"press_day": None, "press_7d": None, "not_counted": None}
        match = build_match(f'"{title}"', variants=query_variants) if title else None
        if match is None:
            unsearchable += 1
            counted["not_counted"] = "unsearchable"
        elif monotonic() - started > deadline_s:
            skipped += 1
            counted["not_counted"] = "time"
        else:
            counted = {
                "press_day": _press_count(corpus, match, day, end),
                "press_7d": _press_count(corpus, match, start7, end),
                "not_counted": None,
            }
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
        "unsearchable": unsearchable,
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
