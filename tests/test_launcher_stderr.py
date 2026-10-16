"""The launcher's stderr filter and the reader of what it recorded (10-17: the ten SIGABRTs left glibc's own line in no record).

The launcher is run for real against a fake server that writes to stderr and then aborts. What is pinned: every line still reaches the
window; only a fixed set of abort messages is recorded; everything else is counted and never stored (a passphrase on a log line included);
the count and the pid/boot ride with the record; the reader shows it beside the trace and refuses a line the filter would not have kept.
"""

from __future__ import annotations

import json
import sys
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
