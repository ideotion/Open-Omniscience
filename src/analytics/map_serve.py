"""In-memory serve for the per-country map-coverage aggregation (D4, scaling 5A-bis).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The live ``/api/insights/map-coverage`` query (:func:`queries.source_country_counts`)
re-scans the articles + keyword_mentions tables on EVERY read. The ``source_coverage``
rollup (:mod:`src.analytics.columnar`, D4) is built + parity-tested but was dormant. This
module serves it, mirroring :mod:`src.analytics.rollup_serve` (the keyword_daily serve) — a
ONE process-lifetime in-memory DuckDB rollup, built once in the background, read under a
lock.

AUTOMATIC by default since P1.11 (SCALE_ROADMAP 2026-07-09): the 12:14 field logs made the
map/ring country GROUP BY the #1 slow query — **748 s total, ~150 s/call, max 211 s** on
the live 3.06 M-keyword / 20.9 M-mention corpus — while this serve sat dormant behind its
opt-in flag. Like rollup_serve it now turns itself ON whenever the columnar extra (duckdb)
is installed; ``OO_COLUMNAR_MAP_SERVE`` remains a deployment override (``0`` forces off,
``1`` forces on).

SAFE BY CONSTRUCTION (the same guarantees as rollup_serve):
  * every serve is wrapped — ANY miss/error returns ``None`` and the caller falls back to
    the IDENTICAL live query, so it can never break the map;
  * the build runs in a BACKGROUND thread; until the first build lands, serves fall back;
  * the shared DuckDB connection is lock-guarded (not thread-safe); the build works on its
    OWN connection and swaps it atomically;
  * BIND-AWARE (#572): it only answers for the SAME database the rollup was built over — a
    session on another engine (a test fixture, any ad-hoc connection) falls back to live;
  * numbers are the SAME the live query returns (both derive from the same GROUP BY; the
    unlocated per-language donut is computed live so the payload is byte-identical), with a
    ``basis`` disclosure stating the source + as-of.

In-memory only (never a plaintext file). The canonical SQLCipher store stays the source of
truth; a cold/missing rollup means the seam falls back to the live query.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from sqlalchemy.orm import Session

_LOG = logging.getLogger(__name__)

# Guards the SHARED served connection; the build holds it only for the instant swap.
_LOCK = threading.Lock()
# Ensures at most ONE background build runs at a time.
_BUILD_LOCK = threading.Lock()
_STATE: dict = {"con": None, "built_at": 0.0, "rows": 0, "bind": None}

# Rebuild if the served rollup is older than this (bounded staleness; a full rebuild).
_STALE_S = int(os.getenv("OO_COLUMNAR_MAP_SERVE_TTL_S", "900"))  # 15 min default


def serve_mode() -> str:
    """How the serve is decided: 'forced-on'/'forced-off' via OO_COLUMNAR_MAP_SERVE, else
    'auto' (the default — on whenever the columnar extra is installed). Mirrors
    :func:`rollup_serve.serve_mode`."""
    env = os.getenv("OO_COLUMNAR_MAP_SERVE")
    if env == "1":
        return "forced-on"
    if env == "0":
        return "forced-off"
    return "auto"


def serve_enabled() -> bool:
    """AUTOMATIC by default (P1.11, flipped 2026-07-09 on the 12:14 field measurement:
    the map/ring country GROUP BY was the #1 slow query at ~150 s/call with this serve
    dormant behind its opt-in flag).

    On whenever the columnar extra (duckdb) is available — the same tri-state as
    rollup_serve: ``OO_COLUMNAR_MAP_SERVE=0`` forces off, ``=1`` forces on, unset = auto.
    SAFE by construction: any miss falls back to the identical live query, the rollup
    builds in a background thread, and the bind-aware guard (#572) never answers for a
    database it was not built over."""
    if serve_mode() == "forced-off":
        return False
    from src.analytics import columnar

    return columnar.duckdb_available()


def status() -> dict:
    """Honest state of the served map rollup (for diagnostics). No score."""
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
        "source_coverage_rows": rows,
        "building": _BUILD_LOCK.locked(),
        "ttl_s": _STALE_S,
    }


def _build_and_swap() -> None:
    """Build a FRESH in-memory source_coverage rollup on its own session/connection, swap."""
    try:
        from src.analytics import columnar
        from src.database.session import session_scope

        con = columnar.connect(passphrase=None)  # offline -> in-memory (never a file)
        if con is None:
            return
        with session_scope() as s:
            columnar.build_source_coverage(con, s)
            rows = con.execute("SELECT COUNT(*) FROM source_coverage").fetchone()[0]
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
        _LOG.info("map serve: built in-memory source_coverage (%s rows)", rows)
    except Exception:  # noqa: BLE001 - a background accelerator must never crash the app
        _LOG.warning("map serve: background build failed", exc_info=True)
    finally:
        _BUILD_LOCK.release()


def _trigger_build_async() -> None:
    """Kick a background build if one is not already running (non-blocking)."""
    if not _BUILD_LOCK.acquire(blocking=False):
        return  # a build is already in flight
    threading.Thread(target=_build_and_swap, name="map-rollup-build", daemon=True).start()


def refresh(_session: Session | None = None) -> None:
    """Trigger a background (re)build — called from warm_cache after a scrape pass so the
    served rollup picks up new sources/articles. No-op unless opted in. Never blocks."""
    if serve_enabled():
        _trigger_build_async()


def _same_bind(session: Session | None, built_bind) -> bool:
    """True only when ``session`` queries the SAME database the current rollup was built over
    (#572: a process-lifetime singleton must never answer for a database it was not built
    from). Serving a session bound to a DIFFERENT engine would return another corpus's
    numbers, so those callers fall back to the live query."""
    if session is None or built_bind is None:
        return False
    try:
        return session.get_bind() is built_bind
    except Exception:  # noqa: BLE001 - any doubt -> live fallback
        return False


def map_coverage(session: Session) -> dict | None:
    """The full ``source_country_counts``-shaped dict served from the in-memory
    source_coverage rollup, or ``None`` to fall back to the live query.

    The rollup carries per-country sources / articles / keyword mentions / tone; the
    unlocated per-language donut is computed LIVE from the caller's session (a small
    ``sources -> articles.language`` scan) so the payload is byte-identical to the live
    query. Returns ``None`` (fallback) when: not opted in, the rollup is not built yet, a
    DIFFERENT database than the caller's, empty, or ANY error. Triggers a background
    (re)build when the rollup is missing or stale, serving the current one meanwhile."""
    if not serve_enabled():
        return None
    from src.analytics import columnar

    with _LOCK:
        have = _STATE["con"] is not None
        stale = time.time() - _STATE["built_at"] > _STALE_S
        built_bind = _STATE["bind"]
    if not have or stale:
        _trigger_build_async()  # background; returns immediately
    if not have:
        return None  # nothing built yet -> live fallback (a build is now underway)
    if not _same_bind(session, built_bind):
        return None  # rollup reflects a DIFFERENT database than this caller -> live fallback
    try:
        with _LOCK:
            con = _STATE["con"]
            if con is None:
                return None
            rows = columnar.source_coverage_rows(con)
    except Exception:  # noqa: BLE001 - any serve failure -> live fallback
        _LOG.warning("map serve: source_coverage serve failed; falling back to live", exc_info=True)
        return None
    if not rows:
        return None  # cold/empty rollup -> live fallback
    try:
        return _assemble(session, rows)
    except Exception:  # noqa: BLE001 - reconstruction failure -> live fallback
        _LOG.warning("map serve: reassembly failed; falling back to live", exc_info=True)
        return None


def _assemble(session: Session, rows: list[dict]) -> dict:
    """Reconstruct the exact ``source_country_counts`` shape from the rollup rows plus the
    LIVE unlocated per-language donut. Same by_country ordering as the live query."""
    from src.analytics.queries import unlocated_language_breakdown

    by_country: list[dict] = []
    unlocated: dict[str, object] = {"sources": 0, "articles": 0, "keywords": 0}
    total_sources = 0
    total_articles = 0
    for r in rows:
        total_sources += int(r["sources"])
        total_articles += int(r["articles"])
        if not r["country"]:  # the '' unlocated bucket -> never placed on the map
            unlocated["sources"] = int(r["sources"])
            unlocated["articles"] = int(r["articles"])
            unlocated["keywords"] = int(r["keywords"])
            continue
        by_country.append(
            {
                "country": r["country"],
                "sources": int(r["sources"]),
                "articles": int(r["articles"]),
                "keywords": int(r["keywords"]),
                "sentiment": r["sentiment"],
                "sentiment_n": int(r["sentiment_n"]),
            }
        )
    by_country.sort(key=lambda x: (-x["sources"], x["country"]))  # same order as live
    unlocated["by_language"] = unlocated_language_breakdown(session)  # live -> byte-identical
    return {
        "by_country": by_country,
        "unlocated": unlocated,
        "total_sources": total_sources,
        "total_articles": total_articles,
        "basis": basis(),
    }


def basis() -> dict:
    """The honesty disclosure attached when the response was served from the rollup: the
    source + as-of. Not a score."""
    with _LOCK:
        built_at = _STATE["built_at"]
    return {
        "source": "columnar-rollup",
        "as_of": (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(built_at)) if built_at else None
        ),
        "note": (
            "Served from the in-memory per-country source-coverage rollup for speed. Counts "
            "are exact as of the last rollup build; the unlocated per-language donut is "
            "computed live. New sources/articles appear after the next background rebuild."
        ),
    }
