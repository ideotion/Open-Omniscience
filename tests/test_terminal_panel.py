"""The launcher window's terminal panel (R600) and what it may never do (R601).

src/tui/panel.py shows the app's state while no browser is open and offers Open UI / Pause collection / Stop app. These tests pin the
parts that are promises rather than layout: it talks to loopback only, it never goes online or resumes collection, it never asks for
the passphrase, Stop needs a second press, it never calls os.kill on Windows, and the launcher's stop paths are unchanged with it
running (a TERM to the launcher still stops the server at once; the server's exit status is still the launcher's).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import select
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from src.tui import panel as P
from tests.os_scope import scope_os

REPO = Path(__file__).resolve().parents[1]
SRC = (REPO / "src" / "tui" / "panel.py").read_text(encoding="utf-8")
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the launcher is a bash script; the pty is POSIX")


# --------------------------------------------------------------------------- the promises, read in the source


def test_the_host_is_loopback_and_cannot_be_configured():
    assert P.HOST == "127.0.0.1"
    # no --host option, no environment variable naming a host
    assert "--host" not in SRC and "OO_HOST" not in SRC
    with pytest.raises(SystemExit):
        P.main(["--host", "example.org"])


def test_it_never_goes_online_or_resumes_collection_r601():
    for path in ("/api/scheduler/start", "/api/scheduler/run-now", "/api/system/network", "/api/system/unlock"):
        assert path not in SRC, path
    posts = set(re.findall(r'"POST",\s*"([^"]+)"', SRC))
    assert posts == {"/api/scheduler/stop", "/api/system/shutdown"}, posts


def test_it_never_asks_for_the_passphrase():
    assert "getpass" not in SRC
    assert "input(" not in SRC
    assert "passphrase" not in SRC.lower().split('"""', 2)[2]  # outside the module docstring, the word never appears


