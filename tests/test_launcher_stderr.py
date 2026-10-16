"""The launcher's stderr filter and the reader of what it recorded (10-17: the ten SIGABRTs left glibc's own line in no record).

The launcher is run for real against a fake server that writes to stderr and then aborts. What is pinned: every line still reaches the
window; only a fixed set of abort messages is recorded; everything else is counted and never stored (a passphrase on a log line included);
the count and the pid/boot ride with the record; the reader shows it beside the trace and refuses a line the filter would not have kept.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.monitoring import exit_evidence as ee
from src.monitoring import session_history as sh
from tests.test_exit_evidence import _launcher_tree, _run_launcher

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the launcher is a bash script")

SERVER = """sleep 0.2
echo 'INFO request served' >&2
echo 'the passphrase hunter2-secret was typed' >&2
echo 'free(): hello hunter2-secret' >&2
echo 'free(): invalid pointer' >&2
echo 'double free or corruption (!prev)' >&2
echo 'Fatal Python error: Aborted' >&2
echo 'plain stdout line'
kill -ABRT $$
"""


def _records(root: Path) -> list[dict]:
    f = root / "data" / "diagnostics" / ee.LAUNCHER_STDERR
    return [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()] if f.exists() else []


@posix_only
def test_only_the_abort_messages_are_recorded_and_every_line_still_reaches_the_window(tmp_path):
    root, env = _launcher_tree(tmp_path, SERVER)
    proc = _run_launcher(root, env, tty=True)
    assert proc.returncode == 134, proc.stderr
    # nothing the window showed before is lost
    for line in ("INFO request served", "free(): hello hunter2-secret", "free(): invalid pointer"):
        assert line in proc.stderr
    recs = _records(root)
    lines = [r["line"] for r in recs if not r.get("summary")]
    assert lines == ["free(): invalid pointer", "double free or corruption (!prev)", "Fatal Python error: Aborted"]
    raw = (root / "data" / "diagnostics" / ee.LAUNCHER_STDERR).read_text(encoding="utf-8")
    assert "hunter2" not in raw and "INFO request" not in raw, "a line that is not an abort message is counted and dropped, never stored"
    pid = int((tmp_path / "server.pid").read_text(encoding="utf-8").strip())
    assert {r["pid"] for r in recs} == {pid} and {r["boot_id"] for r in recs} == {sh.machine_boot_id()}
    [summary] = [r for r in recs if r.get("summary")]
    assert summary["kept_lines"] == 3 and summary["dropped_lines"] == 3 and summary["over_cap_lines"] == 0


@posix_only
def test_a_run_that_printed_no_abort_message_still_leaves_a_summary_so_nothing_is_confused_with_no_filter(tmp_path):
    root, env = _launcher_tree(tmp_path, "sleep 0.2\necho 'INFO fine' >&2\nexit 3\n")
    _run_launcher(root, env)
    [summary] = _records(root)
    assert summary["summary"] is True and summary["kept_lines"] == 0 and summary["dropped_lines"] == 1


@posix_only
def test_the_record_is_capped_per_launch_and_the_overflow_is_counted(tmp_path):
    body = "sleep 0.2\nfor i in $(seq 1 30); do echo 'free(): invalid pointer' >&2; done\nexit 3\n"
    root, env = _launcher_tree(tmp_path, body)
    _run_launcher(root, env)
    recs = _records(root)
    assert sum(1 for r in recs if not r.get("summary")) == 20
    assert [r for r in recs if r.get("summary")][0]["over_cap_lines"] == 10


@posix_only
def test_without_awk_the_server_starts_exactly_as_before_and_no_record_is_made(tmp_path):
    root, env = _launcher_tree(tmp_path, "sleep 0.2\necho 'free(): invalid pointer' >&2\nexit 3\n")
    # a PATH with the fake commands and the shell's basics but no awk
    import os
    import shutil

    bindir = tmp_path / "noawk"
    bindir.mkdir()
    for name in ("bash", "cat", "date", "sleep", "seq", "wc", "tail", "mv", "rm", "mkdir", "env", "dirname", "printf", "uname", "tr", "head"):
        found = shutil.which(name)
        if found:
            (bindir / name).symlink_to(found)
    env["PATH"] = f"{tmp_path / 'bin'}{os.pathsep}{bindir}"
    proc = _run_launcher(root, env)
    assert proc.returncode == 3 and "free(): invalid pointer" in proc.stderr
    assert _records(root) == []


def _write(dd: Path, rows: list[dict]) -> None:
    (dd / "diagnostics").mkdir(parents=True, exist_ok=True)
    (dd / "diagnostics" / ee.LAUNCHER_STDERR).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture
def dd(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    return tmp_path


def test_the_reader_shows_the_message_for_its_pid_and_boot_only(dd):
    _write(dd, [
        {"pid": 5, "boot_id": "b1", "at": "t1", "line": "free(): invalid pointer"},
        {"pid": 6, "boot_id": "b1", "at": "t2", "line": "malloc(): corrupted top size"},
        {"pid": 5, "boot_id": "b0", "at": "t0", "line": "corrupted size vs. prev_size"},
        {"pid": 5, "boot_id": "b1", "summary": True, "kept_lines": 1, "dropped_lines": 40, "over_cap_lines": 0},
    ])
    out = ee.launcher_stderr(5, "b1")
    assert out == {"lines": ["free(): invalid pointer"], "lines_recorded": 1, "dropped_lines": 40}
    assert ee.launcher_stderr(7, "b1") is None


def test_a_line_the_filter_would_not_have_kept_is_never_shown(dd):
    _write(dd, [
        {"pid": 5, "boot_id": "b1", "at": "t", "line": "free(): invalid pointer"},
        {"pid": 5, "boot_id": "b1", "at": "t", "line": "free(): hello hunter2-secret"},
        {"pid": 5, "boot_id": "b1", "at": "t", "line": "free(): invalid " + "x" * 200},
    ])
    out = ee.launcher_stderr(5, "b1")
    assert out["lines"] == ["free(): invalid pointer"] and out["rejected_lines"] == 2
    assert out["no_summary"] is True and out["dropped_lines"] is None, "a launcher killed before its summary says so, not zero"


def test_the_reader_shows_the_newest_few_and_the_full_count(dd):
    _write(dd, [{"pid": 5, "boot_id": "b1", "at": f"t{i}", "line": "free(): invalid pointer"} for i in range(8)])
    out = ee.launcher_stderr(5, "b1")
    assert len(out["lines"]) == ee.STDERR_LINES_SHOWN and out["lines_recorded"] == 8


def test_an_unreadable_or_absent_file_is_none_not_an_error(dd):
    assert ee.launcher_stderr(5, "b1") is None
    (dd / "diagnostics").mkdir()
    (dd / "diagnostics" / ee.LAUNCHER_STDERR).write_bytes(b"\xff\xfe not json\n")
    assert ee.launcher_stderr(5, "b1") is None


def test_an_earlier_end_carries_the_launcher_stderr_beside_its_trace(dd):
    from tests.test_crash_loop_witnesses import _dump, _header, _session, _trace_log

    (dd / "diagnostics").mkdir(parents=True, exist_ok=True)
    recs = _session(1, pid=801, signal="SIGABRT")
    _trace_log(dd, "\n" + _header(801, 1) + "\n" + "\n".join(_dump("c", 10)) + "\n")
    boot = next(r for r in recs if r.get("kind") == "boot").get("machine_boot_id")
    _write(dd, [{"pid": 801, "boot_id": boot, "at": "t", "line": "free(): invalid pointer"}])
    row = ee.earlier_unclean_ends(None, records=recs)["sessions"][0]
    assert row["launcher_stderr"]["lines"] == ["free(): invalid pointer"]


# ---- a stem is not a message: only a line that IS a known message, whole, is stored (the coordinator's check 1, 10-17) ----

FREE_TEXT_AFTER_A_STEM = [
    "free(): invalid pointer 0x7ffd",
    "free(): invalid",
    "free(): hunter2-secret",
    "malloc(): corrupted top size and then some words",
    "double free or corruption (out) extra",
    "corrupted size vs. prev_size, passphrase=abc",
    "Fatal Python error: Aborted: the passphrase was abc",
    " free(): invalid pointer",
    "free(): invalid pointer ",
]


@posix_only
def test_a_line_that_only_starts_like_a_message_is_never_stored_by_the_launcher(tmp_path):
    body = "sleep 0.2\n" + "".join(f"printf '%s\\n' {json.dumps(line)} >&2\n" for line in FREE_TEXT_AFTER_A_STEM) + "echo 'free(): invalid pointer' >&2\nexit 3\n"
    root, env = _launcher_tree(tmp_path, body)
    _run_launcher(root, env)
    recs = _records(root)
    assert [r["line"] for r in recs if not r.get("summary")] == ["free(): invalid pointer"]
    assert [r for r in recs if r.get("summary")][0]["dropped_lines"] == len(FREE_TEXT_AFTER_A_STEM)
    raw = (root / "data" / "diagnostics" / ee.LAUNCHER_STDERR).read_text(encoding="utf-8")
    assert "hunter2" not in raw and "passphrase" not in raw


@pytest.mark.parametrize("line", FREE_TEXT_AFTER_A_STEM)
def test_the_reader_rejects_a_stem_with_a_tail_too(dd, line):
    _write(dd, [{"pid": 5, "boot_id": "b1", "at": "t", "line": line}])
    out = ee.launcher_stderr(5, "b1")
    assert out["lines"] == [] and out["rejected_lines"] == 1


def test_the_launchers_list_of_messages_and_the_readers_are_the_same_list():
    import re as _re

    src = (Path(__file__).resolve().parent.parent / "scripts" / "launch.sh").read_text(encoding="utf-8")
    block = _re.search(r"^STDERR_MESSAGES='(.*?)'\n", src, _re.S | _re.M)
    assert block, "launch.sh must define STDERR_MESSAGES"
    assert set(block.group(1).split("\n")) == set(ee.ABORT_MESSAGES)
    assert all(m.strip() == m and m and "|" not in m for m in ee.ABORT_MESSAGES), "the launcher joins them with | and compares whole lines"


# ---- the independent read's findings (10-17): the window must not go silent, the launcher must not die of the filter, one pid file per launch ----


@posix_only
def test_a_line_reaches_the_window_while_the_server_is_still_running(tmp_path):
    """An awk that reads its whole input before it prints (mawk) must not sit between the server and the window."""
    root, env = _launcher_tree(tmp_path, "echo 'INFO listening' >&2\nsleep 8\n")
    proc = subprocess.Popen(
        ["bash", str(root / "scripts" / "launch.sh")], env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        import selectors

        sel = selectors.DefaultSelector()
        sel.register(proc.stderr, selectors.EVENT_READ)
        got = ""
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline and "INFO listening" not in got:
            if sel.select(timeout=0.2):
                got += proc.stderr.readline()
        assert "INFO listening" in got, "the server is still running, so the window must already have the line"
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.communicate(timeout=30)


@posix_only
def test_a_stop_from_the_window_still_leaves_the_summary(tmp_path):
    root, env = _launcher_tree(tmp_path, "echo 'free(): invalid pointer' >&2\nexec sleep 30\n")
    proc = subprocess.Popen(
        ["bash", str(root / "scripts" / "launch.sh")], env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
    )
    try:
        count = tmp_path / "curl.count"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if count.exists() and int(count.read_text(encoding="utf-8").strip() or 0) >= 2:
                break
            time.sleep(0.05)
        time.sleep(0.3)
        os.killpg(proc.pid, signal.SIGHUP)  # closing the window HUPs the whole process group, the filter included
        proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not any(r.get("summary") for r in _records(root)):
        time.sleep(0.1)
    recs = _records(root)
    assert any(r.get("summary") for r in recs), "a stop the user asked for must still say that the filter ran"
    assert [r["line"] for r in recs if not r.get("summary")] == ["free(): invalid pointer"]


@posix_only
def test_a_record_that_cannot_be_written_starts_the_server_as_before(tmp_path):
    root, env = _launcher_tree(tmp_path, "sleep 0.2\necho 'free(): invalid pointer' >&2\nexit 3\n")
    (root / "data" / "diagnostics" / ee.LAUNCHER_STDERR).mkdir(parents=True)  # a directory where the file should be
    proc = _run_launcher(root, env)
    assert proc.returncode == 3 and "free(): invalid pointer" in proc.stderr
    assert "No such file" not in proc.stderr and "Is a directory" not in proc.stderr, "the launcher says nothing about it"


@posix_only
def test_a_backslash_in_the_data_folder_does_not_end_the_filter(tmp_path):
    root, env = _launcher_tree(tmp_path, "sleep 0.2\necho 'free(): invalid pointer' >&2\necho 'later line' >&2\nexit 3\n")
    odd = tmp_path / "my\\new data"
    env["OO_DATA_DIR"] = str(odd)
    proc = _run_launcher(root, env)
    assert "later line" in proc.stderr, "every line still reaches the window"
    lines = [json.loads(x) for x in (odd / "diagnostics" / ee.LAUNCHER_STDERR).read_text(encoding="utf-8").splitlines()]
    assert [r["line"] for r in lines if not r.get("summary")] == ["free(): invalid pointer"]


@posix_only
def test_two_launches_at_once_each_record_under_their_own_server_pid(tmp_path):
    body = "sleep 1\necho 'free(): invalid pointer' >&2\nexit 3\n"
    root_a, env_a = _launcher_tree(tmp_path / "a", body)
    root_b, env_b = _launcher_tree(tmp_path / "b", body)
    shared = tmp_path / "shared"
    for e in (env_a, env_b):
        e["OO_DATA_DIR"] = str(shared)
    procs = [
        subprocess.Popen(["bash", str(r / "scripts" / "launch.sh")], env=e, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for r, e in ((root_a, env_a), (root_b, env_b))
    ]
    for p in procs:
        p.communicate(timeout=60)
    pids = {int((t / "server.pid").read_text(encoding="utf-8").strip()) for t in (tmp_path / "a", tmp_path / "b")}
    recs = [json.loads(x) for x in (shared / "diagnostics" / ee.LAUNCHER_STDERR).read_text(encoding="utf-8").splitlines()]
    lines = [r for r in recs if not r.get("summary")]
    assert {r["pid"] for r in lines} == pids and len(lines) == 2
    assert not list((shared / "diagnostics").glob(".launcher_stderr.*.pid")), "each filter removes its own pid file"


@posix_only
def test_an_ephemeral_run_leaves_no_record_in_the_persistent_folder(tmp_path):
    root, env = _launcher_tree(tmp_path, "sleep 0.2\necho 'free(): invalid pointer' >&2\nexit 3\n")
    env["OO_EPHEMERAL"] = "1"
    _run_launcher(root, env)
    assert not (root / "data" / "diagnostics" / ee.LAUNCHER_STDERR).exists()


def test_the_pid_write_after_the_server_starts_can_never_end_the_launcher():
    src = (Path(__file__).resolve().parent.parent / "scripts" / "launch.sh").read_text(encoding="utf-8")
    line = next(ln for ln in src.splitlines() if "> \"$STDERR_PIDFILE\"; }" in ln and "SERVER" in ln)
    assert line.rstrip().endswith("|| true"), "this line runs before the launcher's traps exist, under set -e"


def test_the_counts_from_the_file_are_real_counts_not_booleans_or_negatives(dd):
    _write(dd, [
        {"pid": 5, "boot_id": "b1", "line": "free(): invalid pointer"},
        {"pid": 5, "boot_id": "b1", "summary": True, "kept_lines": True, "dropped_lines": -3, "over_cap_lines": True},
    ])
    out = ee.launcher_stderr(5, "b1")
    assert out["dropped_lines"] is None and "over_cap_lines" not in out and out["lines_recorded"] == 1


def test_a_boolean_pid_in_the_file_is_not_pid_one(dd):
    _write(dd, [{"pid": True, "boot_id": "b1", "line": "free(): invalid pointer"}])
    assert ee.launcher_stderr(1, "b1") is None


def test_the_summarys_kept_count_is_reported_and_a_gap_is_named(dd):
    _write(dd, [
        {"pid": 5, "boot_id": "b1", "line": "free(): invalid pointer"},
        {"pid": 5, "boot_id": "b1", "summary": True, "kept_lines": 4, "dropped_lines": 9, "over_cap_lines": 0},
    ])
    out = ee.launcher_stderr(5, "b1")
    assert out["lines_recorded"] == 4 and out["lines_not_found"] == 3


def test_a_match_on_the_pid_alone_says_so(dd):
    _write(dd, [{"pid": 5, "boot_id": None, "line": "free(): invalid pointer"}])
    assert ee.launcher_stderr(5, None)["pid_only_match"] is True
    _write(dd, [{"pid": 5, "boot_id": "b1", "line": "free(): invalid pointer"}])
    assert "pid_only_match" not in ee.launcher_stderr(5, "b1")


def test_a_huge_file_is_read_from_its_end(dd):
    (dd / "diagnostics").mkdir()
    filler = json.dumps({"pid": 9, "boot_id": "b1", "line": "free(): invalid pointer"}) + "\n"
    newest = json.dumps({"pid": 5, "boot_id": "b1", "line": "malloc(): corrupted top size"}) + "\n"
    (dd / "diagnostics" / ee.LAUNCHER_STDERR).write_text(filler * (ee._STDERR_READ_BYTES // len(filler) + 50) + newest, encoding="utf-8")
    assert ee.launcher_stderr(5, "b1")["lines"] == ["malloc(): corrupted top size"]


def test_only_the_newest_earlier_ends_are_looked_up_for_a_launcher_record(dd):
    from tests.test_crash_loop_witnesses import _session

    (dd / "diagnostics").mkdir(parents=True, exist_ok=True)
    recs = []
    for i in range(1, 6):
        recs += _session(i, pid=900 + i, signal="SIGABRT")
    out = ee.earlier_unclean_ends(None, records=recs)["sessions"]
    assert ["launcher_stderr" in r for r in out] == [True] * ee.STDERR_ROWS_SHOWN + [False] * (len(out) - ee.STDERR_ROWS_SHOWN)


def _age(*files: Path, seconds: int = 120) -> None:
    """Make pid files look older than the sweep's one-minute grace."""
    then = time.time() - seconds
    for f in files:
        os.utime(f, (then, then))


