"""
The database is closed to background jobs once the shutdown has stopped waiting for them (R689).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The shutdown asks every running background job to stop and waits for them all against one deadline
(:func:`src.jobs.background.stop_all_jobs`), then writes the log back and disposes the engine. A job that
did not notice the ask in time (one model generation, one 300-article batch) kept its thread, and its next
commit went through after the disposal: ``Engine.dispose()`` only empties the pool, and the next checkout
opens a fresh connection on the same file. So when the wait ends the shutdown CLOSES the database to jobs
(:func:`close_for_jobs`), and from that moment a SQLAlchemy statement, a commit, a write-gate acquire or a
settings write raises :class:`WriteAfterShutdownRefused` on:

* the threads of the jobs still running (named to it, with their kinds);
* any ``bgjob-*`` thread, so a job started after the wait (a request still being served) is refused too;
* a helper thread such a job runs its work on (:func:`inherit`, used by ``run_concurrent``'s pool, where a
  coordinator turn's members commit on ``oo-llmbatch-*`` threads while the job thread only waits for them);
* the manual collection pass (``oo-scrape-now``), which the scheduler's stop never joins.

A refused commit never reaches the driver, so nothing the job had not committed lands; its rollback is not
refused. The refusal is logged once per job, by its kind (never its arguments, which can carry a
passphrase). The shutdown's own steps (the write-back, the disposal, the flushes) run on another thread and
are not touched, nor is any other thread. :func:`clear` (the app's start) reopens it.

Stated limits: a raw DBAPI cursor (``engine.raw_connection()``; the incremental vacuum, the hygiene pass)
runs no SQLAlchemy event, and a settings write already past the write gate when the database closed can
still commit; neither is a job's corpus write today. The columnar store (DuckDB) is a separate file and is
not covered. Threads that are not registry jobs (the import queue, the re-index managers, the backup threads,
the rollup and keyword-fold builders, the request-bound AI streams) keep their own stops.
"""

from __future__ import annotations

import functools
import logging
import threading
import weakref
from collections.abc import Callable
from typing import Any

_LOG = logging.getLogger("database.after_shutdown")

_LOCK = threading.Lock()
#: True from the end of the shutdown's wait until the next start. A plain bool: read on every statement.
_CLOSED = False
#: The threads refused by name, each with the job kind it is logged under. Weak: a thread that ends drops out.
_REFUSED: weakref.WeakKeyDictionary[threading.Thread, str] = weakref.WeakKeyDictionary()
#: A helper thread -> the thread whose work it runs (:func:`inherit`). Weak on both sides.
_PARENT: weakref.WeakKeyDictionary[threading.Thread, threading.Thread] = weakref.WeakKeyDictionary()
#: The kinds already logged, so a job that keeps trying is named once, not once per statement.
_LOGGED: set[str] = set()

_JOB_THREAD_PREFIX = "bgjob-"
_MANUAL_PASS_THREAD = "oo-scrape-now"

class WriteAfterShutdownRefused(RuntimeError):
    """A background job tried to use the database after the shutdown stopped waiting for it."""


def refuse_threads(threads: list[tuple[threading.Thread, str]]) -> None:
    """Refuse every database use on these threads (each given with its job kind), from now on."""
    with _LOCK:
        for t, kind in threads:
            if t is None or not t.is_alive():
                continue
            _REFUSED[t] = str(kind)


def close_for_jobs(threads: list[tuple[threading.Thread, str]] | None = None) -> None:
    """Close the database to background jobs: the given threads by name, every ``bgjob-*`` thread, their helpers and the manual
    collection pass. Called by the shutdown once its wait for the jobs has ended, whatever it found."""
    global _CLOSED
    refuse_threads(list(threads or []))
    with _LOCK:
        for t in threading.enumerate():
            if t.name != _MANUAL_PASS_THREAD:
                continue
            _REFUSED[t] = "manual-collection-pass"
        _CLOSED = True


