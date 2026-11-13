"""
Graceful in-app shutdown — a GUI equivalent of Ctrl-C in the terminal.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer 2026-06-21: turning the app off should be possible from the GUI (a
small status-bar power button + a confirm), not only by killing the terminal.
This stops THE SERVER PROCESS (SIGTERM to self) after the HTTP response is sent.
It is NOT uninstall and NOT panic: the data directory, corpus and keys are left
exactly as they are — the app simply stops, like Ctrl-C would.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time

from src.monitoring.secret_scrub import log_failure

_LOG = logging.getLogger("safety.shutdown")


def _reap_worker_processes() -> None:
    """Kill any precompute worker PROCESSES before this process dies.

    SIGTERM goes to ourselves, and a pool worker is a separate OS process -- not a
    thread -- so nothing else in this path reaps them. A worker still running when
    the parent exits is reparented to init and keeps burning CPU with no UI left to
    stop it.

    Field-reported 2026-08-03: an operator stopped an import whose workers were
    measurably BUSY (four live children at 0.57 cores in the run journal), so the
    parent never unwound through the module's own teardown, and a Python process
    outlived the app until the environment was restarted.
    """
    try:
        from src.analytics.reindex_parallel import terminate_live_pools

        terminate_live_pools()
    except Exception as exc:  # noqa: BLE001 - best-effort; never block the shutdown
        log_failure(_LOG, "shutdown: reaping worker processes failed", exc, level=logging.DEBUG)


def stop_self() -> None:
    """Ask THIS process to take the one graceful path out (uvicorn's, which runs the lifespan shutdown).

    WINDOWS: ``os.kill(pid, SIGTERM)`` there is ``TerminateProcess`` -- an immediate hard kill that runs no handler and no lifespan
    shutdown, so the sentinel was never flipped and every in-app stop read UNCLEAN on the next boot (field bundle of 2026-11-07: 11 of 11
    sessions, each costing about 34 min of verify/warm-cache/rollup, and the user stops the app with this very button). A raised SIGINT
    reaches uvicorn's capture (Server.capture_signals) like Ctrl-C does. Elsewhere SIGTERM is the graceful signal and stays."""
    if os.name == "nt":
        try:
            from src.monitoring.forensics import note_stop_signal

            note_stop_signal("in-app stop")
        except Exception:  # noqa: BLE001 - never block a shutdown on forensics
            pass
        signal.raise_signal(signal.SIGINT)
    else:
        os.kill(os.getpid(), signal.SIGTERM)


def _default_arm(delay: float) -> None:
    """Stop the server after a short delay so the HTTP response is flushed first."""

    def _stop() -> None:
        time.sleep(delay)
        # Children first: once we SIGTERM ourselves there is nobody left to do it.
        _reap_worker_processes()
        # The engine is NOT disposed here (R689): the signal below runs the lifespan shutdown, which stops the scheduler, asks every
        # background job to stop and waits for them, writes the log back and only then disposes. Disposing first, as this did, closed the
        # pool while jobs and the collector were still writing, so they reopened it, the stop-all came too late, and the lifespan's own
        # disposal read EARLIER_DISPOSAL. The codec-teardown quiet this was for comes from the lifespan's disposal just the same.
        _LOG.warning("shutdown: stopping the server (graceful signal to self)")
        stop_self()

    threading.Thread(target=_stop, name="oo-shutdown", daemon=True).start()


def request_shutdown(*, confirm: bool, delay: float = 1.0, _arm=_default_arm) -> dict:
    """Schedule a graceful server stop. Requires ``confirm=True``.

    The data directory / corpus / keys are untouched (this is not uninstall). Returns
    immediately; the actual SIGTERM fires ~``delay`` seconds later, after the response.
    """
    if not confirm:
        return {"ok": False, "detail": "confirmation required"}
    _arm(delay)
    return {"ok": True, "detail": "The app is shutting down — you can close this tab."}
