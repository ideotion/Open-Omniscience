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
import time
from datetime import UTC, datetime

from src.briefing.card import BUCKET_LABELS, BUCKETS
from src.briefing.producers import register_default_producers
from src.briefing.registry import run_all_bounded

_LOG = logging.getLogger(__name__)

# Bumped 1->2 (field report 2026-06-22): a card-SHAPE change (set-based producers now
# carry article_ids, so a card hard-links to its EXACT corpus instead of falling back
# to a fuzzy text search of its seed term) does NOT trip the corpus-growth staleness
# check, so an existing install kept serving pre-fix cards (clicking source-laundering
# searched the origin domain and loaded tens of thousands of articles, not the card's
# exact citing set). Bumping the version forces ONE recompute so live cards gain their
# article_ids. The home-card click diagnostics tool (GET /api/diagnostics/home-cards)
# is the recurring check that every card hard-links.
# Bumped 2->3 (re-walk 2026-09-27, L-1/L-2/N-8/M-6): cards now carry keyed i18n frames
# and the ranking line its order_explain_i18n, both written at CACHE-WRITE time, so a
# v2 cache kept Home English in fr/ar/zh until a scrape or 10% corpus growth, which an
# airplane-mode install may never see. A v2 cache is still SERVED (its shape is a
# subset: the renderer falls back to the English fields) but counts as stale, so the
# first read recomputes it -- in the background on the HTTP path, with the old cards
# on screen meanwhile rather than an empty "building" Home. A v1 cache (no
# article_ids) is still refused outright.
CACHE_VERSION = "oo-briefing-cache-3"
_SERVABLE_PRIOR_VERSIONS: frozenset[str] = frozenset({"oo-briefing-cache-2"})

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


def _is_cache_stale(session, payload: dict, *, current: int | None = None) -> bool:
    """True iff the corpus has grown materially since the cache was generated, so
    the cached cards no longer reflect the corpus (the empty-Home-despite-data bug).
    A cache with no recorded count (pre-this-change) is treated as stale once."""
    cached = payload.get("article_count")
    if current is None:                      # D4: reuse a count the caller already paid for
        current = _article_count(session)
    if cached is None:
        # Unknown baseline: refresh once only if the corpus is non-trivial, so an
        # already-empty corpus doesn't trigger a pointless recompute.
        return current >= _STALE_GROWTH_MIN
    grew = current - int(cached)
    return grew >= _STALE_GROWTH_MIN and grew >= int(cached) * _STALE_GROWTH_FRAC


# A feed that carries a stop marker (``kept_reason`` / ``incomplete_reason``) is repaired
# without anyone pressing Refresh: once the machine has headroom again, the next Home poll
# starts ONE background refresh. Three things keep that from becoming a loop:
#   * ``_MARKER_RETRY_S`` seconds must pass AFTER the last refresh FINISHED (any refresh, the
#     scheduler's included), so a refresh that keeps ending early, or one that itself takes
#     minutes on a large corpus, never runs back to back;
#   * memory must be a margin ABOVE the floor, not a megabyte over it (the floor, up to
#     ``_REPAIR_MARGIN_MAX_MB``): a refresh started there only stops again at the first producer
#     boundary and re-marks the feed. A guard floor set above what the machine usually has free
#     therefore leaves the repair off, and the Refresh button as the way out;
#   * the scheduler's own briefing refresh and housekeeping lane are not running when the
#     repair STARTS. The other direction is not closed: a pass-tail refresh that starts during a
#     repair is not held back, exactly as for the stale-cache refresh and the Refresh button,
#     which never took those locks either.
# The state is per process, so a restart (an app update) tries once straight away.
_MARKER_RETRY_S = 600.0
_REPAIR_MARGIN_MAX_MB = 512.0
_marker_retry: dict[str, float | None] = {"at": None}


def _monotonic() -> float:
    return time.monotonic()


def _scheduler_is_busy_with_the_whole_corpus() -> bool:
    """True while the scheduler's pass-tail briefing refresh or its heavy-tail housekeeping runs."""
    try:
        from src.scheduler import runner

        sched = runner._scheduler  # never created here: no scheduler means nothing is running
        return sched is not None and sched.whole_corpus_work_running()
    except Exception:  # noqa: BLE001 - a probe failure must never break Home
        return False


def _has_headroom_for_a_repair() -> bool:
    """Memory is a margin above the guard's floor (or cannot be measured, the honest default)."""
    try:
        from src.database.maintenance import _available_mb, _read_memory_floor_mb

        floor, avail = _read_memory_floor_mb(), _available_mb()
    except Exception:  # noqa: BLE001 - no DB layer, or no reading
        return True
    return floor is None or avail is None or avail > floor + min(floor, _REPAIR_MARGIN_MAX_MB)


