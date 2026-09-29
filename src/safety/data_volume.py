"""The data drive: noticing when the folder the corpus lives in goes away.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE ASK (maintainer, 2026-09-29, ruled R86): the first-launch data-location step lets the
corpus live on a drive other than the one the app is installed on. A drive can be
unplugged. When it is, the app must record the disconnection where diagnostics can find
it later, give the operator 30 seconds to plug it back, and then shut itself down cleanly
with a second 30-second countdown.

THREE PIECES, all stdlib and all local (no network, no score):

1. **A marker.** The chooser writes ``.oos-volume`` (a random id) into the folder it
   creates and records the same id as ``OO_DATA_VOLUME_ID`` in ``oo.env``. The id is what
   tells "the drive is back" from "a different drive is mounted at the same path". An
   install that never chose a folder has no id and none of this runs.

2. **A boot guard** (:func:`guard_data_dir`, called by ``src.paths.data_dir``). Before this
   module, ``data_dir()`` created a missing folder with ``mkdir(parents=True)``: an app
   started with the drive unplugged made an EMPTY folder on the internal disk where the
   mount point was and booted as a fresh install, with new keys, beside nothing. Now a
   missing folder is never created. At boot, the server serves a small "your data drive is
   not connected" page instead and re-executes itself when the marker is back; anywhere
   else it raises :class:`src.paths.DataVolumeMissing`.

3. **A watchdog** (:class:`VolumeMonitor`). Every two seconds it reads the marker; two
   misses in a row (so a drive that is slow to answer once is not an alarm), or one miss
   right after a disk error on the database, start the sequence: record, pause
   collection, 30 s to reconnect, 30 s to shut down. A drive that comes back in either
   window makes the app RESTART rather than resume in place, because the database
   engine is fixed at import (see ``src/safety/data_location.py`` for why a live rebind
   cannot reach every holder); an encrypted install then asks for its passphrase again.

The incident log lives on the INTERNAL disk, under the per-user state folder, because
the one place it cannot go is the drive that just disappeared.
"""

from __future__ import annotations

import html
import json
import logging
import os
import secrets
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("safety.data_volume")

MARKER_NAME = ".oos-volume"
ENV_ID = "OO_DATA_VOLUME_ID"

#: The two windows the maintainer named (R86), in seconds.
RECONNECT_SECONDS = 30
SHUTDOWN_SECONDS = 30
#: How often the watchdog and the boot page look for the marker.
POLL_SECONDS = 2.0
#: Consecutive misses before the watchdog calls it a disconnection.
MISSES_TO_TRIGGER = 2
#: The incident log keeps the newest lines only; a flapping drive must not grow it forever.
_INCIDENT_KEEP = 200


# --------------------------------------------------------------------------- #
#  The marker
# --------------------------------------------------------------------------- #


def expected_id() -> str | None:
    return (os.getenv(ENV_ID) or "").strip() or None


def configured_folder() -> Path | None:
    raw = os.getenv("OO_DATA_DIR")
    return Path(raw).expanduser() if raw else None


def watched() -> bool:
    """Only a folder the chooser marked is watched: an install without an id is untouched."""
    return expected_id() is not None and configured_folder() is not None


def write_marker(folder: Path) -> str:
    """Write a fresh marker into ``folder`` and return its id (atomic, 0600)."""
    vid = secrets.token_hex(8)
    body = json.dumps(
        {
            "id": vid,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "what": (
                "Open Omniscience data-drive marker. The app checks this id to know its "
                "data drive is connected. Deleting it makes the app wait for the drive."
            ),
        },
        indent=2,
    )
    tmp = folder / (MARKER_NAME + ".tmp")
    tmp.write_text(body + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, folder / MARKER_NAME)
    return vid


