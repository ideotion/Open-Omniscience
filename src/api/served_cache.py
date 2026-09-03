"""Serve-stale + ONE background recompute for the POLLED count endpoints (S3.2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT THIS REPLACES, and WHY the thing it replaces did not work.

``/api/database/stats`` is polled every 4 s by the Library storage view and every
15 s by Home; ``/api/database/figures`` every 16 s; ``/api/library/overview``
reuses the first. Each recomputes whole-table ``COUNT(*)``s -- on the field
corpus the ``keyword_mentions`` count alone measured 43 s, on the request thread.

Both endpoints carried a cache described as VERIFIED: an entry was served only
while two probes -- ``PRAGMA data_version`` and ``SELECT total_changes()`` --
proved the database unchanged. The claim was true and the mechanism was dead.
Both probe components are PER CONNECTION, and they diverge by opposite
mechanisms:

  * ``total_changes()`` counts only the writes THIS connection made since it
    opened, so two pooled connections disagree PERMANENTLY, not transiently;
  * ``data_version`` is the inverse -- it does NOT tick for the connection that
    made the change and DOES tick for every other one.

Measured through the production functions on a two-connection pool with ZERO
writes: six reads, six recomputes -- a 0% hit rate. The default engine runs
``pool_size=5`` + 10 overflow, so on a live server the cache essentially never
served, and every poll paid the full scan inline. That is the request-thread
death spiral this module exists to end.

THE PROBE THIS USES INSTEAD is the write gate's own ``grants`` counter: one
process-global monotonic int, bumped once per write transaction by whichever
thread performs it. Measured against the four properties the pair could not hold
together: pure reads do not bump it (10 reads, unchanged); it sees this
connection's own write (0 -> 1); it sees another connection's write read from
anywhere (1 -> 2); and it is comparable across connections by construction.

ITS HONEST LIMITS, stated rather than papered over. ``grants`` is bumped by the
ORM flush / ORM-DML listeners and by explicit ``write_lock()``, so it does NOT
see (a) a bare textual ``session.execute(text("INSERT ..."))`` taken outside the
gate -- measured, unchanged at 2 -- nor (b) a write from another PROCESS. (b) is
bounded by the same assumption the whole single-writer design already rests on;
(a) is what ``write_lock()`` exists to prevent. Neither is left to luck: the
corpus-swap path calls :func:`invalidate` explicitly, and every served payload
carries its real ``as_of``/``cache_age_s`` -- the guarantee offered is that the
age is VISIBLE, never that it is zero.

THE SHAPE (mirrors :mod:`src.analytics.poll_cache`, which does this for alerts):
  * BIND-AWARE. An entry records the engine it was built over and is served only
    to a session bound to that same engine; a test fixture on its own engine
    never reads another database's numbers.
  * SERVE-STALE. A warm entry is returned immediately, always. A recompute is
    kicked in the BACKGROUND (its own ``session_scope``) only when the entry is
    older than its TTL *and* the probe says something was written -- so an idle
    app rebuilds nothing at all and a collecting one rebuilds at most once per
    TTL, never on the request thread.
  * SINGLE-FLIGHT COLD START. The first caller computes inline (these are plain
    ``def`` handlers, so that blocks a threadpool worker, not the event loop);
    concurrent cold callers wait on the same per-key lock and then find the entry
    warm. N simultaneous polls can never start N scans.

The numbers are the SAME real counts the endpoints always returned -- memoised,
never estimated, never a score.
"""

from __future__ import annotations

import copy
import logging
import threading
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session

_LOG = logging.getLogger(__name__)

_LOCK = threading.Lock()
# key -> {"payload", "built_at", "checked_at", "probe", "bind"}
_CACHE: dict[str, dict] = {}
# One build lock PER KEY: a cold /figures must not block a warm /stats behind it.
_BUILD_LOCKS: dict[str, threading.Lock] = {}
_BUILD_LOCKS_GUARD = threading.Lock()
# Only a handful of fixed keys exist (they are module constants at the call
# sites, never user input), but bound the dict anyway.
_MAX_KEYS = 16


def _build_lock(key: str) -> threading.Lock:
    with _BUILD_LOCKS_GUARD:
        lock = _BUILD_LOCKS.get(key)
        if lock is None:
            lock = _BUILD_LOCKS[key] = threading.Lock()
        return lock


def change_probe() -> int | None:
    """A process-global, cross-connection-comparable "was anything written" token.

    Returns the write gate's ``grants`` count, or ``None`` when no such reading is
    available (the gate disabled via ``OO_WRITE_GATE=0``, or an unexpected error).
    ``None`` means "no probe" and is NEVER treated as "nothing changed": the
    caller then falls back to the TTL alone, which is the conservative direction.
    """
    try:
        from src.database.writer import gate_enabled, write_gate_stats

        if not gate_enabled():
            return None
        return int(write_gate_stats().get("grants", 0))
    except Exception:  # noqa: BLE001 - a probe that cannot read must not break a read
        return None


def _bind_of(session: Session | None) -> object | None:
    try:
        return session.get_bind() if session is not None else None
    except Exception:  # noqa: BLE001 - any doubt -> no bind -> not cacheable
        return None


def _same_bind(session: Session | None, built_bind: object | None) -> bool:
    """True only when ``session`` queries the SAME database the entry was built over.

    The correctness net behind a process-lifetime singleton, mirroring
    :func:`src.analytics.poll_cache._same_bind`.
    """
    if session is None or built_bind is None:
        return False
    try:
        return session.get_bind() is built_bind
    except Exception:  # noqa: BLE001 - any doubt -> live fallback
        return False


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds")