def clear() -> None:
    """Reopen the database to jobs and forget every refused thread (the app is starting)."""
    global _CLOSED
    with _LOCK:
        _CLOSED = False
        _REFUSED.clear()
        _LOGGED.clear()


def is_closed() -> bool:
    return _CLOSED


def inherit[T, R](fn: Callable[[T], R]) -> Callable[[T], R]:
    """Wrap ``fn`` so the thread that runs it answers to the refusal as the thread that wrapped it does. For helper pools a job
    runs its work on: once the job is refused, so is its helper's next statement."""
    parent = threading.current_thread()

    @functools.wraps(fn)
    def run(item: T) -> R:
        me = threading.current_thread()
        if me is not parent:
            with _LOCK:
                _PARENT[me] = parent
        return fn(item)

    return run


def _kind_of(t: threading.Thread) -> str | None:
    kind = _REFUSED.get(t)
    if kind is None and t.name.startswith(_JOB_THREAD_PREFIX):
        kind = t.name[len(_JOB_THREAD_PREFIX) :]
    return kind


def refused_kind() -> str | None:
    """The job kind this thread is refused under, or None. One bool read while the database is open to jobs."""
    if not _CLOSED and not _REFUSED:
        return None
    me = threading.current_thread()
    if not _CLOSED:
        kind = _REFUSED.get(me)
        if kind is None:
            parent = _PARENT.get(me)
            if parent is not None:
                kind = _REFUSED.get(parent)
        return kind
    kind = _kind_of(me)
    if kind is None:
        parent = _PARENT.get(me)
        if parent is not None:
            kind = _kind_of(parent)
    return kind


def check(what: str) -> None:
    """Raise :class:`WriteAfterShutdownRefused` if this thread belongs to a job the database is closed to."""
    kind = refused_kind()
    if kind is None:
        return
    with _LOCK:
        first = kind not in _LOGGED
        _LOGGED.add(kind)
    if first:
        _LOG.warning(
            "background job %s tried to use the database (%s) after the shutdown stopped waiting for it; refused, "
            "and nothing it had not committed through the engine or the write gate was written",
            kind,
            what,
        )
    raise WriteAfterShutdownRefused(
        f"the app is shutting down; the background job {kind} may no longer use the database"
    )


def _on_statement(
    conn: Any, cursor: Any, statement: Any, parameters: Any, context: Any, executemany: Any
) -> None:  # pragma: no cover
    if _CLOSED or _REFUSED:
        check("a statement")


def _on_commit(conn: Any) -> None:  # pragma: no cover - event
    if _CLOSED or _REFUSED:
        check("a commit")


_INSTALLED = False


def install() -> None:
    """Attach the refusal to every engine (the class, so a second engine is covered too). Idempotent."""
    global _INSTALLED
    if _INSTALLED:
        return
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    event.listen(Engine, "before_cursor_execute", _on_statement)
    event.listen(Engine, "commit", _on_commit)
    _INSTALLED = True


# --------------------------------------------------------------------------- the stop that skipped the lifespan
_LIFESPAN_DISPOSED = False
_ATEXIT_ARMED = False


def note_lifespan_disposed() -> None:
    global _LIFESPAN_DISPOSED
    _LIFESPAN_DISPOSED = True


def arm_exit_disposal() -> None:
    """At the app's start: if the process exits without the lifespan's disposal (a second Ctrl-C during the connection drain makes
    uvicorn skip the lifespan shutdown), close the database to jobs and dispose the engine at exit, as the stop thread used to."""
    global _ATEXIT_ARMED, _LIFESPAN_DISPOSED
    _LIFESPAN_DISPOSED = False
    if _ATEXIT_ARMED:
        return
    import atexit

    atexit.register(_dispose_at_exit)
    _ATEXIT_ARMED = True


def _dispose_at_exit() -> None:
    if _LIFESPAN_DISPOSED:
        return
    try:
        from src.jobs.background import running_job_threads

        close_for_jobs(running_job_threads())
        from src.database.session import dispose_engine

        dispose_engine()
    except Exception:  # noqa: BLE001 - an exit hook never raises  # nosec B110
        pass
