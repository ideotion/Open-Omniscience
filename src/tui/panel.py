"""The terminal panel: the ONE window the app keeps open while it runs, whether a browser is open or not (R600 2026-11-08, R658 2026-11-11).

WHY. On an instance left running for days, the browser tab is the largest thing the app costs and the least used: on a 3 GB Qubes VM a
browser frees 0.5 to 1 GB when it closes, and every job the operator cares about (collection, downloads, backups, imports, the AI jobs,
the diagnostics archive) runs inside the server whether a tab is open or not. What was missing was a way to SEE that from the window that
holds the server, and to get the browser back. This module is that view: a small curses screen, clickable where the terminal sends mouse
clicks, readable with keys where it does not (an SSH session, a terminal with no mouse).

WHAT IT SHOWS (R658). A status header, then an ACTIVITY LOG: one dated line per thing that happened (the app answered, collection started,
a download reached 40 %, a backup finished, the network went offline, the app stopped answering and answered again), appended one after
the other for as long as the app runs, newest at the bottom, scrollable with the arrows, PgUp/PgDn and the mouse wheel. The lines are
the differences between successive reads of the same endpoints the browser's task manager reads; nothing is written to disk and nothing
new is asked of the server. The newest LOG_KEEP lines are kept in memory, and the header says how many older ones were let go.

IT DOES NOT CLOSE WHILE THE APP RUNS (R658, the 2026-11-11 field report: "the UI disappeared when I clicked on it after some time"). Three
things used to end it: a "Close panel" button one click away from the others; a "Show log" button that left curses until Enter, which a
click never sends; and a silence rule (20 s on Windows, 5 min elsewhere) that closed it whenever a busy or sleeping server stayed quiet,
and on Windows closed the window with it. Now there is no close button, the log view returns on any key, and silence is SHOWN ("not
answering for 3m 12s"), never acted on. The panel ends only when the server's process has ended, which it checks by the process's
identity (pid AND start time through psutil, so a pid reused by another program is never mistaken for the server), or on a signal. An
error inside the panel redraws it with its log intact instead of ending it (RESTARTS_MAX in RESTART_WINDOW_S, then it says so and ends).

WHAT IT MAY DO, AND WHAT IT NEVER DOES.
  * It talks to ONE host, the literal loopback address below, on the launcher's port. It is not configurable: an address taken from the
    environment or the command line could point this at another machine, and nothing here should ever leave the computer.
  * It reads only what the browser's own task manager reads (``/api/health``, ``/api/system/lock-state``, ``/api/system/vitals``,
    ``/api/scheduler/status``, ``/api/jobs``), plus the interface language the browser reported (``/api/ai/interface-language``, a
    read-only GET, once a minute), and only while it is on screen.
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

IN THE PERSON'S LANGUAGE (R665, OPEN_QUEUE item 39). The words come from the browser's own locale files through ``src/tui/locale.py``:
the language the browser last reported to the app, else the terminal's locale, else English (``OO_PANEL_LANG`` overrides), English for
any missing string. Arabic stays in English with one line saying why: curses cannot shape it or lay it right to left. Lines already in
the log keep the language they were written in (the log is append-only), and widths are measured in terminal cells, so CJK labels and
buttons line up. The keys o, p, l, s never change with the language.

WINDOWS (anticipated; not run on Windows). Python's curses is absent there unless the ``windows-curses`` package is installed (a marker
dependency since R602, on the platforms it publishes wheels for), so without it :func:`main` says so and ends, and ``launch.cmd`` only
asks for the panel when ``import curses`` works. Since R658 it runs IN the launcher's window, started by ``launch_server.ps1`` with the
server's pid, so there is one window and closing it stops the app, as on Linux (it used to open a second window that a quiet server
closed after 20 s). ``os.kill`` is never used to test a pid (on Windows it TERMINATES the process), and the browser opens through
``os.startfile``.
"""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import locale
import os
import shutil
import signal
import subprocess
import sys
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.monitoring.secret_scrub import HELD_ENV_VARS
from src.tui import locale as L

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
STOP_MIN_GAP_S = 0.8  # a confirming press sooner than this after the question is ignored
#: ONLY when the server's identity cannot be pinned (a pid given but psutil missing or refused): a pid can be REUSED by another process
#: once the server has ended, so a long silence still ends the panel there. With the identity pinned, silence never ends it (R658).
GONE_WITH_PID_S = 300.0
NEVER_ANSWERED_WITH_PID_S = 1800.0
#: run()'s answer when it ended because the server stayed silent: main() says so instead of vanishing like a crash.
SILENT_EXIT = 11
#: main()'s answer when the panel itself failed too often to keep redrawing it.
PANEL_FAILED = 4
#: An error inside the panel redraws it, at most this many times in this many seconds.
RESTARTS_MAX = 5
RESTART_WINDOW_S = 600.0
#: The largest response read: the job list of a busy instance is tens of kilobytes.
MAX_BODY = 4_000_000
#: The activity lines kept in memory (about 200 bytes each). Older ones are let go, and the screen says how many.
LOG_KEEP = 20_000
#: A running job with a percentage gets one line each time it crosses a multiple of this.
MILESTONE_PCT = 10
#: Job kinds the log leaves to other lines: the collection loop has its own (from the scheduler), and the fetch in flight changes host
#: every second, which would bury everything else (the header names the host instead).
LOG_SKIP_KINDS = ("collect", "fetch")

