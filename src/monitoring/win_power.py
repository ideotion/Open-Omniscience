"""Windows power and console-end events: write the log back before sleep, and take the graceful path when the console ends the session.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY (field bundle 2026-11-07, finding F7). A Windows session ended unclean every time: the stop button killed the process outright (fixed in
``src/safety/shutdown.py``), and nothing at all listened for the other ways a Windows session ends. Closing the console window, logging
off and shutting down arrive as ``CTRL_CLOSE_EVENT`` / ``CTRL_LOGOFF_EVENT`` / ``CTRL_SHUTDOWN_EVENT``, which Python maps to no signal and
(unlike ``SIGHUP`` on POSIX, see ``install_signal_handlers``) uvicorn does not take, so the lifespan shutdown never ran. And a machine
that goes to sleep with a large ``-wal`` can be lost to a power cut or a failed resume with the log never written back.

WHAT THIS DOES, on Windows only (a no-op everywhere else, and a failure to register is logged and never stops the app):

* ``SetConsoleCtrlHandler``: on CLOSE / LOGOFF / SHUTDOWN it records the reason (``note_stop_signal`` and the ``os-ending`` phase, so a kill
  inside the OS's grace window reads on the next boot as "the OS ended the session" rather than an unknown death), then raises SIGINT, which
  uvicorn's capture turns into the ONE graceful path (lifespan shutdown, ``checkpoint_before_dispose``, the clean sentinel). The handler
  thread then stays in the handler: returning ends the process at once, and the OS stops waiting after its own limit anyway (about 5 s
  for CLOSE, longer for LOGOFF / SHUTDOWN: the OS's number, not ours). HONEST LIMIT: a 90 s write-back of a 1.4 GB log cannot finish inside
  that, so the sentinel may still read unclean; the recorded reason says why.
* ``RegisterSuspendResumeNotification`` (a callback, no window needed; Windows 8 and later): on ``PBT_APMSUSPEND`` a PASSIVE checkpoint
  runs from a connection of its own, interrupted after :data:`SUSPEND_BUDGET_S` (the OS allows about two seconds before it sleeps).
  PASSIVE copies what it can without waiting for any reader or writer and never truncates, so it cannot block the suspend and cannot
  lose a frame; whatever it did not copy stays in the log, which SQLite recovers from on the next open. It runs only for a store this
  process opened (``locked_state``), like the shutdown step. NEVER the TRUNCATE of the shutdown step: that has no time bound.

Everything is recorded in :func:`last_events` (a short list, newest last) for the diagnostics to read; nothing is persisted here.
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import threading
import time
from pathlib import Path
from typing import Any

from src.monitoring.secret_scrub import log_failure

_LOG = logging.getLogger("monitoring.win_power")

#: seconds the suspend checkpoint may run before it is interrupted (the OS gives about two before it sleeps)
SUSPEND_BUDGET_S = 1.5
#: seconds the console handler stays in the handler waiting for the graceful path to end the process
CONSOLE_HOLD_S = 30.0

_CTRL_NAMES = {2: "CTRL_CLOSE_EVENT", 5: "CTRL_LOGOFF_EVENT", 6: "CTRL_SHUTDOWN_EVENT"}
_PBT_APMSUSPEND = 4
_PBT_RESUME = {7: "PBT_APMRESUMESUSPEND", 18: "PBT_APMRESUMEAUTOMATIC"}
_DEVICE_NOTIFY_CALLBACK = 2
_MAX_EVENTS = 20

_events: list[dict[str, Any]] = []
_events_lock = threading.Lock()
# the ctypes objects must outlive the registration, or the OS calls freed memory
_keep: list[Any] = []


def _note(kind: str, **facts: Any) -> dict[str, Any]:
    row = {"at": time.time(), "kind": kind, **facts}
    with _events_lock:
        _events.append(row)
        del _events[:-_MAX_EVENTS]
    return row


def last_events() -> list[dict[str, Any]]:
    """The events seen by this process (newest last, at most :data:`_MAX_EVENTS`)."""
    with _events_lock:
        return [dict(e) for e in _events]


def suspend_checkpoint(*, budget_s: float = SUSPEND_BUDGET_S) -> dict[str, Any]:
    """One PASSIVE checkpoint of the store, interrupted after ``budget_s``. Never raises; returns what happened."""
    out: dict[str, Any] = {"outcome": "skipped"}
    began = time.monotonic()
    try:
        from src.database import library_generation
        from src.database.connect import connect, locked_state
        from src.database.session import DB_FILE

        if not DB_FILE or DB_FILE == ":memory:":
            out["why"] = "no file"
            return out
        db = Path(DB_FILE)
        if not db.exists() or locked_state(db) not in ("unlocked-plaintext", "unlocked-encrypted"):
            out["why"] = "not open here"
            return out
        with library_generation.connecting():
            conn = connect(db, check_same_thread=False)
            timer = threading.Timer(budget_s, lambda: _interrupt(conn))
            timer.daemon = True
            timer.start()
            try:
                conn.execute("PRAGMA busy_timeout = 0")
                row = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
                out["passive"] = [int(x) for x in row] if row is not None else None
                out["outcome"] = "done"
            finally:
                timer.cancel()
                try:
                    conn.close()
                except Exception as exc:  # noqa: BLE001 - the answer stands; a failed close is not the checkpoint's
                    log_failure(_LOG, "suspend checkpoint: closing its connection failed", exc, level=logging.DEBUG)
    except Exception as exc:  # noqa: BLE001 - a sleeping machine never waits on this
        out["outcome"] = "interrupted" if "interrupt" in type(exc).__name__.lower() or "interrupt" in str(exc).lower() else "failed"
        out["error"] = type(exc).__name__
    out["seconds"] = round(time.monotonic() - began, 3)
    return out


def _interrupt(conn: Any) -> None:
    with contextlib.suppress(Exception):  # nothing left to interrupt
        conn.interrupt()


def on_power_event(event_type: int) -> None:
    """The suspend / resume callback's body (separate from ctypes so it is tested without Windows). Never raises."""
    try:
        if event_type == _PBT_APMSUSPEND:
            facts = suspend_checkpoint()
            _note("suspend", **facts)
            _LOG.info("system suspending: passive checkpoint %s", facts.get("outcome"))
        elif event_type in _PBT_RESUME:
            _note("resume", event=_PBT_RESUME[event_type])
    except Exception as exc:  # noqa: BLE001
        log_failure(_LOG, "power event handling failed", exc, level=logging.DEBUG)


