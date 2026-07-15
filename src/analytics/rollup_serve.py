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
  * a FULL rebuild is used (always correct — no incremental double-count trap), and since
    P1.10 (SCALE_ROADMAP 2026-07-09) rebuilds are CHANGE-GATED, not timed: the 12:14 field
    logs showed the blind 15-min TTL churning (62 trending-windows calls / 3,286 s over an
    unchanged corpus). A rebuild now fires when the corpus EPOCH changed (re-index / prune
    / restore — even by another connection) OR the mention tail ADVANCED (max mention id;
    ordinary ingest appends without bumping the epoch, so a pure epoch gate would freeze
    the rollup during collection), throttled to at most one rebuild per
    ``OO_COLUMNAR_SERVE_TTL_S`` (default 15 min), with a LONG backstop rebuild
    (``OO_COLUMNAR_SERVE_BACKSTOP_S``, default 1 h) for change classes the cheap token
    cannot see (cascade deletes, in-place backfills). Staleness stays DISCLOSED (as_of);
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

from src.config.power_profiles import rollup_serve_ttl_s

_LOG = logging.getLogger(__name__)

# Guards the SHARED served connection (DuckDB connections are not thread-safe for
# concurrent execute). Serves hold it for their (fast) query; the build holds it only for
# the instant pointer-swap.
_LOCK = threading.Lock()
# Ensures at most ONE background build runs at a time.
_BUILD_LOCK = threading.Lock()
_STATE: dict = {
    "con": None,
    "built_at": 0.0,
    "rows": 0,
    "bind": None,
    # D1: whether the current served rollup is the PERSISTED encrypted store (survives
    # restarts, refreshed incrementally) or the in-memory fallback (rebuilt per process).
    "persisted": False,
    # P1.10 change gate: the serve_gate.change_token the current build reflects, whether a
    # newer corpus state has been DETECTED (pending -> disclosed as stale), and the last
    # cheap token check (so serves don't re-check on every request).
    "token": None,
    "pending": False,
    "checked_at": 0.0,
}

# P1.10: the old TTL is now the MINIMUM interval between rebuilds (bounds churn while the
# corpus changes continuously during collection). S11: it is read PER SERVE-CHECK via the
# power-profile knob ``rollup_serve_ttl_s()`` (OO_COLUMNAR_SERVE_TTL_S override, else the active
# profile; Optimized = 900, byte-identical to today), so a profile switch is LIVE.
# The LONG backstop: rebuild even with an unchanged token after this long — the honest
# bound on change classes the cheap token cannot see (cascade deletes, in-place backfills).
_BACKSTOP_S = int(os.getenv("OO_COLUMNAR_SERVE_BACKSTOP_S", "3600"))  # 1 h default
# Throttle for the cheap token check itself (3 index-only queries), per serve path.
_CHECK_EVERY_S = 30.0


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


def _persist_passphrase() -> str | None:
    """The corpus passphrase (from the unlocked in-process session) so the served rollup can
    use the PERSISTED encrypted store (D1); None -> the in-memory serve. Set
    ``OO_COLUMNAR_SERVE_PERSIST=0`` to force the in-memory serve even when the secure backend
    + passphrase are available."""
    if os.getenv("OO_COLUMNAR_SERVE_PERSIST") == "0":
        return None
    try:
        from src.database.connect import get_passphrase

        return get_passphrase()
    except Exception:  # noqa: BLE001 - any doubt -> in-memory
        return None


def _persisted_serve_active() -> bool:
    """True when the served rollup should use the PERSISTED encrypted DuckDB store (D1): the
    secure crypto backend is bundled+verified (``secure_crypto_available``) AND the corpus
    passphrase is in memory. False -> the in-memory serve (the fallback). The persisted store
    SURVIVES restarts and refreshes INCREMENTALLY (epoch-gated), so a long-running app never
    pays a per-boot full rebuild. Today the gate is False until the per-OS httpfs binary is
    bundled, so this returns False and the serve stays in-memory (byte-unchanged)."""
    from src.analytics import columnar

    return bool(_persist_passphrase()) and columnar.secure_crypto_available()


