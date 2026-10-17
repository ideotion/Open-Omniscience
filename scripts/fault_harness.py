#!/usr/bin/env python3
"""Crash-pipeline check: start the real app under the real launcher, kill it in a chosen way, boot it again, and assert what the next
boot's session-forensics report holds.

WHY. The chain that explains a crash (launcher exit record, stderr filter, crash trace, native in-flight file, thread census, the report
that carries them) was tested piece by piece, never end to end, so a regression in the join between two pieces would show up only in a
real crash. This runs the whole chain in a throwaway install and a throwaway data directory.

NOTHING IS ADDED TO ``src/``. The fault comes from outside the app: a ``sitecustomize.py`` in a harness-only directory on PYTHONPATH
starts a thread that waits for a trigger file and then does what the scenario names (abort inside an open native call, a null read), or
the harness sends the signal itself. The app is started by a COPY of ``scripts/launch.sh`` inside a fake install whose ``open-omniscience``
is a shim that execs the repo's own entry point.

SCENARIOS (each = boot, wait, fault, launcher exit, boot, read the report):
  native-abort   an open ``native_call("duckdb")`` and then ``os.abort()``: the report must say duckdb was in flight
  sigsegv        a null read in a native call: crash trace written, exit 139
  sigkill        SIGKILL from the harness: no trace is possible; the report must say so rather than claim one
  clean-stop     SIGTERM: the control; nothing may claim a crash

AND ONE LAB SCENARIO (LAB_SCENARIOS, named only; not a crash check, so tests/test_fault_harness.py does not run it):
  contention-zip        a real diagnostics zip with real storage-events: a SQLite write lock held from OUTSIDE the app (a second process, BEGIN IMMEDIATE)
                        makes the app's first writer wait in SQLite's busy handler while it holds the write gate (a gate_hold of the lock's length),
                        and a pool of one connection with a checkout timeout of 0 (the app's own OO_DB_POOL_* settings) makes overlapping requests
                        fail their checkout (pool_timeout). No src hook. Needs OO_FAULT_OUT (a folder for the zip); OO_FAULT_TREE points at the
                        checkout whose src/ is booted. The zip is of a throwaway data folder: no user data exists in it.

AND TWO THAT ARE RUN ONLY WHEN NAMED (EXTRA_SCENARIOS), for a launcher that has no boot id (Windows and macOS have none the app reads; here the
copy of launch.sh is made to find none, which is the same code path):
  bootless-sigkill      SIGKILL on the server: the launcher's own record (status 137) must still be joined to the session by pid
  bootless-reused-pid   an OLD launcher row (dated two days before) holds the pid this server then gets, and server AND launcher are killed so
                        no fresh row is written: the old row must NOT be shown as this session's end (pid reuse). Red when the date guard
                        in exit_evidence.launcher_exit / launcher_stderr is reverted.

EVERY scenario also asserts that the report carries no passphrase canary, no throwaway path and no e-mail-shaped text. The canary reaches
the app as the OO_HARNESS_CANARY environment variable, is printed to stderr and is the name of a Python thread before the fault.

SLOW (about 40 s per scenario: two boots of about 13 s plus the wait). Not part of the default test run: ``tests/test_fault_harness.py``
skips it unless ``OO_FAULT_HARNESS=1``. Linux only; needs ``curl`` and ``bash``.

    python scripts/fault_harness.py [scenario ...]        # default: all; exit 0 when every assertion held
    OO_FAULT_SHOW=1 ...                                   # also print the previous_session report (locally; it carries the throwaway path)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
# another checkout's src/ (a lab boot of a branch that is not this one); the launcher script stays this checkout's
TREE = Path(os.environ["OO_FAULT_TREE"]).resolve() if os.environ.get("OO_FAULT_TREE") else ROOT
CANARY = "hunter2-canary-OOFAULT-91c3"
SCENARIOS = ("native-abort", "sigsegv", "sigkill", "clean-stop")
EXTRA_SCENARIOS = ("bootless-sigkill", "bootless-reused-pid")
LAB_SCENARIOS = ("contention-zip",)  # not a crash scenario: a lab boot that makes real journal events and exports a real diagnostics zip
_BOOT_ID = "/proc/sys/kernel/random/boot_id"
BOOT_WAIT_S = 90
SETTLE_S = 12  # the liveness thread's first observe takes the census and writes the marks within one 5 s tick

_SITECUSTOMIZE = '''
import os, sys, threading, time
_t = os.environ.get("OO_HARNESS_TRIGGER")
_mode = os.environ.get("OO_HARNESS_FAULT", "")
if _t and _mode in ("native-abort", "sigsegv"):
    def _wait():
        while not os.path.exists(_t):
            time.sleep(0.2)
        sys.stderr.write("harness canary " + os.environ.get("OO_HARNESS_CANARY", "") + "\\n")
        sys.stderr.flush()
        if _mode == "native-abort":
            from src.monitoring.native_inflight import native_call
            native_call("duckdb").__enter__()
            os.abort()
        import ctypes
        with __import__("src.monitoring.native_inflight", fromlist=["native_call"]).native_call("lxml"):
            ctypes.string_at(0)
    threading.Thread(target=_wait, name="harness-" + os.environ.get("OO_HARNESS_CANARY", "x"), daemon=True).start()
'''


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _fake_install(base: Path, bootless: bool = False) -> Path:
    """A directory shaped like an install: scripts/launch.sh, .venv/bin/activate and an ``open-omniscience`` shim. No src/ is copied."""
    inst = base / "inst"
    (inst / "scripts").mkdir(parents=True)
    text = (ROOT / "scripts" / "launch.sh").read_text(encoding="utf-8")
    if bootless:  # a launcher that finds no boot id, as on Windows and macOS
        assert _BOOT_ID in text
        text = text.replace(_BOOT_ID, "/nonexistent/boot_id")
    (inst / "scripts" / "launch.sh").write_text(text, encoding="utf-8")
    vbin = inst / ".venv" / "bin"
    vbin.mkdir(parents=True)
    shim = vbin / "open-omniscience"
    shim.write_text(f'#!/bin/sh\necho $$ > "{base}/server.pid"\nexec "{sys.executable}" -c "from src.api.main import main; main()"\n')
    shim.chmod(0o755)
    (vbin / "activate").write_text(f'export PATH="{vbin}:$PATH"\n')
    return inst


def _env(base: Path, port: int, mode: str) -> dict[str, str]:
    hooks = base / "hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "sitecustomize.py").write_text(_SITECUSTOMIZE)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OO_", "PYTHON"))}
    env.update(
        OO_DATA_DIR=str(base / "data"),
        OO_PORT=str(port),
        OO_DB_PLAINTEXT="1",
        OO_HARNESS_CANARY=CANARY,
        OO_HARNESS_FAULT=mode,
        OO_HARNESS_TRIGGER=str(base / "trigger"),
        PYTHONPATH=os.pathsep.join([str(hooks), str(TREE)]),
        HOME=str(base / "home"),
    )
    (base / "home").mkdir(exist_ok=True)
    return env


def _launch(inst: Path, env: dict[str, str], log: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        ["bash", str(inst / "scripts" / "launch.sh")], cwd=str(inst), env=env,
        stdin=subprocess.DEVNULL, stdout=open(log, "ab"), stderr=subprocess.STDOUT,  # noqa: SIM115 - closed with the process
        start_new_session=True,
    )


def _wait_health(port: int, proc: subprocess.Popen[bytes]) -> bool:
    end = time.monotonic() + BOOT_WAIT_S
    while time.monotonic() < end and proc.poll() is None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(0.5)
    return False


def _report(port: int) -> dict[str, Any]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/diagnostics/session-forensics", timeout=60) as r:
        return json.loads(r.read())


def _stop(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(20)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(10)


def _leaks(text: str, base: Path) -> list[str]:
    bad = []
    if CANARY in text:
        bad.append("the passphrase canary")
    for needle in (str(base), base.name):
        at = text.find(needle)
        if at >= 0:
            bad.append(f"the throwaway path (...{text[max(0, at - 70):at + len(needle) + 20]}...)")
            break
    if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text):
        bad.append("an e-mail-shaped text")
    return bad


def _plant_old_rows(diag: Path, pid: int) -> None:
    """Launcher rows from a process that had this pid two days ago (null boot id, as a launcher without one writes them)."""
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    diag.mkdir(parents=True, exist_ok=True)
    rows = {
        "launcher_exits.jsonl": {"schema": "oo-launcher-exit-1", "at": old, "started_at": old, "pid": pid, "boot_id": None, "status": 139, "signal": "SIGSEGV"},
        "launcher_stderr.jsonl": {"schema": "oo-launcher-stderr-1", "at": old, "pid": pid, "boot_id": None, "line": "Fatal Python error: Segmentation fault"},
    }
    for name, row in rows.items():
        with open(diag / name, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")


def run_scenario(mode: str) -> list[str]:
    """Run one scenario; return the list of failed assertions (empty = held)."""
    failures: list[str] = []
    base = Path(tempfile.mkdtemp(prefix="oo-fault-"))
    port = _free_port()
    try:
        bootless = mode.startswith("bootless-")
        inst = _fake_install(base, bootless)
        log = base / "launcher.log"
        env = _env(base, port, mode)
        first = _launch(inst, env, log)
        if not _wait_health(port, first):
            return [f"first boot never became healthy ({log.read_text()[-400:] if log.exists() else 'no log'})"]
        time.sleep(SETTLE_S)
        if mode in ("native-abort", "sigsegv"):
            (base / "trigger").write_text("go")
        elif mode in ("sigkill", "bootless-sigkill"):
            os.kill(int((base / "server.pid").read_text()), signal.SIGKILL)
        elif mode == "bootless-reused-pid":
            _plant_old_rows(base / "data" / "diagnostics", int((base / "server.pid").read_text()))
            os.killpg(first.pid, signal.SIGKILL)  # the launcher dies with the server: no fresh row is written
        else:
            first.send_signal(signal.SIGTERM)
        try:
            status = first.wait(40)
        except subprocess.TimeoutExpired:
            os.killpg(first.pid, signal.SIGKILL)
            return ["the launcher did not end after the fault"]
        want = {"native-abort": 134, "sigsegv": 139, "sigkill": 137, "clean-stop": None, "bootless-sigkill": 137, "bootless-reused-pid": None}[mode]
        if want is not None and status != want:
            failures.append(f"launcher exit status {status}, expected {want}")
        # The launcher can end before its server has (a stop is asked, then the server shuts down for a few seconds): a second launch
        # would find the old server healthy, print "already running" and report the OLD process. Wait for the server itself.
        server = int((base / "server.pid").read_text())
        end = time.monotonic() + 60
        while Path(f"/proc/{server}").exists() and time.monotonic() < end:
            time.sleep(0.3)
        if Path(f"/proc/{server}").exists():
            return [*failures, "the first server did not end"]
        # second boot, same data dir, no fault
        (base / "trigger").unlink(missing_ok=True)
        env2 = dict(env, OO_HARNESS_FAULT="")
        second = _launch(inst, env2, log)
        try:
            if not _wait_health(port, second):
                return [*failures, "second boot never became healthy"]
            try:
                rep = _report(port)
            except OSError as exc:
                tail = log.read_text(errors="replace")[-600:] if log.exists() else "no log"
                return [*failures, f"the report could not be read ({type(exc).__name__}); launcher log ends: {tail!r}"]
        finally:
            _stop(second)
        if os.environ.get("OO_FAULT_SHOW") == "1":
            print(json.dumps(rep.get("previous_session"), indent=1)[:6000])
        failures += _assert_report(mode, rep)
        # The crash evidence is `previous_session`. `inventory`, `storage_footprint` and `data_dir_persistence` exist to NAME the data
        # directory (a local view; a bundle writes the home folder as <home>), so a path in them is their purpose, not a leak.
        failures += [f"previous_session carries {x}" for x in _leaks(json.dumps(rep.get("previous_session")), base)]
        failures += [f"{k} carries {x}" for k in ("expedition", "last_unlock", "last_recovery", "last_init_db", "pass_tail_journal")
                     for x in _leaks(json.dumps(rep.get(k)), base) if "path" not in x]
        return failures
    finally:
        if os.environ.get("OO_FAULT_KEEP") == "1":
            print(f"kept {base}")
        else:
            shutil.rmtree(base, ignore_errors=True)


def _assert_report(mode: str, rep: dict[str, Any]) -> list[str]:
    out: list[str] = []
    prev = rep.get("previous_session") or {}
    ev = prev.get("exit_evidence") or {}
    nif = (ev.get("native_in_flight") or {})
    census = (prev.get("previous_session_peaks") or {}).get("last_thread_census")
    if mode == "clean-stop":
        if prev.get("previous_session") not in ("clean", None) and "clean" not in json.dumps(prev.get("how_it_ended") or {}).lower():
            out.append("a clean stop was not reported as clean")
        return out
    if mode == "native-abort":
        if nif.get("result") != "in-flight" or "duckdb" not in (nif.get("counts") or {}):
            out.append(f"native_in_flight should name duckdb in flight, got {nif}")
    elif mode == "sigsegv":
        if nif.get("result") not in ("in-flight", "none-in-flight", "no-calls-recorded"):
            out.append(f"native_in_flight should be an outcome of the previous session, got {nif}")
        elif nif.get("result") == "in-flight" and "lxml" not in (nif.get("counts") or {}):
            out.append(f"native_in_flight should name lxml, got {nif}")
        if not (ev.get("crash_trace") or {}):
            out.append("no crash_trace member for a SIGSEGV")
    elif mode == "bootless-sigkill":
        lx = ev.get("launcher") or {}
        if lx.get("status") != 137:
            out.append(f"a launcher without a boot id must still join its own exit record by pid (status 137), got {lx}")
    elif mode == "bootless-reused-pid":
        if ev.get("launcher"):
            out.append(f"an exit record dated before this session began was shown as its end: {ev.get('launcher')}")
        if "Segmentation" in json.dumps(ev.get("launcher_stderr") or {}):
            out.append("a stderr row dated before this session began was shown as its own")
    elif mode == "sigkill":
        if nif.get("result") not in ("no-calls-recorded", "none-in-flight"):
            out.append(f"a session killed with no native call open must read as no-calls-recorded or none-in-flight, got {nif}")
        if (ev.get("crash_trace") or {}).get("lines"):
            out.append("a SIGKILL cannot leave a crash trace, but one was reported")
    if not isinstance(census, dict) or census.get("os_threads") is None and not census.get("unavailable"):
        out.append(f"last_thread_census missing or malformed: {census}")
    return out


LOCK_HOLD_S = 45  # past the app's 30 s busy_timeout and the journal's 30 s hold threshold (writer.HOLD_RECORD_S)


def _http(port: int, method: str, path: str, body: dict[str, Any] | None = None, timeout: float = 120) -> tuple[Any, float]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Content-Type": "application/json"})
    t = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            return r.status, round(time.monotonic() - t, 1)
    except urllib.error.HTTPError as exc:
        return exc.code, round(time.monotonic() - t, 1)
    except OSError as exc:
        return type(exc).__name__, round(time.monotonic() - t, 1)


def run_contention_zip() -> list[str]:
    import threading

    out = os.environ.get("OO_FAULT_OUT")
    if not out:
        return ["OO_FAULT_OUT (a folder for the zip) is required"]
    failures: list[str] = []
    base = Path(tempfile.mkdtemp(prefix="oo-lab-"))
    port = _free_port()
    proc = None
    try:
        inst = _fake_install(base)
        env = _env(base, port, "")
        env.update(OO_DB_POOL_SIZE="1", OO_DB_MAX_OVERFLOW="0", OO_DB_POOL_TIMEOUT="0", OO_WRITE_GATE_WATCH_INTERVAL_S="1", OO_NO_BROWSER="1", BROWSER="true")
        proc = _launch(inst, env, base / "launcher.log")
        if not _wait_health(port, proc):
            return ["the lab boot never became healthy"]
        time.sleep(SETTLE_S)
        db = base / "data" / "open_omniscience.db"
        holder = subprocess.Popen([sys.executable, "-I", "-c", f"import sqlite3,time;c=sqlite3.connect({str(db)!r},timeout=0,isolation_level=None);c.execute('BEGIN IMMEDIATE');print('locked',flush=True);time.sleep({LOCK_HOLD_S});c.execute('COMMIT')"],
                                  stdout=subprocess.PIPE, text=True)
        assert holder.stdout is not None
        if holder.stdout.readline().strip() != "locked":
            return ["the outside lock was not taken"]
        results: list[Any] = []
        writers = [threading.Thread(target=lambda i=i: results.append(("write", *_http(port, "PUT", "/api/scheduler/config", {"collect_target_kbps": 500 + i})))) for i in range(3)]
        for t in writers:
            t.start()
            time.sleep(0.3)
        deadline = time.monotonic() + LOCK_HOLD_S + 5
        while time.monotonic() < deadline:  # overlapping reads on a pool of one connection with a checkout timeout of 0
            storm = [threading.Thread(target=lambda: results.append(("read", *_http(port, "GET", "/api/diagnostics/session-forensics")))) for _ in range(6)]
            for t in storm:
                t.start()
            for t in storm:
                t.join()
            time.sleep(1.0)
        holder.wait()
        for t in writers:
            t.join(timeout=60)
        time.sleep(3)  # the journal's writer
        ev = json.loads((base / "data" / "storage_events.json").read_text(encoding="utf-8"))["kinds"]
        for kind in ("gate_hold", "pool_timeout"):
            if not ev.get(kind, {}).get("total"):
                failures.append(f"no {kind} event was recorded (the lab did not force it)")
        status, _ = _http(port, "POST", "/api/diagnostics/all-job", {})
        if status != 200:
            return [*failures, f"the all-diagnostics job did not start ({status})"]
        end = time.monotonic() + 900
        ready = False
        while time.monotonic() < end:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/diagnostics/all-job/status", timeout=30) as r:
                st = json.loads(r.read())
            if st.get("ready"):
                ready = True
                break
            if st.get("state") in ("failed", "error"):
                return [*failures, f"the all-diagnostics job ended {st.get('state')}"]
            time.sleep(5)
        if not ready:
            return [*failures, "the all-diagnostics job did not finish in 900 s"]
        Path(out).mkdir(parents=True, exist_ok=True)
        dest = Path(out) / f"oo-diagnostics-lab-{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}.zip"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/diagnostics/all-job/download", timeout=300) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        print(f"zip: {dest} ({dest.stat().st_size} bytes); requests: " + json.dumps({k: sorted({str(x[1]) for x in results if x[0] == k}) for k in ("write", "read")}))
        return failures
    finally:
        if proc is not None:
            _stop(proc)
        if os.environ.get("OO_FAULT_KEEP") == "1":
            print(f"kept {base}")
        else:
            shutil.rmtree(base, ignore_errors=True)


def main(argv: list[str]) -> int:
    names = argv or list(SCENARIOS)
    bad = [n for n in names if n not in SCENARIOS + EXTRA_SCENARIOS + LAB_SCENARIOS]
    if bad:
        print(f"unknown scenario(s) {bad}; choose from {SCENARIOS + EXTRA_SCENARIOS + LAB_SCENARIOS}", file=sys.stderr)
        return 2
    code = 0
    for name in names:
        t0 = time.monotonic()
        failed = run_contention_zip() if name in LAB_SCENARIOS else run_scenario(name)
        print(f"{'FAIL' if failed else 'ok  '} {name} ({time.monotonic() - t0:.0f} s)")
        for f in failed:
            print(f"     - {f}")
        code |= 1 if failed else 0
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
