"""
The database is closed to a background job that outlived the shutdown's deadline (R689).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The shutdown asks every running background job to stop and waits for them all against one deadline
(:func:`src.jobs.background.stop_all_jobs`), then writes the log back and disposes the engine. A job that
does not notice the ask in time (one model generation, one 300-article batch) kept its thread, and its next
commit went through after the disposal: ``Engine.dispose()`` only empties the pool, and the next checkout
opens a fresh connection on the same file. So the shutdown now names the threads of the jobs it gave up
on, and from that moment every statement, commit and write-gate acquire on those threads raises
:class:`WriteAfterShutdownRefused`. Nothing they had not committed lands; the refusal is logged once per
job, by its kind (never its arguments, which can carry a passphrase).

Only those threads are refused. The shutdown's own steps after the deadline (the write-back, the flushes)
run on another thread and are not touched, and so is every other thread. A thread is held weakly, so a
job thread that ends is forgotten; :func:`clear` (the app's start) forgets them all.

Stated limit: a write that opened its own raw connection (``kv_set_json``) and had already passed the
write gate when the deadline came can still commit; every such write takes the gate first, so a straggler
that reaches one afterwards is refused at the gate.
"""

from __future__ import annotations

import logging
import threading
import weakref

_LOG = logging.getLogger("database.after_shutdown")

_LOCK = threading.Lock()
#: The threads refused, each with the job kind it is logged under. Weak: a thread that ends drops out.
_REFUSED: weakref.WeakKeyDictionary[threading.Thread, str] = weakref.WeakKeyDictionary()
#: The kinds already logged, so a job that keeps trying is named once, not once per statement.
_LOGGED: set[str] = set()


class WriteAfterShutdownRefused(RuntimeError):
    """A background job tried to use the database after the shutdown stopped waiting for it."""


def refuse_threads(threads: list[tuple[threading.Thread, str]]) -> None:
    """From now on, refuse every database use on these threads (each given with its job kind)."""
    with _LOCK:
        for t, kind in threads:
            if t is not None and t.is_alive():
                _REFUSED[t] = str(kind)


def clear() -> None:
    """Forget every refused thread (the app is starting)."""
    with _LOCK:
        _REFUSED.clear()
        _LOGGED.clear()


def refused_kind() -> str | None:
    """The job kind this thread is refused under, or None. One dict read when nothing is refused."""
    if not _REFUSED:
        return None
    return _REFUSED.get(threading.current_thread())


def check(what: str) -> None:
    """Raise :class:`WriteAfterShutdownRefused` if this thread is a job the shutdown gave up on."""
    kind = refused_kind()
    if kind is None:
        return
    with _LOCK:
        first = kind not in _LOGGED
        _LOGGED.add(kind)
    if first:
        _LOG.warning(
            "background job %s tried to use the database (%s) after the shutdown stopped waiting for it; refused, "
            "and nothing it had not committed was written",
            kind,
            what,
        )
    raise WriteAfterShutdownRefused(
        f"the app is shutting down; the background job {kind} may no longer use the database"
    )


def _on_statement(
    conn, cursor, statement, parameters, context, executemany
) -> None:  # pragma: no cover - event
    if _REFUSED:
        check("a statement")


def _on_commit(conn) -> None:  # pragma: no cover - event
    if _REFUSED:
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
