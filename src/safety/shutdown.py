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

_LOG = logging.getLogger("safety.shutdown")


def _close_db_quietly() -> None:
    """Dispose the DB engine before SIGTERM so the encrypted SQLCipher store does not
    emit codec-teardown noise on interpreter exit (same care as the uninstall path)."""
    try:
        from src.database.session import dispose_engine

        dispose_engine()
    except Exception:  # noqa: BLE001 - best-effort; never block the shutdown
        _LOG.debug("shutdown: engine dispose failed", exc_info=True)


def _default_arm(delay: float) -> None:
    """Stop the server after a short delay so the HTTP response is flushed first."""

    def _stop() -> None:
        time.sleep(delay)
        _close_db_quietly()
        _LOG.warning("shutdown: stopping the server (SIGTERM to self)")
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_stop, daemon=True).start()


def request_shutdown(*, confirm: bool, delay: float = 1.0, _arm=_default_arm) -> dict:
    """Schedule a graceful server stop. Requires ``confirm=True``.

    The data directory / corpus / keys are untouched (this is not uninstall). Returns
    immediately; the actual SIGTERM fires ~``delay`` seconds later, after the response.
    """
    if not confirm:
        return {"ok": False, "detail": "confirmation required"}
    _arm(delay)
    return {"ok": True, "detail": "The app is shutting down — you can close this tab."}
