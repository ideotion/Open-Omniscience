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
from src.monitoring.secret_scrub import log_failure, record_text

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
    # The last decline that SAYS SOMETHING ABOUT THIS MACHINE OR CORPUS, kept until another one replaces it (see
    # ``_note_decline``). ``last_skip`` is overwritten by every later check, and every windowed serve that finds no
    # rollup re-runs the verdicts, so a diagnostics run's own ``exclusive-hold`` hid the reason the boot's build
    # stopped (the 2026-10-16 bundle: declined after 921 s, reason lost). None == no such decline yet.
    "last_decline": None,
    # How the last FINISHED in-memory build ran: the shard count it used, what the model predicted for it, DuckDB's own
    # total read between shards, and how long it took (see ``columnar.plan_build_shards``). None until one finishes.
    "last_build": None,
    # How the last build that ENDED ended in this process (built / declined / failed; None until one ends), and the run of builds that
    # ended "failed" since one last served (R172). ``failure_class`` is the exception CLASS NAME of the last of them, never its text.
    "last_outcome": None,
    "failures": 0,
    "failure_class": None,
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


def serving_state() -> dict:
    """Whether the keyword rollup is answering reads RIGHT NOW: ``enabled`` (the serve is on for this install),
    ``built`` (a rollup is held) and ``serving`` (both). Read once per card-audit pass to decide whether the
    producers that need it can be run; a read of two fields, no scan, no network."""
    enabled = bool(serve_enabled())
    with _LOCK:
        built = _STATE["con"] is not None
    return {"enabled": enabled, "built": built, "serving": enabled and built}


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
    with contextlib.suppress(Exception):  # a diagnostics field must never fail the status
        _stopped_hold()  # a stop an earlier process kept is part of the state, before any build has looked at it
    with _LOCK:
        con = _STATE["con"]
        built_at = _STATE["built_at"]
        rows = _STATE["rows"]
        pending = _STATE["pending"]
        persisted = _STATE["persisted"]
        last_skip = _STATE["last_skip"]
        stopped = dict(_STATE["stopped"]) if _STATE["stopped"] else None
        last_decline = dict(_STATE["last_decline"]) if _STATE["last_decline"] else None
        last_build = dict(_STATE["last_build"]) if _STATE.get("last_build") else None
        last_outcome = _STATE.get("last_outcome")
    failures, failure_class = _failure_view()
    out = {
        "enabled": serve_enabled(),
        "mode": serve_mode(),  # auto | forced-on | forced-off
        "store": "persisted" if persisted else "memory",  # D1: persisted encrypted vs in-memory
        "built": con is not None,
        "built_at": (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(built_at)) if built_at else None
        ),
        "keyword_daily_rows": rows,
        "building": _BUILD_LOCK.locked(),
        "build_progress": build_progress(),
        # P1.10 change gate: rebuild on CHANGE (epoch / mention tail), not on a timer. (The constant ``refresh: "change-gated"`` that stood
        # here is gone: it was the same string in every report, and R172 needed the bytes. The refresh is change-gated, always.)
        "change_pending": pending,
        "min_rebuild_s": rollup_serve_ttl_s(),
        "backstop_s": _BACKSTOP_S,
        # S3.5: the last declined AUTO build, with the memory guard's own readings.
        # Absent (None) means it has never declined -- never conflated with "declined
        # and everything was fine".
        "last_skip": last_skip,
        # What stopped the last build PART-WAY, while that hold is in force (the retry rule compares the machine
        # against it); None when no build was stopped or the hold was released.
        "stopped": stopped,
        # The last decline that is a statement about this machine or corpus (a memory verdict, a stopped build,
        # an unaffordable start, a killed earlier build), NOT an import's exclusive window or the boot's ordering,
        # and not replaced by the same reason being found again (``repeats`` counts that). Separate from
        # ``last_skip`` on purpose: that one is whatever declined most recently.
        "last_decline": last_decline,
        # How the last build that finished was cut and what it cost, to be read against ``build_budget``.
        "last_build": last_build,
        # The numbers a build is held to, so a stop can be read against them: DuckDB's limit for this tier and
        # whether it may offload to disk (it may not for an encrypted corpus, so the limit is a wall there).
        "build_budget": _build_budget(),
        # Served queries the engine refused and the live scan answered instead (since the process started): a serve
        # that falls back is correct and, without this, invisible. A rollup that fails the build's own check is a
        # stop, not a count here; this is the wider windows that fail later.
        "serve_fallbacks": _serve_fallbacks(),
    }
    # R172, the failure fields: ABSENT MEANS ZERO FAILURES SINCE THE LAST BUILD THAT SERVED (a reader must not read absence as unknown). Present
    # when the run is above 0: how the last build ended in this process, the run itself (carried over a restart by the kept record) and the
    # exception CLASS NAME of the last failure (never its text). The ``stage`` of a failure hold is the LAST REPORTED stage, not the raising statement.
    if failures > 0:
        out["last_outcome"] = last_outcome
        out["consecutive_failures"] = failures
        out["last_failure_class"] = failure_class
    return out


def _serve_fallbacks() -> dict:
    from src.analytics import columnar

    return columnar.serve_fallback_counts()


