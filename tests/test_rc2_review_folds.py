"""Findings of the read of the RC2 head (10-17), each pinned by a case that is red without its fix."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.monitoring import exit_evidence as ee

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def dd(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    (tmp_path / "diagnostics").mkdir()
    return tmp_path


def _put(dd: Path, name: str, rows: list[dict]) -> None:
    (dd / "diagnostics" / name).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _compact(x) -> int:
    return len(json.dumps(x, separators=(",", ":")))


def test_twenty_macos_lines_of_the_longest_kind_stay_inside_a_sessions_byte_budget(dd):
    line = "p" * 121 + "(4242,0x1f2a3b4c0) malloc: *** set a breakpoint in malloc_error_break to debug"
    assert len(line) <= ee.MAC_LINE_MAX and ee.accepted_abort_line(line)
    rows = [{"pid": 5, "boot_id": "b", "at": "t", "line": line}] * 20
    rows.append({"pid": 5, "boot_id": "b", "at": "t", "summary": True, "kept_lines": 20, "dropped_lines": 3, "over_cap_lines": 0})
    _put(dd, ee.LAUNCHER_STDERR, rows)
    out = ee.launcher_stderr(5, "b")
    assert _compact({"launcher_stderr": out}) - 2 <= 250
    assert out["lines_recorded"] == 20


def test_a_line_that_does_not_fit_is_counted_not_cut_and_an_informative_line_beats_the_breakpoint_line(dd):
    err = "python3(4242,0x1f2a3b4c0) malloc: *** error for object 0x600003a8c0a0: pointer being freed was not allocated"
    bp = "python3(4242,0x1f2a3b4c0) malloc: *** set a breakpoint in malloc_error_break to debug"
    _put(dd, ee.LAUNCHER_STDERR, [{"pid": 5, "boot_id": "b", "at": "t", "line": x} for x in (err, bp)])
    out = ee.launcher_stderr(5, "b")
    assert out["lines"] == [err] and "lines_cut" not in out
    long_ = "p" * 100 + "(4242,0x1f2a3b4c0) malloc: double free for ptr 0x12"
    _put(dd, ee.LAUNCHER_STDERR, [{"pid": 5, "boot_id": "b", "at": "t", "line": long_}])
    out = ee.launcher_stderr(5, "b")
    assert out["lines"] == [] and out["lines_cut"] == 1 and out["lines_recorded"] == 1


def test_a_launcher_exit_row_of_another_shape_is_dropped_at_entry_and_stays_small(dd):
    _put(dd, ee.LAUNCHER_EXITS, [
        {"pid": 77, "status": "jane.doe@example.org /home/jane " + "x" * 5000, "at": "/Users/jane/secret", "started_at": "jane@x.org", "signal": None},
        {"pid": 78, "status": 1, "at": "2026-10-17T01:00:00Z", "signal": "SIG /home/jane/secret jane@x.org"},
    ])
    for pid in (77, 78):
        got = ee.launcher_exit(pid)
        text = json.dumps(got)
        assert "jane" not in text and "@" not in text and "/" not in text.replace("(", "").replace("scripts/launch.sh", "")
        assert _compact(got) <= 400
    assert ee.launcher_exit(78)["signal"] is None and ee.launcher_exit(77)["status"] is None


def test_a_launcher_exit_file_is_read_from_its_tail(dd):
    path = dd / "diagnostics" / ee.LAUNCHER_EXITS
    path.write_text("x" * (ee._STDERR_READ_BYTES * 2) + "\n" + json.dumps({"pid": 9, "status": 3, "at": "2026-10-17T01:00:00Z"}) + "\n", encoding="utf-8")
    assert ee.launcher_exit(9)["status"] == 3


def test_a_record_written_before_the_session_began_is_not_its_end_when_no_boot_id_ties_them(dd):
    _put(dd, ee.LAUNCHER_EXITS, [{"pid": 4120, "boot_id": None, "status": -1073741819, "at": "2026-10-16T10:00:00Z", "started_at": "2026-10-16T09:00:00Z"}])
    assert ee.launcher_exit(4120, None, "2026-10-17T00:00:00+00:00") is None
    assert ee.launcher_exit(4120, None, "2026-10-16T09:30:00Z") is not None  # inside the session: still its own
    assert ee.launcher_exit(4120, None, None) is not None  # no start known: nothing claimed, as before
    assert ee.launcher_exit(4120, "boot-a", "2026-10-17T00:00:00Z") is None  # a boot id on one side only does not tie the row to the session
    _put(dd, ee.LAUNCHER_EXITS, [{"pid": 4120, "boot_id": "boot-a", "status": 3, "at": "2026-10-16T10:00:00Z"}])
    assert ee.launcher_exit(4120, "boot-a", "2026-10-17T00:00:00Z") is not None  # a boot id on both sides: the boot decides


def test_launcher_stderr_rows_from_before_the_session_are_skipped_by_pid_alone_but_an_early_abort_is_kept(dd):
    old = {"pid": 4120, "boot_id": None, "at": "2026-10-16T10:00:00Z", "line": "Fatal Python error: Aborted"}
    early = {"pid": 4121, "boot_id": None, "at": "2026-10-17T00:00:00Z", "line": "Fatal Python error: Aborted"}  # 30 s before the stamp
    _put(dd, ee.LAUNCHER_STDERR, [old, early])
    assert ee.launcher_stderr(4120, None, "2026-10-17T00:00:30Z") is None
    got = ee.launcher_stderr(4121, None, "2026-10-17T00:00:30Z")
    assert got and got["lines"] == ["Fatal Python error: Aborted"] and got["pid_only_match"] is True


def test_the_reason_for_no_trace_follows_the_status_when_there_is_no_signal_name():
    kill = ee._why_no_trace(ee.describe_exit({"status": 137, "signal": None}), False)
    assert "SIGKILL" in kill and "no trace" in kill
    abrt = ee._why_no_trace(ee.describe_exit({"status": 134, "signal": None}), False)
    assert "SIGABRT" in abrt and "uncaught exception" not in abrt
    nt = ee._why_no_trace(ee.describe_exit({"status": -1073741819, "signal": None}), False)
    assert "uncaught exception" not in nt and "native fault" in nt
    plain = ee._why_no_trace(ee.describe_exit({"status": 3, "signal": None}), False)
    assert "uncaught" in plain


def test_the_windows_wrapper_compares_case_sensitively():
    assert "-ccontains" in (REPO / "scripts" / "launch_server.ps1").read_text(encoding="utf-8")