def read_marker_id(folder: Path) -> str | None:
    try:
        data = json.loads((folder / MARKER_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    vid = data.get("id") if isinstance(data, dict) else None
    return vid if isinstance(vid, str) else None


def probe() -> dict[str, Any]:
    """Is the marked folder there, with the right marker? Never creates anything.

    ``state``: ``unwatched`` (no chosen folder) · ``ok`` · ``missing`` (the folder or its
    marker cannot be read) · ``mismatch`` (a marker with another id: a different drive).
    """
    folder, want = configured_folder(), expected_id()
    if folder is None or want is None:
        return {"state": "unwatched"}
    try:
        present = folder.is_dir()
    except OSError:
        present = False
    if not present:
        return {"state": "missing", "detail": "the folder cannot be found"}
    got = read_marker_id(folder)
    if got is None:
        return {"state": "missing", "detail": "the folder's marker cannot be read"}
    if got != want:
        return {"state": "mismatch", "detail": "the marker belongs to a different drive"}
    return {"state": "ok"}


# --------------------------------------------------------------------------- #
#  The incident log (internal disk)
# --------------------------------------------------------------------------- #


def incident_log_path() -> Path:
    base = os.getenv("XDG_STATE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".local" / "state"
    return root / "open-omniscience" / "data-volume-incidents.jsonl"


def record_incident(event: str, **fields: Any) -> None:
    """Append one line; best-effort, never raises (a recorder is never in the way)."""
    line = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "event": event, "pid": os.getpid()}
    line.update(fields)
    path = incident_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        lines.append(json.dumps(line, sort_keys=True))
        tmp = path.with_suffix(".tmp")
        tmp.write_text("\n".join(lines[-_INCIDENT_KEEP:]) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError:
        _LOG.warning("could not record the data-drive incident %s", event, exc_info=True)
    _LOG.warning("data drive: %s %s", event, fields)


def read_incidents(limit: int = 50) -> list[dict[str, Any]]:
    try:
        raw = incident_log_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for ln in raw[-limit:]:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def last_disconnect_since(started_at: str | None) -> dict[str, Any] | None:
    """The newest ``disconnected`` incident at or after ``started_at`` (ISO), if any.

    The session sentinel lives ON the drive, so a session that ended because the drive
    went away could not write its own ending; this is the witness that can.
    """
    for rec in reversed(read_incidents(_INCIDENT_KEEP)):
        if rec.get("event") != "disconnected":
            continue
        if started_at and str(rec.get("at", "")) < started_at[:19]:
            return None
        return rec
    return None


def report() -> dict[str, Any]:
    """The diagnostics-bundle member: current state + the incident log."""
    return {
        "watched": watched(),
        "probe": probe(),
        "monitor": MONITOR.snapshot(),
        "incident_log": str(incident_log_path()),
        "incidents": read_incidents(),
        "method": (
            "The chosen data folder holds a marker file with a random id that oo.env also "
            "records; the watchdog reads it every 2 s and calls two misses in a row (or one "
            "after a database disk error) a disconnection. The log lives on the internal disk."
        ),
    }


def forget_volume_id() -> None:
    """Drop the id from ``oo.env`` and the environment (after a deliberate wipe, so the
    next start makes a fresh folder instead of waiting for a drive that was erased)."""
    os.environ.pop(ENV_ID, None)
    try:
        from src.safety.data_location import env_file_path

        env = env_file_path()
        if not env.exists():
            return
        kept = [ln for ln in env.read_text(encoding="utf-8").splitlines() if not ln.startswith(f"export {ENV_ID}=")]
        env.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    except OSError:
        _LOG.warning("could not remove %s from oo.env", ENV_ID, exc_info=True)


# --------------------------------------------------------------------------- #
#  The boot guard
# --------------------------------------------------------------------------- #

_BOOT_CHECKED = False
#: Set once the server has booted (lifespan); after that a missing folder raises.
_BOOTED = False


def _is_server_launch() -> bool:
    """True for ``open-omniscience`` / ``open-omniscience serve`` / ``python -m src.api.main``."""
    argv = list(getattr(sys, "orig_argv", sys.argv))
    prog = Path(sys.argv[0]).name if sys.argv else ""
    rest = sys.argv[1:]
    serving = not rest or rest[0] == "serve"
    return serving and (prog == "open-omniscience" or "src.api.main" in argv)


def mark_booted() -> None:
    global _BOOTED
    _BOOTED = True


def guard_data_dir(folder: Path) -> None:
    """Called by ``data_dir()`` for a chosen folder. Raises ``DataVolumeMissing`` rather
    than letting the folder be created; at boot, serves the waiting page instead."""
    from src.paths import DataVolumeMissing

    global _BOOT_CHECKED
    if not watched():
        return
    if not _BOOT_CHECKED:
        _BOOT_CHECKED = True
        state = probe()
        if state["state"] != "ok":
            if not _BOOTED and _is_server_launch():
                wait_for_volume(state)   # never returns: re-executes or exits
            raise DataVolumeMissing(f"data drive not available at {folder}: {state.get('detail')}")
        return
    try:
        present = folder.is_dir()
    except OSError:
        present = False
    if not present:
        MONITOR.poke("data_dir() found the folder gone")
        raise DataVolumeMissing(f"data drive not available at {folder}")


def _restart_process() -> None:
    """Re-execute this same command line (same pid, so the launcher keeps holding it)."""
    argv = list(getattr(sys, "orig_argv", [sys.executable, *sys.argv]))
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(sys.executable, [sys.executable, *argv[1:]])


def _locale_map(accept: str) -> tuple[str, dict[str, str]]:
    """The UI's own locale files, picked from Accept-Language (English fallback)."""
    root = Path(__file__).resolve().parents[1] / "static" / "locales"
    for part in (accept or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        f = root / f"{code}.json"
        if code and f.is_file():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                return code, {k: v for k, v in data.items() if isinstance(v, str)}
            except (OSError, ValueError):
                break
    return "en", {}


def waiting_page(state: dict[str, Any], accept: str = "") -> str:
    lang, tr = _locale_map(accept)

    def t(s: str) -> str:
        return tr.get(s, s)

    folder = str(configured_folder() or "")
    from src.safety.data_location import env_file_path

    body = t(
        "Open Omniscience keeps its data in {path}, and that folder cannot be found. "
        "Connect the drive that holds it. This page checks again every few seconds and "
        "opens the app as soon as the drive is back."
    ).replace("{path}", folder)
    extra = ""
    if state.get("state") == "mismatch":
        extra = t("The drive at this path is not the one this app set up: its marker file does not match.")
    wiped = t(
        "If you deleted this folder on purpose, remove the OO_DATA_DIR and OO_DATA_VOLUME_ID "
        "lines from {env} to start with a new, empty corpus."
    ).replace("{env}", str(env_file_path()))
    rtl = ' dir="rtl"' if lang == "ar" else ""
    e = html.escape
    return (
        f'<!doctype html><html lang="{e(lang)}"{rtl}><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="refresh" content="3">'
        f"<title>{e(t('Your data drive is not connected'))} · FOOS</title>"
        "<style>body{font-family:system-ui,sans-serif;background:#111418;color:#e8e6e3;"
        "max-width:40rem;margin:10vh auto;padding:0 16px;line-height:1.5}"
        "h1{font-size:1.4rem}code{word-break:break-all}.cav{color:#eab44e}"
        "button{font:inherit;padding:.4rem 1rem;margin-top:1rem}</style></head><body>"
        f"<h1>{e(t('Your data drive is not connected'))}</h1><p>{e(body)}</p>"
        + (f'<p class="cav">{e(extra)}</p>' if extra else "")
        + f"<p><small>{e(wiped)}</small></p>"
        f'<form method="post" action="/quit"><button type="submit">{e(t("Quit"))}</button></form>'
        "</body></html>"
    )


def wait_for_volume(state: dict[str, Any]) -> None:
    """Serve the waiting page on the app's own address until the marker is back, then
    re-execute; the Quit button exits. Never returns."""
    record_incident("boot_without_drive", path=str(configured_folder()), detail=state.get("detail"))
    host = os.getenv("OO_HOST", "127.0.0.1")
    port = int(os.getenv("OO_PORT", "8000"))
    current = {"state": state}
    quit_flag = threading.Event()

    class _Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - http.server's name
            if self.path.startswith("/api/"):
                # 200 so the launcher opens the browser at once rather than after 20 s.
                body = json.dumps({"status": "waiting_for_data_drive", "data_volume": current["state"]["state"]})
                self._send(200 if self.path.startswith("/api/health") else 503, body.encode(), "application/json")
                return
            page = waiting_page(current["state"], self.headers.get("Accept-Language", ""))
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/quit":
                self._send(200, b"Open Omniscience has stopped.", "text/plain; charset=utf-8")
                quit_flag.set()
                return
            self._send(404, b"", "text/plain")

        def log_message(self, *_a: Any) -> None:
            return

    try:
        server = ThreadingHTTPServer((host, port), _Handler)
    except OSError:
        server = None   # the port is taken; keep waiting without a page
        _LOG.warning("the data drive at %s is not connected; waiting for it", configured_folder())
    if server is not None:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        _LOG.warning("the data drive is not connected; see http://%s:%s/", host, port)
    while True:
        if quit_flag.wait(POLL_SECONDS):
            record_incident("boot_wait_quit")
            if server is not None:
                server.shutdown()
            os._exit(0)
        current["state"] = probe()
        if current["state"]["state"] == "ok":
            record_incident("boot_drive_found")
            if server is not None:
                server.shutdown()
                server.server_close()
            _restart_process()


# --------------------------------------------------------------------------- #
#  The runtime watchdog
# --------------------------------------------------------------------------- #


class VolumeMonitor:
    """ok → reconnect (30 s) → shutdown (30 s) → closing; a returned drive → restarting."""

    def __init__(
        self,
        *,
        probe_fn=probe,
        pause_fn=None,
        restart_fn=None,
        exit_fn=None,
        clock=time.monotonic,
    ) -> None:
        self._probe = probe_fn
        self._pause = pause_fn or _pause_writers
        self._restart = restart_fn or _restart_after_reconnect
        self._exit = exit_fn or _shut_down
        self._clock = clock
        # Re-entrant: recording a disconnection can reach data_dir(), whose guard pokes
        # this monitor back from the same thread (found live, as a hung API, 2026-09-29).
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.phase = "ok"
        self.deadline: float | None = None
        self.misses = 0
        self.last_ok_at: str | None = None
        self.detected_by: str | None = None

    # -- public ---------------------------------------------------------------

    def start(self) -> bool:
        if not watched() or (self._thread is not None and self._thread.is_alive()):
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="oo-data-volume", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def poke(self, reason: str) -> None:
        """A disk error somewhere is corroboration: one failed probe is enough."""
        if not watched():
            return
        # Never waits: if the watchdog is busy, it is already looking.
        if not self._lock.acquire(blocking=False):
            return
        try:
            if self.phase != "ok":
                return
            if self._probe()["state"] != "ok":
                self._trigger(reason)
        finally:
            self._lock.release()

    def close_now(self) -> bool:
        with self._lock:
            if self.phase not in ("reconnect", "shutdown"):
                return False
            self._close("closed by the operator")
            return True

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            left = None
            if self.deadline is not None:
                left = max(0, int(round(self.deadline - self._clock())))
            return {"watched": watched(), "phase": self.phase, "seconds_left": left}

    # -- the loop -------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.wait(POLL_SECONDS):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the watchdog must outlive its own bugs
                _LOG.exception("data-drive watchdog tick failed")

    def tick(self) -> None:
        with self._lock:
            state = self._probe()["state"]
            if state == "unwatched":   # the id was forgotten (a deliberate wipe)
                self.phase, self.deadline, self.misses = "ok", None, 0
                return
            now = self._clock()
            if self.phase == "ok":
                if state == "ok":
                    self.misses = 0
                    self.last_ok_at = datetime.now(UTC).isoformat(timespec="seconds")
                    return
                self.misses += 1
                if self.misses >= MISSES_TO_TRIGGER:
                    self._trigger(f"the marker check failed {self.misses} times in a row ({state})")
                return
            if self.phase in ("reconnect", "shutdown"):
                if state == "ok":
                    record_incident("reconnected", during=self.phase)
                    self.phase, self.deadline = "restarting", None
                    self._restart()
                    return
                if self.deadline is not None and now >= self.deadline:
                    if self.phase == "reconnect":
                        record_incident("shutdown_countdown", seconds=SHUTDOWN_SECONDS)
                        self.phase, self.deadline = "shutdown", now + SHUTDOWN_SECONDS
                    else:
                        self._close("the drive did not come back in time")

    def _trigger(self, reason: str) -> None:
        # The phase moves FIRST, so a poke that re-enters from inside the recording
        # below finds a disconnection already being handled.
        self.detected_by = reason
        self.phase, self.deadline = "reconnect", self._clock() + RECONNECT_SECONDS
        record_incident(
            "disconnected",
            path=str(configured_folder()),
            detected_by=reason,
            last_ok_at=self.last_ok_at,
            activity=_activity(),
        )
        threading.Thread(target=self._pause, name="oo-data-volume-pause", daemon=True).start()

    def _close(self, why: str) -> None:
        self.phase, self.deadline = "closing", None
        record_incident("shutdown", why=why)
        self._exit()


def _activity() -> dict[str, Any]:
    """What was running, best-effort and without the database (it may be the thing gone)."""
    out: dict[str, Any] = {}
    try:
        from src.scheduler.runner import get_scheduler

        out["collection_running"] = get_scheduler().is_running()
    except Exception:  # noqa: BLE001
        pass
    try:
        from src.scheduler.runner import exclusive_window_open

        out["exclusive_operation"] = bool(exclusive_window_open())
    except Exception:  # noqa: BLE001
        pass
    return out


def _pause_writers() -> None:
    """Stop collection (the same pause a restore or an export takes). Deliberately never
    resumed: the sequence ends in a restart or a shutdown either way."""
    try:
        from src.scheduler.runner import pause_for_exclusive_operation

        pause_for_exclusive_operation()
    except Exception:  # noqa: BLE001
        _LOG.warning("data drive: could not pause collection", exc_info=True)


def _reap() -> None:
    try:
        from src.safety.shutdown import _reap_worker_processes

        _reap_worker_processes()
    except Exception:  # noqa: BLE001
        pass


def _restart_after_reconnect() -> None:
    def _go() -> None:
        time.sleep(1.5)   # let the overlay read "restarting" first
        _reap()
        _restart_process()

    threading.Thread(target=_go, name="oo-data-volume-restart", daemon=True).start()


def _shut_down() -> None:
    try:
        from src.monitoring.forensics import record_shutdown_phase

        record_shutdown_phase("shutting-down", reason="data drive disconnected")
    except Exception:  # noqa: BLE001 - the sentinel is on the missing drive; expected
        pass
    from src.safety.shutdown import request_shutdown

    request_shutdown(confirm=True, delay=1.0)


MONITOR = VolumeMonitor()