#: The fields of a decline that go into another report's row (the boot step's): codes and numbers a reader compares
#: against the budget. Free text of the engine is never among them.
_DETAIL_FIELDS = ("reason", "source", "kind", "stage", "at", "rows_done", "duckdb_limit_mb", "grew_mb",
                  "needs_available_mb", "available_mb", "guard_reason", "restored", "repeats", "shards", "shard", "split",
                  "duckdb_threads", "budget_total_mb", "budget_read_at", "query", "peak_mib", "resident_mib", "engine_error_class",
                  "consecutive_failures", "stage_why")


def decline_detail() -> dict:
    """Why the last build declined, for the boot step's row. The record of the build that just declined when it
    declined on the MOMENT (an exclusive window, the boot's ordering: those never reach ``last_decline``, so the
    sticky one would name an older, different reason). Otherwise the sticky ``last_decline`` when there is one (a
    machine- or corpus-level reason, with the stage and numbers a bare echo of it lacks), else whatever declined last."""
    with _LOCK:
        skip = _STATE["last_skip"]
        rec = skip if skip and skip.get("source") in _TRANSIENT_VERDICTS else (_STATE["last_decline"] or skip)
        rec = dict(rec) if rec else None
        stopped = dict(_STATE["stopped"]) if _STATE["stopped"] else None
    if rec is None:
        return {"reason": "unknown", "note": "the build reported a decline but no record of one was kept"}
    out = {k: rec[k] for k in _DETAIL_FIELDS if isinstance(rec.get(k), (str, int, float, bool))}
    if stopped and stopped.get("restored"):
        out["restored"] = True
    return out


def _build_budget() -> dict:
    try:
        return {"duckdb_limit_mb": _duckdb_limit_mb(), "offload_allowed": not _corpus_encrypted()}
    except Exception:  # noqa: BLE001 - a diagnostics field must never fail the status
        return {"duckdb_limit_mb": None, "offload_allowed": None}


#: The verdicts whose decline is about the moment, not about the machine: an exclusive window (a restore, an
#: import, the diagnostics bundle) and the boot's start-up ordering. They are recorded in ``last_skip`` only.
_TRANSIENT_VERDICTS = frozenset({"exclusive", "boot-order"})


def _note_decline(kind: str, source: str, record: dict) -> None:
    """Keep ``record`` as ``last_decline``. A verdict that finds the reason of a build that was STOPPED part-way
    again (every serve request re-runs the verdicts) only counts: the stop's own record, with the stage and the
    numbers it stopped at, is what a reader needs and must not be replaced by its echo."""
    with _LOCK:
        cur = _STATE["last_decline"]
        # The stop's own record is the "stopped" one in the process that ran the build; in a process that restored
        # it from disk the first echo IS the record (kind "skipped", source "stopped"), and later echoes fold into it.
        if (kind == "skipped" and cur is not None and cur.get("reason") == record.get("reason")
                and (cur.get("kind") == "stopped" or (cur.get("source") == "stopped" and source == "stopped"))):
            cur["repeats"] = int(cur.get("repeats") or 0) + 1
            cur["last_seen_at"] = record.get("at")
            return
        _STATE["last_decline"] = {"kind": kind, "source": source, **record, "repeats": 0}


def _compact_stop(compact: dict) -> dict:
    """The stop record for a rollup whose compacting checkpoint hit DuckDB's own limit (a FATAL allocation error, R164).

    ``duckdb-limit`` so the release rules of that stop apply unchanged. Sizes read BEFORE it (the instance is invalid
    afterwards) and the error class, as numbers and codes only."""
    return {"reason": "duckdb-limit", "at": time.time(), "stage": "compact", "resident_mib": compact.get("resident_before_mib"),
            "engine_error_class": compact.get("reason")}


