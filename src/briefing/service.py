"""
Briefing assembly, caching, and dismissal — the feed behind Home.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

App-efficiency rule (offline, single machine): **precompute, cache, serve cached.**
The briefing never computes per request — Home reads a cached card set and loads
instantly. The cache is refreshed by the background scheduler after each scrape (or
on an explicit user "Refresh"). Dismissals are stored separately so a dismissed card
can be restored and a later recompute re-applies the user's choice, not overwrites it.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime

from src.briefing.card import BUCKET_LABELS, BUCKETS
from src.briefing.producers import register_default_producers
from src.briefing.registry import run_all

_LOG = logging.getLogger(__name__)

# Bumped 1->2 (field report 2026-06-22): a card-SHAPE change (set-based producers now
# carry article_ids, so a card hard-links to its EXACT corpus instead of falling back
# to a fuzzy text search of its seed term) does NOT trip the corpus-growth staleness
# check, so an existing install kept serving pre-fix cards (clicking source-laundering
# searched the origin domain and loaded tens of thousands of articles, not the card's
# exact citing set). Bumping the version forces ONE recompute so live cards gain their
# article_ids. The home-card click diagnostics tool (GET /api/diagnostics/home-cards)
# is the recurring check that every card hard-links.
CACHE_VERSION = "oo-briefing-cache-2"

# Register the built-in producers once, at import.
register_default_producers()


# --------------------------------------------------------------------------- #
# Background-refresh coordinator. The HTTP path (get_briefing(..., background=True))
# must NEVER recompute on the request thread — a 60K-article run_all + warm_cache takes
# minutes, which froze Home on "Loading the briefing…" (field test 2026-06-24). It kicks
# ONE background recompute (its OWN session) and serves the best cache it has now, plus a
# refreshing flag + determinate progress so the UI shows a real progress bar.
# --------------------------------------------------------------------------- #
_refresh_lock = threading.Lock()
_refresh_state: dict[str, int | bool] = {"refreshing": False, "done": 0, "total": 0}


def _bg_refresh() -> None:
    """Recompute the briefing in a daemon thread with its OWN session, publishing
    per-producer progress. Best-effort: a failure is logged, never crashes the app."""
    from src.database.session import session_scope

    def _progress(done: int, total: int, _name: str) -> None:
        with _refresh_lock:
            _refresh_state["done"] = done
            _refresh_state["total"] = total

    try:
        with session_scope() as session:
            refresh_briefing(session, on_progress=_progress)
    except Exception:  # noqa: BLE001 - a background refresh must never crash the app
        _LOG.warning("background briefing refresh failed", exc_info=True)
    finally:
        with _refresh_lock:
            _refresh_state["refreshing"] = False


def _ensure_background_refresh() -> None:
    """Start ONE background recompute if none is running (idempotent under the
    concurrent Home polls)."""
    with _refresh_lock:
        if _refresh_state["refreshing"]:
            return
        _refresh_state["refreshing"] = True
        _refresh_state["done"] = 0
        _refresh_state["total"] = 0
    threading.Thread(target=_bg_refresh, name="oo-briefing-refresh", daemon=True).start()


def _refresh_status() -> dict:
    """The current background-refresh state for the API view: a ``refreshing`` bool and,
    while refreshing, a ``progress`` {done, total} for a determinate bar."""
    with _refresh_lock:
        refreshing = bool(_refresh_state["refreshing"])
        status: dict = {"refreshing": refreshing}
        if refreshing:
            status["progress"] = {
                "done": int(_refresh_state["done"]),
                "total": int(_refresh_state["total"]),
            }
    return status


def _cache_path():
    from src.paths import data_dir

    return data_dir() / "briefing_cache.json"


# A cache is STALE once the corpus has grown by this fraction AND this many
# articles since it was generated — only then is recomputing (run_all, heavy)
# worth it. Bounds the regen frequency: normal online operation refreshes the
# cache post-pass, so this safety net fires rarely (e.g. boot-airplane, or a bulk
# import without a scrape pass), not on every Home poll.
_STALE_GROWTH_FRAC = 0.10
_STALE_GROWTH_MIN = 25


def _article_count(session) -> int:
    """Cheap indexed COUNT of articles (the corpus size; no score, no scan)."""
    from sqlalchemy import func

    from src.database.models import Article

    try:
        return int(session.query(func.count(Article.id)).scalar() or 0)
    except Exception:  # noqa: BLE001 - a count failure must never break the feed
        return 0


def _is_cache_stale(session, payload: dict) -> bool:
    """True iff the corpus has grown materially since the cache was generated, so
    the cached cards no longer reflect the corpus (the empty-Home-despite-data bug).
    A cache with no recorded count (pre-this-change) is treated as stale once."""
    cached = payload.get("article_count")
    current = _article_count(session)
    if cached is None:
        # Unknown baseline: refresh once only if the corpus is non-trivial, so an
        # already-empty corpus doesn't trigger a pointless recompute.
        return current >= _STALE_GROWTH_MIN
    grew = current - int(cached)
    return grew >= _STALE_GROWTH_MIN and grew >= int(cached) * _STALE_GROWTH_FRAC


def _dismissed_path():
    from src.paths import data_dir

    return data_dir() / "briefing_dismissed.json"


def _bucket_rank(bucket: str) -> int:
    try:
        return BUCKETS.index(bucket)
    except ValueError:
        return len(BUCKETS)


def _magnitude(card: dict) -> float:
    """A within-bucket ordering proxy: the size of the measured signal, else n."""
    value = (card.get("signal") or {}).get("value")
    if isinstance(value, (int, float)):
        return abs(float(value))
    n = card.get("n")
    return float(n) if isinstance(n, (int, float)) else 0.0


def _sorted(cards: list[dict]) -> list[dict]:
    """Sort Home cards by bucket priority, then by the Leads-2.0 DISCLOSED order_key
    (independent sources -> magnitude tier -> recency) instead of a raw single-value
    magnitude (S5.2, Leads-calibration — "This visibly reorders Home", ship
    conservative + flagged). Defensive: any failure in the reorder falls back to the
    original raw-magnitude sort untouched, so Home is never broken by this change —
    a browser click-through against the Settings→Leads preview is still owed."""
    try:
        from src.briefing.leads import order_key as _leads_order_key

        now = datetime.now(UTC)

        def _wrap(c: dict):
            from types import SimpleNamespace

            return SimpleNamespace(
                evidence=c.get("evidence") or [], n=c.get("n"),
                article_ids=c.get("article_ids") or [],
                type=c.get("type"), key=c.get("key"),
            )

        def _key(c: dict):
            sources, tier, recency = _leads_order_key(_wrap(c), now=now)
            return (_bucket_rank(c["bucket"]), -sources, -tier, -recency)

        return sorted(cards, key=_key)
    except Exception:  # noqa: BLE001 - a reorder problem must never break Home
        _LOG.warning("Leads-2.0 order_key sort failed; using the raw-magnitude fallback", exc_info=True)
        return sorted(cards, key=lambda c: (_bucket_rank(c["bucket"]), -_magnitude(c)))


def dismissed_ids() -> set[str]:
    path = _dismissed_path()
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text("utf-8")).get("ids", []))
    except Exception:  # noqa: BLE001 - a bad file must not break the feed
        _LOG.warning("briefing_dismissed.json unreadable; treating as empty", exc_info=True)
        return set()


def _save_dismissed(ids: set[str]) -> None:
    path = _dismissed_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"version": CACHE_VERSION, "ids": sorted(ids)}, indent=2), "utf-8")
    tmp.replace(path)


def dismiss(card_id: str) -> set[str]:
    ids = dismissed_ids()
    ids.add(card_id)
    _save_dismissed(ids)
    return ids


def restore(card_id: str) -> set[str]:
    ids = dismissed_ids()
    ids.discard(card_id)
    _save_dismissed(ids)
    return ids


def clear_dismissed() -> None:
    _save_dismissed(set())


def refresh_briefing(session, on_progress=None) -> dict:
    """Recompute the briefing from all producers and write the cache. Returns it.

    ``on_progress(done, total, name)`` (optional) is forwarded to ``run_all`` so a
    background recompute can publish a progress bar; callers that don't need it
    (the scheduler, an explicit synchronous get) pass nothing — unchanged behaviour."""
    # The convergence WATCH engine is ON by default (ruling #3): evaluate saved watches
    # BEFORE producing cards, so a watch that just crossed its threshold surfaces in
    # this very refresh. Local-only; a watch problem must never block the briefing.
    try:
        from src.analytics.watches import evaluate_watches

        evaluate_watches(session)
    except Exception:  # noqa: BLE001 - the watch pass is additive, never fatal to the feed
        _LOG.warning("watch evaluation failed; briefing continues", exc_info=True)
    cards = [c.to_dict() for c in run_all(session, on_progress=on_progress)]
    payload = {
        "version": CACHE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        # The corpus size at generation time, so get_briefing can detect a STALE
        # cache (the corpus grew but the scheduler hasn't refreshed — e.g. the app
        # boots in airplane mode, so the scheduler is idle and a briefing built when
        # the corpus was tiny would otherwise show an empty Home forever despite a
        # large corpus; P0-3, field test 2026-06-22).
        "article_count": _article_count(session),
        "cards": _sorted(cards),
    }
    path = _cache_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)
    _LOG.info("briefing refreshed: %d cards", len(cards))
    # Warm the heavy whole-corpus read cache (top / trending / map) in this same
    # background pass, so the Home + Insights surfaces are instant and never trigger
    # a cold multi-second aggregation in the UI (perf, field report 2026-06-18).
    try:
        from src.api.insights import warm_cache

        warm_cache(session)
    except Exception:  # noqa: BLE001 - warming is best-effort, never fatal to the feed
        _LOG.warning("insights cache warm failed; briefing continues", exc_info=True)
    return payload


def _read_cache() -> dict | None:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
        if data.get("version") != CACHE_VERSION:
            return None
        return data
    except Exception:  # noqa: BLE001 - a corrupt cache just triggers a recompute
        _LOG.warning("briefing_cache.json unreadable; will recompute", exc_info=True)
        return None


def _present(payload: dict, *, include_dismissed: bool) -> dict:
    """Shape a cache payload into the API view, applying dismissals + grouping."""
    dismissed = dismissed_ids()
    cards = payload.get("cards", [])
    if not include_dismissed:
        visible = [c for c in cards if c["id"] not in dismissed]
    else:
        visible = [{**c, "dismissed": c["id"] in dismissed} for c in cards]
    buckets = []
    for b in BUCKETS:
        items = [c for c in visible if c["bucket"] == b]
        if items:
            buckets.append({"bucket": b, "label": BUCKET_LABELS[b], "cards": items})
    return {
        "generated_at": payload.get("generated_at"),
        "count": len(visible),
        "total": len(cards),
        "dismissed_count": len(dismissed),
        "buckets": buckets,
        "cards": visible,
    }


def get_briefing(
    session, *, force: bool = False, include_dismissed: bool = False, background: bool = False
) -> dict:
    """Return the cached briefing (computing once if absent, ``force``, or STALE).

    Stale-recompute (P0-3): the scheduler refreshes the cache after each scrape, but
    the app boots in airplane mode (scheduler idle), so a briefing built when the
    corpus was small would otherwise leave Home empty forever despite a large corpus.
    If the corpus has grown materially since the cache, recompute — bounded so a
    stable corpus always reads the cache instantly.

    ``background`` (the HTTP path, field test 2026-06-24): NEVER recompute on the
    caller's thread — a 60K-article run_all + warm_cache takes minutes and froze Home
    on "Loading the briefing…". Kick ONE background recompute and serve the best cache
    we have now (the stale cards, or an honest ``building`` placeholder) with a
    ``refreshing`` flag + progress, so the request returns instantly and the UI shows a
    progress bar. ``background=False`` (tests / scheduler / explicit in-process callers)
    keeps the recompute SYNCHRONOUS on ``session`` — unchanged behaviour."""
    cached = _read_cache()
    stale = cached is not None and _is_cache_stale(session, cached)
    need_recompute = force or cached is None or stale
    if need_recompute and background:
        # Off-request: kick one background recompute, serve the current cache meanwhile.
        _ensure_background_refresh()
        payload = cached
    elif need_recompute:
        if stale:
            _LOG.info("briefing cache is stale (corpus grew); recomputing")
        payload = refresh_briefing(session)
    else:
        payload = cached
    if payload is None:
        # Background path with no cache yet — an honest "building" placeholder that
        # never blocks; the UI shows the progress bar and re-polls until cards land.
        view: dict = {
            "generated_at": None,
            "count": 0,
            "total": 0,
            "dismissed_count": 0,
            "buckets": [],
            "cards": [],
            "building": True,
        }
    else:
        view = _present(payload, include_dismissed=include_dismissed)
    view.update(_refresh_status())
    # Additive: the corpus maturity STAGE (descriptive, never a score) so a Home
    # reader can calibrate how much weight to give the evidence cards. Computed
    # live from real corpus facts (cheap min/max + count) — not cached, so it is
    # always honest about the corpus as it stands right now. Never breaks the feed.
    from src.briefing.producers import corpus_tier

    try:
        view["corpus_tier"] = corpus_tier(session)
    except Exception:  # noqa: BLE001 - the tier must never break the feed
        _LOG.warning("corpus_tier failed; omitting from briefing", exc_info=True)
    return view