def status() -> dict:
    """Honest state of the served rollup (for diagnostics). No score."""
    with _LOCK:
        con = _STATE["con"]
        built_at = _STATE["built_at"]
        rows = _STATE["rows"]
        pending = _STATE["pending"]
        persisted = _STATE["persisted"]
    return {
        "enabled": serve_enabled(),
        "mode": serve_mode(),  # auto | forced-on | forced-off
        "store": "persisted" if persisted else "memory",  # D1: persisted encrypted vs in-memory
        "built": con is not None,
        "built_at": (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(built_at)) if built_at else None
        ),
        "keyword_daily_rows": rows,
        "building": _BUILD_LOCK.locked(),
        # P1.10 change gate: rebuild on CHANGE (epoch / mention tail), not on a timer.
        "refresh": "change-gated",
        "change_pending": pending,
        "min_rebuild_s": rollup_serve_ttl_s(),
        "backstop_s": _BACKSTOP_S,
    }


def _build_inmemory_and_swap() -> None:
    """Build a FRESH in-memory rollup on its own session/connection, then swap it in (a serve
    never touches a half-built store). The in-memory store is rebuilt per process, so a FULL
    build is used (always correct -- no incremental double-count trap). Raises on error (the
    dispatcher logs + releases the build lock)."""
    from src.analytics import columnar, serve_gate
    from src.database.session import session_scope

    con = columnar.connect(passphrase=None)  # no passphrase -> in-memory (never a file)
    if con is None:
        return
    with session_scope() as s:
        # Token BEFORE the build (conservative: rows landing DURING the build make the
        # recorded token compare "changed" next check -> one extra rebuild, never a
        # silently-missed one).
        token = serve_gate.change_token(s)
        columnar.build_keyword_daily(con, s)
        rows = con.execute("SELECT COUNT(*) FROM keyword_daily").fetchone()[0]
        built_bind = s.get_bind()  # the DB this rollup reflects (the process store)
    with _LOCK:
        old = _STATE["con"]
        _STATE["con"] = con
        _STATE["persisted"] = False
        _STATE["built_at"] = time.time()
        _STATE["rows"] = int(rows)
        _STATE["bind"] = built_bind
        _STATE["token"] = token
        _STATE["pending"] = False
        if old is not None:
            try:
                old.close()  # safe: serves hold _LOCK, so none is mid-query here
            except Exception:  # noqa: BLE001
                pass
    _LOG.info("rollup serve: built in-memory keyword_daily (%s rows)", rows)