def _serve_check_stop(canary: dict) -> dict:
    """The stop record for a rollup that was built and cannot answer: DuckDB's own limit, found at the serve check.

    ``duckdb-limit`` so the release rules of that stop apply unchanged (a larger limit, offload allowed, a corpus 5%
    smaller, another version). Names the query, its peak and the resident size, as numbers and codes only."""
    return {"reason": "duckdb-limit", "at": time.time(), "stage": "serve-check", "query": canary.get("query"),
            "peak_mib": canary.get("peak_mib"), "resident_mib": canary.get("resident_mib"),
            "engine_error_class": canary.get("error_class")}


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
    # R147: the budget is read ONCE, here, and this build (its connection, its shard size, its stop record) lives on
    # this snapshot. Nothing below asks the budget for the limit again.
    snap = columnar.budget_snapshot()
    try:
        con = columnar.connect(passphrase=None, spill=spill, snapshot=snap)
    except BaseException:
        _remove_spill(spill)
        raise
    if con is None:
        _remove_spill(spill)
        return None
    r = _readings()
    ok = False
    _progress_begin()
    try:
        rollup_marker.begin(rss_mb=r["rss_mb"], avail_mb=r["avail_mb"], limit_mb=snap["duckdb_limit_mb"])
        with session_scope() as s:
            # Token BEFORE the build (conservative: rows landing DURING the build make the
            # recorded token compare "changed" next check -> one extra rebuild, never a
            # silently-missed one).
            token = serve_gate.change_token(s)
            # the token's second element IS the newest mention id (read in this same session already)
            total_hint = int(token[1]) if token and len(token) > 1 and token[1] is not None else None
            skip: dict | None
            tally: dict = {}
            build_started = time.monotonic()
            try:
                tally = columnar.build_keyword_daily(con, s, on_batch=_make_on_batch(), snapshot=snap)
            except columnar.BuildDeclined as stop:
                skip = {"reason": stop.reason, "at": time.time(), **stop.detail}
            except Exception as exc:  # noqa: BLE001
                if type(exc).__name__ != "OutOfMemoryException":
                    raise
                # DuckDB reached its memory limit and may not offload: the bound held, so decline.
                skip = {"reason": "duckdb-limit", "at": time.time(),
                        "duckdb_limit_mb": snap["duckdb_limit_mb"], "error": record_text(exc, limit=200)}
            else:
                # R157: a rollup that fits its limit can still leave no room for the query that uses it. Ask it the
                # one question the serve asks first (the 30-day terms), now, on the connection nobody else holds.
                # R164: first store what was built compressed (the in-memory rollup is otherwise held uncompressed).
                compact = columnar.compact(con)
                if compact["outcome"] == "fatal":
                    raise RuntimeError("compacting the rollup found the DuckDB instance unusable")
                if compact["outcome"] == "out-of-memory":
                    skip = _compact_stop(compact)
                else:
                    canary = columnar.serve_canary(con)
                    if canary["outcome"] == "fatal":
                        # a FATAL engine error leaves the instance unusable: never served, never retried on (a plain failure)
                        raise RuntimeError("the serve check found the DuckDB instance unusable")
                    skip = _serve_check_stop(canary) if canary["outcome"] == "out-of-memory" else None
            if skip is not None:
                skip.update({
                    # the limit and the machine total this build ran under, whatever stopped it (R147)
                    "duckdb_limit_mb": snap["duckdb_limit_mb"], "duckdb_threads": snap["duckdb_threads"],
                    "budget_total_mb": snap["total_mb"], "budget_read_at": snap["read_at"],
                    "begin_rss_mb": r["rss_mb"], "mentions_total": total_hint,
                    "epoch": token[0] if token else None,
                    # what the wall was measured against, so a corpus that has SHRUNK since is told from one that
                    # has only changed (the hold's release rule compares it; None when the count is unreadable)
                    "mentions_count": _count_in(s),
                })
                return skip
            rows = con.execute("SELECT COUNT(*) FROM keyword_daily").fetchone()[0]
            built_bind = s.get_bind()  # the DB this rollup reflects (the process store)
        ok = True
    finally:
        if not ok:
            _remember_stage()  # the stage the build had reached, for a failure hold: the progress record is gone after this
        _progress_end()
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
        _STATE["last_build"] = {
            "at": time.time(), "build_s": round(time.monotonic() - build_started, 1),
            "streamed_mentions": tally.get("streamed_mentions"), "keyword_daily_rows": int(rows),
            "shards": tally.get("shards"), "shard_splits": tally.get("shard_splits"),
            "predicted_peak_mib": tally.get("predicted_peak_mib"), "observed_mib": tally.get("observed_mib"),
            "shard_checkpoints": tally.get("shard_checkpoints"), "shard_checkpoint_secs": tally.get("shard_checkpoint_secs"),
            "shard_checkpoint_failures": tally.get("shard_checkpoint_failures"),
            "shard_checkpoint_first_failure": tally.get("shard_checkpoint_first_failure"),
            "duckdb_limit_mb": snap["duckdb_limit_mb"], "duckdb_threads": snap["duckdb_threads"],
            "budget_total_mb": snap["total_mb"], "budget_read_at": snap["read_at"],
            # what the finished rollup was asked before it was served, and what that cost (R157)
            "serve_check": canary,
            # whether the rollup was stored compressed before it was asked, and why not when it was not (R164)
            "compact": compact,
        }
        old_spill, _STATE["spill"] = _STATE.get("spill"), spill or None
        if old is not None:
            try:
                old.close()  # safe: serves hold _LOCK, so none is mid-query here
            except Exception:  # noqa: BLE001
                pass
        _remove_spill(old_spill)  # the retired connection's folder, now that nothing uses it
    _LOG.info("rollup serve: built in-memory keyword_daily (%s rows)", rows)
    return None


def columnar_batch_mb() -> float:
    """What one batch of the build costs in Python, in MB (the start check's own figure)."""
    from src.analytics import columnar

    return columnar.BUILD_BATCH_ROWS * _CHUNK_ROW_BYTES / (1024 * 1024)


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
        if _persisted_serve_active():
            return None  # the persisted refresh is incremental and does not hold a corpus in memory
        avail = _readings()["avail_mb"]
        if avail is None:
            return None
        limit = _duckdb_limit_mb()
        chunk = columnar_batch_mb()
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


def _count_in(session: Session) -> int | None:
    try:
        from sqlalchemy import func

        from src.database.derived_views import KeywordMentionRead

        return int(session.query(func.count(KeywordMentionRead.id)).scalar() or 0)
    except Exception:  # noqa: BLE001
        return None