IS_WINDOWS = os.name == "nt"
#: How often the language the browser reported is read again (R665): a switch in the UI reaches the panel within this.
LANG_RECHECK_S = 60.0

#: The panel's words (R665). English until main() reads the person's choice; tests set it with :func:`set_language`.
_TR = L.Translator()


def set_language(tr: L.Translator) -> None:
    global _TR
    _TR = tr


def _t(text: str) -> str:
    return _TR.t(text)


def _tf(text: str, **values: object) -> str:
    return _TR.tf(text, **values)

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
    id: str = ""

    @property
    def key(self) -> str:
        return self.id or f"{self.kind}:{self.label}"


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

    @property
    def fetching(self) -> str:
        """The host of the fetch on the wire right now (the jobs API gives the domain only, never the URL), or ""."""
        return next((j.label for j in self.jobs if j.kind == "fetch" and j.state == "running"), "")


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
                id=str(j.get("id") or ""),
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
    m, s = divmod(s, 60)
    if d:
        return _tf("{d}d {h}h", d=d, h=h)
    if h:
        return _tf("{h}h {m}m", h=h, m=f"{m:02d}")
    if m:
        return _tf("{m}m {s}s", m=m, s=f"{s:02d}")
    return _tf("{s}s", s=s)


def _bar(pct: float, width: int = 16) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = round(width * pct / 100)
    return "[" + "#" * filled + "-" * (width - filled) + f"] {pct:5.1f} %"


# --------------------------------------------------------------------------- the activity log


Line = tuple[str, str]  # (text, style)


@dataclass
class LogLine:
    at: float  # wall-clock seconds, for the time shown
    text: str
    style: str = "normal"


_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class ActivityLog:
    """The lines the panel shows, appended one after the other. The newest ``keep`` are held; ``dropped`` counts the ones let go."""

    def __init__(self, keep: int = LOG_KEEP) -> None:
        self.lines: deque[LogLine] = deque(maxlen=keep)
        self.total = 0
        self._day = ""

    @property
    def dropped(self) -> int:
        return self.total - len(self.lines)

    def add(self, text: str, style: str = "normal", at: float | None = None) -> None:
        at = time.time() if at is None else at
        lt = time.localtime(at)
        day = time.strftime("%Y-%m-%d", lt)
        if day != self._day:  # the panel runs for days: a line at each change of date keeps the times readable
            if self._day:
                # The weekday in the panel's language, the date in ISO order (the same in every language, never a month name to translate).
                self._append(LogLine(at, f"{_t(_WEEKDAYS[lt.tm_wday])} {day}", "date"))
            self._day = day
        self._append(LogLine(at, text, style))

    def _append(self, line: LogLine) -> None:
        self.lines.append(line)
        self.total += 1


def _lock_key(snap: Snapshot) -> str:
    """The lock state as a word of its own, so a change of LANGUAGE is never read as a change of state (it compares keys, not text)."""
    if snap.locked:
        return "locked"
    if snap.lock_state == "unlocked-plaintext":
        return "plain"
    return "encrypted" if snap.lock_state else ""


def _lock_text(snap: Snapshot) -> tuple[str, str] | None:
    key = _lock_key(snap)
    if key == "locked":
        return _t("Locked: open the UI to unlock. Collection and jobs start after you unlock."), "warn"
    if key == "plain":
        return _t("Unlocked (the database is not encrypted)."), "ok"
    if key == "encrypted":
        return _t("Unlocked (encrypted)."), "ok"
    return None


def _job_detail(j: Job) -> str:
    if j.percent is not None:
        return f"{j.percent:.0f} %"
    if j.done is not None:
        return f"{j.done:.0f}" + (f"/{j.total:.0f}" if j.total else "") + (f" {j.unit}" if j.unit else "")
    return ""


#: A job's state as the log says it. A state not listed here is shown as the server sent it, never mapped onto the nearest word.
_STATE_WORDS = {"running": "started", "queued": "queued", "paused": "paused", "failed": "FAILED", "done": "finished",
                "scheduled": "scheduled"}


def _state_word(state: str) -> str:
    return _t(_STATE_WORDS[state]) if state in _STATE_WORDS else (state or _t("changed"))