def _decorate(entry: dict, *, ttl_s: int, cached: bool, now: float) -> dict:
    """Attach the visible freshness disclosure to a DEEP COPY of the cached payload.

    A deep copy because ``{**payload}`` copies only the top level: a caller that
    mutated a nested dict in a served result (``counts`` here) would corrupt the
    shared object every later serve reuses. These payloads are small maps of
    integers, so copying them is nothing next to the scan being avoided.
    """
    built_at = entry["built_at"]
    out = copy.deepcopy(entry["payload"])
    out["computed_at"] = _iso(built_at)
    out["cache_ttl_s"] = ttl_s
    out["as_of"] = _iso(built_at)
    out["cache_age_s"] = max(0, int(now - built_at))
    out["cached"] = bool(cached)
    return out


def _store(key: str, payload: dict, bind: object | None, probe: int | None) -> None:
    """Cache ``payload``. An entry with no bind is not stored: it could never pass
    the bind gate, so it would occupy a slot that can never be served."""
    if bind is None:
        return
    now = time.time()
    with _LOCK:
        _CACHE[key] = {
            "payload": payload,
            "built_at": now,
            "checked_at": now,
            "probe": probe,
            "bind": bind,
        }
        if len(_CACHE) > _MAX_KEYS:
            oldest = min(_CACHE, key=lambda k: _CACHE[k]["built_at"])
            _CACHE.pop(oldest, None)


def refresh(key: str, compute, *, probe: int | None = None) -> dict | None:
    """THE background recompute path: run ``compute(session)`` over a FRESH
    ``session_scope`` session and store the result.

    Always called on a background thread (or directly by a test), never on the
    request thread. Returns the fresh payload, or ``None`` if it could not run.
    """
    try:
        from src.database.session import session_scope

        with session_scope() as s:
            fresh = compute(s)
            _store(key, fresh, _bind_of(s), change_probe() if probe is None else probe)
            return fresh
    except Exception:  # noqa: BLE001 - a background accelerator must never crash the app
        _LOG.warning("served-cache background refresh failed for %s", key, exc_info=True)
        return None


def _kick_background_refresh(key: str, compute) -> None:
    """Kick ONE background recompute for ``key`` when none is already in flight.

    Non-blocking: the stale-but-real value keeps being served meanwhile, which is
    the entire point -- a poll must never wait on the scan.
    """
    lock = _build_lock(key)
    if not lock.acquire(blocking=False):
        return  # a rebuild for this key is already running

    def _run() -> None:
        # The probe is read BEFORE the compute: a write that lands mid-scan must
        # leave the stored token behind the current one, so the next expiry
        # rebuilds again rather than treating the half-old value as verified.
        before = change_probe()
        try:
            refresh(key, compute, probe=before)
        finally:
            lock.release()

    threading.Thread(target=_run, name=f"served-cache-{key}", daemon=True).start()


def cached(key: str, compute, session: Session, *, ttl_s: int) -> dict:
    """Serve ``key``, computing at most once and never on a poll.

    ``compute`` takes a Session and returns the payload dict, so the SAME callable
    can be re-run by the background refresher over its own session -- a closure
    over the request's session would be used after that session is closed, from
    another thread.
    """
    now = time.time()
    probe = change_probe()
    with _LOCK:
        entry = _CACHE.get(key)
        servable = entry is not None and _same_bind(session, entry.get("bind"))
        snapshot = dict(entry) if (servable and entry is not None) else None

    if snapshot is not None:
        age = now - snapshot["checked_at"]
        if age >= ttl_s:
            if probe is not None and probe == snapshot["probe"]:
                # Nothing was written since this value was computed, so it is not
                # merely fresh enough -- it is still exactly right. Re-stamp the
                # CHECK time and leave built_at alone, so `as_of` keeps telling the
                # truth about the value's real age while the interval restarts.
                with _LOCK:
                    live = _CACHE.get(key)
                    if live is not None and live["built_at"] == snapshot["built_at"]:
                        live["checked_at"] = now
            else:
                _kick_background_refresh(key, compute)
        return _decorate(snapshot, ttl_s=ttl_s, cached=True, now=now)

    # Cold (or a bind we may not answer for): compute ONCE, under the per-key
    # build lock, and let concurrent cold callers reuse that one result.
    lock = _build_lock(key)
    with lock:
        with _LOCK:
            entry = _CACHE.get(key)
            servable = entry is not None and _same_bind(session, entry.get("bind"))
            snapshot = dict(entry) if (servable and entry is not None) else None
        if snapshot is not None:
            return _decorate(snapshot, ttl_s=ttl_s, cached=True, now=time.time())
        fresh = compute(session)
        _store(key, fresh, _bind_of(session), probe)
        built = {"payload": fresh, "built_at": time.time()}
        return _decorate(built, ttl_s=ttl_s, cached=False, now=time.time())


def invalidate(key: str | None = None) -> None:
    """Drop one entry, or every entry when ``key`` is None.

    The explicit belt for the writes the ``grants`` probe cannot see -- a corpus
    SWAP (restore) replaces the file wholesale through raw connections that never
    touch the gate, so the counts it serves must be dropped by name rather than
    left to a probe that is blind to exactly that path.
    """
    with _LOCK:
        if key is None:
            _CACHE.clear()
        else:
            _CACHE.pop(key, None)


def status() -> dict:
    """Honest state of the cache, for diagnostics and tests. No score."""
    now = time.time()
    with _LOCK:
        return {
            "probe": change_probe(),
            "entries": {
                k: {
                    "as_of": _iso(v["built_at"]),
                    "age_s": max(0, int(now - v["built_at"])),
                    "checked_age_s": max(0, int(now - v["checked_at"])),
                    "has_bind": v.get("bind") is not None,
                }
                for k, v in _CACHE.items()
            },
        }