def _current_mention_count() -> int | None:
    """How many keyword mentions the corpus holds now, or None if unreadable (an index-only count, read in the
    background build thread and only when the stop's hold asks for it)."""
    try:
        from sqlalchemy import func

        from src.database.derived_views import KeywordMentionRead
        from src.database.session import session_scope

        with session_scope() as s:
            return int(s.query(func.count(KeywordMentionRead.id)).scalar() or 0)
    except Exception:  # noqa: BLE001 - unreadable -> no release (the hold stays as it was)
        return None


#: The version of the BUILD's own memory behaviour, bumped by whoever changes it (the chunked load, the batch size, the
#: DuckDB settings it opens with). A stop kept on disk says what THAT code could not do on this machine; once the app
#: version or this number differs the record is released, or a stop recorded before a fix would keep the rollup off
#: after the upgrade until the limit grew. A kept record from before this field existed has neither, so it is released too.
#: 2 (2026-10-16): the aggregate is sharded and each stage dropped as it is aggregated (``columnar.plan_build_shards``);
#: every stop kept by version 1 was the single GROUP BY meeting the limit and is released.
#: 3 (2026-10-17): a CHECKPOINT before each shard's aggregate (R169) builds corpora that version 2 stopped on DuckDB's limit
#: (20 M mentions at 1,004 MB), so every stop kept by version 2 is released and the build is tried again.
BUILD_CODE_VERSION = 3

#: How much smaller than at the stop the corpus must be before a stop on DuckDB's limit is tried again. WHAT IT PROTECTS:
#: repeated stop/retry cycles near the limit (each a ~15-minute scan that ends at the same wall). The wall is
#: the limit against the corpus, and a re-index drain under a longer stoplist or one pruned article moves the count by
#: a handful of mentions while the same ~15-minute scan would stop at the same wall: a release per mention would be the
#: rescan loop again. What the build needs is not measured at a stop (only that it did not fit), so this is a
#: judgement, not a measurement: 5% is more than the churn of a drain and small enough that a real prune clears it. If
#: it is wrong the cost is a held rollup, which a larger limit, offload becoming allowed, or another version releases.
_SHRINK_TO_RETRY = 0.05

#: The shortest gap between two counts of the whole mention table for this hold (seconds). The rebuild TTL may be set
#: to 0, and the epoch moves on every 300-article call of a re-index drain; a COUNT is a read of the whole table.
_COUNT_MIN_INTERVAL_S = 60.0

#: The reasons of a hold released by what changes the WALL (a larger limit, offload allowed, a smaller corpus, another version): the build ran into the
#: engine's limit, or ended in an error of its own (R172). One rule for both, so a build that fails is not started again by the very next request.
_WALL_REASONS = ("duckdb-limit", "build-failed")

#: Whether this process has looked at the kept stop record yet (it looks once, at the first build decision, and
#: every later change goes through ``_keep_stopped`` / ``_release_stopped``, which keep the two in step).
_HOLD_LOOKED = False


#: Held while the kept record is read, so a second caller waits for the read rather than seeing "looked, found nothing"
#: in the window between the first caller marking the file looked at and its read finishing.
_HOLD_READ_LOCK = threading.Lock()


def _stopped_hold() -> dict | None:
    """The stop record in force: this process's own, else (once per process) the one an earlier process kept.

    The earlier one is marked ``restored``. It is read only when this process has stopped no build of its own, so
    the file can never replace a fresher in-memory record. ``_HOLD_LOOKED`` is set only AFTER the read finished,
    and a caller that arrives meanwhile waits for it."""
    with _LOCK:
        st = _STATE.get("stopped")
        looked = _HOLD_LOOKED
    if st or looked:
        return st
    with _HOLD_READ_LOCK:
        with _LOCK:
            st = _STATE.get("stopped")
            looked = _HOLD_LOOKED
        if st or looked:
            return st
        try:
            return _read_kept_stop()
        finally:
            _mark_hold_looked()


def _mark_hold_looked() -> None:
    global _HOLD_LOOKED
    with _LOCK:
        _HOLD_LOOKED = True


def _read_kept_stop() -> dict | None:
    from src.analytics import rollup_hold

    kept = rollup_hold.read()
    if kept is None:
        return None
    from src import __version__

    if kept.get("app_version") != __version__ or kept.get("build_code") != BUILD_CODE_VERSION:
        _LOG.info("rollup serve: the kept stop was recorded by another version (%s/%s); released",
                  kept.get("app_version"), kept.get("build_code"))
        rollup_hold.clear()
        return None
    if kept.get("reason") == "build-failed":
        # R172: a failure hold is this process's only. The kept record hands over the run of failures and the class, nothing holds.
        n = kept.get("consecutive_failures")
        with _LOCK:
            if isinstance(n, int) and n > int(_STATE.get("failures") or 0):
                _STATE["failures"], _STATE["failure_class"] = n, kept.get("engine_error_class")
        return None
    with _LOCK:
        if _STATE.get("stopped") is None:
            _STATE["stopped"] = {**kept, "restored": True}
        return _STATE["stopped"]