@posix_only
def test_a_pid_file_of_a_dead_launcher_is_swept_at_the_next_launch_and_a_live_one_is_not(tmp_path):
    root, env = _launcher_tree(tmp_path, "sleep 0.2\nexit 0\n")
    diag = root / "data" / "diagnostics"
    diag.mkdir(parents=True)
    gone = subprocess.Popen(["true"])
    gone.wait()
    alive = subprocess.Popen(["sleep", "30"])
    try:
        dead_file, live_file, odd_file = diag / f".launcher_stderr.{gone.pid}.pid", diag / f".launcher_stderr.{alive.pid}.pid", diag / ".launcher_stderr.notapid.pid"
        dead_file.write_text(f"{gone.pid}\n", encoding="utf-8")  # its server is gone too
        live_file.write_text(f"{gone.pid}\n", encoding="utf-8")
        odd_file.write_text("1\n", encoding="utf-8")
        _age(dead_file, live_file, odd_file)
        _run_launcher(root, env)
        assert not dead_file.exists(), "the launcher that wrote this one is gone: its file is swept now, not after a day"
        assert live_file.exists(), "a launcher that is still running keeps its file"
        assert odd_file.exists(), "a name that is not a pid is left to the day-old rule"
    finally:
        alive.kill()
        alive.wait()