class Watcher:
    """Turns successive snapshots into activity lines. Pure apart from its own memory of the previous read (tested without curses)."""

    def __init__(self) -> None:
        self.prev: Snapshot | None = None
        self.ever = False
        self.silent_since: float | None = None  # monotonic
        self.said_silent = False
        self.milestones: dict[str, int] = {}
        self.last_jobs: list[Job] | None = None  # the last read that listed the jobs: one failed read does not replay them all

    def silent_for(self, now: float) -> float | None:
        return None if self.silent_since is None else now - self.silent_since

    def observe(self, snap: Snapshot, now: float) -> list[Line]:
        out: list[Line] = []
        if not snap.reachable:
            if self.silent_since is None:
                self.silent_since = now
            if self.ever and not self.said_silent:
                out.append((_t("The app stopped answering. It may be busy, stopping, or the computer slept; the panel keeps trying."), "warn"))
                self.said_silent = True
            return out
        if not self.ever:
            out.append((_tf("The app answers (version {version}).", version=snap.version) if snap.version else _t("The app answers."), "ok"))
        elif self.said_silent and self.silent_since is not None:
            out.append((_tf("The app answers again, after {duration} without an answer.", duration=fmt_duration(now - self.silent_since)),
                        "ok"))
        self.silent_since, self.said_silent = None, False
        prev = self.prev
        self.ever = True
        lock = _lock_text(snap)
        if lock and _lock_key(snap) != (_lock_key(prev) if prev else None):
            out.append(lock)
        if snap.online is not None and (prev is None or prev.online != snap.online):
            out.append((_t("Network: online.") if snap.online else _t("Network: offline (airplane mode)."), "normal"))
        # The phase is the scheduler's own word (an identifier, not a sentence): shown as sent, inside a translated sentence.
        phase = snap.collect_phase.replace("-", " ").replace("_", " ")
        if prev is None:
            if snap.collecting:
                out.append((_tf("Collection is running ({phase}).", phase=phase) if phase else _t("Collection is running."), "ok"))
        elif snap.collecting and not prev.collecting:
            out.append((_tf("Collection started ({phase}).", phase=phase) if phase else _t("Collection started."), "ok"))
        elif prev.collecting and not snap.collecting:
            out.append((_t("Collection stopped."), "normal"))
        elif snap.collecting and snap.collect_phase != prev.collect_phase and phase:
            out.append((_tf("Collection: {phase}.", phase=phase), "normal"))
        if snap.jobs_known:
            out.extend(self._jobs(self.last_jobs, snap.jobs, snap.collecting))
            self.last_jobs = snap.jobs
        self.prev = snap
        return out

    def _jobs(self, before: list[Job] | None, now_jobs: list[Job], collecting: bool = False) -> list[Line]:
        out: list[Line] = []
        cur = {j.key: j for j in now_jobs if j.kind not in LOG_SKIP_KINDS}
        if before is None:
            under_way = [j for j in cur.values() if j.state in ("running", "queued", "paused")]
            for j in under_way:
                d = _job_detail(j)
                head = _tf("Under way: {job} [{state}]", job=j.label, state=_t(j.state))
                out.append((f"{head}{f'  {d}' if d else ''}", "ok" if j.state == "running" else "dim"))
            if not under_way:
                out.append((_t("No other job is running.") if collecting else _t("No job is running."), "dim"))
        else:
            old = {j.key: j for j in before if j.kind not in LOG_SKIP_KINDS}
            for k, j in cur.items():
                was = old.get(k)
                if was is None or was.state != j.state:
                    word = _state_word(j.state)
                    style = "warn" if j.state == "failed" else "ok" if j.state in ("running", "done") else "normal"
                    d = _job_detail(j) if j.state in ("running", "paused", "failed") else ""
                    out.append((f"{j.label}: {word}{f'  {d}' if d else ''}", style))
            for k, j in old.items():
                if k not in cur:
                    out.append((_tf("{job}: no longer listed (finished or removed).", job=j.label), "dim"))
                    self.milestones.pop(k, None)
        for k, j in cur.items():
            if j.state == "running" and j.percent is not None:
                m = int(max(0.0, min(100.0, j.percent)) // MILESTONE_PCT)
                if k in self.milestones and m > self.milestones[k]:
                    out.append((f"{j.label}: {m * MILESTONE_PCT} %  {_bar(j.percent)}", "normal"))
                self.milestones[k] = max(m, self.milestones.get(k, m))
        return out


# --------------------------------------------------------------------------- the screen


@dataclass
class Button:
    action: str
    label: str
    row: int = 0
    col: int = 0

    @property
    def width(self) -> int:
        return L.cols(self.label) + 4  # "[ " + label + " ]", in terminal cells (a CJK character takes two)

    def hit(self, x: int, y: int) -> bool:
        return y == self.row and self.col <= x < self.col + self.width


@dataclass
class PanelState:
    stop_confirm_until: float = 0.0
    notice: str = ""
    notice_until: float = 0.0
    scroll: int = 0  # lines back from the newest; 0 follows the log as it grows
    stop_armed_at: float = 0.0


def buttons_for(snap: Snapshot, *, windows: bool = IS_WINDOWS) -> list[Button]:
    # The keys stay o, p, l, s in every language (the letter in brackets says which), so a key never moves with the language.
    out = [Button("open", _t("Open UI (o)"))]
    if snap.reachable and (snap.collecting or snap.online):
        out.append(Button("pause", _t("Pause collection (p)")))
    if not windows:  # on Windows the server's lines are not kept behind the panel
        out.append(Button("log", _t("Server messages (l)")))
    out.append(Button("stop", _t("Stop app (s)")))
    return out


#: The rule character: a box-drawing line where the terminal can show it (main() falls back to "-" otherwise).
RULE = "─"


def _rule(title: str, width: int, right: str = "") -> str:
    w = max(width - 1, 0)
    left = f"{RULE * 2} {title} " if title else ""
    tail = f" {right} {RULE * 2}" if right else ""
    return L.clip(left + RULE * max(w - L.cols(left) - L.cols(tail), 0) + tail, w)


def _status_line(snap: Snapshot) -> str:
    key = _lock_key(snap)
    lock = {"locked": _t("Locked: open the UI to unlock"), "plain": _t("not encrypted"), "encrypted": _t("encrypted")}.get(key, "?")
    net = {True: _t("online"), False: _t("offline"), None: "?"}[snap.online]
    coll = _t("collecting") if snap.collecting else _t("collection stopped")
    cpu = f"{snap.cpu_percent:.0f} %" if snap.cpu_percent is not None else "?"
    return "  ·  ".join([lock, net, coll, _tf("CPU {cpu}", cpu=cpu), _tf("memory {size}", size=fmt_bytes(snap.rss_bytes)),
                         _tf("up {duration}", duration=fmt_duration(snap.uptime_s))])


def build_screen(snap: Snapshot, width: int, state: PanelState, url: str, now: float, *, log: ActivityLog | None = None,
                 windows: bool = IS_WINDOWS, starting: bool = False, height: int = 24, silent_for: float | None = None,
                 watched: bool = True) -> tuple[list[Line], list[Button]]:
    """The whole screen as exactly ``height`` text lines (fewer only when the terminal is too short) and the clickable buttons,
    independent of curses (so it is tested without a terminal). ``now`` is wall-clock time."""
    log = log if log is not None else ActivityLog()
    head: list[Line] = []
    title = "Open Omniscience" + (f" {snap.version}" if snap.version else "")
    head.append((f" {title}  ·  {url}", "title"))
    if not snap.reachable:
        if starting:
            head.append((_t("Starting... the panel fills in as soon as the app answers."), "warn"))
        else:
            head.append(((_tf("The app is not answering for {duration}. It may be busy, stopping, or the computer slept; the panel keeps "
                              "trying.", duration=fmt_duration(silent_for)) if silent_for is not None else
                          _t("The app is not answering. It may be busy, stopping, or the computer slept; the panel keeps trying.")),
                         "warn"))
        head.append(("", "normal"))
    else:
        head.append((_status_line(snap), "warn" if snap.locked else "normal"))
        running = [j for j in snap.running if j.kind not in ("fetch",)]
        queued = [j for j in snap.jobs if j.state == "queued"]
        if not snap.jobs_known:
            now_line = _t("Jobs: not readable right now.")
        elif not running and not queued:
            now_line = _t("Now: nothing running, the app is idle.")
        else:
            listed = ", ".join(f"{j.label}{f' {_job_detail(j)}' if _job_detail(j) else ''}" for j in running[:3])
            now_line = _tf("Now: {running} running, {queued} queued", running=len(running), queued=len(queued)) + (
                f"  ·  {listed}" if listed else "")
            if len(running) > 3:
                now_line += " " + _tf("and {n} more", n=len(running) - 3)
        if snap.fetching:
            now_line += "  ·  " + _tf("fetching {host}", host=snap.fetching)
        head.append((now_line, "ok" if running else "dim"))

    # The bottom block: a rule, the notice, the buttons (wrapped to the width), the footer.
    if state.stop_confirm_until > now:
        names = [j.label for j in snap.running if j.kind != "fetch"]
        what = ", ".join(names[:3]) + (" " + _tf("and {n} more", n=len(names) - 3) if len(names) > 3 else "")
        notice: Line = (" ".join([_t("Stop the app?"), _tf("These jobs end: {jobs}.", jobs=what) if names else _t("No job is running."),
                                  _t("Press s again (or click Stop again) to confirm. Any other key cancels.")]), "warn")
    elif state.notice and state.notice_until > now:
        notice = (state.notice, "warn")
    else:
        notice = (_t("You can close the browser: jobs keep running here. Reopen it with Open UI."), "dim")
    btns = buttons_for(snap, windows=windows)
    brow, col = 0, 0
    for b in btns:
        if col and col + b.width > max(width - 1, 1):
            brow, col = brow + 1, 0
        b.row, b.col = brow, col
        col += b.width + 2
    button_rows = brow + 1
    if watched:
        footer = _t("Closing this window stops the app (Ctrl-C too).  ↑↓ PgUp PgDn or the wheel scroll the log; End follows it.")
    else:
        footer = _t("This panel only watches the app: Ctrl-C closes the panel and the app keeps running.")
    bottom_n = 2 + button_rows + 1  # rule + notice + buttons + footer

    # The log fills what is left, newest at the bottom.
    area = max(height - len(head) - 1 - bottom_n, 1)
    total = len(log.lines)
    state.scroll = max(0, min(state.scroll, max(total - area, 0)))
    end = total - state.scroll
    start = max(0, end - area)
    right = ""
    if state.scroll:
        right = (_t("scrolled back: 1 newer line below, End follows") if state.scroll == 1
                 else _tf("scrolled back: {n} newer lines below, End follows", n=state.scroll))
    elif log.dropped:
        right = _tf("{n} older lines not kept", n=log.dropped)
    lines: list[Line] = [*head, (_rule(_t("Activity"), width, right), "dim")]
    shown = list(log.lines)[start:end]
    for ln in shown:
        if ln.style == "date":
            lines.append((_rule(ln.text, width), "dim"))
        else:
            lines.append((f"{time.strftime('%H:%M:%S', time.localtime(ln.at))}  {ln.text}", ln.style))
    lines.extend([("", "normal")] * (area - len(shown)))
    lines.append((_rule("", width), "dim"))
    lines.append(notice)
    first_button_row = len(lines)
    for b in btns:
        b.row += first_button_row
    lines.extend([("", "button")] * button_rows)
    lines.append((footer, "dim"))
    return [(L.clip(t, max(width - 1, 0)), s) for t, s in lines], btns


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
              *, fetch: Fetch = api, opener: Callable[[str], bool] = open_ui, log: ActivityLog | None = None) -> str | None:
    """Apply one action. Returns "log" to show the server's messages, else None. Pure apart from fetch/opener. What an action did is
    both the notice above the buttons and a line in the activity log."""
    def say(text: str, style: str = "normal") -> None:
        state.notice, state.notice_until = text, now + 8.0
        if log is not None:
            log.add(text, style, at=now)

    if action != "stop":
        state.stop_confirm_until = 0.0
    if action == "open":
        say(_t("Opening the UI in your browser...") if opener(url) else _tf("Could not open a browser. Open this address yourself: {url}",
                                                                              url=url))
    elif action == "pause":
        r = fetch(port, "POST", "/api/scheduler/stop", {})
        if isinstance(r, dict) and "_error" not in r:
            say(_t("Collection paused and the app is offline. To resume, open the UI (it asks before going online)."))
        else:
            say(_t("Pause did not go through. Try again, or use the UI."), "warn")
    elif action == "stop":
        if state.stop_confirm_until > now and now - state.stop_armed_at < STOP_MIN_GAP_S:  # a negative gap (the clock moved back) too
            # A press too soon after the last one (a held key repeats every few ms, two presses queued behind a frozen screen): it stays a
            # question, and the gap restarts, so only a press after a real pause answers it.
            state.stop_armed_at = now
            return None
        if state.stop_confirm_until > now:
            state.stop_confirm_until = 0.0
            r = fetch(port, "POST", "/api/system/shutdown", {"confirm": True})
            if isinstance(r, dict) and "_error" not in r:
                say(_t("Stopping the app... running jobs end now."), "warn")
            else:
                say(_t("The stop did not go through. Close this window or press Ctrl-C to stop the app."), "warn")
        else:
            state.stop_confirm_until = now + STOP_CONFIRM_S
            state.stop_armed_at = now
    elif action == "log":
        return "log"
    return None


