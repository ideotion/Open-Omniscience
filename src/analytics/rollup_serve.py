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
source of truth. THE ONE EXCEPTION IS DUCKDB'S OWN OFFLOAD, and it is decided by the corpus: with
an ENCRYPTED corpus the engine is given no temporary directory, so a build that outgrows its memory
limit is declined instead of writing derived counts to disk; with a plaintext corpus (nothing on
that disk is secret) it may offload into ``<data dir>/duckdb_tmp/<pid>-<id>``, ONE FOLDER PER CONNECTION
(a rebuild stages while the previous rollup is still serving, and two live connections must never share
or empty one folder: DuckDB then fails the serving connection's queries, and in testing crashed the
process), removed when that connection is retired; the folders of processes that are gone are swept at
the next build (in either mode, so a corpus encrypted later does not keep what an earlier, plaintext
build left). The OTHER in-memory stores (the map, the benchmarks) still use DuckDB's own
default for the offload directory: that is recorded in OPEN_QUEUE.md, not changed here.

THE BUILD NEVER TAKES MORE MEMORY THAN THE MACHINE HAS (diagnostics of 2026-10-06: eight 4.81 GiB
VMs killed 12 times inside this build). Four layers, each measured and none a fixed cap: a start
check (the limit DuckDB may use, one batch, and the guard's floor, against what is available now);
the guard polled after every batch; the last build's in-progress marker (``rollup_marker``), so a
build that was killed is not started again identically at every boot; and DuckDB's own memory limit
from the machine's budget. Any of them stops the build as a DECLINE: nothing is swapped in and queries
fall back to live ones. A build that was stopped PART-WAY is not started again until the condition that
stopped it has changed (``_stopped_build_verdict``), or every serve request would rescan the corpus up to
the same point.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
import uuid

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
    # S3.5: the last time the AUTO-ON background build declined to run, and why.
    # None == it has never declined. A skip is a disclosure, never a silent no-op.
    "last_skip": None,
    # What stopped the last build PART-WAY (None once a build has finished): the reason and the numbers
    # the retry rule compares the machine against.
    "stopped": None,
    # The offload folder of the connection in "con" (None when it has none): removed when that
    # connection is replaced.
    "spill": None,
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

    if not columnar.duckdb_available():
        return False
    if serve_mode() == "forced-on":
        return True
    # S1.1: below the RAM floor the in-memory rollup is OFF BY DEFAULT. It is a
    # streamed scan of every keyword mention into RAM, and at export time it was still
    # BUILDING on both field machines with the biggest corpora — an unbounded live cost
    # on exactly the machines least able to pay it. Every serve already falls back to
    # the identical live query, so this costs speed and never an answer. The explicit
    # OO_COLUMNAR_SERVE=1 override is honoured above.
    from src.config.memory_budget import budget

    return bool(budget()["columnar_serve_default"])


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
        last_skip = _STATE["last_skip"]
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
        # S3.5: the last declined AUTO build, with the memory guard's own readings.
        # Absent (None) means it has never declined -- never conflated with "declined
        # and everything was fine".
        "last_skip": last_skip,
    }


