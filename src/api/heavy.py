"""Bounded concurrency + single-flight for the heavy read endpoints (field test 2026-07-08, Item 8 P0).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEATH SPIRAL (measured, 3rd batch of the 2026-07-08 diagnostics): the Home polls
(``briefing`` / ``signals/alerts`` / ``trending-windows`` / ``latest``) fire every few
seconds; each heavy analytics query takes 60-200 s on the 60K-article encrypted corpus;
and NOTHING is cancelled when the client gives up — so new polls pile onto unfinished
old ones (``in_flight`` seen at 9-10), all thrashing the ONE SQLCipher connection + the
GIL, so every request gets progressively slower until the single worker is frozen for
minutes. "Serialising is faster than thrashing" (the ledger). Caching/indexing alone is
NOT enough; the STACKING must be stopped.

This module is that structural fix. It provides, for the request-thread compute of a
heavy read:

  * A GLOBAL CONCURRENCY CAP — at most ``OO_HEAVY_CONCURRENCY`` (default 4) distinct heavy
    computes run at once. The (N+1)th does not pile on: it fast-fails with a typed
    :class:`HeavyBusy` (mapped to an honest 429 "busy, retry" by the router) after a short
    acquire wait, so ``in_flight`` for heavy work stays bounded and threadpool tokens are
    never held by a 200 s compute.
  * SINGLE-FLIGHT — identical concurrent requests (same key) share ONE computation: the
    first is the leader and computes; the rest wait a short bounded time to SHARE its
    result, and otherwise degrade honestly (429) — either way only ONE compute runs, so a
    burst of duplicate polls can never launch a burst of duplicate scans.

Guarantees / honesty:
  * The value returned is the leader's REAL computed value — single-flight collapses the
    DUPLICATE work, it never fabricates or summarises a result.
  * BIND-AWARE keys (:func:`flight_key`) so a flight computed over one database is never
    shared with a request bound to another (a test fixture on its own engine). Mirrors the
    ``poll_cache``/``rollup_serve`` ``_same_bind`` discipline.
  * The busy/timeout paths RAISE (never return) so a degraded/partial value is never
    cached by an upstream TTL cache — same invariant the ``_deadlined`` timeout path keeps.
  * Every heavy handler is a plain ``def`` (runs in the Starlette threadpool, not on the
    event loop), so blocking on the semaphore / event here is correct and never freezes the
    async loop. NEVER apply :func:`run_heavy` inside an ``async def`` handler.

No network, no DB access of its own, no score — pure request-admission control.
"""

from __future__ import annotations

import os
import threading
import uuid
from typing import Any, Callable

from sqlalchemy.orm import Session


class HeavyBusy(RuntimeError):
    """The server is at heavy-read capacity (cap reached / a duplicate leader was slow).

    Routers map this to a fast, honest HTTP 429 "busy, retry" — NEVER an unbounded hang."""


def _cap() -> int:
    """Max distinct heavy computes allowed to run at once (OO_HEAVY_CONCURRENCY, default 4)."""
    try:
        return max(1, int(os.getenv("OO_HEAVY_CONCURRENCY", "4")))
    except ValueError:
        return 4


def _acquire_timeout_s() -> float:
    """How long a leader waits for a concurrency slot before it fast-fails (busy). Short —
    the whole point is "never an unbounded pile-up" (OO_HEAVY_ACQUIRE_TIMEOUT_S, default 2.5)."""
    try:
        return max(0.0, float(os.getenv("OO_HEAVY_ACQUIRE_TIMEOUT_S", "2.5")))
    except ValueError:
        return 2.5


def _follower_wait_s() -> float:
    """How long a duplicate (same-key) request waits to SHARE the leader's result before it
    degrades honestly. Kept modest so followers never park a threadpool thread for long —
    single-flight's load-bearing win (collapsing the compute to ONE) holds regardless of
    whether the follower shares or 429s (OO_HEAVY_FOLLOWER_WAIT_S, default 5)."""
    try:
        return max(0.0, float(os.getenv("OO_HEAVY_FOLLOWER_WAIT_S", "5")))
    except ValueError:
        return 5.0


class _Flight:
    __slots__ = ("event", "result", "error", "busy")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None
        # Set when the leader could not get a concurrency slot and bailed WITHOUT computing,
        # so waiting followers know to degrade (busy) rather than read the empty result.
        self.busy = False


_LOCK = threading.Lock()
_FLIGHTS: dict[str, _Flight] = {}

# The concurrency semaphore is rebuilt when the configured cap changes (only relevant to
# tests, which set OO_HEAVY_CONCURRENCY then call _reset_for_tests(); in production the cap
# is fixed at boot). A BoundedSemaphore also self-guards against an over-release bug.
_SEM_LOCK = threading.Lock()
_SEM: threading.BoundedSemaphore | None = None
_SEM_CAP: int | None = None

# Honest counters for diagnostics/tests (no score, local only).
_STATS = {"runs": 0, "shared": 0, "busy": 0, "errors": 0}


def _semaphore() -> threading.BoundedSemaphore:
    global _SEM, _SEM_CAP
    cap = _cap()
    with _SEM_LOCK:
        if _SEM is None or _SEM_CAP != cap:
            _SEM = threading.BoundedSemaphore(cap)
            _SEM_CAP = cap
        return _SEM


def _bump(field: str) -> None:
    with _LOCK:
        _STATS[field] = _STATS.get(field, 0) + 1