KEYS = {"o": "open", "p": "pause", "l": "log", "s": "stop"}


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


def scroll_by(ch: int, page: int) -> int | None:
    """How far a key moves the log back (+) or forward (-); None when the key does not scroll. Home/End are the two ends."""
    if curses is None:
        return None
    return {
        curses.KEY_UP: 1, curses.KEY_DOWN: -1, curses.KEY_PPAGE: page, curses.KEY_NPAGE: -page,
        curses.KEY_HOME: 10**9, curses.KEY_END: -(10**9),
    }.get(ch)


def pid_alive(pid: int | None) -> bool:
    """Whether a process with this pid exists. NEVER ``os.kill`` on Windows: there it terminates the process instead of testing it."""
    if not pid:
        return True
    if IS_WINDOWS:
        try:
            import psutil

            return bool(psutil.pid_exists(pid))
        except Exception:  # noqa: BLE001 - no way to tell: say alive, the caller has its own fallback
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie (ended, not reaped yet: launch.sh reaps its server only after the panel ends) still answers os.kill; on Linux its
    # state letter in /proc says so.
    with contextlib.suppress(OSError, IndexError), open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as f:
        if f.read().rsplit(")", 1)[1].split()[0] == "Z":
            return False
    return True


class ServerProcess:
    """The server the panel watches, pinned by IDENTITY where psutil allows: its pid AND its start time, read once when the panel starts.
    ``psutil.Process.is_running`` compares the start time again, so a pid the system handed to another program after the server ended
    reads as gone, never as the server. Where it cannot be pinned (no pid, no psutil, access refused), ``pinned`` is False and the plain
    pid test is used, with the long-silence rule as the backstop (see :func:`server_silent_too_long`)."""

    def __init__(self, pid: int | None) -> None:
        self.pid = pid
        self.pinned = False
        self.ended = False
        self._proc: Any = None
        if not pid:
            return
        try:
            import psutil

            self._proc = psutil.Process(pid)
            self.pinned = True
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001 - psutil.NoSuchProcess: it has ended already; AccessDenied: fall back to the pid test
            if type(exc).__name__ == "NoSuchProcess":
                self.ended = True

    def alive(self) -> bool:
        if self.ended:
            return False
        if self._proc is not None:
            try:
                import psutil

                return bool(self._proc.is_running() and self._proc.status() != psutil.STATUS_ZOMBIE)
            except _Stop:
                raise
            except Exception as exc:  # noqa: BLE001
                if type(exc).__name__ in ("NoSuchProcess", "ZombieProcess"):
                    return False
                return pid_alive(self.pid)  # AccessDenied or anything else: the plain test
        return pid_alive(self.pid)


