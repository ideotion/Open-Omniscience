"""The session-forensics byte room, measured with the real code (10-17, WAL's finding on 79a811950).

The room is 2,415 B above the 1,500,000 B diagnostics floor. Every member this lane adds is built here in its WORST case by the code that
writes it, serialised the way the report is (compact JSON, the member's key included), and summed. Nothing is typed in but the one member
this lane does not write (crashing_thread_kind, measured by WAL): a member that grows turns this red, which a pinned figure cannot do."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta

import pytest

from src.monitoring import exit_evidence as ee
from src.monitoring import forensics, native_inflight as ni
from src.monitoring import session_hwm as hwm

HEADROOM = 2415
CRASHING_THREAD_KIND = 440  # WAL's measurement; written by the crash-trace code, not by this lane


def _member(key: str, value) -> int:
    """Serialised bytes of ``"key":value`` (no braces, no separating comma), as the report writes it."""
    return len(json.dumps({key: value}, separators=(",", ":"))) - 2


@pytest.fixture
def dd(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    (tmp_path / "diagnostics").mkdir()
    return tmp_path


def _stderr_worst(dd) -> int:
    """The largest ``launcher_stderr`` member the reader can build: 19-digit counts in every field, two lines using the whole character
    share, every optional key present or the no-summary variant, whichever is larger."""
    big = 10**19 - 1
    line = "p" * 28 + "(4242,0x1f2a3b4c0) malloc: double free for ptr 0x12"
    path = dd / "diagnostics" / ee.LAUNCHER_STDERR
    worst = 0
    for with_summary in (True, False):
        rows = [{"pid": 5, "boot_id": None, "at": "t", "line": line}, {"pid": 5, "boot_id": None, "at": "t", "line": "Fatal Python error: Aborted"}]
        rows += [{"pid": 5, "boot_id": None, "at": "t", "line": f"junk {i}"} for i in range(2000)]  # rejected lines (the file tail holds about 3,000 of this size)
        if with_summary:
            rows.append({"pid": 5, "boot_id": None, "at": "t", "summary": True, "kept_lines": big, "dropped_lines": big, "over_cap_lines": big})
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        out = ee.launcher_stderr(5, None, None)
        worst = max(worst, _member("launcher_stderr", out))
    # lines sized to fill the character share exactly with two lines (60 + 60), and two of 100 (which must not both be shown)
    for width in (60, 100):
        pad = "p" * (width - len("(4242,0x1f2a3b4c0) malloc: double free for ptr 0x12"))
        both = [{"pid": 5, "boot_id": None, "at": "t", "line": pad + "(4242,0x1f2a3b4c0) malloc: double free for ptr 0x12"}] * 2
        path.write_text("".join(json.dumps(r) + "\n" for r in both), encoding="utf-8")
        worst = max(worst, _member("launcher_stderr", ee.launcher_stderr(5, None, None)))
    # a line too long to fit the character share is counted, not shown: the cut variant
    long_line = "p" * 100 + "(4242,0x1f2a3b4c0) malloc: double free for ptr 0x12"
    path.write_text(json.dumps({"pid": 5, "boot_id": None, "at": "t", "line": long_line}) + "\n", encoding="utf-8")
    worst = max(worst, _member("launcher_stderr", ee.launcher_stderr(5, None, None)))
    return worst


def _died_worst() -> int:
    t0 = datetime(1, 1, 2, tzinfo=UTC)
    cases = [
        None,
        {"last_ts": t0.isoformat()},
        {"phase": "x", "last_ts": t0.isoformat()},
        {"phase": "x", "phase_since": (t0 + timedelta(days=1)).isoformat(), "last_ts": t0.isoformat()},
        {"phase": "x", "phase_since": datetime(1, 1, 2, tzinfo=UTC).isoformat(), "last_ts": datetime(9999, 12, 30, tzinfo=UTC).isoformat()},
    ]
    return max(_member("died_into_phase", forensics._died_into_phase(c)) for c in cases)


def _native_worst() -> int:
    from tests.test_native_inflight import _rec

    r = ni.report(7, "b" * 36, _rec(slots=[(4_000_000_000, 4_000_000_000)] * 4))
    r["boot_unchecked"] = True
    return _member("native_in_flight", r)


def _census_worst(tmp_path, monkeypatch) -> int:
    for tid in range(1, 400):
        d = tmp_path / "proc" / str(tid)
        d.mkdir(parents=True)
        (d / "comm").write_text(f"name-{tid % 60:02d}-xxxxxxx\n", encoding="utf-8")
    monkeypatch.setattr(hwm, "_CENSUS_TASKS", str(tmp_path / "proc"))
    monkeypatch.setattr(threading, "enumerate", lambda: [])
    return _member("last_thread_census", hwm.thread_census())


def _stack_worst() -> int:
    from tests.test_coredump_stack import _entry

    got = ee.coredump_stack(_entry(threads=((1242, 500),)).replace("xmlParseChunk", "y" * 30), 1242)
    return _member("stack", got)


def test_the_worst_case_of_every_member_this_lane_writes_fits_the_headroom(dd, tmp_path, monkeypatch):
    sizes = {
        "launcher_stderr (per session)": _stderr_worst(dd),
        "died_into_phase": _died_worst(),
        "native_in_flight": _native_worst(),
        "last_thread_census": _census_worst(tmp_path, monkeypatch),
        "stack": _stack_worst(),
    }
    sessions = ee.STDERR_ROWS_SHOWN + 1  # the previous session's own, beside the earlier unclean ends shown
    # the census and the stack are held to their caps by construction (a cap, not a sample, is what they can be at worst)
    sizes["last_thread_census"], sizes["stack"] = max(sizes["last_thread_census"], hwm.CENSUS_BYTES), max(sizes["stack"], ee.COREDUMP_STACK_BYTES)
    total = CRASHING_THREAD_KIND + sizes["launcher_stderr (per session)"] * sessions + sum(v for k, v in sizes.items() if not k.startswith("launcher_stderr"))
    assert total <= HEADROOM, f"{total} B against {HEADROOM} B: {sizes} x {sessions} sessions"


def test_each_member_has_its_own_allowance_so_one_cannot_spend_anothers(dd, tmp_path, monkeypatch):
    assert _stderr_worst(dd) <= 290
    assert _died_worst() <= 80
    assert _native_worst() <= ni.REPORT_BYTES_BUDGET
    assert _census_worst(tmp_path, monkeypatch) <= hwm.CENSUS_BYTES
    assert _stack_worst() <= ee.COREDUMP_STACK_BYTES
