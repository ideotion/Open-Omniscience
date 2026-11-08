"""The terminal panel: what the launcher window shows while the app runs with no browser open (R600, 2026-11-08).

WHY. On an instance left running for days, the browser tab is the largest thing the app costs and the least used: on a 3 GB Qubes VM a
browser frees 0.5 to 1 GB when it closes, and every job the operator cares about (collection, downloads, backups, imports, the AI jobs,
the diagnostics archive) runs inside the server whether a tab is open or not. What was missing was a way to SEE that from the window that
holds the server, and to get the browser back. This module is that view: a small curses screen, clickable where the terminal sends mouse
clicks, readable with keys where it does not (an SSH session, a terminal with no mouse).

WHAT IT MAY DO, AND WHAT IT NEVER DOES.
  * It talks to ONE host, the literal loopback address below, on the launcher's port. It is not configurable: an address taken from the
    environment or the command line could point this at another machine, and nothing here should ever leave the computer.
  * It reads only what the browser's own task manager reads (``/api/health``, ``/api/system/lock-state``, ``/api/system/vitals``,
    ``/api/scheduler/status``, ``/api/jobs``), and only while it is on screen.
  * It POSTs exactly two things: ``/api/scheduler/stop`` (pause collection, which engages airplane mode, a move TOWARD offline) and
    ``/api/system/shutdown`` (the app's own power button, after a second press). It NEVER resumes collection or brings the app online
    (R601): every offline-to-online move passes the browser's one consent popup (invariant #14), which lists the local interfaces and
    names the action; a key in a terminal would be a second, lesser gate beside it.
  * It NEVER asks for, reads, holds or prints the passphrase. A locked app is shown as locked, with the way to unlock: open the UI.
  * It imports nothing from the app but the list of held secret variables (``secret_scrub.HELD_ENV_VARS``, standard library only), so
    it costs a few megabytes, not the server's footprint twice. It drops those variables from its own environment as it starts, so
    no browser it opens can inherit them (on Windows ``os.startfile`` cannot be handed an environment).

THE STOP PATHS ARE THE LAUNCHER'S, UNCHANGED. The panel runs in cbreak mode, never raw, so Ctrl-C still reaches the whole foreground group
as a terminal SIGINT (the server takes its graceful path, the launcher records the stop) and the panel itself just restores the terminal and
ends. Closing the window still sends the hangup that stops the app. "Stop app" is the in-app power button over loopback, so the launcher
sees the same exit (143) it already reads as a stop somebody asked for.

WINDOWS (anticipated, R600; not run on Windows). Python's curses is absent there unless the ``windows-curses`` package is installed (a
marker dependency since R602, on the platforms it publishes wheels for), so without it :func:`main` says so and ends, and ``launch.cmd``
only starts the panel when ``import curses`` works. There the panel opens in a window of
its own beside the server's console: closing it does not stop the app (the footer says so), ``os.kill`` is never used to test a pid
(on Windows it TERMINATES the process), and the browser opens through ``os.startfile``.
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.monitoring.secret_scrub import HELD_ENV_VARS

try:  # absent on Windows without windows-curses; main() says so and ends
    import curses
    from curses import error as CursesError
except ImportError:  # pragma: no cover - exercised on Windows only
    curses = None  # type: ignore[assignment]
    CursesError = OSError  # type: ignore[misc,assignment]  # never raised: main() ends before any curses call

#: The only host this panel ever connects to. Loopback by construction, never read from argv or the environment.
HOST = "127.0.0.1"
#: How often the data is read: faster while something runs, slower when the machine is idle.
REFRESH_BUSY_S = 3.0
REFRESH_IDLE_S = 8.0
#: The whole screen is repainted this often, which also wipes any server log line printed over the panel.
REPAINT_S = 1.0
#: A second press of Stop within this many seconds confirms it; anything else cancels.
STOP_CONFIRM_S = 10.0
#: With no server pid to watch (Windows), the panel ends after the server has stopped answering this long...
GONE_AFTER_S = 20.0
#: ...or when it never answered at all for this long (a first launch preparing its database can take minutes).
NEVER_ANSWERED_S = 300.0
#: With a server pid, the pid is the first test, but a pid can be REUSED by another process once the server has ended, so the
#: silence still ends the panel, over a longer wait that a server busy for a while never reaches.
GONE_WITH_PID_S = 300.0
NEVER_ANSWERED_WITH_PID_S = 1800.0
#: run()'s answer when it ended because the server stayed silent: main() says so instead of vanishing like a crash.
SILENT_EXIT = 11
#: The largest response read: the job list of a busy instance is tens of kilobytes.
MAX_BODY = 4_000_000

IS_WINDOWS = os.name == "nt"

Fetch = Callable[..., Any]


def api(port: int, method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 3.0) -> Any:
    """One JSON request to the local app. Returns the decoded body, ``{"_error": status}`` for an HTTP error, or None when unreachable.

    No Origin or Referer header is sent: the app's CSRF guard admits a request that carries neither (a CLI caller), and refuses only a
    foreign one. A JSON body goes with its Content-Type, which the app requires (fastapi's strict content type)."""
    conn = http.client.HTTPConnection(HOST, port, timeout=timeout)
    try:
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read(MAX_BODY)
        if resp.status >= 400:
            return {"_error": resp.status}
        return json.loads(raw or b"{}")
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        conn.close()


@dataclass
class Job:
    kind: str
    label: str
    state: str
    percent: float | None = None
    done: float | None = None
    total: float | None = None
    unit: str = ""


@dataclass
class Snapshot:
    reachable: bool = False
    version: str = ""
    lock_state: str = ""
    locked: bool = False
    online: bool | None = None
    collecting: bool = False
    collect_phase: str = ""
    rss_bytes: int | None = None
    cpu_percent: float | None = None
    uptime_s: float | None = None
    jobs: list[Job] = field(default_factory=list)
    jobs_known: bool = False

    @property
    def running(self) -> list[Job]:
        return [j for j in self.jobs if j.state == "running"]

    @property
    def busy(self) -> bool:
        return self.collecting or bool(self.running)


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def take_snapshot(port: int, fetch: Fetch = api) -> Snapshot:
    """Read the app's state the way the browser's task manager does. Every read may fail on its own; what failed is shown as unknown."""
    snap = Snapshot()
    health = fetch(port, "GET", "/api/health")
    if not isinstance(health, dict) or "_error" in health:
        return snap
    snap.reachable = True
    snap.version = str(health.get("version") or "")
    lock = fetch(port, "GET", "/api/system/lock-state")
    if isinstance(lock, dict) and "_error" not in lock:
        snap.lock_state = str(lock.get("state") or "")
        snap.locked = bool(lock.get("locked"))
    vit = fetch(port, "GET", "/api/system/vitals")
    if isinstance(vit, dict) and "_error" not in vit:
        proc = vit.get("process") or {}
        rss = _num(proc.get("rss_bytes"))
        snap.rss_bytes = int(rss) if rss is not None else None
        snap.cpu_percent = _num(proc.get("cpu_percent"))
        snap.uptime_s = _num(vit.get("uptime_s"))
    sch = fetch(port, "GET", "/api/scheduler/status")
    if isinstance(sch, dict) and "_error" not in sch:
        snap.online = bool(sch["online"]) if isinstance(sch.get("online"), bool) else None
        snap.collecting = bool(sch.get("running") or sch.get("active"))
        snap.collect_phase = str(sch.get("phase") or "")
    jobs = fetch(port, "GET", "/api/jobs")
    if isinstance(jobs, dict) and isinstance(jobs.get("jobs"), list):
        snap.jobs_known = True
        for j in jobs["jobs"]:
            if not isinstance(j, dict):
                continue
            prog: dict[str, Any] = j["progress"] if isinstance(j.get("progress"), dict) else {}
            snap.jobs.append(Job(
                kind=str(j.get("kind") or ""),
                label=str(j.get("label") or j.get("kind") or "job"),
                state=str(j.get("state") or ""),
                percent=_num(prog.get("percent")),
                done=_num(prog.get("done")),
                total=_num(prog.get("total")),
                unit=str(prog.get("unit") or ""),
            ))
    return snap


def fmt_bytes(n: float | None) -> str:
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") or n >= 100 else f"{n:.1f} {unit}"
        n /= 1000
    return "?"  # pragma: no cover


def fmt_duration(s: float | None) -> str:
    if s is None:
        return "?"
    s = int(s)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def _bar(pct: float, width: int = 16) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = round(width * pct / 100)
    return "[" + "#" * filled + "-" * (width - filled) + f"] {pct:5.1f} %"


@dataclass
class Button:
    action: str
    label: str
    row: int = 0
    col: int = 0

    @property
    def width(self) -> int:
        return len(self.label) + 4  # "[ " + label + " ]"

    def hit(self, x: int, y: int) -> bool:
        return y == self.row and self.col <= x < self.col + self.width


@dataclass
class PanelState:
    stop_confirm_until: float = 0.0
    notice: str = ""
    notice_until: float = 0.0


def buttons_for(snap: Snapshot, *, windows: bool = IS_WINDOWS) -> list[Button]:
    out = [Button("open", "Open UI (o)")]
    if snap.reachable and (snap.collecting or snap.online):
        out.append(Button("pause", "Pause collection (p)"))
    if not windows:  # on Windows the server's log is in its own console window, not behind this panel
        out.append(Button("log", "Show log (l)"))
    out.append(Button("stop", "Stop app (s)"))
    out.append(Button("quit", "Close panel (q)"))
    return out


Line = tuple[str, str]  # (text, style)


def build_screen(snap: Snapshot, width: int, state: PanelState, url: str, now: float,
                 *, windows: bool = IS_WINDOWS, starting: bool = False, height: int | None = None) -> tuple[list[Line], list[Button]]:
    """The whole screen as text lines and the clickable buttons, independent of curses (so it is tested without a terminal)."""
    lines: list[Line] = []
    title = "Open Omniscience" + (f" {snap.version}" if snap.version else "")
    lines.append((f"{title}  ·  {url}", "title"))
    lines.append(("", "normal"))
    if not snap.reachable:
        if starting:
            lines.append(("Starting... the panel fills in as soon as the app answers.", "warn"))
        else:
            lines.append(("The app is not answering. It may be busy, stopping, or the computer just woke up.", "warn"))
    else:
        if snap.locked:
            lines.append(("Locked: open the UI to unlock. Collection and jobs start after you unlock.", "warn"))
        elif snap.lock_state == "unlocked-plaintext":
            lines.append(("Unlocked (not encrypted)", "ok"))
        elif snap.lock_state:
            lines.append(("Unlocked (encrypted)", "ok"))
        net = {True: "online", False: "offline (airplane mode)", None: "unknown"}[snap.online]
        coll = "running" if snap.collecting else "stopped"
        if snap.collecting and snap.collect_phase:
            coll += f" ({snap.collect_phase})"
        lines.append((f"Network: {net}    Collection: {coll}", "normal"))
        lines.append((
            f"Server: CPU {snap.cpu_percent if snap.cpu_percent is not None else '?'} %  ·  "
            f"memory {fmt_bytes(snap.rss_bytes)}  ·  up {fmt_duration(snap.uptime_s)}", "normal"))
        lines.append(("", "normal"))
        running = snap.running
        queued = [j for j in snap.jobs if j.state == "queued"]
        if not snap.jobs_known:
            lines.append(("Jobs: not readable right now.", "dim"))
        elif not snap.jobs:
            lines.append(("Jobs: none. The app is idle.", "dim"))
        else:
            lines.append((f"Jobs: {len(running)} running, {len(queued)} queued", "title"))
            # The buttons come after the list, so a long queue must never push them off a short terminal: the rows the rest of the
            # screen needs are kept, and the jobs that do not fit are counted, never silently dropped.
            shown = snap.jobs
            if height is not None:
                room = max(1, height - len(lines) - 10)
                if len(shown) > room:
                    shown = shown[: max(room - 1, 1)]
            for j in shown:
                mark = {"running": ">", "queued": ".", "paused": "=", "failed": "!"}.get(j.state, " ")
                text = f" {mark} {j.label} [{j.state}]"
                if j.percent is not None and j.state in ("running", "paused"):
                    text += "  " + _bar(j.percent)
                elif j.done is not None and j.state == "running":
                    text += f"  {j.done:.0f}" + (f"/{j.total:.0f}" if j.total else "") + (f" {j.unit}" if j.unit else "")
                lines.append((text, "ok" if j.state == "running" else "dim"))
            if len(shown) < len(snap.jobs):
                lines.append((f"   ... and {len(snap.jobs) - len(shown)} more (the UI's task manager lists them all)", "dim"))
    lines.append(("", "normal"))
    if state.stop_confirm_until > now:
        names = [j.label for j in snap.running]
        what = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
        lines.append(("Stop the app? " + (f"These jobs end: {what}. " if names else "No job is running. ")
                      + "Press s again (or click Stop again) to confirm. Any other key cancels.", "warn"))
    elif state.notice and state.notice_until > now:
        lines.append((state.notice, "warn"))
    else:
        lines.append(("You can close the browser: jobs keep running here. Reopen it with Open UI.", "dim"))
    lines.append(("", "normal"))
    # Buttons, wrapped to the width.
    btns = buttons_for(snap, windows=windows)
    row, col = len(lines), 0
    for b in btns:
        if col and col + b.width > max(width - 1, 1):
            row, col = row + 1, 0
        b.row, b.col = row, col
        col += b.width + 2
    for _ in range(row - len(lines) + 1):
        lines.append(("", "button"))
    lines.append(("", "normal"))
    if windows:
        lines.append(("Closing this panel window does NOT stop the app. Use Stop app, or close the app's own window.", "dim"))
    else:
        lines.append(("Closing this window stops the app. Ctrl-C stops it too.", "dim"))
    return [(t[: max(width - 1, 0)], s) for t, s in lines], btns


def loopback_url(url: str, port: int) -> str:
    """The address Open UI opens: the one given only when it is plain http to loopback (no user part, which would let
    ``http://127.0.0.1:8000@elsewhere/`` through a prefix test), else the app's own address on its port."""
    from urllib.parse import urlsplit

    try:
        u = urlsplit(url)
        ok = (u.scheme == "http" and u.hostname in (HOST, "::1") and u.username is None and u.password is None
              and u.port is not None)
    except ValueError:
        ok = False
    return url if ok else f"http://{HOST}:{port}/"


def open_ui(url: str) -> bool:
    """Open the UI in the default browser, detached from this terminal so closing the window or a Ctrl-C never reaches the browser,
    and with its output thrown away so it never prints over the panel."""
    try:
        if IS_WINDOWS:
            os.startfile(url)  # type: ignore[attr-defined]  # noqa: S606 - the app's own loopback URL
            return True
        cmd = ["open", url] if sys.platform == "darwin" else ["xdg-open", url]
        if not shutil.which(cmd[0]):
            return False
        # The browser is a third-party program that reaches the network: it is given the environment WITHOUT the held secrets.
        env = {k: v for k, v in os.environ.items() if k not in HELD_ENV_VARS}
        subprocess.Popen(  # noqa: S603 - fixed program, the app's own loopback URL
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, env=env,
        )
        return True
    except OSError:
        return False


def do_action(action: str, state: PanelState, snap: Snapshot, port: int, url: str, now: float,
              *, fetch: Fetch = api, opener: Callable[[str], bool] = open_ui) -> str | None:
    """Apply one action. Returns "quit" to close the panel, "log" to show the server log, else None. Pure apart from fetch/opener."""
    def say(text: str) -> None:
        state.notice, state.notice_until = text, now + 8.0

    if action != "stop":
        state.stop_confirm_until = 0.0
    if action == "open":
        say("Opening the UI in your browser..." if opener(url) else f"Could not open a browser. Open this address yourself: {url}")
    elif action == "pause":
        r = fetch(port, "POST", "/api/scheduler/stop", {})
        if isinstance(r, dict) and "_error" not in r:
            say("Collection paused and the app is offline. To resume, open the UI (it asks before going online).")
        else:
            say("Pause did not go through. Try again, or use the UI.")
    elif action == "stop":
        if state.stop_confirm_until > now:
            state.stop_confirm_until = 0.0
            r = fetch(port, "POST", "/api/system/shutdown", {"confirm": True})
            say("Stopping the app... running jobs end now." if isinstance(r, dict) and "_error" not in r
                else "The stop did not go through. Close this window or press Ctrl-C to stop the app.")
        else:
            state.stop_confirm_until = now + STOP_CONFIRM_S
    elif action == "log":
        return "log"
    elif action == "quit":
        return "quit"
    return None


KEYS = {"o": "open", "p": "pause", "l": "log", "s": "stop", "q": "quit"}


def key_action(ch: int, buttons: list[Button], mouse: tuple[int, int] | None = None) -> str | None:
    """Map a key (or a click at ``mouse`` = (x, y)) to an action the current buttons offer. Anything else is "other"."""
    offered = {b.action for b in buttons}
    if mouse is not None:
        for b in buttons:
            if b.hit(*mouse):
                return b.action
        return "other"  # a click beside the buttons cancels a pending Stop, as any other key does
    if 0 <= ch < 256:
        a = KEYS.get(chr(ch).lower())
        if a in offered:
            return a
    return "other"


def pid_alive(pid: int | None) -> bool:
    """Whether the server still runs. NEVER ``os.kill`` on Windows: there it terminates the process instead of testing it."""
    if not pid:
        return True
    if IS_WINDOWS:
        try:
            import psutil

            return bool(psutil.pid_exists(pid))
        except Exception:  # noqa: BLE001 - no way to tell: the reachability rule ends the panel instead
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class _Stop(Exception):
    """Raised by the signal handler so a blocking read (a key, the log view) ends at once and curses.wrapper restores the terminal."""


_STYLES = ("title", "ok", "warn", "dim", "button", "normal")


def _attrs() -> dict[str, int]:
    assert curses is not None
    a = dict.fromkeys(_STYLES, curses.A_NORMAL)
    a["title"] = curses.A_BOLD
    a["dim"] = curses.A_DIM
    if curses.has_colors():
        with contextlib.suppress(CursesError):
            curses.use_default_colors()
        pairs = {"ok": curses.COLOR_GREEN, "warn": curses.COLOR_YELLOW, "button": curses.COLOR_CYAN}
        for i, (name, color) in enumerate(pairs.items(), start=1):
            try:
                curses.init_pair(i, color, -1)
                a[name] = curses.color_pair(i) | (curses.A_BOLD if name == "warn" else 0)
            except CursesError:
                pass
    a["button"] |= curses.A_REVERSE
    return a


def _draw(scr: Any, lines: list[Line], buttons: list[Button], attrs: dict[str, int], full: bool) -> None:
    assert curses is not None
    h, w = scr.getmaxyx()
    if full:
        scr.clear()  # a full repaint: a server log line printed over the panel is wiped here
    else:
        scr.erase()
    for y, (text, style) in enumerate(lines[: h]):
        with contextlib.suppress(CursesError):
            scr.addnstr(y, 0, text, max(w - 1, 0), attrs.get(style, 0))
    for b in buttons:
        if b.row < h and b.col + b.width < w:
            with contextlib.suppress(CursesError):
                scr.addstr(b.row, b.col, f"[ {b.label} ]", attrs["button"])
    scr.refresh()


def _show_log(scr: Any, server_pid: int | None) -> bool:
    """Step out of the panel: the terminal shows the server's own output again until Enter. POSIX only (on Windows the log is in the
    server's own window). Returns False when the server ended meanwhile, so the panel ends instead of waiting on a key nobody presses:
    the launcher waits for this process before it reports how the server ended."""
    assert curses is not None
    import select

    curses.endwin()
    sys.stdout.write("\n--- The server's own messages appear below. Press Enter to return to the panel. ---\n\n")
    sys.stdout.flush()
    # Every way out goes back through curses first: curses.wrapper calls endwin() again when the panel ends, and a second endwin()
    # without a refresh between them fails, which read as "the panel could not start" right above the launcher's own message.
    back = True
    try:
        while True:
            if not pid_alive(server_pid):
                back = False
                break
            ready, _, _ = select.select([sys.stdin], [], [], 0.5)
            if ready:
                if not sys.stdin.readline():
                    back = False  # end of input: no terminal to come back to
                break
    finally:
        with contextlib.suppress(CursesError):
            scr.clear()
            scr.refresh()
    return back


def server_silent_too_long(server_pid: int | None, *, ever: bool, now: float, last_ok: float, started: float) -> bool:
    """Whether the server has not answered for long enough that the panel should end, the pid test aside."""
    gone, never = (GONE_AFTER_S, NEVER_ANSWERED_S) if server_pid is None else (GONE_WITH_PID_S, NEVER_ANSWERED_WITH_PID_S)
    return (now - last_ok > gone) if ever else (now - started > never)


def silent_message(url: str) -> str:
    """What the panel says as it ends because the app stopped answering (it cannot tell a hung app from one that is gone)."""
    return (f"\nThe app has not answered for a while, so the panel closed. If Open Omniscience is still running, open {url} "
            "in the browser.\n")


def run(scr: Any, port: int, url: str, server_pid: int | None, stopping: list[bool]) -> int:
    assert curses is not None
    with contextlib.suppress(CursesError):
        curses.curs_set(0)
    scr.keypad(True)
    scr.timeout(250)
    mouse_ok = False
    try:
        # ONE event per click: the press only. With press, release and click all in the mask (and mouseinterval 0), one physical
        # click arrived as two events, and the second confirmed the Stop the first had armed (Opus read, 8 Nov).
        avail, _ = curses.mousemask(curses.BUTTON1_PRESSED)
        mouse_ok = bool(avail)
        curses.mouseinterval(0)
    except CursesError:
        pass
    attrs = _attrs()
    state = PanelState()
    snap = Snapshot()
    started = time.monotonic()
    last_ok = 0.0
    ever = False
    next_fetch = 0.0
    next_repaint = 0.0
    buttons: list[Button] = []
    while not stopping[0]:
        now = time.monotonic()
        if not pid_alive(server_pid):
            return 0
        full = False
        if now >= next_fetch:
            snap = take_snapshot(port)
            if snap.reachable:
                ever, last_ok = True, now
            elif server_silent_too_long(server_pid, ever=ever, now=now, last_ok=last_ok, started=started):
                return SILENT_EXIT
            next_fetch = now + (REFRESH_BUSY_S if (snap.busy or not snap.reachable) else REFRESH_IDLE_S)
        if now >= next_repaint:
            full, next_repaint = True, now + REPAINT_S
        h, w = scr.getmaxyx()
        lines, buttons = build_screen(snap, w, state, url, time.time(), starting=not ever, height=h)
        if not mouse_ok:
            lines.append(("Keys: o open UI · p pause · s stop · q close panel" if IS_WINDOWS
                          else "Keys: o open UI · p pause · l log · s stop · q close panel", "dim"))
        _draw(scr, lines, buttons, attrs, full)
        ch = scr.getch()
        if ch == -1:
            continue
        click = None
        if ch == curses.KEY_MOUSE:
            try:
                _id, x, y, _z, bstate = curses.getmouse()
            except CursesError:
                continue
            if not bstate & curses.BUTTON1_PRESSED:
                continue
            click = (x, y)
        elif ch == curses.KEY_RESIZE:
            next_repaint = 0.0
            continue
        action = key_action(ch, buttons, click)
        if action is None:
            continue
        if action == "other":
            state.stop_confirm_until = 0.0
            continue
        result = do_action(action, state, snap, port, url, time.time())
        next_fetch = time.monotonic() + 0.5 if action in ("pause", "stop") else next_fetch
        if result == "quit":
            return 10
        if result == "log":
            if not _show_log(scr, server_pid):
                return 0
            next_repaint = 0.0
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m src.tui.panel", description=__doc__.splitlines()[0])
    p.add_argument("--port", type=int, default=int(os.environ.get("OO_PORT") or 8000))
    p.add_argument("--server-pid", type=int, default=None, help="end the panel when this process ends (the launcher's server)")
    p.add_argument("--url", default="", help="the address Open UI opens (defaults to the loopback address and port)")
    for name in HELD_ENV_VARS:  # first: nothing the panel starts (a browser) may inherit them, and it never needs them itself
        os.environ.pop(name, None)
    args = p.parse_args(argv)
    url = loopback_url(args.url, args.port)
    if curses is None:
        print("The terminal panel needs Python's curses module"
              + (" (on Windows: pip install windows-curses)." if IS_WINDOWS else "."), file=sys.stderr)
        return 3
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return 3
    stopping = [False]

    def _end(_sig: int, _frame: Any) -> None:
        # The panel only restores the terminal and ends. A Ctrl-C reaches the server and the launcher on its own (one SIGINT to the
        # whole foreground group), so nothing is forwarded from here: a second signal is what once made uvicorn skip its teardown.
        stopping[0] = True
        raise _Stop

    # The panel is a process of its own, started by the launcher and imported by no server code (tests/test_event_loop_signal_exemption.py).
    for sig in (signal.SIGINT, signal.SIGTERM, *([signal.SIGHUP] if hasattr(signal, "SIGHUP") else [])):
        with contextlib.suppress(OSError, ValueError):
            signal.signal(sig, _end)
    try:
        code = curses.wrapper(run, args.port, url, args.server_pid, stopping)
        if code == 10:
            print("\nPanel closed. Open Omniscience keeps running: close this window or press Ctrl-C to stop it.\n", flush=True)
        elif code == SILENT_EXIT:
            print(silent_message(url), flush=True)
    except _Stop:  # a signal: curses.wrapper has already restored the terminal
        return 0
    except CursesError as exc:
        print(f"The terminal panel could not start ({type(exc).__name__}). The app keeps running.", file=sys.stderr)
        return 3
    return int(code)


if __name__ == "__main__":
    sys.exit(main())