def _console_ctrl_c() -> None:
    """Windows: with the mouse on, the console may deliver Ctrl-C to curses as key 3 instead of a break (the console's input mode is
    shared with the server, which runs in the same window since R658). Send the break to every process of this console, the server
    and the panel included, so Ctrl-C still stops the app as the footer says."""
    with contextlib.suppress(Exception):
        import ctypes

        ctypes.windll.kernel32.GenerateConsoleCtrlEvent(0, 0)  # type: ignore[attr-defined]  # CTRL_C_EVENT to the whole console


class _Stop(Exception):
    """Raised by the signal handler so a blocking read (a key, the log view) ends at once and curses.wrapper restores the terminal."""


_STYLES = ("title", "ok", "warn", "dim", "button", "normal", "date")


def _attrs() -> dict[str, int]:
    assert curses is not None
    a = dict.fromkeys(_STYLES, curses.A_NORMAL)
    a["title"] = curses.A_BOLD | curses.A_REVERSE
    a["dim"] = curses.A_DIM
    a["date"] = curses.A_DIM
    if curses.has_colors():
        with contextlib.suppress(CursesError):
            curses.use_default_colors()
        pairs = {"ok": curses.COLOR_GREEN, "warn": curses.COLOR_YELLOW, "button": curses.COLOR_CYAN, "title": curses.COLOR_CYAN}
        for i, (name, color) in enumerate(pairs.items(), start=1):
            try:
                curses.init_pair(i, color, -1)
                a[name] = curses.color_pair(i) | (curses.A_BOLD if name in ("warn", "title") else 0)
            except CursesError:
                pass
        a["title"] |= curses.A_REVERSE
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
            # Clipped in terminal CELLS (L.clip/L.pad); addnstr's count is in characters, so it is given the clipped text's length.
            if style == "title":  # the title bar spans the width
                bar = L.pad(text, max(w - 1, 0))
                scr.addnstr(y, 0, bar, len(bar), attrs["title"])
            else:
                text = L.clip(text, max(w - 1, 0))
                scr.addnstr(y, 0, text, len(text), attrs.get(style, 0))
    for b in buttons:
        if b.row < h and b.col + b.width < w:
            with contextlib.suppress(CursesError):
                scr.addstr(b.row, b.col, f"[ {b.label} ]", attrs["button"])
    scr.refresh()