def _marker_wants_refresh(payload: dict) -> bool:
    """True when ``payload`` carries a stop marker and a repair is allowed right now."""
    if not (payload.get("kept_reason") or payload.get("incomplete_reason")):
        return False
    if not _has_headroom_for_a_repair() or _scheduler_is_busy_with_the_whole_corpus():
        return False
    with _refresh_lock:
        last = _marker_retry["at"]
    return last is None or _monotonic() - last >= _MARKER_RETRY_S


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

        out = sorted(cards, key=_key)
        # Attach the DISCLOSED reason each card sits where it does (2026-08-01
        # ruling 5). The ordering was already honest, but explain_order had ZERO
        # frontend callers after the Settings restructure removed the Leads
        # preview — so the transparency surface existed and was invisible. It
        # rides the payload the feed already fetches: no second request, and the
        # explanation can never drift from the sort that produced it, because
        # both come from the same order_key here.
        try:
            from src.briefing.card import frames_text
            from src.briefing.leads import explain_order_frames

            for c in out:
                # The keyed frames beside their English (re-walk N-8): Home renders the
                # frames in the reader's language, and a cache written before they
                # existed still has the English line.
                c["order_explain_i18n"] = explain_order_frames(_wrap(c), now=now)
                c["order_explain"] = frames_text(c["order_explain_i18n"])
        except Exception:  # noqa: BLE001 - an explanation is additive, never load-bearing
            _LOG.warning("Leads-2.0 order explanation failed; cards keep their order", exc_info=True)
        return out
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

    Whatever the outcome, the time it finished is remembered: a marker repair waits
    ``_MARKER_RETRY_S`` from there (see ``_marker_wants_refresh``).
    """
    try:
        return _refresh_briefing(session, on_progress)
    finally:
        with _refresh_lock:
            _marker_retry["at"] = _monotonic()


def _refresh_briefing(session, on_progress=None) -> dict:
    """The body of :func:`refresh_briefing`.

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
    # Which feed was on disk when this run STARTED: a refresh that lands while this one runs
    # must not be overwritten with the feed it just replaced, and only a read taken before the
    # run can tell (two reads taken after it cannot).
    started_with = (_read_cache() or {}).get("generated_at")
    # Home is the one place the lane-only cards are made for (Q823: no bulletin carries them).
    produced, stats = run_all_bounded(
        session, on_progress=on_progress, lanes=True, memory_stop=True
    )
    cards = [c.to_dict() for c in produced]

    # S2.3: a truncated run must not REPLACE a good feed with what it managed to
    # finish. The producer loop now stops when an enclosing statement deadline
    # expires (S2.2), so a diagnostic running under one can reach here with a
    # partial -- or empty -- set that is a fact about the DEADLINE, not about the
    # corpus.
    #
    # Gated STRICTLY on that expiry, and only when the new set is EMPTY and the
    # cached one is not. An unconditional "never replace non-empty with empty"
    # would freeze a stale Home forever on a corpus that genuinely yields no cards,
    # which is a worse failure than the one being fixed: the feed would stop being
    # about the corpus at all, and nothing would say so.
    #
    # MEMORY is the second reason, and there a PARTIAL set is not good enough either
    # (diagnostics rank 4): the run stopped because the machine was nearly out of memory,
    # so the producers it never reached are the ones whose cards would silently vanish
    # from Home -- the feed would look complete and be missing whatever ran last. When a
    # cached feed exists it is kept whole and the stop is logged; when none exists the
    # partial set is written (something beats an empty Home), and ``truncated_reason`` in
    # ``run_all_bounded``'s stats records why.
    memory_stopped = stats.get("truncated_reason") == "memory_short"
    if stats.get("truncated") and (memory_stopped or not cards):
        existing = _read_cache()
        if existing and existing.get("cards"):
            _LOG.warning(
                "briefing refresh %s; keeping the %d cached cards rather than "
                "replacing Home with %d",
                "stopped because the machine was nearly out of memory"
                if memory_stopped
                else "truncated by an enclosing deadline and produced no cards",
                len(existing["cards"]),
                len(cards),
            )
            # Said in the payload, not only in a log: the caller must not record this as a
            # refresh that surfaced cards (the Activity Ledger would claim one).
            kept = {**existing, "kept_reason": "memory_short" if memory_stopped else "deadline"}
            # Written into the cache as well, so Home (which reads the cache, not this return
            # value) can say that the feed it shows is the previous one and why. The next
            # refresh that completes replaces the whole payload, marker included.
            # (A refresh that lands between the read above and the write below still loses to
            # this one; the marker repair puts that right, so it is not guarded a second time.)
            if existing.get("generated_at") != started_with:
                # A refresh landed during this run: its feed is the newer one, so the marker is
                # not written (Home would call a fresh feed "the previous feed"); this call
                # still reports that it kept the cache, which is what its caller records.
                return kept
            try:
                _write_cache(kept)
            except OSError:
                _LOG.warning("could not record that the briefing refresh kept the cache", exc_info=True)
            return kept

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
    if stats.get("truncated"):
        # A feed that is missing the producers the run never reached says so, in the cache
        # and in the view: a short feed must not read as a complete one.
        payload["incomplete_reason"] = "memory_short" if memory_stopped else "deadline"
    _write_cache(payload)
    _LOG.info("briefing refreshed: %d cards", len(cards))
    # Warm the heavy whole-corpus read cache (top / trending / map) in this same
    # background pass, so the Home + Insights surfaces are instant and never trigger
    # a cold multi-second aggregation in the UI (perf, field report 2026-06-18).
    #
    # Not after a memory stop: the warm-up reads more of the corpus, and the run just
    # stopped because the machine was nearly out of memory.
    if not memory_stopped:
        try:
            from src.api.insights import warm_cache

            warm_cache(session)
        except Exception:  # noqa: BLE001 - warming is best-effort, never fatal to the feed
            _LOG.warning("insights cache warm failed; briefing continues", exc_info=True)
    return payload