def _failure_view() -> tuple[int, str | None]:
    """(consecutive failures, class of the last) for ``status()``: this process's own run, which starts from the count an earlier process kept."""
    with _LOCK:
        return int(_STATE.get("failures") or 0), _STATE.get("failure_class")


def _record_failure(error_class: str, stage: str | None) -> None:
    """A build ended in an error that no hold maps (R172): keep a failure hold, released by what releases a ``duckdb-limit`` hold, so the very next
    request does not start the same build again. The hold lives in THIS process only: a restart retries once (a transient error must not keep the
    accelerator off), while the kept record carries the run of failures across it. The record's ``stage`` is the LAST REPORTED stage, not the raising
    statement (the key is the one a ``duckdb-limit`` hold uses, and it means the same there). The record carries the stage the build had last reported (None, and ``stage_why``, when it had
    reported none), the exception CLASS (passed as its name) and the run of consecutive failures; never the exception's text. The persisted store is not touched."""
    if _persisted_serve_active():
        return
    cls = error_class
    with _LOCK:
        prior = int(_STATE.get("failures") or 0)
        held = _STATE.get("stopped")
    if held and held.get("reason") == "build-failed" and isinstance(held.get("consecutive_failures"), int):
        prior = max(prior, held["consecutive_failures"])
    n = prior + 1
    with _LOCK:
        _STATE["failures"] = n
        _STATE["failure_class"] = cls
    budget = _build_budget()
    record = {
        "reason": "build-failed", "at": time.time(), "engine_error_class": cls, "consecutive_failures": n,
        "duckdb_limit_mb": budget.get("duckdb_limit_mb"), "offload_allowed": budget.get("offload_allowed"),
        "epoch": _current_epoch(), "mentions_count": _current_mention_count(),
    }
    if stage:
        record["stage"] = stage
    else:
        record["stage_why"] = "not-recorded"
    _keep_stopped(record)
    _note_decline("stopped", "build", record)


def _keep_stopped(record: dict) -> None:
    """Hold later builds back on ``record`` and keep it for the next process."""
    global _HOLD_LOOKED
    from src import __version__
    from src.analytics import rollup_hold

    record = {**record, "app_version": __version__, "build_code": BUILD_CODE_VERSION}
    with _LOCK:
        _STATE["stopped"] = record
        if record.get("reason") != "build-failed":
            # R172: the run counts builds that ended "failed", one after another. A build that ended in a stop of another kind is not one of them
            # and ends the run, so a failure run and a duckdb-limit hold are never in one report (the report's worst case stays what it was).
            _STATE["failures"], _STATE["failure_class"] = 0, None
        _HOLD_LOOKED = True
    rollup_hold.write(record)


def _release_stopped() -> None:
    """The hold is over (the condition changed, or a build finished): forget it here and on disk."""
    global _HOLD_LOOKED
    from src.analytics import rollup_hold

    with _LOCK:
        _STATE["stopped"] = None
        _HOLD_LOOKED = True
    rollup_hold.clear()


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
    if _persisted_serve_active():
        return None
    st = _stopped_hold()
    if not st:
        return None
    try:
        if st.get("reason") in _WALL_REASONS:
            # The wall is DuckDB's limit against the size of the corpus, and the epoch moves for reasons that do not
            # touch either (``/api/insights/reindex-all`` bumps it on every 300-article call): a release per epoch
            # would start the same 15-minute scan again for the length of a re-index drain, and again after every
            # restart. So this stop is released by what changes the wall: a larger limit, or a corpus with FEWER
            # mentions than it had at the stop (a prune, a restore of a smaller backup, a re-index under a longer
            # stoplist). The count is taken only when the epoch has moved since the stop (or the last count), and
            # not before the rebuild TTL, so it is not a read per serve.
            limit = _duckdb_limit_mb()
            if limit > float(st.get("duckdb_limit_mb") or 0):
                _release_stopped()
                return None
            if st.get("offload_allowed") is False and _build_budget().get("offload_allowed") is True:
                # stopped while the corpus was encrypted (no spill, so the limit was a wall); DuckDB may spill now
                _release_stopped()
                return None
            seen = float(st.get("checked_at") or st.get("at") or 0.0)
            if time.time() - seen >= max(float(rollup_serve_ttl_s()), _COUNT_MIN_INTERVAL_S):
                now_epoch = _current_epoch()
                epoch_moved = now_epoch is not None and st.get("epoch") is not None and now_epoch != st["epoch"]
                # The epoch is bumped by the non-append mutators it knows (re-index, prune, restore-merge) and is blind to
                # the rest: a cascade delete of the mentions of a removed source or article moves neither the epoch nor a
                # max id (serve_gate's disclosed invisible classes). The same long backstop that bounds a served rollup's
                # staleness bounds this one: a stop not looked at for that long is counted once, epoch or no epoch.
                backstop = time.time() - seen >= _BACKSTOP_S
                if epoch_moved or backstop:
                    count = _current_mention_count()
                    base = st.get("mentions_count")
                    if count is not None and isinstance(base, int) and count < base * (1.0 - _SHRINK_TO_RETRY):
                        _release_stopped()
                        return None
                    if count is not None:
                        # not smaller by enough: the wall stands; look again when the epoch moves next (or at the
                        # backstop). The count the stop was measured at stays the base, so small drops add up.
                        _keep_stopped({**st, "epoch": now_epoch if now_epoch is not None else st.get("epoch"),
                                       "checked_at": time.time(),
                                       "mentions_count": base if isinstance(base, int) else count})
            return {"reason": st["reason"], "at": time.time(), "duckdb_limit_mb": limit,
                    "stopped_at": st.get("at"), "restored": bool(st.get("restored")),
                    "note": ("a build under this limit was already stopped by it" if st["reason"] == "duckdb-limit" else
                             "the last build ended in an error (its class is in the hold) and the same build is not started again until something it depends on changes") + "; retried when the memory budget's "
                            "limit grows, offload becomes allowed, or the corpus is smaller than at the stop "
                            "(counted when the corpus epoch moves, and at the long backstop for a delete the epoch "
                            "does not see)"}
        # A corpus that has been re-indexed, pruned or restored is a different corpus (the epoch moves for
        # exactly those); what stopped the last build says nothing about it, so the hold is released.
        # Not before the rebuild TTL (``rollup_serve_ttl_s``, the churn bound every rebuild already honours):
        # ``/api/insights/reindex-all`` bumps the epoch on EVERY 300-article call, and a release per call would
        # bring the rescan loop back for the length of that drain.
        now_epoch = _current_epoch() if time.time() - float(st.get("at") or 0.0) >= rollup_serve_ttl_s() else None
        if now_epoch is not None and st.get("epoch") is not None and now_epoch != st["epoch"]:
            _release_stopped()
            return None
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
#: What the build in flight is doing, for the boot sequence's block and the rollup_serve status: the stage, the
#: rows it has handed to DuckDB in that stage and when each last moved. Counts and times only. ``None`` while no
#: build runs. Written by the build's own per-batch hook, read by anyone.
_PROGRESS: dict | None = None
_PROGRESS_LOCK = threading.Lock()


