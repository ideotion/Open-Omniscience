"""Background-refreshed memo cache for the POLLED alert strip (field test 2026-07-08, Item 8).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Home severity-alert strip polls ``GET /api/signals/alerts`` on a short cadence.
That endpoint runs :func:`src.analytics.alerts.compute_alerts`, which re-scans the
space-time convergence pass (``find_convergences`` over a 45-day lookback) on EVERY
poll — measured p50 23.7 s / p95 60 s over 156 calls on the live 59K-article corpus,
saturating the single worker (the request-death-spiral driver). ``alerts.py`` itself
flagged this ("a shared/memoised convergence pass is a later optimisation, not
correctness"). This module IS that memoisation.

WHAT IT DOES (and, just as importantly, does NOT):
  * It serves the LAST computed :func:`compute_alerts` result for the polled params,
    refreshed in the BACKGROUND (from ``warm_cache`` after each scrape pass / at boot,
    and self-healed off the serve path when it goes stale). The convergence scan is
    NEVER run on the request/event-loop thread beyond the very first cold call.
  * The cached value is the SAME real value ``compute_alerts`` would return — just
    memoised. It is NOT a fabricated or a summarised number. A visible ``as_of`` (and
    ``cache_age_s`` / ``cached``) is attached so the UI can disclose the staleness; the
    ``method``/``caveat`` (still "a transparent rule over locally-cached signals, no
    network") are unchanged — the memoisation adds an as_of, it does not change WHAT is
    computed.

SAFE BY CONSTRUCTION (mirrors :mod:`src.analytics.rollup_serve`):
  * BIND-AWARE. A cache entry records the DB engine (``session.get_bind()``) it was
    computed over; it is only ever served to a session bound to that SAME engine. A
    process-lifetime singleton must never answer for a database it was not built from
    (a test fixture, an ad-hoc connection). Any mismatch → a fresh live compute.
  * FALL BACK TO LIVE on ANY miss — cold cache, bind mismatch, or an error path — so a
    caller always gets a correct answer, at worst slower (the first cold call only).
  * The heavy compute NEVER runs while the lock is held (the lock guards only the tiny
    dict read/write); the self-heal refresh runs on a background thread over its own
    ``session_scope`` and swaps the value in atomically.

No network (``compute_alerts`` reads the local hazard snapshot + local corpus only).
No score anywhere — every figure stays a real count carried straight from
``compute_alerts``.
"""

from __future__ import annotations

import copy
import logging
import os
import threading
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session

_LOG = logging.getLogger(__name__)

# Guards the tiny in-memory cache dict (never held across the heavy compute).
_LOCK = threading.Lock()
# Ensures at most ONE background self-heal refresh runs at a time.
_BUILD_LOCK = threading.Lock()

# key -> {"payload": dict, "built_at": float(epoch), "bind": <engine> | None}
_CACHE: dict[str, dict] = {}
# Only a handful of param combos are ever polled (the UI polls the defaults); bound the
# dict so a stray param sweep can never grow it without limit.
_MAX_KEYS = 8

# The endpoint/UI defaults — the key the background warmer populates and the poll reads.
DEFAULT_WITHIN_HOURS = 48
DEFAULT_HAZARD_MAX_AGE_HOURS = 48
DEFAULT_CONVERGENCE_LOOKBACK_DAYS = 45

# How old a served entry may get before the serve path kicks a background refresh. The
# PRIMARY refresher is ``warm_cache`` (after each scrape pass); this TTL is the self-heal
# floor for an idle-but-polled app. Serving continues (with an honest as_of) regardless
# of age — a stale-but-real value never triggers the request-thread recompute that this
# module exists to prevent. OO_ALERTS_CACHE_TTL_S overrides.
def _ttl_s() -> int:
    try:
        return max(1, int(os.getenv("OO_ALERTS_CACHE_TTL_S", "600")))
    except ValueError:
        return 600


def _key(within_hours: int, hazard_max_age_hours: int, convergence_lookback_days: int) -> str:
    return f"alerts|wh={within_hours}|hz={hazard_max_age_hours}|cv={convergence_lookback_days}"


def _bind_of(session: Session | None) -> object | None:
    try:
        return session.get_bind() if session is not None else None
    except Exception:  # noqa: BLE001 - any doubt -> no bind -> not cacheable/served
        return None


