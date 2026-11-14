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

import contextlib
import contextvars
import json
import logging
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from src.briefing.card import BUCKET_LABELS, BUCKETS
from src.briefing.producers import register_default_producers
from src.briefing.registry import PRODUCER_DEADLINE_S, run_all_bounded
from src.monitoring.secret_scrub import log_failure
from src.safety.file_lock import atomic_replace, holding

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
_refresh_state: dict[str, int | bool | str] = {"refreshing": False, "done": 0, "total": 0, "paused": ""}
#: The background rebuild's thread, kept so a caller can find it without walking ``threading.enumerate()`` (a test that must not leave it
#: running, a later shutdown step). Set under ``_refresh_lock`` when the thread is started; it stays set after the thread ends (``is_alive()`` says
#: whether it is still running). Nothing in ``shutdown.py`` joins it today: the daemon thread dies with the process, as before.
_refresh_thread: threading.Thread | None = None
#: The cache file a background rebuild writes, fixed when its thread STARTS (``_ensure_background_refresh``) and read by ``_cache_path`` in that
#: thread alone (a ContextVar set inside the thread). Unset everywhere else, where the path is resolved from the data folder at each use, as before.
_run_cache_path: contextvars.ContextVar[Path | None] = contextvars.ContextVar("oo_briefing_run_cache_path", default=None)


def _log_pinned() -> bool:
    """Whether a rebuild should stand aside now: the write-ahead log is pinned and the guard that ends the pin is running (the same
    question every pause asks, ``storage_guard.log_pause_in_force``). A non-blocking read that never raises into a view."""
    try:
        from src.scheduler.storage_guard import log_pause_in_force

        return bool(log_pause_in_force())
    except Exception as exc:  # noqa: BLE001 - a view must never break on the guard
        log_failure(_LOG, "briefing: the storage guard could not be read; not pausing", exc, level=logging.WARNING)
        return False


def _bg_refresh(cache_path: Path) -> None:
    """Recompute the briefing in a daemon thread with its OWN session, publishing
    per-producer progress. Best-effort: a failure is logged, never crashes the app.

    ``cache_path`` is where the caller meant the cache to be when it started this thread, and every read and write of the cache in this run
    goes there. A thread that asked ``data_dir()`` again at its write could land the cache in a different folder than the one it started in
    (a data folder changed while it ran, a test that moved ``OO_DATA_DIR`` and left the thread behind)."""
    from src.database.session import session_scope

    def _progress(done: int, total: int, _name: str) -> None:
        with _refresh_lock:
            _refresh_state["done"] = done
            _refresh_state["total"] = total

    token = _run_cache_path.set(cache_path)
    try:
        # A rebuild is a run of whole-corpus scans, the readers that hold the write-ahead log's checkpoint back (the 16 Oct 2026 pin
        # reports named them). While the LOG latch is engaged it does not start: the thread ends at once and the view says ``paused``,
        # with ``refreshing`` false, so the stale cards stay on screen, the Refresh button works and Home does not poll at its fast
        # cadence for as long as the pin lasts. It is not parked: a thread that waited would hold ``refreshing`` true for a pin that has
        # lasted hours. The next poll after the pin drains finds the cache stale again and starts the rebuild. The drive latch is not
        # asked: a full drive does not hurt a read.
        if _log_pinned():
            with _refresh_lock:
                _refresh_state["paused"] = "wal"
            return
        with session_scope() as session:
            refresh_briefing(session, on_progress=_progress)
    except Exception as exc:  # noqa: BLE001 - a background refresh must never crash the app
        log_failure(_LOG, "background briefing refresh failed", exc, level=logging.WARNING)
    finally:
        _run_cache_path.reset(token)  # a dedicated thread's context dies with it; a pooled one would keep the pin for its next task
        with _refresh_lock:
            _refresh_state["refreshing"] = False


def _ensure_background_refresh() -> None:
    """Start ONE background recompute if none is running (idempotent under the
    concurrent Home polls)."""
    global _refresh_thread
    try:
        cache_path = _cache_path()  # resolved once, here, for the whole run (see _bg_refresh)
    except Exception as exc:  # noqa: BLE001 - a background refresh must never crash the app
        log_failure(_LOG, "background briefing refresh not started: the cache folder could not be resolved", exc, level=logging.WARNING)
        return
    with _refresh_lock:
        if _refresh_state["refreshing"]:
            return
        _refresh_state["refreshing"] = True
        _refresh_state["done"] = 0
        _refresh_state["total"] = 0
        thread = threading.Thread(target=_bg_refresh, args=(cache_path,), name="oo-briefing-refresh", daemon=True)
        _refresh_thread = thread
    try:
        thread.start()
    except RuntimeError as exc:  # no thread could be started: leave the state as it was, or ``refreshing`` stays true for good
        with _refresh_lock:
            _refresh_state["refreshing"] = False
            if _refresh_thread is thread:
                _refresh_thread = None
        log_failure(_LOG, "background briefing refresh not started: no thread could be started", exc, level=logging.WARNING)