def _progress_begin() -> None:
    global _PROGRESS
    now = time.monotonic()
    with _PROGRESS_LOCK:
        _PROGRESS = {"started_at": now, "stage": "start", "rows_done": 0, "stage_started_at": now,
                     "updated_at": now}


def _progress_note(stage: str, rows_done: int) -> None:
    now = time.monotonic()
    with _PROGRESS_LOCK:
        p = _PROGRESS
        if p is None:
            return
        if stage != p["stage"]:
            # a stage begins when the previous one last moved, so its first batch is inside its own rate;
            # one announced at zero rows (the keywords stage after the GROUP BY) begins now, so the
            # statement before it is not charged to its rate
            p.update(stage=stage, stage_started_at=now if int(rows_done) == 0 else p["updated_at"])
        p.update(rows_done=int(rows_done), updated_at=now)


#: The stage the last build that did not finish had reported (None: none reported). Read once by ``_record_failure``.
_LAST_STAGE: dict = {"value": None}


def _remember_stage() -> None:
    with _PROGRESS_LOCK:
        _LAST_STAGE["value"] = _PROGRESS["stage"] if _PROGRESS is not None and isinstance(_PROGRESS.get("stage"), str) else None


def _progress_end() -> None:
    global _PROGRESS
    with _PROGRESS_LOCK:
        _PROGRESS = None


def build_progress() -> dict | None:
    """The build in flight: its stage, the rows streamed in that stage so far, rows/s over that stage (absent
    when it cannot be measured, never ``0``: an unmeasurable rate is not a stall) and the seconds since it last
    moved. ``None`` while no build runs."""
    now = time.monotonic()
    with _PROGRESS_LOCK:
        p = dict(_PROGRESS) if _PROGRESS is not None else None
    if p is None:
        return None
    out: dict = {
        "stage": p["stage"],
        "rows_done": p["rows_done"],
        "running_s": round(now - p["started_at"], 1),
        "idle_s": round(now - p["updated_at"], 1),
    }
    span = p["updated_at"] - p["stage_started_at"]
    if p["stage"] in ("mentions", "keywords") and p["rows_done"] > 0 and span > 0:
        rate = p["rows_done"] / span
        out["rows_per_s"] = round(rate) if rate >= 10 else round(rate, 1)  # never a measured 0 from rounding
        if not out["rows_per_s"]:
            del out["rows_per_s"]
    return out


#: When ``_memory_verdict`` last took its own reading (see there).
_LAST_VERDICT_POLL = float("-inf")