def _build_inmemory_and_swap() -> dict | None:
    """Build a FRESH in-memory rollup on its own session/connection, then swap it in (a serve
    never touches a half-built store). The in-memory store is rebuilt per process, so a FULL
    build is used (always correct -- no incremental double-count trap). Raises on error (the
    dispatcher logs + releases the build lock).

    Returns ``None`` when the rollup was built and swapped in, or a skip record when the build was
    STOPPED part-way (the memory guard engaged, or DuckDB reached its own limit with no offload
    allowed): nothing is swapped in and the previous rollup keeps serving."""
    from src.analytics import columnar, rollup_marker, serve_gate
    from src.database.session import session_scope

    # No passphrase -> in-memory (never a file); the offload folder follows the corpus (see the module note).
    spill = _spill_setting()
    con = columnar.connect(passphrase=None, spill=spill)
    if con is None:
        _remove_spill(spill)
        return None
    r = _readings()
    ok = False
    try:
        rollup_marker.begin(rss_mb=r["rss_mb"], avail_mb=r["avail_mb"], limit_mb=_duckdb_limit_mb())
        with session_scope() as s:
            # Token BEFORE the build (conservative: rows landing DURING the build make the
            # recorded token compare "changed" next check -> one extra rebuild, never a
            # silently-missed one).
            token = serve_gate.change_token(s)
            total_hint = _mentions_total(s)
            skip: dict | None
            try:
                columnar.build_keyword_daily(con, s, on_batch=_make_on_batch())
            except columnar.BuildDeclined as stop:
                skip = {"reason": stop.reason, "at": time.time(), **stop.detail}
            except Exception as exc:  # noqa: BLE001
                if type(exc).__name__ != "OutOfMemoryException":
                    raise
                # DuckDB reached its memory limit and may not offload: the bound held, so decline.
                skip = {"reason": "duckdb-limit", "at": time.time(),
                        "duckdb_limit_mb": _duckdb_limit_mb(), "error": str(exc)[:200]}
            else:
                skip = None
            if skip is not None:
                skip.update({
                    "begin_rss_mb": r["rss_mb"], "mentions_total": total_hint,
                    "epoch": token[0] if token else None,
                })
                return skip
            rows = con.execute("SELECT COUNT(*) FROM keyword_daily").fetchone()[0]
            built_bind = s.get_bind()  # the DB this rollup reflects (the process store)
        ok = True
    finally:
        rollup_marker.clear()  # ended by a path Python saw: a marker left behind means a kill
        if not ok:  # a decline or an error: this connection is never served, so it must not leak
            with contextlib.suppress(Exception):
                con.close()
            _remove_spill(spill)  # after the close: DuckDB holds its files open until then
    with _LOCK:
        old = _STATE["con"]
        _STATE["con"] = con
        _STATE["persisted"] = False
        _STATE["built_at"] = time.time()
        _STATE["rows"] = int(rows)
        _STATE["bind"] = built_bind
        _STATE["token"] = token
        _STATE["pending"] = False
        old_spill, _STATE["spill"] = _STATE.get("spill"), spill or None
        if old is not None:
            try:
                old.close()  # safe: serves hold _LOCK, so none is mid-query here
            except Exception:  # noqa: BLE001
                pass
        _remove_spill(old_spill)  # the retired connection's folder, now that nothing uses it
    _LOG.info("rollup serve: built in-memory keyword_daily (%s rows)", rows)
    return None


def _mentions_total(session) -> int | None:
    """The newest mention id: a cheap (index-only) stand-in for how many mentions the build will stream,
    used to project what a stopped build would have taken in total."""
    try:
        from sqlalchemy import text

        v = session.execute(text("SELECT MAX(id) FROM keyword_mentions")).scalar()
        return int(v) if v is not None else None
    except Exception:  # noqa: BLE001
        return None


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


#: What one batch of the build costs in Python while it is being bound, in bytes per row. Measured
#: on the 50,000-row batches of both streams (tuples, the JSON text and the parameters together, short
#: terms): about 300 to 450; 600 leaves room for longer terms. It sizes the start check only.
_CHUNK_ROW_BYTES = 600

#: DuckDB's memory limit counts its buffer pool, not everything it allocates (hash tables of the
#: grouping, the connection's own working memory), so the process grows past it. Measured on a seeded
#: corpus of 12 million mentions and 1.5 million keywords with the limit at 740 MB (a 4.81 GiB
#: machine): the process peaked at 1,193 MB resident, about 120 MB of it already there before the
#: build, so the build added about 1,070 MB, 1.45 times the limit. 1.5 leaves the measured margin.
_LIMIT_OVERSHOOT = 1.5


