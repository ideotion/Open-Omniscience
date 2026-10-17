"""A launcher record file an editor re-saved is read, and a file nothing can be read from is never reported as an empty one.

Before: the readers decoded the three record files as UTF-8 without the byte-order mark, so a file saved with a BOM lost its FIRST row without a word, and a file
saved as UTF-16 (a Windows PowerShell 5.1 redirect, Notepad's "Unicode") lost every row and read as "the launcher left nothing" (measured 17 Oct: 2 of 3 rows
found with a BOM, 0 of 3 with UTF-16, in all three files). What is pinned: a BOM (with LF or CRLF) loses no row; a file that holds lines and no row is
reported as UNREADABLE with how many lines it held, in the three readers, and rendered as such; and a clean file's block carries no new field (absent = 0, as R172)."""

from __future__ import annotations

import json

import pytest

from src.monitoring import exit_evidence as ee
from src.monitoring import forensics

PIDS = (101, 102, 103)


def _row(kind: str, pid: int) -> dict:
    at = f"2026-10-17T07:00:0{pid % 10}Z"
    if kind == "exits":
        return {"schema": "oo-launcher-exit-1", "pid": pid, "at": at, "boot_id": "-", "status": 3, "signal": None}
    if kind == "stops":
        return {"schema": "oo-launcher-stop-1", "pid": pid, "at": at, "signal": "SIGINT", "boot_id": "-"}
    return {"schema": "oo-launcher-stderr-1", "pid": pid, "at": at, "boot_id": "-", "line": "Fatal Python error: Aborted"}


def _lines(kind: str) -> list[str]:
    return [json.dumps(_row(kind, p), separators=(",", ":")) for p in PIDS]


FILES = {"exits": ee.LAUNCHER_EXITS, "stops": ee.LAUNCHER_STOPS, "stderr": ee.LAUNCHER_STDERR}
READERS = {"exits": ee.launcher_exit, "stops": ee.launcher_stop, "stderr": ee.launcher_stderr}


@pytest.fixture
def diag(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    d = tmp_path / "diagnostics"
    d.mkdir()
    return d


def _write(diag, kind: str, data: bytes) -> None:
    (diag / FILES[kind]).write_bytes(data)


@pytest.mark.parametrize("kind", ["exits", "stops", "stderr"])
@pytest.mark.parametrize("eol", ["\n", "\r\n"])
def test_a_byte_order_mark_loses_no_row(diag, kind, eol):
    _write(diag, kind, b"\xef\xbb\xbf" + (eol.join(_lines(kind)) + eol).encode())
    for pid in PIDS:
        assert READERS[kind](pid) is not None, f"the {kind} row for {pid} was lost to the byte-order mark"


@pytest.mark.parametrize("kind", ["exits", "stops", "stderr"])
def test_a_clean_file_block_carries_no_unparsed_field(diag, kind):
    _write(diag, kind, ("\r\n".join(_lines(kind)) + "\r\n").encode())
    got = READERS[kind](102)
    assert got is not None and "unparsed_lines" not in got and "unreadable" not in got


@pytest.mark.parametrize("kind", ["exits", "stops", "stderr"])
def test_a_torn_line_is_counted_not_hidden(diag, kind):
    _write(diag, kind, ("\n".join(_lines(kind) + ['{"pid": 10']) + "\n").encode())
    got = READERS[kind](102)
    assert got is not None and got["unparsed_lines"] == 1


@pytest.mark.parametrize("kind", ["exits", "stops", "stderr"])
def test_a_utf16_file_is_unreadable_not_empty(diag, kind):
    _write(diag, kind, b"\xff\xfe" + ("\r\n".join(_lines(kind)) + "\r\n").encode("utf-16-le"))
    got = READERS[kind](102)
    assert got is not None, "a file nothing could be read from was reported as 'the launcher left nothing'"
    assert got["unparsed_lines"] > 0
    if kind == "stderr":
        assert got["unreadable"] is True and got["lines_recorded"] is None
    else:
        assert got["kind"] == "unreadable" and FILES[kind] in got["unreadable_files"]
        assert got["status"] is None and got["signal"] is None


def test_both_exit_and_stop_files_unreadable_name_both_and_add_their_lines(diag):
    for kind in ("exits", "stops"):
        _write(diag, kind, b"\xff\xfe" + ("\r\n".join(_lines(kind)) + "\r\n").encode("utf-16-le"))
    got = ee.launcher_exit(102)
    assert got["kind"] == "unreadable" and sorted(got["unreadable_files"]) == sorted([ee.LAUNCHER_EXITS, ee.LAUNCHER_STOPS])
    assert got["unparsed_lines"] > 2


def test_an_unreadable_exit_file_does_not_hide_a_stop_row(diag):
    _write(diag, "exits", b"\xff\xfe" + ("\r\n".join(_lines("exits")) + "\r\n").encode("utf-16-le"))
    _write(diag, "stops", ("\n".join(_lines("stops")) + "\n").encode())
    got = ee.launcher_exit(102)
    assert got["kind"] == "stop asked"


def test_the_report_says_unreadable_not_no_record():
    block = {"launcher": ee._unreadable([ee.LAUNCHER_EXITS], 7)}
    text = "\n".join(forensics._render_exit_evidence(block))
    assert "unreadable" in text and "7 lines" in text and "no record" not in text