def _show_log(scr: Any, server: ServerProcess, stopping: list[bool] | None = None) -> bool:
    """Step out of the panel: the terminal shows the server's own output again until ANY key (it was Enter, which a click never sends,
    so a click on "Show log" read as the panel vanishing). POSIX only (on Windows the panel runs in the server's window). Returns False
    when the server ended meanwhile, so the panel ends instead of waiting on a key nobody presses: the launcher waits for this process
    before it reports how the server ended."""
    assert curses is not None
    import select
    import termios
    import tty
    from termios import error as TermiosError

    curses.endwin()
    fd = sys.stdin.fileno()
    saved = None
    # cbreak BEFORE the prompt: endwin() leaves the terminal in line mode, and a key pressed as soon as the prompt shows used to land
    # there (echoed, waiting for Enter) or be discarded by setcbreak's flush, so the view did not return on it (a CI flake, 2026-11-13).
    with contextlib.suppress(TermiosError, OSError):
        saved = termios.tcgetattr(fd)
        tty.setcbreak(fd)  # one key, no Enter; ISIG stays, so Ctrl-C is still the terminal's stop
    # Every way out goes back through curses first: curses.wrapper calls endwin() again when the panel ends, and a second endwin()
    # without a refresh between them fails, which read as "the panel could not start" right above the launcher's own message.
    back = True
    try:
        # Inside the try: a write that fails (the terminal hung up) still restores the terminal's own mode below.
        sys.stdout.write("\n--- " + _t("The server's own messages appear below as it prints them. Press any key to return to the panel.")
                         + " ---\n\n")
        sys.stdout.flush()
        while True:
            if not server.alive() or (stopping is not None and stopping[0]):
                back = False
                break
            ready, _, _ = select.select([fd], [], [], 0.5)
            if ready:
                if not os.read(fd, 64):
                    back = False  # end of input: no terminal to come back to
                break
    finally:
        if saved is not None:
            with contextlib.suppress(TermiosError, OSError):
                termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        with contextlib.suppress(CursesError):
            scr.clear()
            scr.refresh()
    return back


def server_silent_too_long(server_pid: int | None, *, ever: bool, now: float, last_ok: float, started: float) -> bool:
    """Whether a server whose identity could NOT be pinned has been silent long enough that the panel should end (its pid may now be
    another program's). Never used for a pinned server, nor with no pid at all: silence is shown there, never acted on (R658)."""
    if server_pid is None:
        return False
    return (now - last_ok > GONE_WITH_PID_S) if ever else (now - started > NEVER_ANSWERED_WITH_PID_S)