def _refresh_status() -> dict:
    """The current background-refresh state for the API view: a ``refreshing`` bool and,
    while refreshing, a ``progress`` {done, total} for a determinate bar. ``paused`` (``"wal"``)
    is present only while the last rebuild was held back by the write-ahead log's pin AND the pin
    still stands; it is read against the guard each time, so it never outlives its cause."""
    pinned = _log_pinned()
    with _refresh_lock:
        if not pinned:
            _refresh_state["paused"] = ""
        refreshing = bool(_refresh_state["refreshing"])
        status: dict = {"refreshing": refreshing}
        if refreshing:
            status["progress"] = {
                "done": int(_refresh_state["done"]),
                "total": int(_refresh_state["total"]),
            }
        if _refresh_state["paused"]:
            status["paused"] = str(_refresh_state["paused"])
    return status


def _cache_path():
    fixed = _run_cache_path.get()
    if fixed is not None:
        return fixed
    from src.paths import data_dir

    return data_dir() / "briefing_cache.json"


def cache_path_for_a_new_run() -> Path:
    """The cache file a rebuild started NOW reads and writes. A caller that starts a rebuild on a thread of its own (the scheduler's pass tail)
    resolves it before the thread exists and hands it to ``pinned_cache_path`` inside the thread, for the reason ``_bg_refresh`` gives."""
    return _cache_path()


@contextlib.contextmanager
def pinned_cache_path(path: Path) -> Iterator[None]:
    """Inside the block, ``_cache_path()`` answers ``path`` in the calling thread, whatever the data folder is meanwhile. The pin is reset on the
    way out, so a pooled thread does not carry it into its next task."""
    token = _run_cache_path.set(path)
    try:
        yield
    finally:
        _run_cache_path.reset(token)


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


def _stoplist_fingerprint() -> str | None:
    """The shipped stoplist's fingerprint, or None when it cannot be read (never raises)."""
    try:
        from src.analytics.stoplist_recompute import current_fingerprint

        return current_fingerprint()
    except Exception:  # noqa: BLE001 - an unreadable list must not make the feed stale
        return None


def _stoplist_wants_refresh(payload: dict) -> bool:
    """True when the cards were made under another shipped stoplist and a refresh is allowed now.

    A word an update hides stays in the titles of cached cards until they are recomputed
    (R111 step T3). The same background refresh the other stale causes use does it, under the
    marker repair's own throttle, so a refresh that keeps ending early (``kept_reason``) is
    retried every ``_MARKER_RETRY_S``, never on every Home poll. A cache written before this
    field existed has none and is refreshed once."""
    current = _stoplist_fingerprint()
    if current is None or payload.get("stoplist") == current:
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
        except Exception as exc:  # noqa: BLE001 - an explanation is additive, never load-bearing
            log_failure(_LOG, "Leads-2.0 order explanation failed; cards keep their order", exc, level=logging.WARNING)
        return out
    except Exception as exc:  # noqa: BLE001 - a reorder problem must never break Home
        log_failure(_LOG, "Leads-2.0 order_key sort failed; using the raw-magnitude fallback", exc, level=logging.WARNING)
        return sorted(cards, key=lambda c: (_bucket_rank(c["bucket"]), -_magnitude(c)))


def dismissed_ids() -> set[str]:
    path = _dismissed_path()
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text("utf-8")).get("ids", []))
    except Exception as exc:  # noqa: BLE001 - a bad file must not break the feed
        log_failure(_LOG, "briefing_dismissed.json unreadable; treating as empty", exc, level=logging.WARNING)
        return set()


def _save_dismissed(ids: set[str]) -> None:
    atomic_replace(_dismissed_path(), json.dumps({"version": CACHE_VERSION, "ids": sorted(ids)}, indent=2), encoding="utf-8")


@holding(lambda: _dismissed_path())
def dismiss(card_id: str) -> set[str]:
    ids = dismissed_ids()
    ids.add(card_id)
    _save_dismissed(ids)
    return ids