def _readings() -> dict:
    """This process's resident size and the machine's available memory, in MB (None where unread)."""
    out: dict = {"rss_mb": None, "avail_mb": None}
    try:
        import psutil

        out["avail_mb"] = round(psutil.virtual_memory().available / (1024 * 1024), 1)
        out["rss_mb"] = round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001 - a missing reading is "no information", never a verdict
        pass
    return out


def _guard_floor_mb() -> float:
    try:
        from src.scheduler.memguard import memory_guard

        return float(memory_guard.avail_floor_mb)
    except Exception:  # noqa: BLE001
        return 256.0


def _duckdb_limit_mb() -> float:
    from src.config.memory_budget import budget

    return float(budget()["duckdb_memory_limit_mb"])


def _affordability_verdict() -> dict | None:
    """Decline a build the machine cannot afford at ITS START, from what is measured now.

    The most the build can add is what DuckDB may take (its memory limit, from the machine's own
    budget, times the measured overshoot above; a serving rollup's resident size is already inside the
    available figure), one batch in Python, and the margin the memory guard itself keeps. If that is more than is available the build
    does not start; the readings are returned. Unreadable memory is no evidence: the build proceeds,
    and the guard polled after every batch is the net beneath."""
    try:
        from src.analytics import columnar

        if _persisted_serve_active():
            return None  # the persisted refresh is incremental and does not hold a corpus in memory
        avail = _readings()["avail_mb"]
        if avail is None:
            return None
        limit = _duckdb_limit_mb()
        chunk = columnar.BUILD_BATCH_ROWS * _CHUNK_ROW_BYTES / (1024 * 1024)
        floor = _guard_floor_mb()
        need = limit * _LIMIT_OVERSHOOT + chunk + floor
        if avail >= need:
            return None
        return {
            "reason": "mem-short",
            "at": time.time(),
            "needs_available_mb": round(need, 1),
            "available_mb": avail,
            "duckdb_limit_mb": limit,
            "limit_overshoot": _LIMIT_OVERSHOOT,
            "batch_mb": round(chunk, 1),
            "guard_floor_mb": floor,
        }
    except Exception:  # noqa: BLE001 - an unreadable budget must not block the build
        return None


def _current_epoch() -> int | None:
    """The corpus epoch now (the first element of the serve gate's change token), or None if unreadable."""
    try:
        from src.analytics import serve_gate
        from src.database.session import session_scope

        with session_scope() as s:
            tok = serve_gate.change_token(s)
        return int(tok[0]) if tok else None
    except Exception:  # noqa: BLE001 - unreadable -> no release (the hold stays as it was)
        return None


def _last_build_verdict() -> dict | None:
    """Decline while the machine does not have what a KILLED earlier build held (see rollup_marker)."""
    try:
        from src.analytics import rollup_marker

        if _persisted_serve_active():
            return None
        return rollup_marker.retry_verdict(_readings()["avail_mb"], _guard_floor_mb())
    except Exception:  # noqa: BLE001
        return None


def _stopped_build_verdict() -> dict | None:
    """Decline while the condition that stopped the last build PART-WAY still holds.

    Without it a stopped build is started again by the very next serve request (``windowed_rows`` kicks
    one whenever no rollup is built) and rescans the corpus up to the same point, again and again. Two
    stops, two measured rules and no timer: a corpus that outgrew DuckDB's limit with no offload allowed
    is retried when the budget's limit is LARGER than the one it stopped at; a build the memory guard
    stopped is retried when the machine has what that build had grown by, plus the guard's floor."""
    with _LOCK:
        st = _STATE.get("stopped")
    if not st or _persisted_serve_active():
        return None
    try:
        # A corpus that has been re-indexed, pruned or restored is a different corpus (the epoch moves for
        # exactly those); what stopped the last build says nothing about it, so the hold is released.
        now_epoch = _current_epoch()
        if now_epoch is not None and st.get("epoch") is not None and now_epoch != st["epoch"]:
            with _LOCK:
                _STATE["stopped"] = None
            return None
        if st.get("reason") == "duckdb-limit":
            limit = _duckdb_limit_mb()
            if limit > float(st.get("duckdb_limit_mb") or 0):
                return None
            return {"reason": "duckdb-limit", "at": time.time(), "duckdb_limit_mb": limit,
                    "stopped_at": st.get("at"), "note": "retried when the memory budget's limit grows"}
        avail = _readings()["avail_mb"]
        if avail is None:
            return None
        need = float(st.get("grew_mb") or 0.0) + _guard_floor_mb()
        if avail >= need:
            return None
        return {"reason": "mem-low", "at": time.time(), "stopped_at": st.get("at"),
                "needs_available_mb": round(need, 1), "available_mb": avail,
                "grew_mb": st.get("grew_mb"), "stage": st.get("stage")}
    except Exception:  # noqa: BLE001 - an unreadable budget must not block the build
        return None


