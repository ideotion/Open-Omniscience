"""What the launcher does with the signals of a stop (17 Oct: a Ctrl-C through launch.sh sometimes skipped the app's shutdown).

One Ctrl-C used to reach the server twice: the terminal's SIGINT to the whole foreground group, and a SIGTERM from the launcher's own trap. uvicorn reads
a SIGINT that arrives after a stop has begun as the second Ctrl-C and forces the exit, skipping the lifespan shutdown (the app's teardown, which writes
the clean-stop mark). The server here is REAL uvicorn (the locked version) serving a stub ASGI app whose lifespan shutdown writes a file, with a
request in flight so the stop has a window. The ORDER is forced, not left to timing: the launcher is sent SIGINT alone; if it forwards a SIGTERM (the old
trap) the test waits for that TERM to arrive, and only then delivers the terminal's SIGINT to the server, the order that skips the teardown. Fixed
launcher: no TERM ever comes, the late SIGINT is the only signal, the teardown runs. Set OO_LAUNCH_SH_UNDER_TEST to run another copy of the script.
"""

from __future__ import annotations

import contextlib
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.test_exit_evidence import _launcher_tree

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the launcher is a bash script")

STUB = r'''
import asyncio, os, pathlib, sys
import uvicorn

D = pathlib.Path(os.environ["OO_TEST_DIR"])
_orig = uvicorn.Server.handle_exit


def _logged(self, sig, frame):  # only records which signal arrived; the real handler still runs
    with open(D / "signals.log", "a") as f:
        f.write({2: "INT", 15: "TERM", 1: "HUP"}.get(sig, str(sig)) + "\n")
    return _orig(self, sig, frame)


uvicorn.Server.handle_exit = _logged


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            m = await receive()
            if m["type"] == "lifespan.startup":
                (D / "ready").write_text("1")
                await send({"type": "lifespan.startup.complete"})
            elif m["type"] == "lifespan.shutdown":
                (D / "teardown").write_text("1")
                await send({"type": "lifespan.shutdown.complete"})
                return
    elif scope["type"] == "http":
        await receive()
        (D / "request.started").write_text("1")
        await asyncio.sleep(float(os.environ.get("OO_TEST_HOLD_S", "4")))  # the stop has a window while this runs
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


uvicorn.run(app, host="127.0.0.1", port=int(os.environ["OO_TEST_APP_PORT"]), log_level="warning", lifespan="on")
'''


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait(path: Path, secs: float) -> bool:
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if path.exists():
            return True
        time.sleep(0.05)
    return path.exists()


def _start(tmp_path: Path):
    root, env = _launcher_tree(tmp_path, "")
    work = tmp_path / "work"
    work.mkdir()
    stub = tmp_path / "stub.py"
    stub.write_text(STUB, encoding="utf-8")
    server = tmp_path / "bin" / "open-omniscience"
    server.write_text(f'#!/usr/bin/env bash\necho $$ > "$OO_TEST_PIDFILE"\nexec "{sys.executable}" "{stub}"\n', encoding="utf-8")
    port = _free_port()
    env.update(OO_TEST_DIR=str(work), OO_TEST_APP_PORT=str(port), OO_NO_BROWSER="1")
    script = os.environ.get("OO_LAUNCH_SH_UNDER_TEST")
    if script:
        (root / "scripts" / "launch.sh").write_bytes(Path(script).read_bytes())
    # a launcher run from a terminal is the foreground group's leader: its own session here, so no signal of the test leaks into it
    proc = subprocess.Popen(["bash", str(root / "scripts" / "launch.sh")], cwd=str(root), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True, preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    assert _wait(work / "ready", 60), "the stub server did not come up"
    server_pid = int((tmp_path / "server.pid").read_text(encoding="utf-8").strip())
    end = time.monotonic() + 15
    while True:  # the lifespan startup completes BEFORE uvicorn binds its socket: wait for the listener
        try:
            conn = socket.create_connection(("127.0.0.1", port), timeout=10)  # a request in flight, so the stop has a window to be forced in
            break
        except ConnectionRefusedError:
            assert time.monotonic() < end, "the stub server never listened"
            time.sleep(0.05)
    conn.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
    assert _wait(work / "request.started", 10)
    return proc, server_pid, work, conn


def _signals(work: Path) -> list[str]:
    f = work / "signals.log"
    return f.read_text(encoding="utf-8").split() if f.exists() else []


def _finish(proc, server_pid, conn) -> None:
    conn.close()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:  # never leave either behind
        proc.kill()
    with contextlib.suppress(OSError):
        os.kill(server_pid, signal.SIGKILL)


def test_a_ctrl_c_through_the_launcher_reaches_the_server_once_and_its_teardown_runs(tmp_path):
    proc, server_pid, work, conn = _start(tmp_path)
    try:
        os.kill(proc.pid, signal.SIGINT)  # the launcher alone: what its trap does with the signal is the thing under test
        _wait(work / "never-written", 3.0)  # the old trap forwards a TERM within this window; the fixed one never does
        os.kill(server_pid, signal.SIGINT)  # the terminal's own SIGINT reaching the server, arriving AFTER any TERM: the order that forced the exit
        assert _wait(work / "teardown", 15), f"the lifespan shutdown was skipped; the server was sent {_signals(work)}"
        assert _signals(work) == ["INT"], f"one Ctrl-C must be one signal at the server, got {_signals(work)}"
        assert proc.wait(timeout=30) in (130, 0)
    finally:
        _finish(proc, server_pid, conn)


def test_the_launcher_leaves_after_the_server_has_finished_its_teardown(tmp_path):
    proc, server_pid, work, conn = _start(tmp_path)
    try:
        os.kill(proc.pid, signal.SIGTERM)  # a close-the-window or service stop: not a terminal-group signal, so the launcher forwards it, once
        assert _wait(work / "ready", 1)
        time.sleep(1.0)
        assert proc.poll() is None, "the launcher left while the server was still stopping (a request was in flight)"
        conn.close()
        status = proc.wait(timeout=30)
        assert (work / "teardown").exists(), "the launcher exited before the server's teardown ran"
        assert _signals(work) == ["TERM"], f"TERM is forwarded exactly once, got {_signals(work)}"
        assert status in (143, 0), status
    finally:
        _finish(proc, server_pid, conn)