@holding(lambda: _dismissed_path())
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
    except Exception as exc:  # noqa: BLE001 - the watch pass is additive, never fatal to the feed
        log_failure(_LOG, "watch evaluation failed; briefing continues", exc, level=logging.WARNING)
    # Which feed was on disk when this run STARTED: a refresh that lands while this one runs
    # must not be overwritten with the feed it just replaced, and only a read taken before the
    # run can tell (two reads taken after it cannot).
    previous = _read_cache() or {}
    started_with = previous.get("generated_at")
    # R666: the producers the previous refresh stopped at their bound run last this time, so their ten minutes come after
    # every other producer has had its turn rather than before.
    stopped_before = previous.get("stopped_producers")
    run_last = frozenset(n for n in stopped_before if isinstance(n, str)) if isinstance(stopped_before, list) else None
    # Home is the one place the lane-only cards are made for (Q823: no bulletin carries them).
    # Item 32: each producer is bounded (PRODUCER_DEADLINE_S) and the log latch is asked between producers, so one producer can
    # no longer hold the write-ahead log's read mark for hours while the log fills the disk.
    timings: list[dict] = []
    produced, stats = run_all_bounded(
        session, on_progress=on_progress, lanes=True, memory_stop=True,
        producer_deadline_s=PRODUCER_DEADLINE_S, log_pin_stop=True, run_last=run_last, timings=timings,
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
    # A pinned log is the same kind of stop as a memory one (the run ended between producers for a reason about the machine, not
    # the corpus), so it gets the same treatment: the previous feed is kept whole rather than shown with whatever ran last missing.
    pin_stopped = stats.get("truncated_reason") == "wal_pinned"
    machine_stopped = memory_stopped or pin_stopped
    stop_reason = "memory_short" if memory_stopped else "wal_pinned" if pin_stopped else "deadline"
    if stats.get("truncated") and (machine_stopped or not cards):
        existing = _read_cache()
        if existing and existing.get("cards"):
            _LOG.warning(
                "briefing refresh %s; keeping the %d cached cards rather than "
                "replacing Home with %d",
                "stopped because the machine was nearly out of memory"
                if memory_stopped
                else "stopped because the write-ahead log is pinned"
                if pin_stopped
                else "truncated by an enclosing deadline and produced no cards",
                len(existing["cards"]),
                len(cards),
            )
            # Said in the payload, not only in a log: the caller must not record this as a
            # refresh that surfaced cards (the Activity Ledger would claim one).
            kept = {**existing, "kept_reason": stop_reason}
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
            except OSError as exc:
                log_failure(_LOG, "could not record that the briefing refresh kept the cache", exc, level=logging.WARNING)
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
        # The shipped stoplist these cards were made under (R111 step T3): a different one
        # makes the cache stale, because a newly hidden word would otherwise stay in a title.
        "stoplist": _stoplist_fingerprint(),
        "cards": _sorted(cards),
        # Each producer's time and outcome on this refresh, and which producer made each card, for the card quality check
        # (Lane X). A map beside the cards rather than a key inside them: the cards keep Card.to_dict's shape.
        "producer_timings": timings,
        "card_producers": {
            str(getattr(c, "id", "")): getattr(c, "produced_by", "") for c in produced if getattr(c, "produced_by", "")
        },
    }
    if stats.get("truncated"):
        # A feed that is missing the producers the run never reached says so, in the cache
        # and in the view: a short feed must not read as a complete one.
        payload["incomplete_reason"] = stop_reason
    stopped = [str(p.get("name")) for p in stats.get("stopped_producers") or [] if p.get("name")]
    if stopped:
        # Item 32: the producers stopped by their own bound, BY NAME, so Home can say which kinds of card this feed is missing.
        # Deliberately not an ``incomplete_reason``: that marker asks for an automatic repair every _MARKER_RETRY_S, and a
        # producer that needs longer than its bound would then be re-run, and re-stopped, every ten minutes for good.
        payload["stopped_producers"] = stopped
        payload["producer_deadline_s"] = PRODUCER_DEADLINE_S
    _write_cache(payload)
    _LOG.info("briefing refreshed: %d cards", len(cards))
    record_card_self_check(payload)
    # Warm the heavy whole-corpus read cache (top / trending / map) in this same
    # background pass, so the Home + Insights surfaces are instant and never trigger
    # a cold multi-second aggregation in the UI (perf, field report 2026-06-18).
    #
    # Not after a memory stop: the warm-up reads more of the corpus, and the run just
    # stopped because the machine was nearly out of memory.
    if not machine_stopped:
        try:
            from src.api.insights import warm_cache

            warm_cache(session)
        except Exception as exc:  # noqa: BLE001 - warming is best-effort, never fatal to the feed
            log_failure(_LOG, "insights cache warm failed; briefing continues", exc, level=logging.WARNING)
    return payload


