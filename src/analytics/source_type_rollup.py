"""In-memory serve for ``/api/insights/source-types`` (D3, 2026-09-11).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field diagnostics measured ``queries.source_type_facets`` -- a
``COALESCE(sources.source_type), COUNT(articles.id) ... GROUP BY`` over the
articles/sources join -- as the single slowest aggregate in the whole perf bundle:
48,471.9 ms worst-case, p50 7,181.9 ms behind ``/api/insights/source-types``. Unlike
``/api/database/stats``/``/api/database/figures`` (already fixed via
:mod:`src.api.served_cache`'s serve-stale pattern), this endpoint's TTL/deadline
cache (``src.api.insights._deadlined``) only shortens the pain BETWEEN misses; on a
cold or expired entry the request thread still pays the full scan.

Mirrors :mod:`src.analytics.source_country_rollup` -- read that module's docstring
for the shared shape (this one repeats only what differs) -- with TWO changes
forced by this aggregate's own cost profile:

1. THE COMPUTE IS REUSED VERBATIM, NEVER RE-IMPLEMENTED. ``source_type_facets``'s
   own docstring states, as a PROPERTY found by adversarial review, that its count
   EQUALS what clicking the facet returns from ``/api/articles`` -- which is exactly
   why it filters ``Article.quarantined.isnot(True)``. ``Source.article_count`` (the
   denormalised per-source counter ``reconcile_source_counters`` already maintains,
   and the obvious-looking shortcut here) does NOT carry that exclusion, so serving
   from it would silently break the stated equality. :func:`_live_source_type_facets`
   therefore calls ``queries.source_type_facets`` unchanged -- the served payload can
   never drift from what the live query (still the fallback on any miss) returns.

2. THE REBUILD IS GATED ON A CHANGE TOKEN, unlike ``source_country_rollup``'s
   unconditional-every-300s refresh. That module's own docstring justifies going
   unconditional because ``sources`` rows are few (hundreds-thousands); THIS
   aggregate scans ``articles`` (1.34M measured), so an unconditional rebuild every
   ``OO_MAINT_INTERVAL_S`` (default 300s) would trade one slow endpoint for a
   permanent background cost paid whether or not anything changed. The gate mirrors
   ``columnar.refresh_source_coverage`` (the DuckDB rollups' own change-token
   precedent, alongside :mod:`src.analytics.corpus_epoch`): a plain ``MAX(Article.id)``
   read is a single indexed lookup (the primary key) -- negligible next to the GROUP
   BY it gates -- compared against the watermark recorded at the last real build.
   Unchanged watermark AND unchanged corpus epoch -> :func:`refresh` returns without
   touching ``articles``/``sources`` at all.

   NOT a complete change detector, and that is a stated, accepted trade rather than
   an oversight: the watermark sees ordinary ingest (the dominant driver of this
   facet's answer) and, via the corpus-epoch check, a re-index/prune/restore. It
   does NOT see a source's ``source_type`` hand-edited with no new article ingested,
   or an article's quarantine flag flipped in isolation with none ingested since --
   both rare, operator-driven edits, against the 1.34M-row rescan they would each
   otherwise cost every idle window. The staleness this can leave is disclosed via
   ``basis.as_of``, exactly like the interval-driven staleness every other rollup
   here discloses, never hidden.

SAFE BY CONSTRUCTION, BIND-AWARE, CORPUS-EPOCH-AWARE: identical contract to
``source_country_rollup`` -- see that module's docstring for why each matters.
"""

from __future__ import annotations

import copy
import threading
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

_LOCK = threading.Lock()
_STATE: dict = {
    "payload": None,
    "bind": None,
    "built_at": None,
    "epoch": None,
    "watermark": None,
}

# Matches OO_MAINT_INTERVAL_S's default (src.scheduler.runner) -- disclosed in
# basis() so a viewer knows the worst-case CHECK cadence. Unlike
# source_country_rollup, this is not a bound on staleness by itself: a rebuild at
# this cadence is only a REAL rebuild when the change token (below) actually moved.
_REFRESH_INTERVAL_S = 300


def _live_source_type_facets(session: Session) -> dict:
    """The exact live compute ``queries.source_type_facets`` -- reused verbatim (see
    the module docstring point 1) so the served payload and the live fallback can
    never drift apart."""
    from src.analytics.queries import source_type_facets

    return source_type_facets(session)