def _finish(key: str, fl: _Flight) -> None:
    """Retire a completed/bailed flight and wake any followers (idempotent)."""
    with _LOCK:
        if _FLIGHTS.get(key) is fl:
            _FLIGHTS.pop(key, None)
    fl.event.set()


def flight_key(session: Session | None, name: str) -> str:
    """A single-flight key qualified by the session's DB engine, so a flight computed over
    one database is never shared with a request on another (test fixtures on their own
    engines). ``get_db``/``session_scope`` all derive from the one module ``SessionLocal``
    in production → the same bind id → correct sharing; a test fixture engine differs.

    When the bind is unknown (no session, or ``get_bind()`` raised) we mint a per-CALLER key
    (a uuid) rather than the constant ``nobind`` a naive fallback would use: an unknown-bind
    flight must NOT be shared, because two such callers could be over different databases and
    sharing would return one corpus's result to the other. A per-caller key simply disables
    single-flight collapsing for that (rare) call — the safe, honest default."""
    try:
        if session is not None:
            return f"{name}|bind={id(session.get_bind())}"
    except Exception:  # noqa: BLE001 - fall through to a per-caller key (never a wrong share)
        pass
    return f"{name}|nobind={uuid.uuid4().hex}"


def run_heavy(key: str, compute: Callable[[], Any]) -> Any:
    """Run ``compute`` under the global heavy-read cap + single-flight; return its result.

    Raises :class:`HeavyBusy` if the server is at capacity (the caller maps it to a fast
    429). Propagates any exception ``compute`` raises (e.g. a ``StatementTimeout`` from an
    inner deadline) — to the leader AND to any followers that shared the flight, so the
    caller's existing timeout handling fires uniformly.
    """
    with _LOCK:
        fl = _FLIGHTS.get(key)
        if fl is None:
            fl = _Flight()
            _FLIGHTS[key] = fl
            leader = True
        else:
            leader = False

    if not leader:
        # Duplicate in-flight compute: wait a bounded time to share the leader's result.
        if fl.event.wait(timeout=_follower_wait_s()):
            if fl.busy:
                _bump("busy")
                raise HeavyBusy("server busy — a duplicate request could not be served")
            if fl.error is not None:
                raise fl.error
            _bump("shared")
            return fl.result
        # The leader is slower than the follower's patience — degrade honestly. The compute
        # is still collapsed to the single leader (the load-bearing win); this follower just
        # doesn't wait for it.
        _bump("busy")
        raise HeavyBusy("server busy — this request timed out waiting to share a result")

    # Leader: take a concurrency slot, or fast-fail so we never pile onto the one connection.
    sem = _semaphore()
    if not sem.acquire(timeout=_acquire_timeout_s()):
        fl.busy = True
        _finish(key, fl)
        _bump("busy")
        raise HeavyBusy("server busy — too many heavy analytics requests in flight")
    try:
        fl.result = compute()
        _bump("runs")
        return fl.result
    except BaseException as exc:  # noqa: BLE001 - record + share the failure, then re-raise
        fl.error = exc
        _bump("errors")
        raise
    finally:
        sem.release()
        _finish(key, fl)


def guarded_read(
    session: Session,
    name: str,
    compute: Callable[[], Any],
    *,
    on_timeout: Callable[[BaseException], Any] | None = None,
    on_busy: Callable[[BaseException], Any] | None = None,
):
    """Compose the heavy-read cap + single-flight + a statement DEADLINE around ``compute``,
    for the heavy read endpoints that have NO TTL cache of their own (signals/flood, bury,
    lunar-correlation, …). Mirrors :func:`src.api.insights._deadlined` but without a cache.

    On a deadline overrun → ``on_timeout(exc)`` if given, else HTTP 503. When the server is
    at capacity → ``on_busy(exc)`` if given (an honest degraded/stale payload), else a fast
    HTTP 429 "busy, retry". Both fall-back paths return a value WITHOUT caching it (there is
    no cache here) — a partial is never mistaken for the real answer.
    """
    from fastapi import HTTPException

    from src.database.maintenance import StatementTimeout, statement_deadline

    def _run() -> Any:
        with statement_deadline(session):
            return compute()

    try:
        return run_heavy(flight_key(session, name), _run)
    except StatementTimeout as exc:
        if on_timeout is not None:
            return on_timeout(exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except HeavyBusy as exc:
        if on_busy is not None:
            return on_busy(exc)
        raise HTTPException(
            status_code=429, detail=str(exc), headers={"Retry-After": "2"}
        ) from exc


def status() -> dict:
    """Honest state of the heavy-read guard (for diagnostics/tests). No score."""
    with _LOCK:
        stats = dict(_STATS)
        in_flight = len(_FLIGHTS)
    return {
        "cap": _cap(),
        "acquire_timeout_s": _acquire_timeout_s(),
        "follower_wait_s": _follower_wait_s(),
        "in_flight_keys": in_flight,
        "counters": stats,
        "method": (
            "Request-admission control for the heavy analytics reads: a global concurrency "
            "cap + single-flight (identical concurrent requests share one compute). No score."
        ),
    }


def _reset_for_tests() -> None:
    """Drop all in-flight state + rebuild the semaphore at the current cap (test hook)."""
    global _SEM, _SEM_CAP
    with _LOCK:
        _FLIGHTS.clear()
        for k in _STATS:
            _STATS[k] = 0
    with _SEM_LOCK:
        _SEM = None
        _SEM_CAP = None