def _corpus_encrypted() -> bool:
    """True when the corpus is unlocked under a passphrase (the encrypted-at-rest case)."""
    try:
        from src.database.connect import get_passphrase

        return bool(get_passphrase())
    except Exception:  # noqa: BLE001 - any doubt -> treat as encrypted (the stricter reading)
        return True


#: Set once this process has swept the folders a PREVIOUS process with the same pid left behind (a container
#: restarts as pid 1 every time). After that, this pid's folders are live connections' and are never swept.
_OWN_SPILL_SWEPT = False


def _sweep_spill_folders(root) -> None:
    """Remove the offload folders of processes that are gone (and nothing else): the folders are named
    ``<pid>-<id>``; a folder of THIS pid is swept once, before this process has made any."""
    import shutil

    global _OWN_SPILL_SWEPT
    try:
        import psutil
    except ImportError:
        return  # no way to tell a live process from a dead one: leave them
    mine = os.getpid()
    for child in root.iterdir():
        head = child.name.split("-", 1)[0]
        if not (child.is_dir() and head.isdigit()):
            continue
        pid = int(head)
        if pid == mine:
            if not _OWN_SPILL_SWEPT:
                shutil.rmtree(child, ignore_errors=True)
        elif not psutil.pid_exists(pid):
            shutil.rmtree(child, ignore_errors=True)
    _OWN_SPILL_SWEPT = True


def _remove_spill(path: str | None) -> None:
    """Remove ONE connection's offload folder, after that connection is closed."""
    if path:
        import shutil

        shutil.rmtree(path, ignore_errors=True)


def _spill_setting() -> str:
    """DuckDB's offload directory for the in-memory build: ``""`` (none) for an encrypted corpus, else a NEW
    folder under the data directory for this connection alone. The folders of processes that are gone are
    swept in BOTH cases: one a plaintext build left before the corpus was encrypted is exactly what must
    not stay."""
    encrypted = _corpus_encrypted()
    try:
        from src.paths import data_dir

        global _OWN_SPILL_SWEPT
        root = data_dir() / "duckdb_tmp"
        if root.is_dir():
            _sweep_spill_folders(root)
        _OWN_SPILL_SWEPT = True  # even with no folder to sweep: from here on this pid's folders are live ones
        if encrypted:
            return ""
        root.mkdir(parents=True, exist_ok=True)
        mine = root / f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        mine.mkdir()
        return str(mine)
    except Exception:  # noqa: BLE001 - no folder -> no offload (a decline, never a crash)
        return ""


#: The memory guard counts ``trip_after`` CONSECUTIVE over-threshold samples, tuned for a monitor that
#: samples about once a second. The build asks it after every batch, which at ~560 thousand rows/s is
#: several times a second, so three sub-second spikes would trip the process-wide guard (and pause
#: collection). The hook asks at most this often.
_GUARD_POLL_EVERY_S = 1.0


