"""The native in-flight black box: what a killed process leaves, and what the next boot may claim from it."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from src.monitoring import native_inflight as ni

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _data(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ni, "_path", lambda: str(tmp_path / "diagnostics" / ni.FILE_NAME))
    ni._reset_for_tests()
    yield tmp_path
    ni._reset_for_tests()


def _rec(pid=7, boot="b" * 36, slots=None, wrote=1_700_000_000):
    raw = bytearray(ni.SIZE)
    ni._HEAD.pack_into(raw, 0, ni._MAGIC, ni._VERSION, pid, boot.encode(), wrote)
    for i, (f, e) in enumerate(slots or []):
        ni._SLOT.pack_into(raw, ni._HEAD.size + i * ni._SLOT.size, f, e)
    return bytes(raw)


def test_three_outcomes_are_distinct():
    b = "b" * 36
    a = ni.report(7, b, _rec(slots=[(0, 0)] * 4))
    n = ni.report(7, b, _rec(slots=[(0, 5), (0, 2)]))
    f = ni.report(7, b, _rec(slots=[(0, 5), (2, 3), (0, 0), (1, 1)]))
    assert a["result"] == "no-calls-recorded"
    assert n["result"] == "none-in-flight" and n["calls_entered"] == 7
    assert f["result"] == "in-flight" and f["counts"] == {"connect": 2, "duckdb": 1}
    assert a["as_of"] == "2023-11-14T22:13:20Z"


def test_stale_pid_or_boot_never_reports_counts():
    raw = _rec(slots=[(3, 3)])
    assert ni.report(8, "b" * 36, raw) == {"result": "other-session", "why": "pid differs"}
    r = ni.report(7, "c" * 36, raw)
    assert r == {"result": "other-session", "why": "boot differs"}
    assert "counts" not in r
    assert ni.report(None, "b" * 36, raw)["result"] == "other-session"
    assert ni.report(True, "b" * 36, raw)["result"] == "other-session"


def test_unknown_boot_is_flagged_not_assumed():
    r = ni.report(7, None, _rec(slots=[(1, 1)]))
    assert r["result"] == "in-flight" and r["boot_unchecked"] is True


def test_absent_and_unreadable():
    assert ni.report(7, "b", None) == {"result": "absent"}
    assert ni.report(7, "b", b"junk" * 40)["result"] == "unreadable"
    assert ni.report(7, "b", _rec()[:20])["result"] == "unreadable"
    bad = bytearray(_rec())
    bad[8] = 9
    assert ni.report(7, "b", bytes(bad))["result"] == "unreadable"


def test_worst_case_report_fits_budget():
    slots = [(4_000_000_000, 4_000_000_000)] * 4
    r = ni.report(7, "b" * 36, _rec(slots=slots))
    assert len(json.dumps(r, separators=(",", ":"))) <= ni.REPORT_BYTES_BUDGET
    r["boot_unchecked"] = True
    assert len(json.dumps(r, separators=(",", ":"))) <= ni.REPORT_BYTES_BUDGET


def test_context_manager_counts_and_does_not_swallow(_data):
    with ni.native_call("dns"), ni.native_call("dns"):
        mm = ni._STATE["map"]
        assert ni.read_record(bytes(mm[:]))["slots"][0] == (2, 2)
    assert ni.read_record(bytes(ni._STATE["map"][:]))["slots"][0] == (0, 2)
    with pytest.raises(KeyError), ni.native_call("connect"):
        raise KeyError("body")
    assert ni.read_record(bytes(ni._STATE["map"][:]))["slots"][1] == (0, 1)


def test_unknown_slot_and_unavailable_file_are_noops(_data, monkeypatch):
    with ni.native_call("nope"):
        pass
    assert ni._STATE["map"] is None
    ni._reset_for_tests()
    monkeypatch.setattr(ni, "_path", lambda: str(_data / "file" / "x" / "\0bad"))
    with ni.native_call("dns"):
        pass
    assert ni._STATE["map"] is None and ni._STATE["failed"]


_CHILD = textwrap.dedent(
    """
    import os, sys
    from src.monitoring import native_inflight as ni
    ni._path = lambda: sys.argv[1]
    mode = sys.argv[2]
    ctx = ni.native_call("duckdb"); ctx.__enter__()
    print(os.getpid(), flush=True)
    if mode == "abort":
        os.abort()
    elif mode == "kill":
        os.kill(os.getpid(), 9)
    """
)


@pytest.mark.parametrize("mode,sig", [("abort", signal.SIGABRT), ("kill", signal.SIGKILL)])
def test_file_survives_a_killed_process(tmp_path, mode, sig):
    path = tmp_path / "d" / ni.FILE_NAME
    p = subprocess.run(
        [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(_ROOT)!r})\n" + _CHILD, str(path), mode],
        capture_output=True, text=True, cwd=str(_ROOT), env={**os.environ, "PYTHONPATH": str(_ROOT)},
    )
    assert p.returncode == -sig, p.stderr
    pid = int(p.stdout.split()[0])
    raw = path.read_bytes()
    assert ni.report(pid, None, raw)["counts"] == {"duckdb": 1}
    assert ni.report(pid + 1, None, raw)["result"] == "other-session"


def test_next_process_keeps_the_previous_bytes_before_truncating(_data):
    path = Path(ni._path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_rec(pid=4242, slots=[(0, 0), (1, 1)]))
    with ni.native_call("dns"):
        pass
    assert ni.report(4242, "b" * 36)["counts"] == {"connect": 1}
    assert ni.report(os.getpid(), None, bytes(ni._STATE["map"][:]))["result"] == "none-in-flight"


def test_report_before_any_call_reads_previous_file(_data):
    path = Path(ni._path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_rec(pid=9, slots=[(2, 2)]))
    assert ni.report(9, "b" * 36)["counts"] == {"dns": 2}


def test_airplane_wraps_the_native_calls():
    src = (_ROOT / "src" / "ingest" / "airplane.py").read_text()
    assert src.count('native_call("dns")') == 1
    assert src.count('native_call("connect")') == 2


def test_forensics_carries_the_field():
    src = (_ROOT / "src" / "monitoring" / "forensics.py").read_text()
    assert 'out["native_in_flight"]' in src