@posix_only
def test_a_pid_file_whose_recorded_server_still_runs_is_not_swept(tmp_path):
    # A launcher killed outright can leave its server and stderr filter running; the filter reads the pid file for the server's pid.
    root, env = _launcher_tree(tmp_path, "sleep 0.2\nexit 0\n")
    diag = root / "data" / "diagnostics"
    diag.mkdir(parents=True)
    gone = subprocess.Popen(["true"])
    gone.wait()
    gone2 = subprocess.Popen(["true"])
    gone2.wait()
    server = subprocess.Popen(["sleep", "30"])
    try:
        in_use, abandoned = diag / f".launcher_stderr.{gone.pid}.pid", diag / f".launcher_stderr.{gone2.pid}.pid"
        in_use.write_text(f"{server.pid}\n", encoding="utf-8")
        abandoned.write_text(f"{gone2.pid}\n", encoding="utf-8")
        _age(in_use, abandoned)
        _run_launcher(root, env)
        assert in_use.exists(), "the launcher is gone but the server it recorded runs: the filter still needs this file"
        assert not abandoned.exists(), "neither the launcher nor its server runs: swept"
    finally:
        server.kill()
        server.wait()


@posix_only
def test_a_pid_file_touched_in_the_last_minute_is_never_swept(tmp_path):
    # The previous launch's filter reads its pid file until its END has written the summary row; that can follow the launcher's exit.
    root, env = _launcher_tree(tmp_path, "sleep 0.2\nexit 0\n")
    diag = root / "data" / "diagnostics"
    diag.mkdir(parents=True)
    gone = subprocess.Popen(["true"])
    gone.wait()
    fresh, old = diag / f".launcher_stderr.{gone.pid}.pid", diag / ".launcher_stderr.999999.pid"
    for f in (fresh, old):
        f.write_text(f"{gone.pid}\n", encoding="utf-8")
    _age(old)
    _run_launcher(root, env)
    assert fresh.exists(), "touched a moment ago: the filter that owns it may still be writing its summary"
    assert not old.exists(), "the same file two minutes old, dead launcher and dead server: swept"