def _make_on_batch():
    """The per-batch hook of the build: refresh the in-progress marker, then ask the memory guard."""

    last_poll = [0.0]

    def _on_batch(stage: str, rows_done: int) -> None:
        from src.analytics import columnar, rollup_marker

        r = _readings()
        rollup_marker.progress(stage, rows_done, rss_mb=r["rss_mb"], avail_mb=r["avail_mb"])
        now = time.monotonic()
        if now - last_poll[0] < _GUARD_POLL_EVERY_S:
            return
        last_poll[0] = now
        try:
            from src.scheduler.memguard import memory_guard

            poll = getattr(memory_guard, "poll", None)
            if poll is None or not poll():
                return
            st = memory_guard.state()
        except Exception:  # noqa: BLE001 - an unreadable guard must not stop the build
            return
        raise columnar.BuildDeclined("mem-low", {
            "stage": stage,
            "rows_done": rows_done,
            "guard_reason": st.get("reason"),
            "last_reading": st.get("last_reading"),
            "readings_available": st.get("readings_available"),
            "rss_mb": r["rss_mb"],
            "available_mb": r["avail_mb"],
        })

    return _on_batch


def _memory_verdict() -> dict | None:
    """The memory guard's OWN verdict on whether a whole-corpus build should start now.

    Returns a skip record when the guard is engaged, else None. It never computes a
    memory number of its own -- the readings it reports are the guard's, so the two can
    never disagree about the machine. A guard with no readings (no psutil) is BLIND, and
    a blind guard is not evidence of pressure: it reports ``engaged: False`` and the
    build proceeds, which is the honest direction (declining on an absent measurement
    would refuse the build on every core install).
    """
    try:
        from src.scheduler.memguard import memory_guard
        # `engaged` is a PROPERTY, not a method -- calling it raises TypeError, and a
        # bare except here would have swallowed that into "not engaged" forever.
        if not memory_guard.engaged:
            return None
        st = memory_guard.state()
        return {
            "reason": "mem-low",
            "at": time.time(),
            # The guard's own numbers, passed through rather than re-measured.
            "guard_reason": st.get("reason"),
            "last_reading": st.get("last_reading"),
            "readings_available": st.get("readings_available"),
        }
    except Exception:  # noqa: BLE001 - an unreadable guard must not block the build
        return None


def _boot_order_verdict() -> dict | None:
    """Decline while the boot's cache warm-up runs: the three heavy start-up jobs go one after
    the other (``src.api.boot_sequence``), and the sequence builds the rollup itself right after.
    The serve falls back to live queries meanwhile, as it does for memory."""
    from src.api import boot_sequence

    if boot_sequence.warm_running():
        return boot_sequence.heavy_step_verdict()
    return None


def build_now_and_wait() -> str:
    """Build the rollup in the CALLING thread and return when it is done (the boot sequence).

    Returns what happened: ``built``, ``declined`` (memory, an import's exclusive window: the serve
    keeps falling back to live queries and retries on its next check, exactly as for the background
    kick) or ``failed``. When a build a serve kicked was already running, this waits for it
    instead of starting a second and reports THAT build's outcome, so a boot step never shows
    ``done`` for a build that declined or failed. That wait is real (the call blocks on the lock until the
    running build ends), and the one caller, ``boot_sequence._rollup_first_build``, acts on the outcome it
    returns; nothing relies on a rollup existing merely because this returned."""
    if not _BUILD_LOCK.acquire(blocking=False):
        with _BUILD_LOCK:  # the running build releases it in its own finally
            return _LAST_OUTCOME["value"]
    return _build_and_swap()  # releases _BUILD_LOCK


# The outcome of the build that last released _BUILD_LOCK. It is written while the lock is still
# held, so a thread that waited on the lock reads the outcome of the build it waited for.
_LAST_OUTCOME: dict = {"value": "built"}


