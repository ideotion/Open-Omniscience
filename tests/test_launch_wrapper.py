"""The Windows launcher's server wrapper (scripts/launch_server.ps1) and its caller (scripts/launch.cmd).

NOT RUN ON WINDOWS. The wrapper is run here by PowerShell 7 on Linux against a fake server, which proves its logic (pass-through, the fixed
list, the cap, the records, the fallbacks); it does not prove Windows PowerShell 5.1, a real console or the exit codes of a real crash. These
tests skip when no ``pwsh`` is installed (set OO_PWSH to its path)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.monitoring import exit_evidence as ee

REPO = Path(__file__).resolve().parent.parent
PS1 = REPO / "scripts" / "launch_server.ps1"
CMD = REPO / "scripts" / "launch.cmd"
PWSH = os.environ.get("OO_PWSH") or shutil.which("pwsh")
needs_pwsh = pytest.mark.skipif(not PWSH or os.name == "nt", reason="no PowerShell 7 here (OO_PWSH)")


def _fake_server(tmp_path: Path, body: str) -> Path:
    exe = tmp_path / "server"
    exe.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    exe.chmod(0o755)
    return exe


def _run(tmp_path: Path, body: str, *extra: str, dd: Path | bool | None = None, env: dict[str, str] | None = None):
    exe = _fake_server(tmp_path, body)
    marker = tmp_path / "started.marker"
    data = dd if isinstance(dd, Path) else tmp_path / "data"
    cmd = [PWSH, "-NoProfile", "-File", str(PS1), "-App", str(exe), "-Marker", str(marker), *(["-DataDir", str(data)] if dd is not False else []), *extra]
    e = {k: v for k, v in os.environ.items() if not k.startswith("OO_")}
    e.update(env or {})
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90, env=e, stdin=subprocess.DEVNULL)
    return proc, marker, data / "diagnostics"


def _rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


@needs_pwsh
def test_every_line_reaches_the_window_and_only_the_fixed_headers_are_recorded(tmp_path):
    body = "echo 'INFO fine' >&2\necho 'the passphrase hunter2-secret was typed' >&2\necho 'Fatal Python error: Aborted' >&2\necho 'Fatal Python error: Aborted now' >&2\necho stdout-line\nexit 3\n"
    proc, marker, diag = _run(tmp_path, body)
    assert proc.returncode == 3, proc.stderr
    for line in ("INFO fine", "the passphrase hunter2-secret was typed", "Fatal Python error: Aborted now"):
        assert line in proc.stderr
    assert "stdout-line" in proc.stdout
    rows = _rows(diag / ee.LAUNCHER_STDERR)
    assert [r["line"] for r in rows if not r.get("summary")] == ["Fatal Python error: Aborted"]
    assert "hunter2" not in (diag / ee.LAUNCHER_STDERR).read_text(encoding="utf-8")
    [summary] = [r for r in rows if r.get("summary")]
    assert summary["kept_lines"] == 1 and summary["dropped_lines"] == 3 and summary["over_cap_lines"] == 0
    pid = int(marker.read_text(encoding="utf-8"))
    assert {r["pid"] for r in rows} == {pid} and {r["boot_id"] for r in rows} == {None}


@needs_pwsh
def test_a_header_in_another_case_is_not_recorded(tmp_path):
    proc, marker, diag = _run(tmp_path, "echo 'FATAL PYTHON ERROR: ABORTED' >&2\necho 'fatal python error: aborted' >&2\nexit 3\n")
    rows = _rows(diag / ee.LAUNCHER_STDERR)
    assert [r for r in rows if not r.get("summary")] == []
    [summary] = [r for r in rows if r.get("summary")]
    assert summary["kept_lines"] == 0 and summary["dropped_lines"] == 2


@needs_pwsh
def test_the_record_is_capped_per_launch_and_the_overflow_counted(tmp_path):
    body = "for i in $(seq 1 30); do echo 'Fatal Python error: Bus error' >&2; done\nexit 0\n"
    proc, _, diag = _run(tmp_path, body)
    assert proc.returncode == 0
    rows = _rows(diag / ee.LAUNCHER_STDERR)
    assert sum(1 for r in rows if not r.get("summary")) == 20
    assert [r for r in rows if r.get("summary")][0]["over_cap_lines"] == 10


@needs_pwsh
def test_an_error_exit_is_recorded_with_the_servers_pid_and_a_clean_exit_or_ctrl_c_is_not(tmp_path):
    proc, marker, diag = _run(tmp_path, "exit 5\n")
    assert proc.returncode == 5
    [rec] = _rows(diag / "launcher_exits.jsonl")
    assert rec["schema"] == "oo-launcher-exit-1" and rec["status"] == 5 and rec["pid"] == int(marker.read_text(encoding="utf-8")) and rec["boot_id"] is None and rec["signal"] is None
    sub = tmp_path / "clean"
    sub.mkdir()
    _, _, diag2 = _run(sub, "exit 0\n")
    assert not (diag2 / "launcher_exits.jsonl").exists()


@needs_pwsh
def test_the_reader_finds_both_records_by_pid_and_says_the_match_is_by_pid_alone(tmp_path, monkeypatch):
    proc, marker, diag = _run(tmp_path, "echo 'Fatal Python error: Segmentation fault' >&2\nexit 7\n")
    pid = int(marker.read_text(encoding="utf-8"))
    monkeypatch.setenv("OO_DATA_DIR", str(diag.parent))
    out = ee.launcher_stderr(pid, "a-boot-id-the-wrapper-could-not-know")
    assert out["lines"] == ["Fatal Python error: Segmentation fault"] and out["pid_only_match"] is True
    assert ee.launcher_exit(pid, "a-boot-id-the-wrapper-could-not-know")["status"] == 7


@needs_pwsh
def test_the_data_folder_is_asked_of_the_app_not_copied(tmp_path):
    # a python.exe beside the server that prints the folder, as the venv's would
    data = tmp_path / "asked"
    py = tmp_path / "python.exe"
    py.write_text(f"#!/usr/bin/env bash\necho '{data}'\n", encoding="utf-8")
    py.chmod(0o755)
    proc, _, _ = _run(tmp_path, "echo 'Fatal Python error: Aborted' >&2\nexit 0\n", dd=False)
    assert proc.returncode == 0, proc.stderr
    assert any(r.get("line") for r in _rows(data / "diagnostics" / ee.LAUNCHER_STDERR))


@needs_pwsh
def test_an_unwritable_record_never_stops_the_server_or_changes_its_exit_code(tmp_path):
    blocker = tmp_path / "file-not-folder"
    blocker.write_text("x", encoding="utf-8")
    proc, marker, _ = _run(tmp_path, "echo 'Fatal Python error: Aborted' >&2\nexit 4\n", dd=blocker / "nested")
    assert proc.returncode == 4 and marker.exists() and "Fatal Python error: Aborted" in proc.stderr


@needs_pwsh
def test_an_ephemeral_run_leaves_no_record(tmp_path):
    _, _, diag = _run(tmp_path, "echo 'Fatal Python error: Aborted' >&2\nexit 9\n", env={"OO_EPHEMERAL": "1"})
    assert not diag.exists()


@needs_pwsh
def test_a_server_that_cannot_be_started_leaves_no_marker_so_the_caller_starts_it_plainly(tmp_path):
    marker = tmp_path / "m"
    proc = subprocess.run([PWSH, "-NoProfile", "-File", str(PS1), "-App", str(tmp_path / "nope"), "-Marker", str(marker), "-DataDir", str(tmp_path / "d")],
                          capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert proc.returncode != 0 and not marker.exists()  # 9009 on Windows; POSIX keeps 8 bits of it. The marker is the contract.


def test_the_wrappers_list_is_the_python_fatal_headers_of_the_readers_list():
    text = PS1.read_text(encoding="utf-8")
    block = re.search(r"\$Messages = @\((.*?)\n\)", text, re.S)
    assert block
    listed = set(re.findall(r'"([^"]+)"', block.group(1)))
    assert listed == {m for m in ee.ABORT_MESSAGES if m.startswith("Fatal Python error:")}


def test_the_caller_falls_back_to_the_plain_start_and_keeps_every_earlier_step():
    text = CMD.read_text(encoding="utf-8")
    assert "launch_server.ps1" in text and "-Marker" in text
    # the plain start is still there, and is reached when the wrapper left no marker
    assert text.count('"%APP%"') >= 2 and ":plain" in text and ":stopped" in text
    for earlier in ("install.ps1", "already running", "Invoke-WebRequest", "Open Omniscience has stopped"):
        assert earlier in text


@pytest.mark.parametrize(
    ("status", "kind", "word"),
    [(-1073741819, "crashed", "ACCESS_VIOLATION"), (3221226356, "crashed", "HEAP_CORRUPTION"), (-1073740791, "crashed", "STACK_BUFFER_OVERRUN"), (-1073741510, "stopped", "CONTROL_C"), (-1073741515, "failed to start", "DLL_NOT_FOUND")],
)
def test_a_windows_exit_status_is_named(status, kind, word):
    out = ee.describe_exit({"status": status, "signal": None})
    assert out["kind"] == kind and word in out["meaning"]


@needs_pwsh
def test_every_named_windows_status_survives_the_wrappers_own_row_writer_and_is_read_back_by_name(tmp_path):
    """A server cannot exit with an NT status on Linux (exit codes are 8 bits here), so the real server run cannot be made. What can be run is
    the wrapper's own Add-Row on the signed 32-bit number .NET gives for each status in the reader's table: it must write a plain JSON
    integer (not a float or an exponent), and the reader must name it."""
    text = PS1.read_text(encoding="utf-8")
    fn = re.search(r"^function Add-Row.*?^}\n", text, re.S | re.M)
    assert fn
    out = tmp_path / "rows.jsonl"
    assert re.search(r"status = \$code", text), "the wrapper must write the exit code it got, as it is"
    for unsigned in ee._NT_STATUS_MEANING:
        signed = unsigned - 2**32 if unsigned >= 2**31 else unsigned
        script = (
            "$Utf8 = New-Object System.Text.UTF8Encoding($false)\n" + fn.group(0)
            + f"\n[int]$code = {signed}\n[void](Add-Row '{out}' ([ordered]@{{ schema = 'oo-launcher-exit-1'; pid = 7; boot_id = $null; status = $code; signal = $null }}))\n"
        )
        proc = subprocess.run([PWSH, "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
        row = json.loads(out.read_text(encoding="utf-8").splitlines()[-1])
        assert row["status"] == signed and type(row["status"]) is int
        assert re.search(rf'"status":{signed}[,}}]', out.read_text(encoding="utf-8").splitlines()[-1]), "written as a plain integer"
        named = ee.describe_exit(row)
        assert named["kind"] != "unknown" and named["status"] == signed


def test_an_ordinary_exit_status_is_still_an_ordinary_exit():
    assert ee.describe_exit({"status": 3, "signal": None})["kind"] == "exited"
    assert ee.describe_exit({"status": 1, "signal": None})["kind"] == "exited"
    assert ee.describe_exit({"status": 70000, "signal": None})["kind"] == "unknown"
