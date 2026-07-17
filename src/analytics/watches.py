"""The convergence WATCH engine (ruling 2026-06-17 #3, ON by default).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A *watch* is a saved local condition: an FTS query + a threshold + a recent window.
The engine re-evaluates every ENABLED watch after each scrape pass; when the corpus
gains enough NEW matching articles in the window, the watch FIRES — recording a
``WatchMatch`` (the browsable history) and surfacing a "watch" Lead card. The user can
enable / edit / delete each watch (the Watches view).

By ruling, deliberately MINIMAL and honest:
  * LOCAL-ONLY — no notifications, no network, no telemetry, no escalation tiers
    beyond the single Lead card. Evaluation reads the corpus and writes only the two
    local tables.
  * fires on a real COUNT crossing a USER-SET threshold — never a fabricated urgency
    or score; the Lead card states the count + the query, nothing inflated.
  * fires only on genuinely NEW evidence — ``last_seen_ids`` records the previous
    firing set so a watch never re-alarms on the same articles every pass.
  * the matcher reuses the SAME search the user sees (FTS5 ``search_ids``), so a watch
    means exactly what searching for its query means.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.database.models import Article, Watch, WatchMatch

# A matcher maps (session, query) -> the list of article ids matching the query, best
# first. Injectable so the firing logic is unit-testable without an FTS table.
Matcher = Callable[[Session, str], "list[int] | None"]

# Keep the stored "already reported" set bounded (one busy window's worth is plenty).
_MAX_SEEN = 500
# Chunk size for the Article.id IN(...) date lookup in _recent_matching (audit finding
# 2026-07-17): the default matcher (_fts_matcher -> search_ids) can return up to its own
# _MAX_CANDIDATES (20000, src/database/fts.py) -- well past SQLite's historical ~999
# bound-variable ceiling used everywhere else in this codebase (_IN_CHUNK/
# GRAPH_ARTICLE_CAP/_FTS_ID_CHUNK/_BULK_ID_CHUNK). A broad watch query would otherwise
# raise "too many SQL variables" on EVERY scrape pass, silently swallowed by
# evaluate_watches's per-watch try/except -- so the watch would simply never fire again,
# with no visible error to the user.
_IN_CHUNK = 900


def _fts_matcher(session: Session, query: str) -> list[int] | None:
    """The production matcher: FTS5 ids for ``query`` (None = no positive constraint)."""
    from src.database.fts import search_ids

    return search_ids(session, query)


def _id_list(blob: str | None) -> list[int]:
    if not blob:
        return []
    try:
        return [int(x) for x in json.loads(blob)]
    except (ValueError, TypeError):
        return []


def _loads_ids(blob: str | None) -> set[int]:
    return set(_id_list(blob))


# --------------------------------------------------------------------------- #
# CRUD (the Watches view: create / list / edit / enable-disable / delete)
# --------------------------------------------------------------------------- #
def create_watch(
    session: Session, *, name: str, query: str, threshold: int = 3, window_days: int = 7,
    enabled: bool = True,
) -> Watch:
    """Save a new watch. ``enabled`` defaults TRUE (the engine is ON by default, #3)."""
    name = (name or "").strip() or (query or "").strip()[:120] or "watch"
    if not (query or "").strip():
        raise ValueError("a watch needs a query condition")
    w = Watch(
        name=name[:120], query=query.strip(),
        threshold=max(1, int(threshold)), window_days=max(1, int(window_days)),
        enabled=bool(enabled),
    )
    session.add(w)
    session.flush()
    return w


def list_watches(session: Session, *, history_limit: int = 5) -> list[dict]:
    """Every watch with its recent firing history (the Watches panel data). No score."""
    out = []
    for w in session.execute(select(Watch).order_by(Watch.created_at.desc())).scalars():
        hist = (
            session.execute(
                select(WatchMatch).where(WatchMatch.watch_id == w.id)
                .order_by(WatchMatch.matched_at.desc()).limit(history_limit)
            ).scalars().all()
        )
        out.append({**_watch_dict(w), "history": [_match_dict(m) for m in hist]})
    return out


def _watch_dict(w: Watch) -> dict:
    return {
        "id": w.id, "name": w.name, "query": w.query,
        "threshold": w.threshold, "window_days": w.window_days, "enabled": bool(w.enabled),
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "last_evaluated_at": w.last_evaluated_at.isoformat() if w.last_evaluated_at else None,
        "last_matched_at": w.last_matched_at.isoformat() if w.last_matched_at else None,
    }


def _match_dict(m: WatchMatch) -> dict:
    return {
        "matched_at": m.matched_at.isoformat() if m.matched_at else None,
        "n_articles": m.n_articles, "new_articles": m.new_articles,
        "article_ids": _id_list(m.article_ids),
    }


def update_watch(session: Session, watch_id: int, **fields) -> Watch | None:
    """Edit a watch (name/query/threshold/window_days/enabled). Returns None if absent."""
    w = session.get(Watch, watch_id)
    if w is None:
        return None
    if "name" in fields and fields["name"]:
        w.name = str(fields["name"]).strip()[:120]
    if "query" in fields and str(fields["query"]).strip():
        w.query = str(fields["query"]).strip()
    if "threshold" in fields and fields["threshold"] is not None:
        w.threshold = max(1, int(fields["threshold"]))
    if "window_days" in fields and fields["window_days"] is not None:
        w.window_days = max(1, int(fields["window_days"]))
    if "enabled" in fields and fields["enabled"] is not None:
        w.enabled = bool(fields["enabled"])
    session.flush()
    return w


def delete_watch(session: Session, watch_id: int) -> bool:
    w = session.get(Watch, watch_id)
    if w is None:
        return False
    session.delete(w)  # cascade removes its WatchMatch history
    session.flush()
    return True


def watch_history(session: Session, watch_id: int, *, limit: int = 50) -> list[dict]:
    rows = session.execute(
        select(WatchMatch).where(WatchMatch.watch_id == watch_id)
        .order_by(WatchMatch.matched_at.desc()).limit(limit)
    ).scalars().all()
    return [_match_dict(m) for m in rows]


# --------------------------------------------------------------------------- #
# Evaluation — the engine (runs after each scrape pass; ON by default)
# --------------------------------------------------------------------------- #
def _recent_matching(
    session: Session, query: str, window_days: int, matcher: Matcher
) -> list[int]:
    """Article ids matching ``query`` whose date falls within ``window_days``.

    Uses published_at when present, else created_at (the ingest time) — so a freshly
    scraped article without a publication date still counts as recent evidence.
    """
    ids = matcher(session, query)
    if not ids:  # None (no positive constraint) or [] (matched nothing) -> nothing fires
        return []
    cutoff = datetime.now(UTC) - timedelta(days=window_days)
    cutoff_naive = cutoff.replace(tzinfo=None)  # stored datetimes are naive UTC
    rows: list[Any] = []
    for i in range(0, len(ids), _IN_CHUNK):
        chunk = ids[i : i + _IN_CHUNK]
        rows.extend(
            session.execute(
                select(Article.id, Article.published_at, Article.created_at)
                .where(Article.id.in_(chunk))
            ).all()
        )
    recent = []
    for aid, pub, created in rows:
        when = pub or created
        if when is not None and when.tzinfo is not None:
            when = when.replace(tzinfo=None)  # normalise: stored UTC is naive
        if when is None or when >= cutoff_naive:
            recent.append(aid)
    return recent


def evaluate_watches(
    session: Session, *, now: datetime | None = None, matcher: Matcher | None = None
) -> list[dict]:
    """Evaluate every ENABLED watch; fire those with new evidence over threshold.

    For each enabled watch: find the matching articles in its window, compute which are
    NEW since the last firing, and FIRE (record a WatchMatch + update the watch) when
    the in-window count is >= threshold AND there is at least one new article. Always
    stamps ``last_evaluated_at``. The caller owns the transaction (the single-writer
    gate serialises the flush). Returns the list of watches that fired this pass.
    """
    now = now or datetime.now(UTC)
    now_naive = now.replace(tzinfo=None)
    matcher = matcher or _fts_matcher
    fired: list[dict] = []
    for w in session.execute(select(Watch).where(Watch.enabled.is_(True))).scalars():
        try:
            recent = _recent_matching(session, w.query, w.window_days, matcher)
        except Exception:  # noqa: BLE001 - one bad watch query must never break the pass
            w.last_evaluated_at = now_naive
            continue
        w.last_evaluated_at = now_naive
        seen = _loads_ids(w.last_seen_ids)
        new_ids = [a for a in recent if a not in seen]
        if len(recent) >= w.threshold and new_ids:
            m = WatchMatch(
                watch_id=w.id, matched_at=now_naive,
                n_articles=len(recent), new_articles=len(new_ids),
                article_ids=json.dumps(sorted(recent)),
            )
            session.add(m)
            w.last_matched_at = now_naive
            # Remember this firing set (bounded) so we only fire again on NEW evidence.
            w.last_seen_ids = json.dumps(sorted(recent)[-_MAX_SEEN:])
            fired.append({"id": w.id, "name": w.name, "query": w.query,
                          "n_articles": len(recent), "new_articles": len(new_ids),
                          "article_ids": sorted(recent)})
    session.flush()
    return fired


def recent_fired_watches(session: Session, *, within_hours: int = 48, limit: int = 20) -> list[dict]:
    """Watches whose LATEST firing was within ``within_hours`` — the Lead-card source.

    Each entry carries the latest WatchMatch's count + article set so a card can open
    the exact articles. Counts only, no score.
    """
    cutoff = (datetime.now(UTC) - timedelta(hours=within_hours)).replace(tzinfo=None)
    out: list[dict] = []
    rows = session.execute(
        select(Watch).where(Watch.last_matched_at.is_not(None), Watch.last_matched_at >= cutoff)
        .order_by(Watch.last_matched_at.desc()).limit(limit)
    ).scalars().all()
    for w in rows:
        latest = session.execute(
            select(WatchMatch).where(WatchMatch.watch_id == w.id)
            .order_by(WatchMatch.matched_at.desc()).limit(1)
        ).scalars().first()
        if latest is None:
            continue
        out.append({
            "id": w.id, "name": w.name, "query": w.query,
            "n_articles": latest.n_articles, "new_articles": latest.new_articles,
            "matched_at": latest.matched_at.isoformat() if latest.matched_at else None,
            "article_ids": _id_list(latest.article_ids),
        })
    return out