def _refresh_persisted_build() -> None:
    """Refresh the PERSISTED encrypted rollup store (D1) and serve from it.

    A SINGLE connection is held for the process -- the columnar store's ATTACH open REJECTS a
    second in-process handle to the same file ("Unique file handle conflict"), so the in-memory
    swap model (build a second connection, swap) cannot apply. The store is refreshed EPOCH-
    GATED INCREMENTALLY via ``refresh_keyword_daily``: a full rebuild only on an epoch change
    (re-index / prune / restore) or the first build; otherwise only the appended mention tail is
    merged. Because the persisted FILE survives restarts, a fresh process reopens it and merges
    just the new tail -- no per-boot full rebuild (the D1 durability win).

    The DuckDB connection is not thread-safe, so the refresh + read + state update run under
    ``_LOCK`` (serves also hold ``_LOCK`` for their query, so none reads a half-merge). A serve
    therefore blocks briefly on an incremental merge; a rare FULL rebuild (epoch change) blocks
    longer -- the honest limit, documented; a temp-file swap to remove even that is the deferred
    larger design. First build: ``_STATE["con"]`` is set only AFTER the refresh completes, so a
    serve during the very first build falls back to live (never an empty half-built table)."""
    from src.analytics import columnar, serve_gate
    from src.analytics.corpus_epoch import get_corpus_epoch
    from src.database.session import session_scope

    with _LOCK:
        con = _STATE["con"] if _STATE["persisted"] else None
    opened_now = con is None
    if opened_now:
        con = columnar.connect(passphrase=_persist_passphrase())  # opens the persisted file
    if con is None:
        return  # secure backend / passphrase vanished mid-flight -> in-memory next time
    try:
        with session_scope() as s:
            token = serve_gate.change_token(s)
            epoch = get_corpus_epoch(s)
            with _LOCK:
                columnar.refresh_keyword_daily(con, s, corpus_epoch=epoch)
                rows = con.execute("SELECT COUNT(*) FROM keyword_daily").fetchone()[0]
                _STATE["con"] = con
                _STATE["persisted"] = True
                _STATE["built_at"] = time.time()
                _STATE["rows"] = int(rows)
                _STATE["bind"] = s.get_bind()
                _STATE["token"] = token
                _STATE["pending"] = False
    except Exception:
        if opened_now:  # release the file handle so the next attempt can reopen it cleanly
            try:
                con.close()
            except Exception:  # noqa: BLE001
                pass
        raise
    _LOG.info("rollup serve: refreshed persisted keyword_daily (%s rows)", rows)


def _build_and_swap() -> None:
    """Background (re)build dispatcher: the PERSISTED store when D1 is active, else the
    in-memory store. Always releases the build lock; a failure never crashes the app."""
    try:
        if _persisted_serve_active():
            _refresh_persisted_build()
        else:
            _build_inmemory_and_swap()
    except Exception:  # noqa: BLE001 - a background accelerator must never crash the app
        _LOG.warning("rollup serve: background build failed", exc_info=True)
    finally:
        _BUILD_LOCK.release()


def _trigger_build_async() -> None:
    """Kick a background build if one is not already running (non-blocking)."""
    if not _BUILD_LOCK.acquire(blocking=False):
        return  # a build is already in flight
    threading.Thread(target=_build_and_swap, name="rollup-build", daemon=True).start()


def _maybe_refresh(session: Session, *, force_check: bool = False) -> None:
    """The P1.10 CHANGE GATE — kick a background rebuild only when the corpus visibly
    changed (epoch bumped / mention tail advanced) or the long backstop elapsed; a blind
    timer rebuilt the 20.9 M-mention rollup every 15 min regardless (the measured churn).

    Call ONLY with a session on the SAME bind the rollup was built over (the caller checks
    ``_same_bind`` first) — comparing another database's ids to this rollup's token would
    be meaningless. Never blocks: the token check is 2–3 index-only queries, itself
    throttled to once per ``_CHECK_EVERY_S`` (``force_check`` skips that throttle — the
    post-pass ``refresh`` uses it, a completed pass being a natural batch boundary)."""
    now = time.time()
    with _LOCK:
        built_at = _STATE["built_at"]
        token = _STATE["token"]
        checked_at = _STATE["checked_at"]
    age = now - built_at
    if age > _BACKSTOP_S:
        # The honest bound on change classes the cheap token cannot see (cascade deletes,
        # in-place backfills): rebuild even with an unchanged token.
        with _LOCK:
            _STATE["pending"] = True
        _trigger_build_async()
        return
    if age < rollup_serve_ttl_s():
        return  # churn bound: never rebuild more often than this, however busy ingest is
    if not force_check and now - checked_at < _CHECK_EVERY_S:
        return  # token checked recently -> nothing new to learn yet
    from src.analytics import serve_gate

    cur = serve_gate.change_token(session)
    with _LOCK:
        _STATE["checked_at"] = now
    if cur is None:
        return  # can't tell -> stay on the backstop cadence (never churn on doubt)
    if token is None or cur != token:
        with _LOCK:
            _STATE["pending"] = True
        _trigger_build_async()


