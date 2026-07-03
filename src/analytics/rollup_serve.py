"""Opt-in in-memory rollup serve for the windowed keyword aggregations (scaling 5A-bis).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The persisted-store speedup (D1) needs per-OS crypto binaries bundled — a packaging step.
This module gives a REAL windowed speedup WITHOUT it, for a long-running app: it holds ONE
process-lifetime in-memory DuckDB ``keyword_daily`` rollup, builds it ONCE in the
background, and serves the windowed most-mentioned rows from it instead of scanning the
multi-GB mentions table each time (the Insights/trends freeze).

AUTOMATIC by default (field ask 2026-07-02) — it turns itself ON whenever the columnar
extra (duckdb) is installed, no flag to flip; ``OO_COLUMNAR_SERVE`` is only a deployment
override (``0`` forces off, ``1`` forces on) and the diagnostics ``columnar`` report shows
the mode + build state so the self-optimisation is observable. SAFE BY CONSTRUCTION:
  * every serve is wrapped — ANY problem returns ``None`` and the caller falls back to the
    live query (identical results, just slower), so it can never break a view;
  * the build runs in a BACKGROUND thread (never blocks a request); until the first build
    finishes, serves fall back to live;
  * the shared DuckDB connection is guarded by a lock (a DuckDB connection is not safe for
    concurrent use); the background build works on its OWN connection and swaps it in
    atomically, so a serve never touches a half-built store;
  * a FULL rebuild is used (always correct — no incremental double-count trap), refreshed
    periodically and after a scrape pass, so new articles appear after the next rebuild;
  * numbers are the SAME the live query would return (mentions exact; the distinct-article
    count is the disclosed upper bound, equal today under the unique keyword+article index)
    — the caller attaches a ``basis`` disclosure stating the source + as-of.

In-memory only (never a plaintext file). The canonical SQLCipher store is always the
source of truth.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from sqlalchemy.orm import Session

_LOG = logging.getLogger(__name__)

# Guards the SHARED served connection (DuckDB connections are not thread-safe for
# concurrent execute). Serves hold it for their (fast) query; the build holds it only for
# the instant pointer-swap.
_LOCK = threading.Lock()
# Ensures at most ONE background build runs at a time.
_BUILD_LOCK = threading.Lock()
_STATE: dict = {"con": None, "built_at": 0.0, "rows": 0, "bind": None}

# Rebuild if the served rollup is older than this (a full rebuild; bounded staleness).
_STALE_S = int(os.getenv("OO_COLUMNAR_SERVE_TTL_S", "900"))  # 15 min default


def serve_mode() -> str:
    """How the serve is decided: 'forced-on'/'forced-off' via OO_COLUMNAR_SERVE, else
    'auto' (the default — on whenever the columnar extra is installed)."""
    env = os.getenv("OO_COLUMNAR_SERVE")
    if env == "1":
        return "forced-on"
    if env == "0":
        return "forced-off"
    return "auto"


def serve_enabled() -> bool:
    """AUTOMATIC by default (field ask 2026-07-02: it should not be a manual env var).

    The windowed keyword speedup turns itself ON whenever the columnar extra (duckdb) is
    available — no flag to flip. It stays SAFE by construction: every serve falls back to
    the identical live query on any miss, and the rollup builds in the background. The
    OO_COLUMNAR_SERVE env var is an explicit override for deployments ('0' forces off,
    '1' forces on); the diagnostics 'columnar' report shows the mode + build state."""
    if serve_mode() == "forced-off":
        return False
    from src.analytics import columnar

    return columnar.duckdb_available()


def status() -> dict:
    """Honest state of the served rollup (for diagnostics). No score."""
    with _LOCK:
        con = _STATE["con"]
        built_at = _STATE["built_at"]
        rows = _STATE["rows"]
    return {
        "enabled": serve_enabled(),
        "mode": serve_mode(),  # auto | forced-on | forced-off
        "built": con is not None,
        "built_at": (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(built_at)) if built_at else None
        ),
        "keyword_daily_rows": rows,
        "building": _BUILD_LOCK.locked(),
        "ttl_s": _STALE_S,
    }


def _build_and_swap() -> None:
    """Build a FRESH in-memory rollup on its own session/connection, then swap it in."""
    try:
        from src.analytics import columnar
        from src.database.session import session_scope

        con = columnar.connect(passphrase=None)  # offline -> in-memory (never a file)
        if con is None:
            return
        with session_scope() as s:
            columnar.build_keyword_daily(con, s)
            rows = con.execute("SELECT COUNT(*) FROM keyword_daily").fetchone()[0]
            built_bind = s.get_bind()  # the DB this rollup reflects (the process store)
        with _LOCK:
            old = _STATE["con"]
            _STATE["con"] = con
            _STATE["built_at"] = time.time()
            _STATE["rows"] = int(rows)
            _STATE["bind"] = built_bind
            if old is not None:
                try:
                    old.close()  # safe: serves hold _LOCK, so none is mid-query here
                except Exception:  # noqa: BLE001
                    pass
        _LOG.info("rollup serve: built in-memory keyword_daily (%s rows)", rows)
    except Exception:  # noqa: BLE001 - a background accelerator must never crash the app
        _LOG.warning("rollup serve: background build failed", exc_info=True)
    finally:
        _BUILD_LOCK.release()


def _trigger_build_async() -> None:
    """Kick a background build if one is not already running (non-blocking)."""
    if not _BUILD_LOCK.acquire(blocking=False):
        return  # a build is already in flight
    threading.Thread(target=_build_and_swap, name="rollup-build", daemon=True).start()


def refresh(_session: Session | None = None) -> None:
    """Trigger a background (re)build — called from warm_cache after a scrape pass so the
    served rollup picks up new articles. No-op unless opted in. Never blocks."""
    if serve_enabled():
        _trigger_build_async()


def _same_bind(session: Session | None, built_bind) -> bool:
    """True only when ``session`` queries the SAME database the current rollup was built
    over. The rollup is built over the process store (``session_scope``); serving it to a
    session bound to a DIFFERENT engine (a test fixture, or any ad-hoc connection) would
    return another corpus's numbers, so those callers fall back to the live query. This is
    the correctness net behind the auto-on serve — a process-lifetime singleton must never
    answer for a database it was not built from."""
    if session is None or built_bind is None:
        return False
    try:
        return session.get_bind() is built_bind
    except Exception:  # noqa: BLE001 - any doubt -> live fallback
        return False


def windowed_rows(
    _session: Session, *, days: int, kind: str | None = None, limit: int = 80
) -> list[dict] | None:
    """The windowed most-mentioned rows served from the in-memory rollup, or ``None`` to
    fall back to the live query. Rows: ``{term, normalized, kind, language, mentions,
    articles}`` ordered by mentions desc (the same shape/order the live windowed query
    produces before the hidden-word / family / ring layers).

    Returns ``None`` (fallback) when: not opted in, the rollup is not built yet, or ANY
    error. Triggers a background (re)build when the rollup is missing or stale, but serves
    the current one meanwhile (never blocks)."""
    if not serve_enabled() or not days:
        return None
    from datetime import date, timedelta

    from src.analytics import columnar

    start = date.today() - timedelta(days=days)
    with _LOCK:
        have = _STATE["con"] is not None
        stale = time.time() - _STATE["built_at"] > _STALE_S
        built_bind = _STATE["bind"]
    if not have or stale:
        _trigger_build_async()  # background; returns immediately
    if not have:
        return None  # nothing built yet -> live fallback (a build is now underway)
    if not _same_bind(_session, built_bind):
        return None  # rollup reflects a DIFFERENT database than this caller -> live fallback
    try:
        with _LOCK:
            con = _STATE["con"]
            if con is None:
                return None
            return columnar.windowed_top_terms_raw(con, start_day=start, kind=kind, limit=limit)
    except Exception:  # noqa: BLE001 - any serve failure -> live fallback
        _LOG.warning("rollup serve: windowed serve failed; falling back to live", exc_info=True)
        return None


def windowed_counts(_session: Session, *, lo, hi) -> dict[int, int] | None:
    """Per-keyword windowed mention SUM for the INCLUSIVE day range ``[lo, hi]`` from the
    rollup, or ``None`` to fall back to the live query. Used by ``trending`` (its recent /
    prior windows) — which is why wiring it also accelerates ``trending_windows`` (the Home
    poll), since that calls ``trending`` per window. Same safety as :func:`windowed_rows`:
    opted-in only, background (re)build, serves the current build meanwhile, any error ->
    ``None``."""
    if not serve_enabled():
        return None
    from src.analytics import columnar

    with _LOCK:
        have = _STATE["con"] is not None
        stale = time.time() - _STATE["built_at"] > _STALE_S
        built_bind = _STATE["bind"]
    if not have or stale:
        _trigger_build_async()
    if not have:
        return None
    if not _same_bind(_session, built_bind):
        return None  # rollup reflects a DIFFERENT database than this caller -> live fallback
    try:
        with _LOCK:
            con = _STATE["con"]
            if con is None:
                return None
            counts = columnar.windowed_term_counts(con, start_day=lo, end_day=hi)
        return {kid: mv[0] for kid, mv in counts.items()}  # mentions only (exact)
    except Exception:  # noqa: BLE001 - any serve failure -> live fallback
        _LOG.warning("rollup serve: windowed counts failed; falling back to live", exc_info=True)
        return None


def basis(_days: int) -> dict:
    """The honesty disclosure the caller attaches when a response was served from the
    rollup: the source + as-of + the upper-bound note. Not a score."""
    with _LOCK:
        built_at = _STATE["built_at"]
    return {
        "source": "columnar-rollup",
        "as_of": (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(built_at)) if built_at else None
        ),
        "note": (
            "Served from the in-memory keyword-daily rollup for speed. Mention counts are "
            "exact; article counts are an upper bound (equal under the current one-row-per-"
            "keyword-per-article index). Reflects the corpus as of the last rollup build; "
            "new articles appear after the next background rebuild."
        ),
    }