def on_console_event(ctrl_type: int, *, hold_s: float = CONSOLE_HOLD_S, sleep=time.sleep) -> bool:
    """The console handler's body. ``True`` = handled (the process is not ended by the default handler). Events other than the three that end
    a session are left to the next handler (uvicorn's own Ctrl-C / Ctrl-Break)."""
    name = _CTRL_NAMES.get(ctrl_type)
    if name is None:
        return False
    try:
        _note("console-end", event=name)
        try:
            from src.monitoring.forensics import note_stop_signal, record_shutdown_phase

            note_stop_signal(name)
            record_shutdown_phase("os-ending", reason=name)
        except Exception as exc:  # noqa: BLE001
            log_failure(_LOG, "could not record the console end", exc, level=logging.DEBUG)
        signal.raise_signal(signal.SIGINT)
        sleep(hold_s)  # the graceful path ends the process; returning would end it first
    except Exception as exc:  # noqa: BLE001
        log_failure(_LOG, "console end handling failed", exc, level=logging.DEBUG)
    return True


def install() -> list[str]:
    """Register the two listeners; returns the names registered (empty off Windows). Never raises."""
    if os.name != "nt":
        return []
    installed: list[str] = []
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handler_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
        handler = handler_t(lambda t: on_console_event(int(t)))
        if kernel32.SetConsoleCtrlHandler(handler, True):
            _keep.append(handler)
            installed.append("console-ctrl")
    except Exception as exc:  # noqa: BLE001 - never stops the app
        log_failure(_LOG, "could not register the console control handler", exc, level=logging.DEBUG)
    try:
        import ctypes
        from ctypes import wintypes

        callback_t = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p)

        class _Params(ctypes.Structure):
            _fields_ = [("Callback", callback_t), ("Context", ctypes.c_void_p)]

        callback = callback_t(lambda _ctx, typ, _setting: (on_power_event(int(typ)), 0)[1])
        params = _Params(callback, None)
        powrprof = ctypes.WinDLL("powrprof")
        powrprof.RegisterSuspendResumeNotification.restype = ctypes.c_void_p  # HPOWERNOTIFY, NULL on failure
        powrprof.RegisterSuspendResumeNotification.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        handle = powrprof.RegisterSuspendResumeNotification(ctypes.byref(params), _DEVICE_NOTIFY_CALLBACK)
        if handle:
            _keep.extend([callback, params, handle])
            installed.append("suspend-resume")
    except Exception as exc:  # noqa: BLE001 - never stops the app
        log_failure(_LOG, "could not register for suspend and resume", exc, level=logging.DEBUG)
    return installed