def refresh(session: Session | None = None) -> None:
    """(Re)build trigger — called from warm_cache after a scrape pass so the served rollup
    picks up new articles. CHANGE-GATED since P1.10: a pass that changed nothing (or a
    call within the min-rebuild window) no longer forces a full rebuild of the rollup.
    No-op unless enabled. Never blocks."""
    if not serve_enabled():
        return
    with _LOCK:
        have = _STATE["con"] is not None
        built_bind = _STATE["bind"]
    if not have:
        _trigger_build_async()
        return
    if session is None or not _same_bind(session, built_bind):
        # Can't run the cheap check against this rollup -> the old unconditional rebuild
        # (rebuild-on-doubt: freshness is the safe direction; _BUILD_LOCK bounds the cost).
        _trigger_build_async()
        return
    _maybe_refresh(session, force_check=True)


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
    error. Kicks a background (re)build when the rollup is missing or the change gate
    detects a newer corpus state (P1.10), but serves the current one meanwhile (never
    blocks)."""
    if not serve_enabled() or not days:
        return None
    from datetime import date, timedelta

    from src.analytics import columnar

    start = date.today() - timedelta(days=days)
    with _LOCK:
        have = _STATE["con"] is not None
        built_bind = _STATE["bind"]
    if not have:
        _trigger_build_async()  # background; returns immediately
        return None  # nothing built yet -> live fallback (a build is now underway)
    if not _same_bind(_session, built_bind):
        return None  # rollup reflects a DIFFERENT database than this caller -> live fallback
    _maybe_refresh(_session)  # change-gated background rebuild; serves the current build
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
        built_bind = _STATE["bind"]
    if not have:
        _trigger_build_async()
        return None
    if not _same_bind(_session, built_bind):
        return None  # rollup reflects a DIFFERENT database than this caller -> live fallback
    _maybe_refresh(_session)  # change-gated background rebuild; serves the current build
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
    rollup: the source, as-of, age, and — the D3 addition — whether these are the PREVIOUS
    build's numbers being served STALE-BUT-DISCLOSED while a rebuild runs (instead of falling
    back to a full mentions scan). Not a score.

    ``stale`` = a NEWER corpus state is known to exist than the one served (the P1.10
    change gate detected it, or the backstop elapsed); ``rebuilding`` = a background build
    is in flight right now. Either way the numbers are the real previous build's (never a
    blend), with ``as_of`` visible so the staleness is honest."""
    with _LOCK:
        built_at = _STATE["built_at"]
        pending = _STATE["pending"]
        persisted = _STATE["persisted"]
    age_s = (time.time() - built_at) if built_at else None
    stale = bool(built_at) and (pending or (age_s is not None and age_s > _BACKSTOP_S))
    rebuilding = _BUILD_LOCK.locked()
    store_desc = (
        "the persisted encrypted keyword-daily rollup (D1; survives restarts, refreshed "
        "incrementally)" if persisted else "the in-memory keyword-daily rollup"
    )
    note = (
        f"Served from {store_desc} for speed. Mention counts are "
        "exact; article counts are an upper bound (equal under the current one-row-per-"
        "keyword-per-article index). Reflects the corpus as of the last rollup build; "
        "new articles appear after the next background rebuild."
    )
    if stale or rebuilding:
        note += (
            " A rebuild is in progress — these are the PREVIOUS build's numbers, served "
            "stale-but-disclosed (see as_of) rather than falling back to a full mentions "
            "scan; the next build supersedes them."
        )
    return {
        "source": "columnar-rollup",
        "store": "persisted" if persisted else "memory",
        "as_of": (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(built_at)) if built_at else None
        ),
        "age_seconds": int(age_s) if age_s is not None else None,
        "stale": stale,
        "rebuilding": rebuilding,
        "note": note,
    }