def _make_on_batch():
    """The per-batch hook of the build: refresh the in-progress marker, then ask the memory guard."""

    last_poll = [float("-inf")]  # never a clock-dependent 0.0: a fresh runner's monotonic clock starts near it

    def _on_batch(stage: str, rows_done: int) -> None:
        from src.analytics import columnar, rollup_marker

        _progress_note(stage, rows_done)
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

        # The guard is released only by a SAMPLE that finds memory healthy again, and the samples come from
        # collection passes. While collection is paused the guard can therefore stay engaged for good, the
        # build's own poll having engaged it, and keep the rollup off with no one left to release it: take one
        # fresh reading here, at most as often as the build asks (``_GUARD_POLL_EVERY_S``).
        global _LAST_VERDICT_POLL
        now = time.monotonic()
        if memory_guard.engaged and now - _LAST_VERDICT_POLL >= _GUARD_POLL_EVERY_S:
            _LAST_VERDICT_POLL = now
            poll = getattr(memory_guard, "poll", None)
            if poll is not None:
                poll()
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
    ran = False  # a build was started (not refused by a verdict): only then does ``last_outcome`` change
    _LAST_STAGE["value"] = None  # a decline of an earlier build left its stage here: this build reports its own or none
    try:
        # TWO reasons to decline, checked in order; the FIRST that fires is recorded, so
        # `last_skip` always names the condition that actually stopped this build rather
        # than whichever check happens to be listed last. S6.1 (2026-09-03) added the
        # exclusive one: this build is kicked from a SERVE, so it never met the collection
        # pause and would happily rebuild a whole-corpus rollup underneath a restore.
        from src.analytics.serve_gate import exclusive_verdict

        skip: dict | None = None
        source: str | None = None
        for name, verdict in (
            ("exclusive", exclusive_verdict), ("boot-order", _boot_order_verdict), ("memory", _memory_verdict),
            ("stopped", _stopped_build_verdict), ("last-build", _last_build_verdict),
            ("affordability", _affordability_verdict),
        ):
            skip = verdict()
            if skip:
                source = name
                break
        if skip:
            with _LOCK:
                _STATE["last_skip"] = {**skip, "source": source}
            if source is not None and source not in _TRANSIENT_VERDICTS:
                _note_decline("skipped", source, skip)
            _LOG.info(
                "rollup serve: build skipped (%s)",
                skip.get("guard_reason") or skip.get("reason") or "mem-low",
            )
            outcome = "declined"
            return outcome
        ran = True
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
                    # The build is bounded by DuckDB's limit (times the measured overshoot) plus one batch, so a
                    # projection past that is the linear extrapolation outrunning the build's own ceiling (and
                    # MAX(id) overstates the rows after re-index churn): never ask for more than the start check does.
                    chunk = columnar_batch_mb()
                    ceiling = round(float(stopped.get("duckdb_limit_mb") or _duckdb_limit_mb()) * _LIMIT_OVERSHOOT + chunk, 1)
                    grew = min(grew, max(ceiling, observed))
                with _LOCK:
                    _STATE["last_skip"] = stopped
                _keep_stopped({
                    "reason": stopped.get("reason"), "at": stopped.get("at"), "grew_mb": grew,
                    "observed_grew_mb": observed, "epoch": stopped.get("epoch"),
                    "duckdb_limit_mb": stopped.get("duckdb_limit_mb"), "stage": stopped.get("stage"),
                    "duckdb_threads": stopped.get("duckdb_threads"), "budget_total_mb": stopped.get("budget_total_mb"),
                    "budget_read_at": stopped.get("budget_read_at"),
                    "mentions_total": stopped.get("mentions_total"), "rows_done": stopped.get("rows_done"),
                    "mentions_count": stopped.get("mentions_count"),
                    "shards": stopped.get("shards"), "shard": stopped.get("shard"), "split": stopped.get("split"),
                    "query": stopped.get("query"), "peak_mib": stopped.get("peak_mib"),
                    "resident_mib": stopped.get("resident_mib"), "engine_error_class": stopped.get("engine_error_class"),
                    "offload_allowed": _build_budget().get("offload_allowed"),
                })
                _LOG.warning(
                    "rollup serve: build stopped part-way (%s); nothing was swapped in and it is not "
                    "retried until that condition changes",
                    stopped.get("guard_reason") or stopped.get("reason"),
                )
                _note_decline("stopped", "build", {**stopped, "grew_mb": grew, "observed_grew_mb": observed})
                outcome = "declined"
                return outcome
        _release_stopped()
        with _LOCK:  # a build that serves ends the run of failures (R172)
            _STATE["failures"] = 0
            _STATE["failure_class"] = None
        outcome = "built"
        return outcome
    except Exception as exc:  # noqa: BLE001 - a background accelerator must never crash the app
        log_failure(_LOG, "rollup serve: background build failed", exc, level=logging.WARNING)
        outcome = "failed"
        stage, _LAST_STAGE["value"] = _LAST_STAGE["value"], None
        try:
            if ran:  # an error in a verdict, before any build started, is no build that failed: it keeps no hold that would refuse real builds
                _record_failure(type(exc).__name__, stage)  # the class only: the sink sweep's rule
        except Exception as hold_exc:  # noqa: BLE001 - a hold that cannot be kept must not turn a failed build into a crash
            log_failure(_LOG, "rollup serve: could not keep the failure hold", hold_exc, level=logging.WARNING)
        return outcome
    finally:
        _LAST_OUTCOME["value"] = outcome
        if ran or outcome == "failed":  # a request the hold refuses ran no build: the field says how the last build that ENDED ended
            with _LOCK:
                _STATE["last_outcome"] = outcome
        _BUILD_LOCK.release()