def _same_bind(session: Session | None, built_bind: object | None) -> bool:
    """True only when ``session`` queries the SAME database the entry was built over.

    Mirrors :func:`src.analytics.rollup_serve._same_bind` — the correctness net behind a
    process-lifetime singleton. ``get_db`` and ``session_scope`` both derive from the one
    ``SessionLocal`` bound to the module engine, so a background refresh (via
    ``session_scope`` or ``warm_cache``'s session) matches a request's ``get_db`` session
    in production, while a test fixture on its own engine never does.
    """
    if session is None or built_bind is None:
        return False
    try:
        return session.get_bind() is built_bind
    except Exception:  # noqa: BLE001 - any doubt -> live fallback
        return False


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds")


def _compute(
    session: Session,
    *,
    within_hours: int,
    hazard_max_age_hours: int,
    convergence_lookback_days: int,
) -> dict:
    """Run the real :func:`compute_alerts` (no caching side effect)."""
    from src.analytics.alerts import compute_alerts

    return compute_alerts(
        session,
        within_hours=within_hours,
        hazard_max_age_hours=hazard_max_age_hours,
        convergence_lookback_days=convergence_lookback_days,
    )


def _store(key: str, payload: dict, bind: object | None) -> float | None:
    """Cache ``payload`` under ``key`` with its build time + bind. Returns the build
    epoch, or ``None`` when the bind is unknown (an entry with no bind can never pass the
    bind gate, so it is not worth caching — avoids a dead/unservable slot)."""
    if bind is None:
        return None
    built_at = time.time()
    with _LOCK:
        _CACHE[key] = {"payload": payload, "built_at": built_at, "bind": bind}
        if len(_CACHE) > _MAX_KEYS:
            oldest = min(_CACHE, key=lambda k: _CACHE[k]["built_at"])
            _CACHE.pop(oldest, None)
    return built_at


def _decorate(payload: dict, *, built_at: float, cached: bool, now: float) -> dict:
    """Attach the visible freshness disclosure. Returns a DEEP COPY of the cached payload
    so NO downstream caller can corrupt the cache: ``{**payload, …}`` only copies the TOP
    level, so a caller that mutates a nested list/dict in a served result (e.g. annotating
    convergence rows) would silently corrupt the shared cached object that later serves —
    and followers — reuse. The deep copy makes each serve independent. The alert payload is
    a small, bounded set of convergence clusters, so copying it is negligible next to the
    convergence scan this whole module exists to avoid. Adds NO score field."""
    out = copy.deepcopy(payload)
    out.update(
        {
            "as_of": _iso(built_at),
            "cache_age_s": max(0, int(now - built_at)),
            "cached": bool(cached),
            "cache_note": (
                "Memoised alert strip: the SAME locally-computed result, refreshed in the "
                "background — see as_of for its age. Nothing here is fetched from the network."
            ),
        }
    )
    return out


def get_alerts(
    session: Session,
    *,
    within_hours: int = DEFAULT_WITHIN_HOURS,
    hazard_max_age_hours: int = DEFAULT_HAZARD_MAX_AGE_HOURS,
    convergence_lookback_days: int = DEFAULT_CONVERGENCE_LOOKBACK_DAYS,
) -> dict:
    """The request path for ``GET /api/signals/alerts`` — never recomputes convergence
    on the request thread once warm.

    Serves the memoised ``compute_alerts`` payload (bind-gated) with a visible ``as_of``,
    kicking a background self-heal when it is older than the TTL. On a cold cache OR a
    bind mismatch it falls back to a live compute (once), populates, and returns it. The
    numbers are identical to a direct ``compute_alerts`` call — only the latency (and the
    added as_of/cached disclosure) differs.
    """
    key = _key(within_hours, hazard_max_age_hours, convergence_lookback_days)
    now = time.time()
    with _LOCK:
        entry = _CACHE.get(key)
    if entry is not None and _same_bind(session, entry.get("bind")):
        built_at = entry["built_at"]
        if (now - built_at) > _ttl_s():
            _trigger_self_heal(within_hours, hazard_max_age_hours, convergence_lookback_days)
        return _decorate(entry["payload"], built_at=built_at, cached=True, now=now)
    # Cold cache OR the entry reflects a DIFFERENT database than this caller -> live.
    fresh = _compute(
        session,
        within_hours=within_hours,
        hazard_max_age_hours=hazard_max_age_hours,
        convergence_lookback_days=convergence_lookback_days,
    )
    built_at = _store(key, fresh, _bind_of(session)) or now
    return _decorate(fresh, built_at=built_at, cached=False, now=now)