def test_open_ui_only_ever_opens_the_apps_own_address(monkeypatch):
    seen = {}

    def fake_wrapper(fn, session):
        seen["url"] = session.url
        return 0

    monkeypatch.setattr(P.signal, "signal", lambda *a: None)  # main() installs handlers; never in the pytest process
    monkeypatch.setattr(P.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(P.sys.stdout, "isatty", lambda: True, raising=False)
    if P.curses is None:
        pytest.skip("no curses here")
    monkeypatch.setattr(P.curses, "wrapper", fake_wrapper)
    P.main(["--port", "8123", "--url", "http://evil.example/"])
    assert seen["url"] == "http://127.0.0.1:8123/"
    P.main(["--port", "8123", "--url", "http://127.0.0.1:8123/"])
    assert seen["url"] == "http://127.0.0.1:8123/"
    for bad in ("http://127.0.0.1:8000@evil.example/", "https://127.0.0.1:8000/", "http://127.0.0.1.evil.example:80/", "file:///etc/passwd"):
        assert P.loopback_url(bad, 8000) == "http://127.0.0.1:8000/", bad
    # only a literal loopback address: "localhost" is whatever the hosts file says it is
    assert P.loopback_url("http://localhost:8001/", 8000) == "http://127.0.0.1:8000/"
    assert P.loopback_url("http://[::1]:8001/", 8000) == "http://[::1]:8001/"


def test_the_browser_the_panel_starts_never_inherits_the_passphrase(monkeypatch):
    seen = {}

    def fake_popen(cmd, **kw):
        seen.update(kw, cmd=cmd)

    monkeypatch.setattr(P, "IS_WINDOWS", False)
    monkeypatch.setattr(P.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(P.subprocess, "Popen", fake_popen)
    monkeypatch.setenv("OO_DB_PASSPHRASE", "never-in-a-child")
    monkeypatch.setenv("OO_PANEL_TEST_KEEP", "1")
    assert P.open_ui("http://127.0.0.1:8000/")
    assert seen["cmd"][-1] == "http://127.0.0.1:8000/"
    assert "OO_DB_PASSPHRASE" not in seen["env"] and seen["env"]["OO_PANEL_TEST_KEEP"] == "1"
    assert not set(seen["env"]) & set(P.HELD_ENV_VARS)


def test_main_drops_every_held_secret_from_its_own_environment_before_anything_else(monkeypatch):
    """Security read, 8 Nov: on Windows os.startfile cannot be handed an env, so the browser it starts inherits the panel's. The
    panel never needs the held variables, so main() drops them from its own environment first, on every platform."""
    for name in P.HELD_ENV_VARS:
        monkeypatch.setenv(name, "never-in-a-child")
    monkeypatch.setattr(P.signal, "signal", lambda *a: None)
    monkeypatch.setattr(P.sys.stdin, "isatty", lambda: False, raising=False)  # main() returns 3 right after the arguments
    P.main(["--port", "8123"])
    assert not set(P.HELD_ENV_VARS) & set(os.environ)


def test_silence_never_ends_a_panel_whose_server_is_pinned_r658():
    """R658 (field report 11 Nov, "the UI disappeared after some time"): a quiet server closed the panel after 20 s on Windows and
    5 min elsewhere. Silence is now shown, never acted on, except where the server's identity cannot be pinned (a pid with no psutil),
    where a pid reused by another program would otherwise hold the panel and launch.sh's wait up for ever (security read, 8 Nov)."""
    t0 = 1000.0
    assert not P.server_silent_too_long(None, ever=True, now=t0 + 10**6, last_ok=t0, started=0), "no pid: never ends on silence"
    assert not P.server_silent_too_long(123, ever=True, now=t0 + P.GONE_WITH_PID_S - 1, last_ok=t0, started=0)
    assert P.server_silent_too_long(123, ever=True, now=t0 + P.GONE_WITH_PID_S + 1, last_ok=t0, started=0)
    assert not P.server_silent_too_long(123, ever=False, now=P.NEVER_ANSWERED_WITH_PID_S - 1, last_ok=0, started=0)
    assert P.server_silent_too_long(123, ever=False, now=P.NEVER_ANSWERED_WITH_PID_S + 1, last_ok=0, started=0)
    # and run() consults it only for an unpinned server
    assert "not session.server.pinned and server_silent_too_long(" in SRC
    code = SRC.split('"""', 2)[2]  # outside the module docstring, which tells the story of the three
    for gone in ("GONE_AFTER_S", "NEVER_ANSWERED_S ", "Close panel", '"quit"'):
        assert gone not in code, gone


def test_a_panel_ended_by_silence_says_so_instead_of_vanishing(monkeypatch, capsys):
    """Security read, 8 Nov: the silence path exited 0 with nothing printed, which reads as a crash."""
    if P.curses is None:
        pytest.skip("no curses here")
    monkeypatch.setattr(P.signal, "signal", lambda *a: None)
    monkeypatch.setattr(P.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(P.sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(P.curses, "wrapper", lambda *a: P.SILENT_EXIT)
    assert P.main(["--port", "8123", "--server-pid", str(os.getpid())]) == P.SILENT_EXIT
    out = capsys.readouterr().out
    assert "has not answered" in out and "http://127.0.0.1:8123/" in out


# --------------------------------------------------------------------------- the actions


class _Fetch:
    def __init__(self, answers=None):
        self.calls: list[tuple[str, str, object]] = []
        self.answers = answers or {}

    def __call__(self, port, method, path, body=None, timeout=3.0):
        self.calls.append((method, path, body))
        return self.answers.get(path, {"ok": True})


def _snap(**kw):
    s = P.Snapshot(reachable=True, version="0.5.0", lock_state="unlocked-encrypted", online=True, collecting=True, jobs_known=True)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_stop_needs_a_second_press_and_any_other_key_cancels():
    f = _Fetch()
    st = P.PanelState()
    snap = _snap(jobs=[P.Job("backup-volumes", "Volume backup", "running", percent=40.0)])
    P.do_action("stop", st, snap, 8000, "u", 100.0, fetch=f)
    assert f.calls == [] and st.stop_confirm_until > 100.0
    lines, _ = P.build_screen(snap, 200, st, "u", 101.0, windows=False)
    assert any("These jobs end: Volume backup" in t for t, _ in lines)
    P.do_action("stop", st, snap, 8000, "u", 101.0, fetch=f)
    assert f.calls == [("POST", "/api/system/shutdown", {"confirm": True})]
    # a confirmation that expired, or was cancelled by another action, does not stop
    f2, st2 = _Fetch(), P.PanelState()
    P.do_action("stop", st2, snap, 8000, "u", 0.0, fetch=f2)
    P.do_action("stop", st2, snap, 8000, "u", 0.0 + P.STOP_CONFIRM_S + 1, fetch=f2)
    assert f2.calls == []
    f3, st3 = _Fetch(), P.PanelState()
    P.do_action("stop", st3, snap, 8000, "u", 0.0, fetch=f3)
    P.do_action("open", st3, snap, 8000, "u", 1.0, fetch=f3, opener=lambda u: True)
    P.do_action("stop", st3, snap, 8000, "u", 2.0, fetch=f3)
    assert f3.calls == []


def test_pause_posts_the_scheduler_stop_and_says_how_to_resume():
    f = _Fetch()
    st = P.PanelState()
    P.do_action("pause", st, _snap(), 8000, "u", 0.0, fetch=f)
    assert f.calls == [("POST", "/api/scheduler/stop", {})]
    assert "open the UI" in st.notice and "asks before going online" in st.notice


def test_pause_is_offered_only_while_there_is_something_to_pause():
    on = {b.action for b in P.buttons_for(_snap(), windows=False)}
    off = {b.action for b in P.buttons_for(_snap(online=False, collecting=False), windows=False)}
    assert "pause" in on and "pause" not in off
    assert {"open", "stop", "log"} <= off and "quit" not in off


def test_keys_and_clicks_map_to_the_offered_buttons_only():
    lines, btns = P.build_screen(_snap(online=False, collecting=False), 120, P.PanelState(), "u", 0.0, windows=False)
    assert P.key_action(ord("o"), btns) == "open"
    assert P.key_action(ord("P"), btns) == "other"  # pause is not offered here
    assert P.key_action(ord("x"), btns) == "other"
    stop = next(b for b in btns if b.action == "stop")
    assert P.key_action(0, btns, (stop.col + 2, stop.row)) == "stop"
    assert P.key_action(0, btns, (stop.col + 2, stop.row + 5)) == "other"  # a click beside the buttons cancels a pending Stop
    # buttons do not overlap and fit the width
    spans = sorted((b.row, b.col, b.col + b.width) for b in btns)
    for (r1, _, e1), (r2, s2, _) in zip(spans, spans[1:], strict=False):
        assert r1 != r2 or e1 <= s2


def test_buttons_wrap_on_a_narrow_terminal():
    _, btns = P.build_screen(_snap(), 40, P.PanelState(), "u", 0.0, windows=False)
    assert len({b.row for b in btns}) > 1
    assert all(b.col + b.width <= 40 for b in btns)


# --------------------------------------------------------------------------- what the screen says


def test_a_locked_app_says_how_to_unlock_and_offers_no_passphrase_field():
    lines, btns = P.build_screen(_snap(locked=True, lock_state="locked"), 200, P.PanelState(), "u", 0.0, windows=False)
    text = "\n".join(t for t, _ in lines)
    assert "Locked: open the UI to unlock" in text
    assert "passphrase" not in text.lower()
    assert {b.action for b in btns} >= {"open"}


def test_the_header_says_what_runs_now_and_the_log_says_what_happened():
    snap = _snap(jobs=[P.Job("wiki-dump", "frwiki articles", "running", percent=12.5, id="dump:fr"),
                       P.Job("osm-map", "Belgium", "queued", id="osm:be"),
                       P.Job("import", "Import", "running", done=40, total=100, unit="articles", id="import:1"),
                       P.Job("fetch", "lemonde.fr", "running", id="fetch:current")])
    log = P.ActivityLog()
    for text, style in P.Watcher().observe(snap, 0.0):
        log.add(text, style)
    lines, _ = P.build_screen(snap, 200, P.PanelState(), "u", 0.0, log=log, windows=False)
    text = "\n".join(t for t, _ in lines)
    assert "Now: 2 running, 1 queued" in text and "frwiki articles 12 %" in text and "40/100 articles" in text
    assert "fetching lemonde.fr" in text
    assert "Under way: frwiki articles [running]" in text and "Under way: Belgium [queued]" in text
    assert "Collection is running" in text and "Network: online." in text and "Unlocked (encrypted)." in text
    assert "lemonde.fr" not in "\n".join(ln.text for ln in log.lines), "the fetch in flight changes every second: header only"
    assert "You can close the browser" in text
    assert "Closing this window stops the app" in text


def test_windows_is_one_window_whose_closing_stops_the_app_and_has_no_log_view():
    """R658: the panel runs in the launcher's own window there now (launch_server.ps1), so closing it stops the app, as on Linux."""
    lines, btns = P.build_screen(_snap(), 200, P.PanelState(), "u", 0.0, windows=True)
    assert any("Closing this window stops the app" in t for t, _ in lines)
    assert not any("does NOT stop the app" in t for t, _ in lines)
    assert "log" not in {b.action for b in btns}
    # without a server to watch (run by hand), it says the app is left running
    lines, _ = P.build_screen(_snap(), 200, P.PanelState(), "u", 0.0, windows=True, watched=False)
    assert any("the app keeps running" in t for t, _ in lines)


def test_an_unreachable_app_reads_as_starting_then_as_not_answering():
    s = P.Snapshot()
    a, _ = P.build_screen(s, 200, P.PanelState(), "u", 0.0, starting=True, windows=False)
    b, _ = P.build_screen(s, 200, P.PanelState(), "u", 0.0, starting=False, windows=False)
    assert any("Starting" in t for t, _ in a)
    assert any("not answering" in t for t, _ in b)


def test_every_line_fits_the_width():
    lines, _ = P.build_screen(_snap(jobs=[P.Job("x", "y" * 300, "running")]), 50, P.PanelState(), "u", 0.0, windows=False)
    assert all(len(t) <= 49 for t, _ in lines)


def test_take_snapshot_tolerates_each_read_failing_on_its_own():
    f = _Fetch({
        "/api/health": {"version": "0.5.0"},
        "/api/system/lock-state": None,
        "/api/system/vitals": {"_error": 500},
        "/api/scheduler/status": {"online": False, "running": False},
        "/api/jobs": {"jobs": [{"kind": "collect", "label": "collection loop (idle)", "state": "scheduled", "progress": None}, "junk"]},
    })
    s = P.take_snapshot(1, fetch=f)
    assert s.reachable and s.version == "0.5.0" and s.lock_state == ""
    assert s.rss_bytes is None and s.online is False
    assert [j.label for j in s.jobs] == ["collection loop (idle)"]
    assert not P.take_snapshot(1, fetch=_Fetch({"/api/health": None})).reachable


# --------------------------------------------------------------------------- the platform rules


def test_pid_alive_never_calls_os_kill_on_windows(monkeypatch):
    def boom(*a):
        raise AssertionError("os.kill on Windows terminates the process")

    monkeypatch.setattr(P, "IS_WINDOWS", True)
    scope_os(monkeypatch, P, kill=boom)
    assert P.pid_alive(os.getpid()) in (True, False)
    assert P.pid_alive(None) is True


@posix_only
def test_pid_alive_on_posix():
    assert P.pid_alive(os.getpid())
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    assert not P.pid_alive(p.pid)


# --------------------------------------------------------------------------- the HTTP client, against a real loopback server


class _H(BaseHTTPRequestHandler):
    seen: list[dict] = []

    def log_message(self, *a):
        pass

    def _reply(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        _H.seen.append({"m": "GET", "p": self.path, "h": dict(self.headers)})
        answers = {
            "/api/health": {"status": "healthy", "version": "9.9.9"},
            "/api/system/lock-state": {"state": "unlocked-encrypted", "locked": False},
            "/api/system/vitals": {"uptime_s": 4000, "process": {"rss_bytes": 812_000_000, "cpu_percent": 3.5}},
            "/api/scheduler/status": {"online": True, "running": True, "active": True, "phase": "collecting"},
            "/api/jobs": {"jobs": [{"kind": "collect", "label": "collection pass", "state": "running", "progress": None}]},
        }
        if self.path in answers:
            self._reply(200, answers[self.path])
        else:
            self._reply(404, {"detail": "no"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        _H.seen.append({"m": "POST", "p": self.path, "h": dict(self.headers), "b": self.rfile.read(n)})
        self._reply(200, {"ok": True})


@pytest.fixture
def server():
    _H.seen = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_sends_json_with_its_content_type_and_no_origin(server):
    assert P.api(server, "POST", "/api/scheduler/stop", {}) == {"ok": True}
    post = _H.seen[-1]
    hdr = {k.lower(): v for k, v in post["h"].items()}
    assert hdr["content-type"] == "application/json"
    assert "origin" not in hdr and "referer" not in hdr
    assert P.api(server, "GET", "/nope") == {"_error": 404}


def test_api_returns_none_when_nothing_listens():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert P.api(port, "GET", "/api/health", timeout=1.0) is None


def test_take_snapshot_against_a_real_server(server):
    s = P.take_snapshot(server)
    assert s.reachable and s.version == "9.9.9" and s.collecting and s.online
    assert s.rss_bytes == 812_000_000 and s.uptime_s == 4000
    assert [j.label for j in s.running] == ["collection pass"]


# --------------------------------------------------------------------------- the real curses screen in a pty


def _read_until(fd: int, needle: bytes, secs: float) -> bytes:
    buf = b""
    end = time.monotonic() + secs
    while time.monotonic() < end and needle not in buf:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try:
                buf += os.read(fd, 65536)
            except OSError:
                break
    return buf


@posix_only
@pytest.mark.skipif(P.curses is None, reason="no curses")
def test_the_real_panel_draws_its_log_and_no_key_closes_it(server):
    """R658: there is no close button and no close key; the panel ends with its server or on a signal."""
    import pty

    master, slave = pty.openpty()
    env = dict(os.environ, TERM="xterm-256color", PYTHONPATH=str(REPO))
    proc = subprocess.Popen([sys.executable, "-m", "src.tui.panel", "--port", str(server), "--server-pid", str(os.getpid())],
                            cwd=str(REPO), env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    os.close(slave)
    try:
        out = _read_until(master, b"Collection is running", 20)
        out += _read_until(master, b"Stop app", 10)
        assert b"Stop app" in out and b"Open UI" in out and b"Activity" in out, out[-2000:]
        for key in (b"q", b"Q", b"x", b"\x1b"):
            os.write(master, key)
        time.sleep(1.0)
        assert proc.poll() is None, "no key closes the panel"
        assert not [s for s in _H.seen if s["m"] == "POST"], "drawing the panel and pressing keys must post nothing"
        proc.send_signal(signal.SIGINT)
        assert proc.wait(timeout=15) == 0
    finally:
        with contextlib.suppress(OSError):
            proc.kill()
        os.close(master)


@posix_only
@pytest.mark.skipif(P.curses is None, reason="no curses")
def test_the_real_panel_ends_on_sigint_and_when_its_server_ends(server):
    import pty

    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    for how in ("sigint", "server-gone"):
        master, slave = pty.openpty()
        env = dict(os.environ, TERM="xterm-256color", PYTHONPATH=str(REPO))
        pid = sleeper.pid if how == "server-gone" else os.getpid()
        proc = subprocess.Popen([sys.executable, "-m", "src.tui.panel", "--port", str(server), "--server-pid", str(pid)],
                                cwd=str(REPO), env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        os.close(slave)
        try:
            _read_until(master, b"Stop app", 20)
            if how == "sigint":
                proc.send_signal(signal.SIGINT)
            else:
                sleeper.kill()
                sleeper.wait()
            assert proc.wait(timeout=15) == 0
        finally:
            with contextlib.suppress(OSError):
                proc.kill()
            os.close(master)


# --------------------------------------------------------------------------- the launcher with the panel


def _tree_with_panel(tmp_path: Path, panel_body: str, server_body: str = "trap 'exit 143' TERM\nwhile :; do sleep 0.1; done\n"):
    from tests.test_exit_evidence import _launcher_tree

    root, env = _launcher_tree(tmp_path, server_body)
    (root / "src" / "tui").mkdir(parents=True)
    (root / "src" / "tui" / "panel.py").write_text("# stand-in\n", encoding="utf-8")
    py = root / ".venv" / "bin" / "python"
    py.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > \"$OO_TEST_PANEL_ARGS\"\n[ -t 0 ] && echo tty >> \"$OO_TEST_PANEL_ARGS\"\n"
                  # presence only, never a value (the passphrase rule): one "held:NAME=set|unset" line per name in
                  # OO_TEST_PRESENCE_NAMES, which the test hands over in the environment so no name is written in this file
                  "for n in $OO_TEST_PRESENCE_NAMES; do if [ -n \"${!n+x}\" ]; then s=set; else s=unset; fi; "
                  "echo \"held:$n=$s\" >> \"$OO_TEST_PANEL_ARGS\"; done\n" + panel_body,
                  encoding="utf-8")
    py.chmod(0o755)
    env.update(OO_TEST_PANEL_ARGS=str(tmp_path / "panel.args"),
               OO_TEST_PRESENCE_NAMES=" ".join((*P.HELD_ENV_VARS, "OO_TEST_PANEL_ARGS")))  # the last is the control: always set
    return root, env


#: the stand-in panel waits for the server pid it was handed, as the real one does
_WAIT_FOR_SERVER = 'while [ "$1" != "--server-pid" ]; do shift; done; s=$2\nwhile kill -0 "$s" 2>/dev/null; do sleep 0.1; done\n'


def _launch(root: Path, env: dict[str, str], *, stdout_tty: bool = True):
    import pty

    master, slave = pty.openpty()
    proc = subprocess.Popen(["bash", str(root / "scripts" / "launch.sh")], cwd=str(root), env=env, stdin=slave,
                            stdout=slave if stdout_tty else subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    os.close(slave)
    return proc, master


def _wait_file(p: Path, secs: float) -> bool:
    end = time.monotonic() + secs
    while time.monotonic() < end and not p.exists():
        time.sleep(0.05)
    return p.exists()


def _drain(master: int) -> None:
    with contextlib.suppress(OSError):
        while select.select([master], [], [], 0)[0]:
            os.read(master, 65536)


@posix_only
def test_the_launcher_starts_the_panel_with_its_server_pid_on_a_terminal(tmp_path):
    root, env = _tree_with_panel(tmp_path, _WAIT_FOR_SERVER)
    env.update(OO_DB_PASSPHRASE="never-in-the-panel", OO_KEY_PASSPHRASE="never-either")
    proc, master = _launch(root, env)
    try:
        assert _wait_file(tmp_path / "panel.args", 30), "the panel was not started"
        time.sleep(0.3)
        args = (tmp_path / "panel.args").read_text(encoding="utf-8").split("\n")
        server_pid = (tmp_path / "server.pid").read_text(encoding="utf-8").strip()
        assert args[:2] == ["-m", "src.tui.panel"]
        assert args[args.index("--server-pid") + 1] == server_pid
        assert args[args.index("--port") + 1] == "8000"
        assert "tty" in args, "the panel must keep the terminal as its input (<&0), not bash's /dev/null"
        assert "held:OO_TEST_PANEL_ARGS=set" in args, "the control: the stand-in sees the rest of the environment"
        for name in P.HELD_ENV_VARS:
            assert f"held:{name}=unset" in args, f"the panel was handed {name}: launch.sh must start it without them"
        # A TERM to the launcher still stops the server AT ONCE with the panel running (a foreground panel would hold the trap back).
        t0 = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        rc = proc.wait(timeout=20)
        assert time.monotonic() - t0 < 10
        assert rc == 143
        assert not P.pid_alive(int(server_pid))
    finally:
        _drain(master)
        with contextlib.suppress(OSError):
            proc.kill()
        os.close(master)


@posix_only
def test_a_closed_panel_leaves_the_launcher_holding_the_server_and_its_status(tmp_path):
    root, env = _tree_with_panel(tmp_path, "exit 10\n")
    proc, master = _launch(root, env)
    try:
        assert _wait_file(tmp_path / "panel.args", 30)
        time.sleep(0.5)
        assert proc.poll() is None, "closing the panel must not end the launcher or the app"
        server_pid = int((tmp_path / "server.pid").read_text(encoding="utf-8").strip())
        os.kill(server_pid, signal.SIGTERM)  # a stop from outside, as the in-app power button is
        assert proc.wait(timeout=20) == 143
    finally:
        _drain(master)
        with contextlib.suppress(OSError):
            proc.kill()
        os.close(master)


@posix_only
@pytest.mark.parametrize("case", ["OO_PANEL=0", "stdout-not-a-terminal"])
def test_no_panel_without_a_terminal_or_when_turned_off(tmp_path, case):
    root, env = _tree_with_panel(tmp_path, _WAIT_FOR_SERVER)
    if case == "OO_PANEL=0":
        env["OO_PANEL"] = "0"
    proc, master = _launch(root, env, stdout_tty=case != "stdout-not-a-terminal")
    try:
        assert _wait_file(tmp_path / "server.pid", 30)
        time.sleep(1.5)
        assert not (tmp_path / "panel.args").exists()
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=20) == 143
    finally:
        _drain(master)
        with contextlib.suppress(OSError):
            proc.kill()
        os.close(master)


def test_launch_cmd_asks_for_the_panel_and_launch_server_runs_it_in_the_same_window():
    """R658: one window. launch.cmd no longer `start`s a second window for the panel; it hands the venv's python to
    launch_server.ps1, which checks curses and starts the panel in the same console with the server's pid."""
    cmd = (REPO / "scripts" / "launch.cmd").read_text(encoding="utf-8")
    assert "-m src.tui.panel" not in cmd and 'start "Open Omniscience panel"' not in cmd
    assert 'if not "%OO_PANEL%"=="0" if exist ".venv\\Scripts\\python.exe" set "PANELPY=.venv\\Scripts\\python.exe"' in cmd
    assert 'if defined PANELPY set PANELARG=-PanelPython "%PANELPY%"' in cmd
    assert '-Marker "%MARK%" %PANELARG% -Port "%PORT%" -Url "%URL%/"' in cmd, "no empty -PanelPython reaches PowerShell 5.1"
    ps1 = (REPO / "scripts" / "launch_server.ps1").read_text(encoding="utf-8")
    start = ps1.index("$panel = [System.Diagnostics.Process]::Start((New-PanelStartInfo $panelArgs))")
    assert ps1.index("[void]$p.Start()") < start, "the panel starts after the server, whose pid it is handed"
    assert ps1.index("if ($cp.ExitCode -eq 0) {") < start, "only when curses imports"
    assert '"-m src.tui.panel --port $Port --server-pid $($p.Id)"' in ps1
    assert "$si.UseShellExecute = $false" in ps1, "the same console: no new window"
    assert ps1.index("$panel.WaitForExit(15000)") > ps1.index("$p.WaitForExit()"), "the console is the launcher's again before it prints"


def test_a_long_log_never_pushes_the_buttons_off_a_short_terminal_and_scrolls():
    log = P.ActivityLog()
    for i in range(500):
        log.add(f"line {i}", at=1_000_000.0 + i)
    st = P.PanelState()
    lines, btns = P.build_screen(_snap(), 120, st, "u", 0.0, log=log, windows=False, height=24)
    assert len(lines) == 24 and max(b.row for b in btns) < 24
    text = "\n".join(t for t, _ in lines)
    assert "line 499" in text and "line 400" not in text, "newest at the bottom, following"
    st.scroll = 100
    lines, _ = P.build_screen(_snap(), 120, st, "u", 0.0, log=log, windows=False, height=24)
    text = "\n".join(t for t, _ in lines)
    assert "line 399" in text and "line 499" not in text and "100 newer lines below" in text
    st.scroll = 10**9
    P.build_screen(_snap(), 120, st, "u", 0.0, log=log, windows=False, height=24)
    assert st.scroll == 500 - (24 - 3 - 1 - 4), "clamped to the oldest line"


def test_the_log_keeps_the_newest_lines_and_counts_the_rest():
    log = P.ActivityLog(keep=10)
    for i in range(25):
        log.add(f"l{i}", at=1_000_000.0)
    assert len(log.lines) == 10 and log.total == 25 and log.dropped == 15
    assert log.lines[-1].text == "l24"
    lines, _ = P.build_screen(_snap(), 120, P.PanelState(), "u", 0.0, log=log, windows=False, height=30)
    assert any("15 older lines not kept" in t for t, _ in lines)


def test_a_new_day_gets_a_dated_rule_in_the_log():
    log = P.ActivityLog()
    log.add("a", at=time.mktime((2026, 11, 10, 23, 59, 0, 0, 0, -1)))
    log.add("b", at=time.mktime((2026, 11, 11, 0, 1, 0, 0, 0, -1)))
    assert [ln.style for ln in log.lines] == ["normal", "date", "normal"]
    assert "2026" in log.lines[1].text


def test_one_click_is_one_event():
    """Press, release and click in the mask turned one click into two events, and the second confirmed the Stop the first armed."""
    assert "mousemask(curses.BUTTON1_PRESSED | wheel_up | wheel_down)" in SRC  # the wheel is two other buttons: no second click event
    assert "bstate & curses.BUTTON1_PRESSED" in SRC


@posix_only
@pytest.mark.skipif(P.curses is None, reason="no curses")
def test_a_server_ending_while_the_log_is_shown_ends_the_panel_cleanly(server):
    """Leaving the log view through a stop used to call endwin() twice and print 'could not start' above the launcher's message."""
    import pty

    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    master, slave = pty.openpty()
    env = dict(os.environ, TERM="xterm-256color", PYTHONPATH=str(REPO))
    proc = subprocess.Popen([sys.executable, "-m", "src.tui.panel", "--port", str(server), "--server-pid", str(sleeper.pid)],
                            cwd=str(REPO), env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    os.close(slave)
    try:
        _read_until(master, b"Stop app", 20)
        os.write(master, b"l")
        out = _read_until(master, b"Press any key to return", 10)
        assert b"Press any key to return" in out
        sleeper.kill()
        sleeper.wait()
        assert proc.wait(timeout=15) == 0
        tail = _read_until(master, b"could not start", 1)
        assert b"could not start" not in tail
    finally:
        with contextlib.suppress(OSError):
            proc.kill()
        os.close(master)


# --------------------------------------------------------------------------- R658: the activity log, the identity watch, the redraw


def test_the_watcher_writes_one_line_per_change_and_nothing_when_nothing_changed():
    w = P.Watcher()
    first = _snap(jobs=[P.Job("wiki-dump", "frwiki", "running", percent=12.0, id="dump:fr"), P.Job("osm", "Belgium", "queued", id="osm:be")])
    w.observe(first, 0.0)
    assert w.observe(first, 3.0) == [], "an unchanged read writes nothing"
    moved = _snap(jobs=[P.Job("wiki-dump", "frwiki", "running", percent=34.0, id="dump:fr"),
                        P.Job("osm", "Belgium", "running", percent=1.0, id="osm:be")])
    lines = [t for t, _ in w.observe(moved, 6.0)]
    assert "Belgium: started  1 %" in lines
    assert any(t.startswith("frwiki: 30 %") for t in lines), "one line per 10 % crossed, at the highest crossed"
    assert not any("20 %" in t for t in lines)
    done = _snap(online=False, collecting=False, jobs=[P.Job("osm", "Belgium", "failed", percent=2.0, id="osm:be")])
    lines = [t for t, _ in w.observe(done, 9.0)]
    assert "frwiki: no longer listed (finished or removed)." in lines
    assert "Belgium: FAILED  2 %" in lines
    assert "Network: offline (airplane mode)." in lines and "Collection stopped." in lines


def test_silence_is_written_once_and_the_return_says_how_long():
    w = P.Watcher()
    assert [t for t, _ in w.observe(P.Snapshot(), 0.0)] == [], "before the first answer the header says Starting"
    assert [t for t, _ in w.observe(_snap(), 5.0)][0].startswith("The app answers (version 0.5.0)")
    gone = [t for t, _ in w.observe(P.Snapshot(), 10.0)]
    assert len(gone) == 1 and "stopped answering" in gone[0] and "keeps trying" in gone[0]
    assert w.observe(P.Snapshot(), 13.0) == [] and w.silent_for(200.0) == 190.0
    back = [t for t, _ in w.observe(_snap(), 200.0)]
    assert back == ["The app answers again, after 3m 10s without an answer."]
    lines, _ = P.build_screen(P.Snapshot(), 200, P.PanelState(), "u", 0.0, silent_for=75.0, windows=False)
    assert any("not answering for 1m 15s" in t for t, _ in lines)


def test_the_log_stays_where_the_reader_scrolled_while_lines_arrive():
    s = P.Session(port=1, url="u", server=P.ServerProcess(None))
    answers = {"/api/health": {"version": "1"}, "/api/jobs": {"jobs": []}}
    s.state.scroll = 5
    P.refresh(s, 0.0, fetch=_Fetch(answers))
    assert s.state.scroll == 5 + s.log.total, "every new line pushes the view back by one, so what was read stays put"
    s.state.scroll = 0
    n = s.log.total
    P.refresh(s, 3.0, fetch=_Fetch({**answers, "/api/scheduler/status": {"online": False}}))
    assert s.log.total == n + 1 and s.state.scroll == 0, "following the log: it stays at the newest line"


def test_actions_are_written_in_the_log_too():
    log, st = P.ActivityLog(), P.PanelState()
    P.do_action("pause", st, _snap(), 8000, "u", 0.0, fetch=_Fetch(), log=log)
    P.do_action("open", st, _snap(), 8000, "u", 1.0, fetch=_Fetch(), opener=lambda u: False, log=log)
    texts = [ln.text for ln in log.lines]
    assert texts[0].startswith("Collection paused") and texts[1].startswith("Could not open a browser")


@posix_only
def test_the_server_is_watched_by_identity_so_an_ended_or_unreaped_one_is_gone():
    if not P.ServerProcess(os.getpid()).pinned:
        pytest.skip("no psutil here")
    me = P.ServerProcess(os.getpid())
    assert me.pinned and me.alive()
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    watched = P.ServerProcess(child.pid)
    assert watched.alive()
    child.kill()
    deadline = time.monotonic() + 10
    while watched.alive() and time.monotonic() < deadline:  # not reaped yet: a zombie, which os.kill(pid, 0) still calls alive
        time.sleep(0.05)
    assert not watched.alive()
    child.wait()
    assert not watched.alive() and not P.ServerProcess(child.pid).alive()


def test_a_pid_given_to_another_program_is_not_the_server(monkeypatch):
    """The start time is part of the identity: psutil's is_running() says False once the pid holds another process."""
    sp = P.ServerProcess(os.getpid())
    if not sp.pinned:
        pytest.skip("no psutil here")

    class _Reused:
        def is_running(self):
            return False

        def status(self):
            return "running"

    sp._proc = _Reused()
    assert not sp.alive()


def _main_with_wrapper(monkeypatch, wrapper):
    if P.curses is None:
        pytest.skip("no curses here")
    monkeypatch.setattr(P.signal, "signal", lambda *a: None)
    monkeypatch.setattr(P.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(P.sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(P.curses, "wrapper", wrapper)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    return P.main(["--port", "8123"])


def test_an_error_inside_the_panel_redraws_it_with_its_log(monkeypatch):
    calls: list = []

    def wrapper(fn, session):
        calls.append(session)
        session.drawn = True
        if len(calls) == 1:
            raise ValueError("a secret-looking message that must never be shown")
        return 0

    assert _main_with_wrapper(monkeypatch, wrapper) == 0
    assert len(calls) == 2 and calls[0] is calls[1], "the same session, so the log survives"
    texts = [ln.text for ln in calls[1].log.lines]
    assert "The panel hit an error (ValueError) and redrew itself." in texts
    assert not any("secret-looking" in t for t in texts)


def test_repeated_errors_end_the_panel_and_say_so(monkeypatch, capsys):
    def wrapper(fn, session):
        session.drawn = True
        raise KeyError("x")

    assert _main_with_wrapper(monkeypatch, wrapper) == P.PANEL_FAILED
    err = capsys.readouterr().err
    assert "stopped after repeated errors (KeyError)" in err and "http://127.0.0.1:8123/" in err


def test_a_terminal_that_curses_cannot_drive_still_says_so(monkeypatch, capsys):
    def wrapper(fn, session):
        raise P.CursesError("setupterm")

    assert _main_with_wrapper(monkeypatch, wrapper) == 3
    assert "could not start (error)" in capsys.readouterr().err


class _Quiet(_H):
    """Answers the panel at first, then stops answering (a busy or sleeping server): the connection is accepted and never replied to."""

    quiet = False

    def do_GET(self):
        if _Quiet.quiet:
            time.sleep(5)
            return
        super().do_GET()


@posix_only
@pytest.mark.skipif(P.curses is None, reason="no curses")
def test_a_quiet_server_keeps_its_panel_and_it_says_so(monkeypatch):
    """R658, the field report: the panel closed when the server went quiet. Here it shows the silence and stays."""
    import pty

    if not P.ServerProcess(os.getpid()).pinned:
        pytest.skip("no psutil here")
    _H.seen, _Quiet.quiet = [], False
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    master, slave = pty.openpty()
    env = dict(os.environ, TERM="xterm-256color", PYTHONPATH=str(REPO))
    proc = subprocess.Popen([sys.executable, "-m", "src.tui.panel", "--port", str(srv.server_address[1]), "--server-pid", str(os.getpid())],
                            cwd=str(REPO), env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    os.close(slave)
    try:
        assert b"Collection is running" in _read_until(master, b"Collection is running", 20)
        _Quiet.quiet = True
        out = _read_until(master, b"stopped answering", 30)
        assert b"stopped answering" in out
        out = _read_until(master, b"not answering for", 15)
        assert b"not answering for" in out
        assert proc.poll() is None, "silence is shown, never acted on"
        _Quiet.quiet = False
        assert b"answers again" in _read_until(master, b"answers again", 30)
        proc.send_signal(signal.SIGINT)
        assert proc.wait(timeout=15) == 0
    finally:
        with contextlib.suppress(OSError):
            proc.kill()
        os.close(master)
        srv.shutdown()
        srv.server_close()


@posix_only
@pytest.mark.skipif(P.curses is None, reason="no curses")
def test_the_server_messages_view_returns_on_any_key(server):
    """A click on "Show log" used to leave the panel until Enter, which a click never sends: it read as the panel vanishing."""
    import pty

    master, slave = pty.openpty()
    env = dict(os.environ, TERM="xterm-256color", PYTHONPATH=str(REPO))
    proc = subprocess.Popen([sys.executable, "-m", "src.tui.panel", "--port", str(server), "--server-pid", str(os.getpid())],
                            cwd=str(REPO), env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    os.close(slave)
    try:
        _read_until(master, b"Stop app", 20)
        os.write(master, b"l")
        assert b"Press any key to return" in _read_until(master, b"Press any key to return", 10)
        os.write(master, b"x")
        assert b"Stop app" in _read_until(master, b"Stop app", 10), "back in the panel after one key, no Enter"
        assert proc.poll() is None
        proc.send_signal(signal.SIGINT)
        assert proc.wait(timeout=15) == 0
    finally:
        with contextlib.suppress(OSError):
            proc.kill()
        os.close(master)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="/proc")
def test_without_psutil_an_unreaped_server_still_reads_as_gone():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    deadline = time.monotonic() + 10
    while P.pid_alive(child.pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not P.pid_alive(child.pid), "a zombie answers os.kill(pid, 0); /proc says Z"
    child.wait()


def test_a_second_signal_does_not_cut_the_restore_short_and_ctrl_c_on_windows_is_sent_as_a_break():
    assert "if session.stopping[0]:\n            return" in SRC
    assert "except _Stop:\n                raise" in SRC, "a signal inside psutil is never swallowed"
    assert "IS_WINDOWS and ch == 3" in SRC and "GenerateConsoleCtrlEvent(0, 0)" in SRC