def _self_check_path() -> Path:
    return _cache_path().with_name("card_quality_selfcheck.jsonl")


def record_card_self_check(payload: dict) -> None:
    """The recurring card self-check: the cheap card quality checks over the feed just written, one line kept in
    ``card_quality_selfcheck.jsonl`` beside the cache (newest 200). The Field data button carries the history; nothing
    is shown on Home. Pure work over the cards in memory (no corpus read), and never fatal to the feed."""
    try:
        from src.briefing.card_audit import check_trigger
        from src.briefing.card_quality import append_history, self_check
        from src.briefing.registry import producers

        per_card = {
            str(c.get("id")): {"arithmetic": check_trigger(c.get("trigger"))}
            for c in payload.get("cards") or [] if isinstance(c, dict)
        }
        record = self_check(payload, registered=[n for n, _p in producers()], per_card=per_card)
        path = _self_check_path()
        lines = path.read_text("utf-8").splitlines() if path.exists() else []
        atomic_replace(path, "\n".join(append_history(lines, record)) + "\n", encoding="utf-8", fsync=False)
    except Exception as exc:  # noqa: BLE001 - a quality check must never break the feed it checks
        log_failure(_LOG, "card self-check not recorded; briefing continues", exc, level=logging.WARNING)


def _write_cache(payload: dict) -> None:
    atomic_replace(_cache_path(), json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", fsync=False)


def _read_cache() -> dict | None:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
        if data.get("version") != CACHE_VERSION and data.get("version") not in _SERVABLE_PRIOR_VERSIONS:
            return None
        return data
    except Exception as exc:  # noqa: BLE001 - a corrupt cache just triggers a recompute
        log_failure(_LOG, "briefing_cache.json unreadable; will recompute", exc, level=logging.WARNING)
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
        # Only the dismissed cards this feed holds: an id kept from a card no producer emits any
        # more is not a card the "Show N dismissed cards" button could bring back.
        "dismissed_count": sum(1 for c in cards if c["id"] in dismissed),
        "buckets": buckets,
        "cards": visible,
    }
    # Why this feed may not be the whole picture (diagnostics rank 4): the last refresh
    # stopped early, either leaving cards out ("incomplete") or leaving this earlier feed
    # in place ("kept"). Absent when the last refresh completed.
    for key in ("incomplete_reason", "kept_reason"):
        if payload.get(key) in ("memory_short", "deadline", "wal_pinned"):
            view[key] = payload[key]
    # Item 32: the kinds of card this feed is missing because their producer was stopped at its time bound, as the catalog's
    # plain labels (a name the catalog does not know is left out, never echoed: the cache is a file on disk).
    stopped = payload.get("stopped_producers")
    if isinstance(stopped, list) and stopped:
        labels = _producer_labels(stopped)
        if labels:
            view["stopped_producers"] = labels
            minutes = payload.get("producer_deadline_s")
            view["producer_deadline_min"] = (
                round(float(minutes) / 60.0) if isinstance(minutes, (int, float)) and minutes > 0
                else round(PRODUCER_DEADLINE_S / 60.0)
            )
    return view


def _producer_labels(names: list) -> list[str]:
    """The catalog's plain label for each known producer name, in order, without repeats. Never raises."""
    try:
        from src.briefing.catalog import spec_for
    except Exception:  # noqa: BLE001 - a missing catalog must never break Home
        return []
    out: list[str] = []
    for name in names[:64]:
        spec = spec_for(name) if isinstance(name, str) else None
        label = getattr(spec, "label", None) if spec is not None else None
        if isinstance(label, str) and label and label not in out:
            out.append(label)
    return out


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
        or _stoplist_wants_refresh(cached)
    )
    need_recompute = force or cached is None or stale
    if need_recompute and background:
        # Off-request: kick one background recompute, serve the current cache meanwhile.
        _ensure_background_refresh()
        payload = cached
    elif need_recompute:
        if stale:
            _LOG.info("briefing cache is stale (corpus grew, an older cache shape, a stop marker to repair, or a new stoplist); recomputing")
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
    except Exception as exc:  # noqa: BLE001 - the tier must never break the feed
        log_failure(_LOG, "corpus_tier failed; omitting from briefing", exc, level=logging.WARNING)
    return view