def refresh_alerts(
    session: Session,
    *,
    within_hours: int = DEFAULT_WITHIN_HOURS,
    hazard_max_age_hours: int = DEFAULT_HAZARD_MAX_AGE_HOURS,
    convergence_lookback_days: int = DEFAULT_CONVERGENCE_LOOKBACK_DAYS,
) -> dict:
    """THE background refresh path (called from ``warm_cache`` after each scrape pass and
    at boot — always on a background thread, so a multi-second convergence scan here never
    touches the request/event-loop thread). Computes ``compute_alerts`` over ``session``
    and stores it keyed by params + the session's bind. Returns the fresh payload."""
    fresh = _compute(
        session,
        within_hours=within_hours,
        hazard_max_age_hours=hazard_max_age_hours,
        convergence_lookback_days=convergence_lookback_days,
    )
    _store(
        _key(within_hours, hazard_max_age_hours, convergence_lookback_days),
        fresh,
        _bind_of(session),
    )
    return fresh


def _kick_background_refresh(
    within_hours: int, hazard_max_age_hours: int, convergence_lookback_days: int
) -> None:
    """Kick ONE background refresh over the PROCESS store (``session_scope``) when no
    refresh is already in flight. Non-blocking; the stale-but-real value keeps being
    served meanwhile. Shared by the ``warm_cache`` hook (:func:`refresh`) and the serve
    path's self-heal (:func:`get_alerts` on a stale entry)."""
    if not _BUILD_LOCK.acquire(blocking=False):
        return  # a refresh is already running

    def _run() -> None:
        try:
            from src.database.session import session_scope

            with session_scope() as s:
                refresh_alerts(
                    s,
                    within_hours=within_hours,
                    hazard_max_age_hours=hazard_max_age_hours,
                    convergence_lookback_days=convergence_lookback_days,
                )
        except Exception:  # noqa: BLE001 - a background accelerator must never crash the app
            _LOG.warning("alert poll-cache background refresh failed", exc_info=True)
        finally:
            _BUILD_LOCK.release()

    threading.Thread(target=_run, name="alerts-poll-refresh", daemon=True).start()


def _trigger_self_heal(
    within_hours: int, hazard_max_age_hours: int, convergence_lookback_days: int
) -> None:
    """Self-heal a STALE served entry off the serve path (for an idle-but-polled app;
    ``warm_cache`` is the primary refresher). Never blocks the request."""
    _kick_background_refresh(within_hours, hazard_max_age_hours, convergence_lookback_days)


def refresh(_session: Session | None = None) -> None:
    """The ``warm_cache`` hook — kick a background (re)build of the DEFAULT-param alert
    payload after each scrape pass / at boot, so the polled strip stays fresh without ever
    paying the convergence scan on the request thread. Mirrors
    :func:`src.analytics.rollup_serve.refresh` / ``map_serve.refresh``: non-blocking, its
    own ``session_scope`` (so it never touches the caller's session), best-effort. The
    ``_session`` argument is accepted for call-site symmetry and intentionally unused."""
    _kick_background_refresh(
        DEFAULT_WITHIN_HOURS, DEFAULT_HAZARD_MAX_AGE_HOURS, DEFAULT_CONVERGENCE_LOOKBACK_DAYS
    )


def status() -> dict:
    """Honest state of the memo cache (for diagnostics/tests). No score."""
    with _LOCK:
        entries = {
            k: {
                "built_at": _iso(v["built_at"]),
                "age_s": max(0, int(time.time() - v["built_at"])),
                "has_bind": v.get("bind") is not None,
            }
            for k, v in _CACHE.items()
        }
    return {"ttl_s": _ttl_s(), "refreshing": _BUILD_LOCK.locked(), "entries": entries}


def clear() -> None:
    """Drop every cached entry (used by tests to stay order-independent)."""
    with _LOCK:
        _CACHE.clear()