def _build_and_swap() -> str:
    """Background (re)build dispatcher: the PERSISTED store when D1 is active, else the
    in-memory store. Always releases the build lock; a failure never crashes the app.

    S3.5: declines while the memory guard is engaged. This is the AUTO-ON path only --
    an operator asking for a build explicitly (the rollup benchmark calls
    ``columnar.build_keyword_daily`` directly) is never refused. Skipping leaves the
    previous rollup serving and ``change_pending`` true, so the next check retries; the
    serve also falls back to live queries, so a declined build costs latency, never an
    answer.

    Returns ``built``, ``declined`` or ``failed`` (the background kick ignores it)."""
    outcome = "failed"
    try:
        # TWO reasons to decline, checked in order; the FIRST that fires is recorded, so
        # `last_skip` always names the condition that actually stopped this build rather
        # than whichever check happens to be listed last. S6.1 (2026-09-03) added the
        # exclusive one: this build is kicked from a SERVE, so it never met the collection
        # pause and would happily rebuild a whole-corpus rollup underneath a restore.
        from src.analytics.serve_gate import exclusive_verdict

        skip = (
            exclusive_verdict() or _boot_order_verdict() or _memory_verdict()
            or _stopped_build_verdict() or _last_build_verdict() or _affordability_verdict()
        )
        if skip is not None:
            with _LOCK:
                _STATE["last_skip"] = skip
            _LOG.info(
                "rollup serve: build skipped (%s)",
                skip.get("guard_reason") or skip.get("reason") or "mem-low",
            )
            outcome = "declined"
            return outcome
        if _persisted_serve_active():
            _refresh_persisted_build()
        else:
            stopped = _build_inmemory_and_swap()
            if stopped is not None:
                grew = observed = None
                if isinstance(stopped.get("rss_mb"), (int, float)) and isinstance(
                    stopped.get("begin_rss_mb"), (int, float)
                ):
                    observed = grew = round(max(0.0, stopped["rss_mb"] - stopped["begin_rss_mb"]), 1)
                    # A guard stop happens when memory is ALREADY nearly gone, so what was held at the stop is
                    # the lower bound of what the build needs: project it over the mentions still to stream.
                    done, total = stopped.get("rows_done"), stopped.get("mentions_total")
                    if stopped.get("stage") == "mentions" and isinstance(done, int) and done > 0 \
                            and isinstance(total, int) and total > done:
                        grew = round(observed * total / done, 1)
                with _LOCK:
                    _STATE["last_skip"] = stopped
                    _STATE["stopped"] = {
                        "reason": stopped.get("reason"), "at": stopped.get("at"), "grew_mb": grew,
                        "observed_grew_mb": observed, "epoch": stopped.get("epoch"),
                        "duckdb_limit_mb": stopped.get("duckdb_limit_mb"), "stage": stopped.get("stage"),
                    }
                _LOG.warning(
                    "rollup serve: build stopped part-way (%s); nothing was swapped in and it is not "
                    "retried until that condition changes",
                    stopped.get("guard_reason") or stopped.get("reason"),
                )
                outcome = "declined"
                return outcome
        with _LOCK:
            _STATE["stopped"] = None
        outcome = "built"
        return outcome
    except Exception:  # noqa: BLE001 - a background accelerator must never crash the app
        _LOG.warning("rollup serve: background build failed", exc_info=True)
        outcome = "failed"
        return outcome
    finally:
        _LAST_OUTCOME["value"] = outcome
        _BUILD_LOCK.release()


def _trigger_build_async() -> None:
    """Kick a background build if one is not already running (non-blocking)."""
    if not _BUILD_LOCK.acquire(blocking=False):
        return  # a build is already in flight
    thread = threading.Thread(target=_build_and_swap, name="rollup-build", daemon=True)
    try:
        thread.start()
    except Exception:  # noqa: BLE001 - "can't start new thread" is what a memory-starved machine raises
        # The thread that would have released the lock never ran: release it here, or every later
        # build (and the boot sequence's wait for this one) blocks on it forever.
        _LAST_OUTCOME["value"] = "failed"
        _BUILD_LOCK.release()
        _LOG.warning("rollup serve: could not start the build thread", exc_info=True)


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