def silent_message(url: str) -> str:
    """What the panel says as it ends because the app stopped answering (it cannot tell a hung app from one that is gone)."""
    return "\n" + _tf("The app has not answered for a while, so the panel closed. If Open Omniscience is still running, open {url} "
                      "in the browser.", url=url) + "\n"


@dataclass
class Session:
    """What outlives one curses screen: an error inside the panel redraws it with the same log and the same state."""
    port: int
    url: str
    server: ServerProcess
    stopping: list[bool] = field(default_factory=lambda: [False])
    activity: ActivityLog = field(default_factory=ActivityLog)
    watcher: Watcher = field(default_factory=Watcher)
    state: PanelState = field(default_factory=PanelState)
    snap: Snapshot = field(default_factory=Snapshot)
    started: float = field(default_factory=time.monotonic)
    last_ok: float = 0.0
    drawn: bool = False
    #: The language (R665): the code the browser last reported (None: none, or not readable), when it is read next, and the code of
    #: the right-to-left notice already written, so it is said once per switch and not at every read.
    lang_reported: str | None = None
    lang_next: float = 0.0
    lang_code: str = L.DEFAULT
    rtl_noted: str = ""


def apply_language(session: Session, reported: str | None, env: dict[str, str] | None = None) -> None:
    """Choose the panel's language from what the browser reported (R665) and say once when a right-to-left one stays in English.
    Lines already in the log keep the language they were written in: the log is append-only (R658)."""
    session.lang_reported = reported
    tr, note = L.choose(reported, env)
    set_language(tr)
    session.lang_code = tr.code
    if note and session.rtl_noted != note:
        session.activity.add(note, "dim")
        session.rtl_noted = note
    elif not note:
        session.rtl_noted = ""


def read_reported_language(port: int, fetch: Fetch = api) -> tuple[bool, str | None]:
    """``(answered, code)``: whether the app answered the question, and the interface language the browser last reported (None when
    none was). A failed read (locked, timed out, an error) is ``(False, None)``, so the caller keeps the language it has rather than
    flipping to the fallback on a transient fault. A read only: the route is read-only and the lock gate answers for a locked app, so
    nothing is unlocked or woken to answer it (R665)."""
    r = fetch(port, "GET", "/api/ai/interface-language")
    if not isinstance(r, dict) or "_error" in r:
        return False, None
    lang = r.get("lang")
    return True, (lang or None) if isinstance(lang, str) else None


def refresh(session: Session, now_mono: float, fetch: Fetch = api) -> None:
    """One read of the app, its lines appended to the log (kept anchored while the reader has scrolled back)."""
    session.snap = take_snapshot(session.port, fetch)
    if session.snap.reachable:
        session.last_ok = now_mono
        if now_mono >= session.lang_next:
            session.lang_next = now_mono + LANG_RECHECK_S
            answered, reported = read_reported_language(session.port, fetch)
            if answered and reported != session.lang_reported:
                apply_language(session, reported)
    before = session.activity.total
    for text, style in session.watcher.observe(session.snap, now_mono):
        session.activity.add(text, style)
    if session.state.scroll:
        session.state.scroll += session.activity.total - before


