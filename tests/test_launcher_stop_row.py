"""A stop the launcher was ASKED for leaves a row, and the next boot reads an unclean end with that row as "stop requested, teardown incomplete" (R168).

Before: a Ctrl-C, a closed window or a service stop is marked STOP_REQUESTED in the launcher and leaves nothing, so a teardown that did not finish
looked at the next boot exactly like a SIGKILL (measured 17 Oct on a stopped server: the same report, byte for byte but for times and pids). What is
pinned: the launcher writes ONE row per trapped INT/TERM/HUP, before it forwards anything, with the signal, the server pid, the boot and the time
and nothing else; the reader joins it by pid and boot, never to another process, never when an exit row exists, never for a signal the launcher
does not trap; the words say a request and an unfinished teardown and never a crash; no row keeps the old wording; and the block it adds is no
wider than the exit block it takes the place of (the Diagnostics budget argument: the two cannot exist for one pid).
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.monitoring import exit_evidence as ee
from tests.test_exit_evidence import _launcher_tree

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the launcher is a bash script")

SERVER_WAITS = """trap 'if [ -s "$OO_TEST_STOPFILE" ]; then echo row-first > "$OO_TEST_ORDER"; else echo no-row-yet > "$OO_TEST_ORDER"; fi; exit 0' TERM HUP
echo up > "$OO_TEST_READY"
while :; do sleep 0.1; done
"""


def _wait(path: Path, secs: float = 20) -> bool:
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if path.exists():
            return True
        time.sleep(0.05)
    return path.exists()


def _launch(tmp_path: Path):
    root, env = _launcher_tree(tmp_path, SERVER_WAITS)
    env.update(OO_DATA_DIR=str(root / "data"), OO_TEST_STOPFILE=str(root / "data" / "diagnostics" / ee.LAUNCHER_STOPS),
               OO_TEST_ORDER=str(tmp_path / "order"), OO_TEST_READY=str(tmp_path / "ready"))
    proc = subprocess.Popen(["bash", str(root / "scripts" / "launch.sh")], cwd=str(root), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    assert _wait(tmp_path / "ready"), "the fake server did not start"
    time.sleep(0.5)  # the launcher installs its traps right after the server starts
    pid = int((tmp_path / "server.pid").read_text(encoding="utf-8").strip())
    return root, proc, pid


def _rows(root: Path) -> list[dict]:
    f = root / "data" / "diagnostics" / ee.LAUNCHER_STOPS
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()] if f.exists() else []


@posix_only
@pytest.mark.parametrize(("sig", "name"), [(signal.SIGTERM, "SIGTERM"), (signal.SIGHUP, "SIGHUP")])
def test_a_forwarded_stop_leaves_its_row_before_the_server_is_told(tmp_path, sig, name):
    root, proc, pid = _launch(tmp_path)
    try:
        os.kill(proc.pid, sig)
        assert proc.wait(timeout=30) is not None
    finally:
        if proc.poll() is None:
            proc.kill()
    assert (tmp_path / "order").read_text(encoding="utf-8").strip() == "row-first", "the row must exist when the server receives the signal"
    [row] = _rows(root)
    assert set(row) == {"schema", "at", "pid", "boot_id", "signal"}, "the signal, the server pid, the boot and the time; nothing from the environment"
    assert row["pid"] == pid and row["signal"] == name and row["schema"] == "oo-launcher-stop-1"


@posix_only
def test_ctrl_c_leaves_its_row_and_the_server_is_not_sent_a_signal_by_the_launcher(tmp_path):
    root, proc, pid = _launch(tmp_path)
    try:
        os.kill(proc.pid, signal.SIGINT)
        time.sleep(1.5)
        assert proc.poll() is None, "INT is not forwarded: the launcher waits for the server (the terminal sent it the SIGINT)"
        assert not (tmp_path / "order").exists(), "the server was sent nothing by the launcher"
        [row] = _rows(root)
        assert row["pid"] == pid and row["signal"] == "SIGINT"
    finally:
        os.kill(pid, signal.SIGKILL)
        proc.wait(timeout=30)


def _write(dd: Path, name: str, *rows: dict) -> None:
    (dd / "diagnostics").mkdir(parents=True, exist_ok=True)
    with (dd / "diagnostics" / name).open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


@pytest.fixture()
def dd(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    return tmp_path


def _stop(pid=4242, sig="SIGINT", at="2026-10-17T10:00:00Z", boot="b" * 8):
    return {"schema": "oo-launcher-stop-1", "at": at, "pid": pid, "boot_id": boot, "signal": sig}


def test_the_reader_joins_a_stop_row_by_pid_and_boot_and_says_a_request_not_a_crash(dd):
    _write(dd, ee.LAUNCHER_STOPS, _stop(pid=111), _stop(pid=4242), _stop(pid=4242, boot="other"))
    got = ee.launcher_exit(4242, "b" * 8, "2026-10-17T09:00:00Z")
    assert got["kind"] == "stop asked" and got["signal"] == "SIGINT" and got["status"] is None
    assert "Not a crash" in got["meaning"] and "did not complete" in got["meaning"]
    assert ee.launcher_exit(999, "b" * 8) is None, "another pid is another process"
    assert ee.launcher_exit(4242, "c" * 8) is None, "a row from another boot of the machine is never this session's"


def test_a_row_older_than_the_session_is_pid_reuse_where_no_boot_id_exists(dd):
    _write(dd, ee.LAUNCHER_STOPS, _stop(pid=4242, at="2026-10-15T10:00:00Z", boot=None))
    assert ee.launcher_exit(4242, None, "2026-10-17T09:00:00Z") is None
    assert ee.launcher_exit(4242, None, "2026-10-15T09:00:00Z")["kind"] == "stop asked"


def test_an_exit_row_wins_and_a_stop_row_never_answers_beside_it(dd):
    _write(dd, ee.LAUNCHER_STOPS, _stop(pid=4242))
    _write(dd, ee.LAUNCHER_EXITS, {"schema": "oo-launcher-exit-1", "at": "2026-10-17T10:00:05Z", "started_at": "2026-10-17T09:00:00Z", "pid": 4242,
                                   "boot_id": "b" * 8, "status": 137, "signal": "SIGKILL"})
    got = ee.launcher_exit(4242, "b" * 8)
    assert got["signal"] == "SIGKILL" and got["kind"] != "stop asked"


@pytest.mark.parametrize("bad", ["SIGKILL", "SIGSEGV", "INT", "SIGINT; rm -rf", "", None, 2])
def test_only_the_three_trapped_signals_are_read_as_a_stop(dd, bad):
    _write(dd, ee.LAUNCHER_STOPS, _stop(pid=4242, sig=bad))
    assert ee.launcher_exit(4242, "b" * 8) is None


@pytest.mark.parametrize("junk", ["123", "null", '"x"', "[1, 2]", "true", '{"pid": 4242, "signal": ["SIGINT"], "boot_id": null}',
                                  '{"pid": 4242, "signal": {"a": 1}, "boot_id": null}', "{torn", "\x00\x00\x00"])
def test_a_line_that_is_not_a_row_is_skipped_not_an_error(dd, junk):
    """A torn or interleaved line (or one an older launcher left) can be valid JSON that is not a row. It used to raise, which cost the caller its
    other witnesses (forensics reads the launcher row, the stderr row and the crash trace in one try). Found by the reader audit of 17 Oct."""
    (dd / "diagnostics").mkdir(parents=True, exist_ok=True)
    (dd / "diagnostics" / ee.LAUNCHER_STOPS).write_text(junk + "\n" + json.dumps(_stop(pid=4242, sig="SIGTERM")) + "\n" + junk + "\n", encoding="utf-8")
    got = ee.launcher_exit(4242, "b" * 8)
    assert got is not None and got["kind"] == "stop asked" and got["signal"] == "SIGTERM", "the good row between the junk lines is still read"
    (dd / "diagnostics" / ee.LAUNCHER_STOPS).write_text(junk + "\n", encoding="utf-8")
    assert ee.launcher_exit(4242, "b" * 8) is None


def test_the_sentence_says_stop_requested_teardown_incomplete_and_without_a_row_keeps_the_old_one():
    block = {"kind": "stop asked", "signal": "SIGTERM", "status": None}
    said = ee.how_it_ended(launcher=block, killers=None, kernel=None, trace=None)
    assert said["known"] is True and "stop requested, teardown incomplete, not a crash" in said["summary"] and "SIGTERM" in said["summary"]
    assert "saw it end by" not in said["summary"]
    none = ee.how_it_ended(launcher=None, killers=None, kernel=None, trace=None)
    assert none["known"] is False and "no launcher record" in none["summary"]
    killed = ee.how_it_ended(launcher={"signal": "SIGKILL", "status": 137, "kind": "killed"}, killers=None, kernel=None, trace=None)
    assert "the launcher saw it end by SIGKILL" in killed["summary"]


def test_the_stop_block_is_no_wider_than_the_exit_block_it_takes_the_place_of(dd):
    """The Diagnostics argument (net-zero): a session has an exit block or a stop block, never both, because the launcher writes an exit row only when
    no stop was asked and the reader answers with the exit row first. The budget already counts the exit block at its worst. Measured with the real
    readers: the widest stop block against the widest exit block (a 19-digit stamp-less record, the longest signal name, the longest meaning)."""
    _write(dd, ee.LAUNCHER_STOPS, _stop(pid=7, sig="SIGTERM", at="2026-10-17T10:00:00+00:00"))
    stop = ee.launcher_exit(7, "b" * 8)
    assert stop is not None and stop["kind"] == "stop asked"
    wide = ee.describe_exit({"at": "2026-10-17T10:00:00+00:00", "started_at": "2026-10-17T09:00:00+00:00", "status": 2**32, "signal": "SIGXXXXXXXXXX"})
    widest_signal = max((ee.describe_exit({"at": "2026-10-17T10:00:00+00:00", "started_at": "2026-10-17T09:00:00+00:00", "status": 137, "signal": s}) for s in ee._SIGNAL_MEANING), key=lambda d: len(json.dumps(d)))  # noqa: SLF001
    widest_exit = max(len(json.dumps(wide, separators=(",", ":"))), len(json.dumps(widest_signal, separators=(",", ":"))))
    got = len(json.dumps(stop, separators=(",", ":")))
    assert got <= widest_exit, f"the stop block is {got} B, the exit block's widest is {widest_exit} B"
    print(f"stop block {got} B, widest exit block {widest_exit} B")


# --- Windows: scripts/launch_server.ps1 writes the same row on Ctrl-C (R168 parity). TESTED ONLY ON POWERSHELL 7 ON LINUX WITH A FAKE SERVER: the real
# --- exit status of a Ctrl-C in a Windows console, PowerShell 5.1 and cmd.exe are untested (docs/ledger/OPEN_QUEUE.md).

_PWSH = os.environ.get("OO_PWSH") or shutil.which("pwsh")
_needs_pwsh = pytest.mark.skipif(not _PWSH or os.name == "nt", reason="no PowerShell 7 here (OO_PWSH)")
_WIN_CTRL_C = -1073741510


def _run_wrapper(tmp_path, body, ctrl_c_as=58):
    """Run a COPY of the wrapper whose Ctrl-C status is replaced by one a Linux process can exit with (a Linux exit code is 0-255, never an NTSTATUS)."""
    ps1 = Path(__file__).resolve().parents[1] / "scripts" / "launch_server.ps1"
    text = ps1.read_text(encoding="utf-8")
    assert text.count("-1073741510") == 3, "the Ctrl-C status is named in three places in the wrapper (a comment, the stop row, the exit row); this test substitutes all of them"
    copy = tmp_path / "launch_server_copy.ps1"
    copy.write_text(text.replace("-1073741510", str(ctrl_c_as)), encoding="utf-8")
    exe = tmp_path / "server"
    exe.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    exe.chmod(0o755)
    data = tmp_path / "data"
    marker = tmp_path / "started.marker"
    env = {k: v for k, v in os.environ.items() if not k.startswith("OO_")}
    proc = subprocess.run([_PWSH, "-NoProfile", "-File", str(copy), "-App", str(exe), "-Marker", str(marker), "-DataDir", str(data)],
                           capture_output=True, text=True, timeout=90, env=env, stdin=subprocess.DEVNULL)
    return proc, int(marker.read_text(encoding="utf-8")), data


@_needs_pwsh
def test_a_windows_ctrl_c_leaves_a_stop_row_and_no_exit_row_and_other_ends_leave_none(tmp_path, monkeypatch):
    proc, pid, data = _run_wrapper(tmp_path, "exit 58\n")
    assert proc.returncode == 58
    rows = [json.loads(x) for x in (data / "diagnostics" / "launcher_stops.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["pid"] == pid and rows[0]["signal"] is None and rows[0]["boot_id"] is None
    assert set(rows[0]) == {"schema", "at", "pid", "boot_id", "signal", "status"} and rows[0]["schema"] == "oo-launcher-stop-1"
    assert rows[0]["status"] == 58, "the copy's substituted status; the shipped script writes -1073741510"
    assert not (data / "diagnostics" / "launcher_exits.jsonl").exists()
    for n, (body, code) in enumerate((("exit 0\n", 0), ("exit 5\n", 5))):
        sub = tmp_path / f"other{n}"
        sub.mkdir()
        _, _, d2 = _run_wrapper(sub, body)
        assert not (d2 / "diagnostics" / "launcher_stops.jsonl").exists(), f"exit {code} is not a Ctrl-C"


def test_the_reader_names_a_windows_ctrl_c_row_and_refuses_a_null_signal_with_any_other_status(dd):
    _write(dd, ee.LAUNCHER_STOPS,
           {"schema": "oo-launcher-stop-1", "at": "2026-10-17T10:00:00Z", "pid": 31, "boot_id": None, "signal": None, "status": _WIN_CTRL_C},
           {"schema": "oo-launcher-stop-1", "at": "2026-10-17T10:00:00Z", "pid": 32, "boot_id": None, "signal": None, "status": 5},
           {"schema": "oo-launcher-stop-1", "at": "2026-10-17T10:00:00Z", "pid": 33, "boot_id": None, "signal": None})
    got = ee.launcher_exit(31, None, "2026-10-17T09:00:00Z")
    assert got["kind"] == "stop asked" and got["signal"] == "Ctrl-C" and "(Ctrl-C)" in got["meaning"] and "Not a crash" in got["meaning"]
    assert "launch_server.ps1" in got["seen_by"]
    assert ee.launcher_exit(32) is None and ee.launcher_exit(33) is None
    assert ee.launcher_exit(31, None, "2026-10-17T11:00:00Z") is None, "a row older than the session is another process's (no boot id on Windows)"
    said = ee.how_it_ended(launcher=got, killers=None, kernel=None, trace=None)
    assert "Ctrl-C" in said["summary"] and "not a crash" in said["summary"]


def test_the_windows_stop_block_is_no_wider_than_the_exit_block_it_takes_the_place_of(dd):
    _write(dd, ee.LAUNCHER_STOPS, {"schema": "oo-launcher-stop-1", "at": "2026-10-17T10:00:00+00:00", "pid": 4294967295, "boot_id": None, "signal": None, "status": _WIN_CTRL_C})
    block = ee.launcher_exit(4294967295, None)
    assert block is not None and block["kind"] == "stop asked"
    wide = ee.describe_exit({"at": "2026-10-17T10:00:00+00:00", "started_at": "2026-10-17T09:00:00+00:00", "status": 2**32, "signal": "SIGXXXXXXXXXX"})
    widest_signal = max((ee.describe_exit({"at": "2026-10-17T10:00:00+00:00", "started_at": "2026-10-17T09:00:00+00:00", "status": 137, "signal": sg}) for sg in ee._SIGNAL_MEANING), key=lambda d: len(json.dumps(d)))  # noqa: SLF001
    got = len(json.dumps(block, separators=(",", ":")))
    widest = max(len(json.dumps(wide, separators=(",", ":"))), len(json.dumps(widest_signal, separators=(",", ":"))))
    assert got <= widest, f"the Windows stop block is {got} B, the exit block's widest is {widest} B"
    print(f"windows stop block {got} B, widest exit block {widest} B")