def _write_cache(payload: dict) -> None:
    path = _cache_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)


def _read_cache() -> dict | None:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
        if data.get("version") != CACHE_VERSION and data.get("version") not in _SERVABLE_PRIOR_VERSIONS:
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
    view = {
        "generated_at": payload.get("generated_at"),
        "count": len(visible),
        "total": len(cards),
        "dismissed_count": len(dismissed),
        "buckets": buckets,
        "cards": visible,
    }
    # Why this feed may not be the whole picture (diagnostics rank 4): the last refresh
    # stopped early, either leaving cards out ("incomplete") or leaving this earlier feed
    # in place ("kept"). Absent when the last refresh completed.
    for key in ("incomplete_reason", "kept_reason"):
        if payload.get(key) in ("memory_short", "deadline"):
            view[key] = payload[key]
    return view


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
    # D4 (field diagnostics 2026-09-11): /api/briefing measured p95 60,113.8 ms, and it
    # ran the SAME `SELECT count(Article.id)` THREE times per request -- once for the
    # staleness check and twice more inside corpus_tier (which called _corpus_articles
    # and _is_young, each counting independently). Over a 1.34M-row table that is three
    # full index scans for one number that cannot change mid-request. Counted at most
    # ONCE here, lazily (a request that needs neither still pays nothing), and threaded
    # into both consumers.
    #
    # NOT the mechanism the field brief proposed. It looked for "a second pool
    # acquisition or a retry" on the strength of three routes landing within 700 ms of
    # exactly 60 s = 2x pool_timeout. There is no second acquisition: none of these
    # routes opens a second session on the request thread, and the ~60 s is
    # OO_STATEMENT_TIMEOUT_S, a DELIBERATE single statement deadline that happens to sit
    # at twice the pool timeout. /api/insights/latest and /api/insights/trending-windows
    # are therefore working as designed and are left alone. This route had a real
    # duplicate-work defect, and it is this one.
    _counted: list[int] = []

    def _count_once() -> int:
        if not _counted:
            _counted.append(_article_count(session))
        return _counted[0]

    stale = cached is not None and (
        cached.get("version") != CACHE_VERSION  # a servable prior shape: recompute once
        or _is_cache_stale(session, cached, current=_count_once())
        or _marker_wants_refresh(cached)
    )
    need_recompute = force or cached is None or stale
    if need_recompute and background:
        # Off-request: kick one background recompute, serve the current cache meanwhile.
        _ensure_background_refresh()
        payload = cached
    elif need_recompute:
        if stale:
            _LOG.info("briefing cache is stale (corpus grew, an older cache shape, or a stop marker to repair); recomputing")
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
        view["corpus_tier"] = corpus_tier(session, article_count=_count_once())
    except Exception:  # noqa: BLE001 - the tier must never break the feed
        _LOG.warning("corpus_tier failed; omitting from briefing", exc_info=True)
    return view
