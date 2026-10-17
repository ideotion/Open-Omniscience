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
from src.monitoring import forensics
from src.monitoring import native_inflight as ni
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
    # the largest shape (WAL's re-measure of 9d970ebfc): the newest accepted line fills the whole character share, the older one is cut so
    # ``lines_cut`` sits beside a shown line, every count saturates, and ``rejected_lines`` reaches five digits from minimal rows (about
    # 20,000 of them fit in the 256 KiB tail the reader takes; the file is on disk and anything may have written it)
    fill = "p" * (ee.STDERR_SHOWN_CHARS - len("(4242,0x1f2a3b4c0) malloc: double free for ptr 0x12")) + "(4242,0x1f2a3b4c0) malloc: double free for ptr 0x12"
    assert len(fill) == ee.STDERR_SHOWN_CHARS and ee.accepted_abort_line(fill)
    big_rows = [{"pid": 5}] * 20_000
    shape = big_rows + [{"pid": 5, "boot_id": None, "at": "t", "line": "Fatal Python error: Aborted"}, {"pid": 5, "boot_id": None, "at": "t", "line": fill},
                        {"pid": 5, "boot_id": None, "at": "t", "summary": True, "kept_lines": big, "dropped_lines": big, "over_cap_lines": big}]
    path.write_text("".join(json.dumps(r) + "\n" for r in shape), encoding="utf-8")
    out = ee.launcher_stderr(5, None, None)
    assert out["lines"] == [fill] and out["lines_cut"] == 1 and out["rejected_lines"] >= 10_000, out
    worst = max(worst, _member("launcher_stderr", out))
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
    assert _stderr_worst(dd) <= 319  # the measured worst (WAL re-measured the same figure on 9d970ebfc)
    assert _died_worst() <= 80
    assert _native_worst() <= ni.REPORT_BYTES_BUDGET
    assert _census_worst(tmp_path, monkeypatch) <= hwm.CENSUS_BYTES
    assert _stack_worst() <= ee.COREDUMP_STACK_BYTES


def test_a_count_at_the_limit_is_written_as_saturated_never_as_an_exact_looking_number(dd):
    path = dd / "diagnostics" / ee.LAUNCHER_STDERR
    rows = [{"pid": 5, "boot_id": "b", "at": "t", "line": "Fatal Python error: Aborted"}]
    for kept, dropped, over, want_dropped, want_over in ((3, 10**19, 10**9, ee.COUNT_SATURATED, ee.COUNT_SATURATED), (3, 999_998, 999_999, 999_998, ee.COUNT_SATURATED)):
        path.write_text("".join(json.dumps(r) + "\n" for r in rows + [{"pid": 5, "boot_id": "b", "at": "t", "summary": True, "kept_lines": kept, "dropped_lines": dropped, "over_cap_lines": over}]), encoding="utf-8")
        out = ee.launcher_stderr(5, "b")
        assert out["dropped_lines"] == want_dropped and out["over_cap_lines"] == want_over
        assert out["lines_recorded"] == 3 and out["lines_not_found"] == 2
    path.write_text("".join(json.dumps(r) + "\n" for r in rows + [{"pid": 5, "boot_id": "b", "at": "t", "summary": True, "kept_lines": 10**9, "dropped_lines": 0, "over_cap_lines": 0}]), encoding="utf-8")
    out = ee.launcher_stderr(5, "b")
    assert out["lines_recorded"] == ee.COUNT_SATURATED and out["lines_not_found"] == ee.COUNT_SATURATED
    assert ee.COUNT_SATURATED == "999999+" and isinstance(ee.COUNT_SATURATED, str)


def test_every_died_into_phase_code_has_its_words():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    codes = {forensics._died_into_phase(c).get("reason") for c in (None, {"last_ts": t0.isoformat()}, {"phase": "x", "last_ts": t0.isoformat()},
                                                                    {"phase": "x", "phase_since": (t0 + timedelta(days=1)).isoformat(), "last_ts": t0.isoformat()})}
    assert codes == set(forensics.DIED_REASON_WORDS)
    got = forensics.render_text({"previous_session": {"previous_session": {"summary": "x"}, "how_it_ended": {"summary": "s", "died_into_phase": {"seconds_in_peaks_phase": None, "reason": "no phase start"}}}})
    assert "phase start not recorded (older build)" in got


# ---- the scan: a member cannot be added without its worst case being measured here ----

_BUILDERS = {  # member -> a function returning the worst-case serialised bytes of that member
    "launcher_stderr": lambda dd, tmp, mp: _stderr_worst(dd),
    "died_into_phase": lambda dd, tmp, mp: _died_worst(),
    "native_in_flight": lambda dd, tmp, mp: _native_worst(),
    "last_thread_census": lambda dd, tmp, mp: _census_worst(tmp, mp),
    "stack": lambda dd, tmp, mp: _stack_worst(),
}
_EXTERNAL = {"crashing_thread_kind": CRASHING_THREAD_KIND}  # written by the crash-trace code; WAL's measurement
_CAP_OF = {"COREDUMP_STACK_BYTES": "stack", "CENSUS_BYTES": "last_thread_census", "REPORT_BYTES_BUDGET": "native_in_flight"}
_NOT_A_MEMBER = {  # byte constants that are not a share of the headroom, each with why
    "_TRACE_MAX_BYTES": "how much of the trace log is read",
    "_TRACE_LINE_BYTES": "the width of one trace line",
    "_STDERR_READ_BYTES": "how much of the launcher stderr file is read",
    "RECOVERY_RATE_MIN_BYTES": "a rate threshold",
}


def test_every_headroom_member_has_a_worst_case_builder_here_and_nothing_else_does():
    assert set(forensics.HEADROOM_MEMBERS) == set(_BUILDERS) | set(_EXTERNAL), "a member was added or removed without its worst case being measured here"


def test_every_byte_cap_in_the_monitoring_modules_is_claimed_by_a_member_or_named_as_not_one():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "src" / "monitoring"
    found: set[str] = set()
    for name in ("exit_evidence.py", "forensics.py", "session_hwm.py", "native_inflight.py"):
        found |= set(re.findall(r"^(_?[A-Z][A-Z_]*BYTES[A-Z_]*) *=", (root / name).read_text(encoding="utf-8"), re.M))
    unclaimed = found - set(_CAP_OF) - set(_NOT_A_MEMBER)
    assert not unclaimed, f"byte constants no headroom member claims and no reason names: {sorted(unclaimed)}"
    assert set(_CAP_OF.values()) <= set(_BUILDERS)
    assert found >= set(_CAP_OF), "a cap this test maps no longer exists in the source"