def _same_bind(session: Session | None, built_bind) -> bool:
    """True only when ``session`` queries the SAME database the current rollup was
    built over (mirrors ``source_country_rollup._same_bind``/``map_serve._same_bind``)."""
    if session is None or built_bind is None:
        return False
    try:
        return session.get_bind() is built_bind
    except Exception:  # noqa: BLE001 - any doubt -> live fallback
        return False


def _current_epoch(session: Session) -> int:
    """The corpus epoch, degrading to ``0`` (never-bumped) on any read failure --
    mirrors ``source_country_rollup._current_epoch``. A failure here must never
    break :func:`refresh`/:func:`served`."""
    try:
        from src.analytics.corpus_epoch import get_corpus_epoch

        return get_corpus_epoch(session)
    except Exception:  # noqa: BLE001 - a coordination read must never break its caller
        return 0


def _article_watermark(session: Session) -> int:
    """``MAX(Article.id)`` -- the cheap change token :func:`refresh` gates its
    rebuild on (module docstring point 2). Degrades to ``0`` on any read failure,
    the same direction ``_current_epoch`` degrades in: an unreadable watermark
    just means the next call rebuilds (safe), never that it wrongly skips one."""
    try:
        from src.database.models import Article

        return int(session.query(func.max(Article.id)).scalar() or 0)
    except Exception:  # noqa: BLE001 - a coordination read must never break its caller
        return 0


def refresh(session: Session) -> dict:
    """Rebuild the rollup ONLY when the change token moved since the last build (or
    there is no prior build) -- called from ``run_idle_maintenance`` every off-peak
    pass, same cadence as ``source_country_rollup.refresh``, but a no-op on an
    idle/unchanging corpus: the watermark + epoch reads never touch the expensive
    join. Returns ``{"rebuilt": bool}`` so the caller can report which happened,
    honestly, rather than always claiming a refresh occurred.
    """
    epoch = _current_epoch(session)
    watermark = _article_watermark(session)
    with _LOCK:
        stale = (
            _STATE["payload"] is None
            or _STATE["epoch"] != epoch
            or _STATE["watermark"] != watermark
        )
    if not stale:
        return {"rebuilt": False}
    payload = _live_source_type_facets(session)
    with _LOCK:
        _STATE["payload"] = payload
        _STATE["bind"] = session.get_bind()
        _STATE["built_at"] = datetime.now(UTC)
        _STATE["epoch"] = epoch
        _STATE["watermark"] = watermark
    return {"rebuilt": True}


def served(session: Session) -> dict | None:
    """The ``source_type_facets``-shaped payload served from the in-memory rollup,
    or ``None`` to fall back to the live query. ``None`` on: never built yet, a
    session bound to a DIFFERENT database, a corpus epoch bump since the rollup was
    built (a restore/re-index/prune), or any internal error -- never a fabricated
    or wrong value (this function must itself never raise, so its whole body is
    guarded, mirroring ``source_country_rollup.served``)."""
    try:
        with _LOCK:
            payload = _STATE["payload"]
            built_bind = _STATE["bind"]
            built_at = _STATE["built_at"]
            built_epoch = _STATE["epoch"]
        if payload is None or not _same_bind(session, built_bind):
            return None
        if built_epoch != _current_epoch(session):
            return None
        # A shallow dict(payload) would share the nested `facets` list with the
        # singleton across every caller until the next refresh -- deep-copy so a
        # returned response is always this caller's own to mutate (mirrors
        # source_country_rollup.served's identical skeptic-found guard).
        out = copy.deepcopy(payload)
        out["basis"] = {
            "source": "rollup",
            "as_of": built_at.isoformat(timespec="seconds") if built_at else None,
            "refresh_interval_s": _REFRESH_INTERVAL_S,
        }
        return out
    except Exception:  # noqa: BLE001 - the documented contract: never raise, always fall back
        return None


def _reset_for_tests() -> None:
    """Drop the process-global rollup singleton (test hook) -- the same
    order-dependent-pollution class ``source_country_rollup._reset_for_tests``
    guards against: a test that calls ``refresh()`` against the shared real engine
    would otherwise leave a WARM rollup a later, unrelated test sees via the same
    bind."""
    with _LOCK:
        _STATE["payload"] = None
        _STATE["bind"] = None
        _STATE["built_at"] = None
        _STATE["epoch"] = None
        _STATE["watermark"] = None
