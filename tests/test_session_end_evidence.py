"""What an unclean end carries of its own session (B1, 2026-10-07).

Only the seed wrote ``previous_peaks`` into the ledger before, so a crash loop kept the evidence of its last crash and the
earlier ones read as bare ``clean: false``. Each end now carries its own session's marks, what the memory was made of at the
peak and the newest heavy snapshot's essentials, cut to a stated size with the cut named, no home path whole, and the memory
read taking no connection and no lock.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from src.monitoring import boots, path_tokens, session_hwm
from src.monitoring import session_history as sh

T0 = 1_700_000_000.0
PID = 4242


@pytest.fixture
def ledger(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OO_SESSION_LIVENESS", "0")
    sh._reset_for_tests()
    monkeypatch.setattr(sh.time, "time", lambda: T0)
    yield tmp_path / "data"
    sh._reset_for_tests()


def _hwm(rss: float, *, pid: int = PID, threads: int = 3, frame: str = "x") -> dict[str, Any]:
    return {
        "pid": pid, "rss_max_mb": rss, "rss_max_at": "2023-11-14T22:14:00Z", "avail_min_mb": 200.0,
        "avail_min_at": "2023-11-14T22:14:01Z", "swap_used_max_mb": 10.0, "swap_used_max_at": "2023-11-14T22:14:02Z",
        "phase": "collect",
        "at_peak": {"anon_mb": rss - 5, "file_mb": 5.0, "note": "n", "nested": {"skipped": 1}},
        "pressure": [{
            "why": "avail-low", "at": "2023-11-14T22:14:03Z", "avail_mb": 150, "rss_mb": rss,
            "memory": {"py_alloc_blocks": 123456},
            "guard": {"engaged": True, "last_release": {"freed_mb": 7, "rung": 2}},
            "threads": [{"name": f"t{i}", "stack": [frame], "cpu_s": 1.5 * i} for i in range(threads)],
        }],
    }


def _boot(monkeypatch, epoch: float, hwm: dict[str, Any] | None, prev_state=None):
    sh._reset_for_tests()
    monkeypatch.setattr(sh.time, "time", lambda: epoch)
    monkeypatch.setattr(session_hwm, "previous", lambda: hwm)
    return sh.record_boot(prev_state)


def _ends():
    return [r for r in sh.read_records() if r["kind"] == "end"]


def test_a_crash_loop_keeps_each_sessions_own_peaks(ledger, monkeypatch):
    sh.record_boot(None)
    for n, rss in enumerate((900.0, 1800.0, 2700.0), start=1):
        _boot(monkeypatch, T0 + n * 100, _hwm(rss), {"state": "running", "pid": PID})
    ends = _ends()
    assert [e["previous_peaks"]["rss_max_mb"] for e in ends] == [900.0, 1800.0, 2700.0]
    for e in ends:
        assert e["clean"] is False
        assert e["previous_peaks"]["rss_max_at"] == "2023-11-14T22:14:00Z"
        assert e["previous_at_peak"]["anon_mb"] == e["previous_peaks"]["rss_max_mb"] - 5
        assert "nested" not in e["previous_at_peak"], "only plain fields of the composition are kept"
        assert e["previous_pressure"]["py_alloc_blocks"] == 123456
        assert e["previous_pressure"]["release"] == {"freed_mb": 7, "rung": 2}
        assert "last_release" not in e["previous_pressure"]["guard"]


def test_another_processs_sidecar_is_no_evidence(ledger, monkeypatch):
    sh.record_boot(None)
    _boot(monkeypatch, T0 + 100, _hwm(900.0, pid=PID + 1), {"state": "running", "pid": PID})
    end = _ends()[0]
    assert "previous_peaks" not in end and "previous_pressure" not in end and "previous_at_peak" not in end


def test_a_clean_end_carries_no_crash_evidence(ledger, monkeypatch):
    sh.record_boot(None)
    _boot(monkeypatch, T0 + 100, _hwm(900.0), {"state": "clean", "ended_at": "2023-11-14T22:14:00Z", "pid": PID})
    assert "previous_peaks" not in _ends()[0]


def test_no_sidecar_is_an_absent_field_not_a_failed_boot(ledger, monkeypatch):
    sh.record_boot(None)
    rec = _boot(monkeypatch, T0 + 100, None, {"state": "running", "pid": PID})
    assert rec["previous_closed_by_this_boot"] is True
    assert "previous_peaks" not in _ends()[0]


def test_the_cut_is_named_and_the_record_stays_within_its_size(ledger, monkeypatch):
    sh.record_boot(None)
    _boot(monkeypatch, T0 + 100, _hwm(900.0, threads=3, frame="y" * 400), {"state": "running", "pid": PID})
    pressure = _ends()[0]["previous_pressure"]
    assert sh._json_size(pressure) <= sh.END_RECORD_MAX_BYTES
    assert pressure["threads_in_snapshot"] == 3
    shown = len(pressure.get("threads", []))
    assert shown + pressure.get("cut", {}).get("threads_left_out", 0) == 3
    assert all(len(t["frame"]) <= 160 for t in pressure.get("threads", []))


def test_a_cut_that_leaves_threads_out_counts_them(ledger):
    hwm = _hwm(900.0, threads=3)
    hwm["pressure"][0]["guard"]["pad"] = "p" * (sh.END_RECORD_MAX_BYTES - 200)
    got = sh._pressure_record(hwm)
    assert got is not None and sh._json_size(got) <= sh.END_RECORD_MAX_BYTES
    assert got["cut"]["threads_left_out"] == 3 and "threads" not in got
    assert got["threads_in_snapshot"] == 3


def test_the_record_survives_compaction(ledger, monkeypatch):
    sh.record_boot(None)
    _boot(monkeypatch, T0 + 100, _hwm(900.0), {"state": "running", "pid": PID})
    sh.compact_if_needed(max_lines=2)
    assert _ends()[-1]["previous_peaks"]["rss_max_mb"] == 900.0


def test_ledger_features_name_the_new_evidence():
    assert "end-peaks" in sh.LEDGER_FEATURES


def test_frames_hold_no_home_path(ledger, monkeypatch, tmp_path):
    home = tmp_path / "home" / "alice"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    frame = f"{home}/work/secret-case/venv/lib/x.py:12 in run"
    sh.record_boot(None)
    hwm = _hwm(900.0, frame=frame)
    hwm["pressure"][0]["threads"][0]["name"] = f"worker {home}/job"
    _boot(monkeypatch, T0 + 100, hwm, {"state": "running", "pid": PID})
    text = json.dumps(_ends()[0], ensure_ascii=False)
    assert "alice" not in text and str(home) not in text
    assert "<home>/…/x.py" in text


def test_tokenise_paths_forms(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "h"))
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "d"))
    app = path_tokens.Path(path_tokens.__file__).resolve().parents[2]
    assert path_tokens.tokenise_paths(f"{app}/src/monitoring/x.py") == "src/monitoring/x.py"
    assert path_tokens.tokenise_paths(f"{tmp_path}/d/a/b.db") == "<data>/…/b.db"
    assert path_tokens.tokenise_paths(f"{tmp_path}/h/Documents/c.txt") == "<home>/…/c.txt"
    assert path_tokens.tokenise_paths("/opt/other/lib/z.py") == "…/z.py"
    assert path_tokens.tokenise_paths(r"C:\Users\bob\file.py") == "…/file.py"
    assert path_tokens.tokenise_paths("no path here, a/b is relative") == "no path here, a/b is relative"


def test_the_guard_block_carries_the_release_record(monkeypatch):
    monkeypatch.setattr(session_hwm, "_release_view", lambda: {"freed_mb": 3})
    monkeypatch.setattr(session_hwm, "composition", lambda **k: {})
    monkeypatch.setattr(session_hwm, "thread_snapshot", lambda: [])
    snap = session_hwm._pressure_snapshot({"avail_mb": 1.0}, "t", {"engaged": True, "paused": 1})
    assert snap["guard"]["last_release"] == {"freed_mb": 3}
    assert "holders" in snap
    calm = session_hwm._pressure_snapshot({"avail_mb": 1.0}, "t", {"engaged": False})
    assert "guard" not in calm


def test_holders_view_opens_nothing(monkeypatch):
    import sys
    import types

    from src.database import session as dbs

    opened: list[str] = []
    monkeypatch.setattr(dbs.engine, "connect", lambda *a, **k: opened.append("connect"))
    monkeypatch.setattr(dbs.engine, "raw_connection", lambda *a, **k: opened.append("raw"))
    gate = sys.modules.get("src.database.write_gate")
    if gate is not None and hasattr(gate, "write_lock"):
        monkeypatch.setattr(gate, "write_lock", lambda *a, **k: opened.append("write_lock"))
    fake = types.SimpleNamespace(_STATE={"con": object(), "built_at": 1700000000.0})
    monkeypatch.setitem(sys.modules, "src.analytics.rollup_serve", fake)
    got = session_hwm._holders_view()
    assert opened == []
    assert got["serves"]["rollup_serve"]["connection"] is True
    assert "sqlite_cache_upper_bound_mb" not in got or "upper bound" in got["sqlite_cache_basis"]


def test_the_boots_member_reports_its_measured_size_and_cuts_oldest_first(ledger, monkeypatch):
    sh.record_boot(None)
    for n in range(1, 14):
        _boot(monkeypatch, T0 + n * 100, _hwm(100.0 * n), {"state": "running", "pid": PID})
    full = boots.diagnostics_member()
    assert full["boots_in_ledger"] == 14 and len(full["boots"]) == boots.BOOTS_KEPT
    assert full["boots_not_shown"] == 4 and "unlock timing" in full["not_in_this_build"]
    assert full["boots"][-1]["end"] is None, "the live session has no end yet"
    assert full["boots"][-2]["end"]["previous_peaks"]["rss_max_mb"] == 1300.0
    size = len(json.dumps(full, ensure_ascii=False, separators=(",", ":"), default=str).encode())
    assert size <= boots.DEFAULT_MAX_BYTES
    tight = boots.diagnostics_member(max_bytes=size // 2)
    assert tight["dropped_oldest_to_fit"] > 0
    assert tight["boots"][-1] == full["boots"][-1], "the newest is the one that stays"
    assert tight["boots_not_shown"] == 14 - len(tight["boots"])
    assert "omitted" in boots.diagnostics_member(max_bytes=10)


def test_the_boots_member_never_raises(monkeypatch):
    monkeypatch.setattr(sh, "read_records", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert "error" in boots.diagnostics_member()


def test_data_dir_env_is_isolated(ledger):
    assert os.environ["OO_DATA_DIR"].endswith("data")