def _trigger_build_async() -> None:
    """Kick a background build if one is not already running (non-blocking)."""
    if not _BUILD_LOCK.acquire(blocking=False):
        return  # a build is already in flight
    thread = threading.Thread(target=_build_and_swap, name="rollup-build", daemon=True)
    try:
        thread.start()
    except Exception as exc:  # noqa: BLE001 - "can't start new thread" is what a memory-starved machine raises
        # The thread that would have released the lock never ran: release it here, or every later
        # build (and the boot sequence's wait for this one) blocks on it forever.
        _LAST_OUTCOME["value"] = "failed"
        _BUILD_LOCK.release()
        log_failure(_LOG, "rollup serve: could not start the build thread", exc, level=logging.WARNING)


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


def _drop_if_unusable(con) -> bool:
    """A served query that hit DuckDB's FATAL error leaves the instance unusable: drop it so nothing is served from it
    again (the caller answers live), and when the error said it could not allocate (the memory wall) keep the same
    ``duckdb-limit`` stop a build gets, at stage ``serve-fatal``, so the next request does not rebuild into it.
    Any other fatal is a plain failure: dropped, counted, and a later request may rebuild as for any failed build.
    INFERRED, not observed in the field (2026-10-17: the build-time fatal was). Returns True when it dropped ``con``.
    No engine text is kept: the kind comes from ``columnar`` as a word."""
    from src.analytics import columnar

    kind = columnar.take_serve_fatal(con)
    if kind is None:
        return False
    with _LOCK:
        if _STATE["con"] is not con or _STATE["persisted"]:
            return False  # a newer build already replaced it, or it is the persisted store (not ours to drop)
        _STATE.update(con=None, built_at=0.0, rows=0, bind=None, token=None, pending=False)
        spill, _STATE["spill"] = _STATE.get("spill"), None
        last = _STATE.get("last_build") or {}
    with contextlib.suppress(Exception):
        con.close()
    _remove_spill(spill)
    _LOG.warning("rollup serve: a served query hit a FATAL engine error (%s); the rollup was dropped and the live scan answers", kind)
    if kind == "allocation":
        check = last.get("serve_check") or {}
        record = {
            "reason": "duckdb-limit", "at": time.time(), "stage": "serve-fatal", "engine_error_class": "FatalException",
            "duckdb_limit_mb": last.get("duckdb_limit_mb") or _duckdb_limit_mb(), "duckdb_threads": last.get("duckdb_threads"),
            "budget_total_mb": last.get("budget_total_mb"), "budget_read_at": last.get("budget_read_at"),
            # the sizes of the finished build's own serve check: the instance cannot be read now
            "peak_mib": check.get("peak_mib"), "resident_mib": check.get("resident_mib"),
            "epoch": _current_epoch(), "mentions_count": _current_mention_count(),
        }
        with _LOCK:
            _STATE["last_skip"] = record
        _keep_stopped({**record, "offload_allowed": _build_budget().get("offload_allowed")})
        _note_decline("stopped", "serve", record)
    return True


def windowed_rows(
    _session: Session, *, days: int, kind: str | None = None, limit: int = 80
) -> list[dict] | None:
    """The windowed most-mentioned rows served from the in-memory rollup, or ``None`` to
    fall back to the live query. Rows: ``{term, normalized, kind, language, mentions,
    articles}`` ordered by mentions desc (the same shape/order the live windowed query
    produces before the hidden-word / family / ring layers).

    Returns ``None`` (fallback) when: not opted in, the rollup is not built yet, the engine
    answered with its out-of-memory error (R194) or left the instance unusable (a fatal), or an
    error escaped the query. An ORDINARY engine error inside the query is NOT a fallback: the
    columnar layer answers empty (and counts it), and that empty list is returned. Kicks a background (re)build when the rollup is missing or the change gate
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
            rows = columnar.windowed_top_terms_raw(con, start_day=start, kind=kind, limit=limit)
        return None if _drop_if_unusable(con) else rows
    except Exception as exc:  # noqa: BLE001 - any serve failure -> live fallback
        log_failure(_LOG, "rollup serve: windowed serve failed; falling back to live", exc, level=logging.WARNING)
        return None


def windowed_counts(_session: Session, *, lo, hi) -> dict[int, int] | None:
    """Per-keyword windowed mention SUM for the INCLUSIVE day range ``[lo, hi]`` from the
    rollup, or ``None`` to fall back to the live query. Used by ``trending`` (its recent /
    prior windows) — which is why wiring it also accelerates ``trending_windows`` (the Home
    poll), since that calls ``trending`` per window. Same safety as :func:`windowed_rows`:
    opted-in only, background (re)build, serves the current build meanwhile. ``None`` on the
    engine's out-of-memory error (R194), on a fatal instance, or on an escaped error; an
    ordinary engine error inside the query answers ``{}`` (empty on error, live only on OOM
    or a fatal instance)."""
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
        dropped = _drop_if_unusable(con)  # always asked: it takes the fatal the query left, if any
        if dropped or counts is None:  # None = the engine's out-of-memory error (R194): the live scan answers
            return None
        return {kid: mv[0] for kid, mv in counts.items()}  # mentions only (exact)
    except Exception as exc:  # noqa: BLE001 - any serve failure -> live fallback
        log_failure(_LOG, "rollup serve: windowed counts failed; falling back to live", exc, level=logging.WARNING)
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