def run(scr: Any, session: Session) -> int:
    assert curses is not None
    with contextlib.suppress(CursesError):
        curses.curs_set(0)
    scr.keypad(True)
    scr.timeout(250)
    wheel_up = getattr(curses, "BUTTON4_PRESSED", 0)
    wheel_down = getattr(curses, "BUTTON5_PRESSED", 0)
    try:
        # ONE event per click: the press only. With press, release and click all in the mask (and mouseinterval 0), one physical
        # click arrived as two events, and the second confirmed the Stop the first had armed (Opus read, 8 Nov). The wheel is two
        # other buttons, so it adds no event to a click.
        curses.mousemask(curses.BUTTON1_PRESSED | wheel_up | wheel_down)
        curses.mouseinterval(0)
    except CursesError:
        pass
    attrs = _attrs()
    state = session.state
    next_fetch = 0.0
    next_repaint = 0.0
    buttons: list[Button] = []
    area = 10
    while not session.stopping[0]:
        now = time.monotonic()
        if not session.server.alive():
            return 0
        full = False
        if now >= next_fetch:
            refresh(session, now)
            if time.monotonic() - now > 1.0 and state.stop_confirm_until <= time.time():
                # A slow read: keys typed into a frozen screen were not answering anything it showed. Not while the Stop question is up:
                # a press then is the answer (or the cancel), and the gap above already guards against repeats.
                with contextlib.suppress(CursesError):
                    curses.flushinp()
            snap = session.snap
            if not snap.reachable and not session.server.pinned and server_silent_too_long(
                    session.server.pid, ever=session.watcher.ever, now=now, last_ok=session.last_ok, started=session.started):
                return SILENT_EXIT
            next_fetch = now + (REFRESH_BUSY_S if (snap.busy or not snap.reachable) else REFRESH_IDLE_S)
        if now >= next_repaint:
            full, next_repaint = True, now + REPAINT_S
        h, w = scr.getmaxyx()
        lines, buttons = build_screen(session.snap, w, state, session.url, time.time(), log=session.activity,
                                      starting=not session.watcher.ever, height=h, silent_for=session.watcher.silent_for(now),
                                      watched=bool(session.server.pid))
        area = max(h - 10, 1)
        _draw(scr, lines, buttons, attrs, full)
        session.drawn = True
        ch = scr.getch()
        if ch == -1:
            continue
        if IS_WINDOWS and ch == 3:
            _console_ctrl_c()
            continue
        click = None
        if ch == curses.KEY_MOUSE:
            try:
                _id, x, y, _z, bstate = curses.getmouse()
            except CursesError:
                continue
            if wheel_up and bstate & wheel_up:
                state.scroll += 3
                continue
            if wheel_down and bstate & wheel_down:
                state.scroll = max(0, state.scroll - 3)
                continue
            if not bstate & curses.BUTTON1_PRESSED:
                continue
            click = (x, y)
        elif ch == curses.KEY_RESIZE:
            if IS_WINDOWS:  # PDCurses reports the new size only after resize_term; ncurses does it on its own
                with contextlib.suppress(CursesError, AttributeError):
                    curses.resize_term(0, 0)
            next_repaint = 0.0
            continue
        else:
            step = scroll_by(ch, area)
            if step is not None:  # scrolling is reading, not answering: it leaves a pending Stop as it is
                state.scroll = max(0, state.scroll + step)
                continue
        action = key_action(ch, buttons, click)
        if action is None:
            continue
        if action == "other":
            state.stop_confirm_until = 0.0
            continue
        result = do_action(action, state, session.snap, session.port, session.url, time.time(), log=session.activity)
        if action == "stop" and state.stop_confirm_until:
            state.scroll = 0  # the question is at the bottom, beside the newest lines
        next_fetch = time.monotonic() + 0.5 if action in ("pause", "stop") else next_fetch
        if result == "log":
            if not _show_log(scr, session.server, session.stopping):
                return 0
            next_repaint = 0.0
    return 0


def _recent(times: list[float], now: float) -> list[float]:
    """The failure times inside the restart window. A frame of its own: a filtered comprehension inside main()'s try would leave its
    back-edge outside the cleanup (src/utils/interrupts.py; tests/test_loop_heads_reach.py). Not imported from there, so the panel
    keeps importing nothing of the app but HELD_ENV_VARS."""
    return [f for f in times if now - f < RESTART_WINDOW_S]


def main(argv: list[str] | None = None) -> int:
    global RULE
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
    with contextlib.suppress(locale.Error):
        locale.setlocale(locale.LC_CTYPE, "")  # curses draws the terminal's own characters only after this
    enc = (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "")
    RULE = "─" if enc.startswith("utf") else "-"
    session = Session(port=args.port, url=url, server=ServerProcess(args.server_pid))
    apply_language(session, None)  # the terminal's own language until the app says which one the person chose (R665)
    session.activity.add(_t("Panel started. It stays here while the app runs; the lines below are what happened, newest last."), "dim")

    def _end(_sig: int, _frame: Any) -> None:
        # The panel only restores the terminal and ends. A Ctrl-C reaches the server and the launcher on its own (one SIGINT to the
        # whole foreground group), so nothing is forwarded from here: a second signal is what once made uvicorn skip its teardown.
        if session.stopping[0]:
            return  # a second signal (TERM after Ctrl-C, HUP as the window closes) must not cut the terminal's restore short
        session.stopping[0] = True
        raise _Stop

    # The panel is a process of its own, started by the launcher and imported by no server code (tests/test_event_loop_signal_exemption.py).
    for sig in (signal.SIGINT, signal.SIGTERM, *([signal.SIGHUP] if hasattr(signal, "SIGHUP") else [])):
        with contextlib.suppress(OSError, ValueError):
            signal.signal(sig, _end)
    failures: list[float] = []
    try:
        while True:
            try:
                code = curses.wrapper(run, session)
            except _Stop:
                raise
            except Exception as exc:  # noqa: BLE001 - the panel redraws itself rather than leave the window to the server's output
                if not session.drawn and isinstance(exc, CursesError):
                    print(_tf("The terminal panel could not start ({error}). The app keeps running.", error=type(exc).__name__),
                          file=sys.stderr)
                    return 3
                t = time.monotonic()
                failures = [*_recent(failures, t), t]
                if len(failures) > RESTARTS_MAX or session.stopping[0]:
                    print("\n" + _tf("The terminal panel stopped after repeated errors ({error}). The app keeps running: open {url} "
                                      "in the browser.", error=type(exc).__name__, url=url) + "\n", file=sys.stderr, flush=True)
                    return PANEL_FAILED
                # The class only, never the message: an exception's text can carry what the panel read.
                session.activity.add(_tf("The panel hit an error ({error}) and redrew itself.", error=type(exc).__name__), "warn")
                time.sleep(0.5)
                continue
            break
    except _Stop:  # a signal: curses.wrapper has already restored the terminal
        return 0
    if code == SILENT_EXIT:
        print(silent_message(url), flush=True)
    return int(code)


if __name__ == "__main__":
    sys.exit(main())
