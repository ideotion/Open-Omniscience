"""What an unclean end carries of its own session (B1, 2026-10-07; fold 2 the same day).

Only the seed wrote ``previous_peaks`` into the ledger before, so a crash loop kept the evidence of its last crash and the
earlier ones read as bare ``clean: false``. Each end now carries its own session's marks, what the memory was made of at the
peak and the newest heavy snapshot's essentials, from a sidecar that the ledger's own session id vouches for, cut to a stated
size (as the line is written) with the cut named, no home path whole, nothing an engine said, and the memory read taking no
connection and no write gate.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from src.monitoring import boots, session_hwm
from src.monitoring import session_history as sh

T0 = 1_700_000_000.0
PID = 4242
PASS = "Qv9#end-record-key'Lm2"


@pytest.fixture
def ledger(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OO_SESSION_LIVENESS", "0")
    sh._reset_for_tests()
    session_hwm.reset_for_tests()
    monkeypatch.setattr(sh.time, "time", lambda: T0)
    yield tmp_path / "data"
    sh._reset_for_tests()
    session_hwm.reset_for_tests()


def _hwm(rss: float, sid: str | None, *, pid: int = PID, threads: int = 3, frame: str = "x", release: Any = None) -> dict[str, Any]:
    guard: dict[str, Any] = {"engaged": True, "engagements": 1}
    if release is not None:
        guard["last_release"] = release
    rec: dict[str, Any] = {
        "pid": pid, "rss_max_mb": rss, "rss_max_at": "2023-11-14T22:14:00Z", "avail_min_mb": 200.0,
        "avail_min_at": "2023-11-14T22:14:01Z", "swap_used_max_mb": 10.0, "swap_used_max_at": "2023-11-14T22:14:02Z",
        "phase": "collect",
        "at_peak": {"anon_mb": rss - 5, "file_mb": 5.0, "note": "n", "nested": {"skipped": 1}},
        "pressure": [{
            "why": "avail-low", "at": "2023-11-14T22:14:03Z", "avail_mb": 150, "rss_mb": rss,
            "memory": {"py_alloc_blocks": 123456}, "guard": guard,
            "threads": [{"name": f"t{i}", "stack": [frame], "cpu_s": 1.5 * i} for i in range(threads)],
        }],
    }
    if sid is not None:
        rec["session_id"] = sid
    return rec


def _boot(monkeypatch, epoch: float, hwm: dict[str, Any] | None, prev_state=None, why: str | None = None):
    sh._reset_for_tests()
    monkeypatch.setattr(sh.time, "time", lambda: epoch)
    monkeypatch.setattr(session_hwm, "previous_why", lambda: (hwm, None if hwm else (why or "absent")))
    return sh.record_boot(prev_state)


def _ends():
    return [r for r in sh.read_records() if r["kind"] == "end"]


def _sid() -> str:
    return sh.current_session()["session_id"]


# --------------------------------------------------------------------------- #
#  Whose evidence it is
# --------------------------------------------------------------------------- #
def test_a_crash_loop_keeps_each_sessions_own_peaks(ledger, monkeypatch):
    """MUTATION TARGET: the identity check in ``_hwm_last_seen`` (without it a sidecar of the wrong session is attached)."""
    sh.record_boot(None)
    for n, rss in enumerate((900.0, 1800.0, 2700.0), start=1):
        _boot(monkeypatch, T0 + n * 100, _hwm(rss, _sid()), {"state": "running", "pid": PID})
    ends = _ends()
    assert [e["previous_peaks"]["rss_max_mb"] for e in ends] == [900.0, 1800.0, 2700.0]
    for e in ends:
        assert e["clean"] is False and "previous_evidence_missing" not in e
        assert e["previous_peaks"]["rss_max_at"] == "2023-11-14T22:14:00Z"
        assert e["previous_at_peak"]["anon_mb"] == e["previous_peaks"]["rss_max_mb"] - 5
        assert "nested" not in e["previous_at_peak"], "only plain fields of the composition are kept"
        assert e["previous_pressure"]["py_alloc_blocks"] == 123456


def test_a_stale_sidecar_with_a_reused_process_id_is_another_sessions_and_no_evidence(ledger, monkeypatch):
    """The failure the pid check alone lets through: the system reuses process ids, a failed reset leaves the old file, and the
    new session's end would carry an EARLIER session's numbers as its own."""
    sh.record_boot(None)
    _boot(monkeypatch, T0 + 100, _hwm(900.0, "20230101T000000Z-4242"), {"state": "running", "pid": PID})
    end = _ends()[0]
    assert end["previous_evidence_missing"] == "another session"
    assert not {"previous_peaks", "previous_at_peak", "previous_pressure"} & set(end)


def test_a_sidecar_with_no_session_id_is_no_evidence(ledger, monkeypatch):
    sh.record_boot(None)
    _boot(monkeypatch, T0 + 100, _hwm(900.0, None), {"state": "running", "pid": PID})
    assert _ends()[0]["previous_evidence_missing"] == "no identity"


def test_another_processs_sidecar_is_no_evidence_for_the_seed(ledger, monkeypatch):
    """The seed (no ledger boot of the session that died) has only the sentinel's process id to go by."""
    monkeypatch.setattr(session_hwm, "previous_why", lambda: (_hwm(900.0, None, pid=PID + 1), None))
    assert sh._hwm_last_seen({"state": "running", "pid": PID}) == (None, "another session")
    assert sh._hwm_last_seen({"state": "running", "pid": PID}, None)[1] == "another session"
    assert sh._hwm_last_seen(None) == (None, "no identity"), "no sentinel state: any sidecar must not pass"
    assert sh._hwm_last_seen({"state": "running"}) == (None, "no identity")
    monkeypatch.setattr(session_hwm, "previous_why", lambda: (_hwm(900.0, None, pid=PID), None))
    got, why = sh._hwm_last_seen({"state": "running", "pid": PID})
    assert why is None and got["rss_max_mb"] == 900.0


def test_a_clean_end_carries_no_crash_evidence(ledger, monkeypatch):
    sh.record_boot(None)
    _boot(monkeypatch, T0 + 100, _hwm(900.0, _sid()), {"state": "clean", "ended_at": "2023-11-14T22:14:00Z", "pid": PID})
    end = _ends()[0]
    assert "previous_peaks" not in end and "previous_evidence_missing" not in end


@pytest.mark.parametrize("why", ["absent", "unreadable"])
def test_no_sidecar_is_an_end_that_says_why(ledger, monkeypatch, why):
    sh.record_boot(None)
    rec = _boot(monkeypatch, T0 + 100, None, {"state": "running", "pid": PID}, why=why)
    assert rec["previous_closed_by_this_boot"] is True
    assert _ends()[0]["previous_evidence_missing"] == why


def test_the_real_sidecar_round_trip_in_either_order_of_boot(ledger, monkeypatch):
    """No stand-ins: the ledger boots, the sidecar is captured, a reading is taken, the process 'dies', the next boot reads it.
    Both orders of the two boot calls (ledger first, sidecar first) leave the sidecar with the ledger's id."""
    monkeypatch.setattr(session_hwm, "_readings", lambda: {"rss_mb": 1234.0, "avail_mb": 321.0, "total_mb": 4000.0})
    monkeypatch.setattr(session_hwm, "composition", lambda walk_heap=False: {})
    sids: list[str] = []
    for n, ledger_first in enumerate((True, False)):
        monkeypatch.setattr(sh.time, "time", lambda n=n: T0 + 1000.0 * n)  # a session id is minted from the clock and the pid
        sh._reset_for_tests()
        session_hwm.reset_for_tests()
        if ledger_first:
            sh.record_boot(None)
            session_hwm.capture_previous()
        else:
            session_hwm.capture_previous()
            sh.record_boot(None)
        sid = _sid()
        assert sid not in sids, "each iteration is a session of its own (a frozen clock and one pid mint one id)"
        sids.append(sid)
        assert session_hwm._read()["session_id"] == sid, f"ledger_first={ledger_first}"
        session_hwm.observe()
        # the process dies: nothing is reset by a clean path; the next process boots
        sh._reset_for_tests()
        session_hwm.reset_for_tests()
        sh.record_boot({"state": "running", "pid": os.getpid()})
        ends = [e for e in _ends() if e["session_id"] == sid]
        assert len(ends) == 1, "this iteration's own end, not an earlier one's"
        assert ends[0]["previous_peaks"]["rss_max_mb"] == 1234.0 and "previous_evidence_missing" not in ends[0]


@pytest.mark.parametrize("content, why", [(b"\xff\xfe not json", "unreadable"), (b"[1, 2]", "unreadable"), (None, "absent")])
def test_a_damaged_sidecar_file_is_read_as_unreadable_and_a_missing_one_as_absent(ledger, content, why):
    sh.record_boot(None)
    path = session_hwm._path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if content is None:
        path.unlink(missing_ok=True)
    else:
        path.write_bytes(content)
    session_hwm.reset_for_tests()
    sh._reset_for_tests()
    sh.record_boot({"state": "running", "pid": PID})
    assert _ends()[-1]["previous_evidence_missing"] == why


# --------------------------------------------------------------------------- #
#  The cuts
# --------------------------------------------------------------------------- #
def test_the_cut_is_named_and_the_record_stays_within_its_size_as_written(ledger, monkeypatch):
    sh.record_boot(None)
    _boot(monkeypatch, T0 + 100, _hwm(900.0, _sid(), threads=3, frame="y" * 400), {"state": "running", "pid": PID})
    pressure = _ends()[0]["previous_pressure"]
    assert sh._json_size(pressure) <= sh.END_RECORD_MAX_BYTES
    assert pressure["threads_in_snapshot"] == 3 and pressure["cut"]["texts_cut"] == 3
    assert all(t["frame"].endswith(sh._CUT_MARK) and len(t["frame"]) == sh._FRAME_MAX + len(sh._CUT_MARK) for t in pressure["threads"])


def test_a_name_that_is_cut_ends_in_the_mark():
    hwm = _hwm(900.0, "s")
    hwm["pressure"][0]["threads"][0]["name"] = "n" * 200
    got = sh._pressure_record(hwm)
    assert got["threads"][0]["name"] == "n" * sh._THREAD_NAME_MAX + sh._CUT_MARK


def test_a_cut_that_leaves_threads_out_counts_them_and_the_size_includes_the_count():
    hwm = _hwm(900.0, "s", threads=3)
    hwm["pressure"][0]["guard"]["pad"] = "p" * (sh.END_RECORD_MAX_BYTES - 200)
    got = sh._pressure_record(hwm)
    assert got is not None and sh._json_size(got) <= sh.END_RECORD_MAX_BYTES
    assert got["cut"]["threads_left_out"] >= 1 and got["threads_in_snapshot"] == 3
    shown = len(got.get("threads", []))
    assert shown + got["cut"]["threads_left_out"] == 3


def test_texts_cut_counts_texts_and_only_those_of_the_threads_that_stayed():
    """MUTATION TARGET: the count (it counted threads, and was not taken again after the size loop left threads out)."""
    hwm = _hwm(900.0, "s", threads=3, frame="f" * 300)
    for t in hwm["pressure"][0]["threads"]:
        t["name"] = "n" * 200
    got = sh._pressure_record(hwm)
    assert got["cut"]["texts_cut"] == 6, "a name and a frame in each of three threads"
    hwm["pressure"][0]["guard"]["pad"] = "p" * (sh.END_RECORD_MAX_BYTES - 700)
    got = sh._pressure_record(hwm)
    kept = got.get("threads", [])
    assert got["cut"]["threads_left_out"] >= 1 and len(kept) < 3
    assert got["cut"].get("texts_cut", 0) == 2 * len(kept), "the threads left out take their cut texts with them"


@pytest.mark.parametrize("pad", range(0, 2100, 37))
def test_the_limit_holds_at_every_size_of_the_padding(pad):
    """The cut's own text is counted: no padding size lets the record, with its ``cut`` written, pass the limit."""
    hwm = _hwm(900.0, "s", threads=3, frame="é" * 150)
    hwm["pressure"][0]["guard"]["pad"] = "p" * pad
    got = sh._pressure_record(hwm)
    assert got is not None and sh._json_size(got) <= sh.END_RECORD_MAX_BYTES, pad


@pytest.mark.parametrize("fields", [5, 40, 120, 400])
def test_the_at_peak_record_counts_its_own_cut(fields):
    hwm = {"at_peak": {f"field_{i:03d}": 123456.789 + i for i in range(fields)}}
    got = sh._at_peak_record(hwm)
    assert sh._json_size(got) <= sh.END_RECORD_MAX_BYTES
    if "cut" in got:
        assert got["cut"]["fields_left_out"] + len([k for k in got if k != "cut"]) == fields


def test_the_size_is_measured_as_the_line_is_written():
    """A letter outside ASCII is six bytes in the ledger line (ASCII-escaped JSON): measured as UTF-8 it would be two."""
    assert sh._json_size({"a": "é"}) == len(json.dumps({"a": "é"}, separators=(",", ":")).encode("ascii")) > len('{"a":"é"}'.encode())


def test_the_record_survives_compaction(ledger, monkeypatch):
    sh.record_boot(None)
    _boot(monkeypatch, T0 + 100, _hwm(900.0, _sid()), {"state": "running", "pid": PID})
    sh.compact_if_needed(max_lines=2)
    assert _ends()[-1]["previous_peaks"]["rss_max_mb"] == 900.0


def test_ledger_features_name_the_new_evidence():
    assert "end-peaks" in sh.LEDGER_FEATURES


# --------------------------------------------------------------------------- #
#  Nothing an engine said, at each layer
# --------------------------------------------------------------------------- #
_HOSTILE = (
    f"OperationalError: near PRAGMA key = '{PASS}' in /home/alice/secret-case/store.db: "
    "'utf-8' codec can't decode byte 0xff in position 3"
)


def test_a_failing_release_step_records_the_class_and_none_of_its_words(monkeypatch):
    """LAYER 1 (``src/scheduler/release.py``): each of the six sites."""
    from src.database import session as dbs
    from src.scheduler import release

    class _Boom(Exception):
        pass

    def boom(*a, **k):
        raise _Boom(_HOSTILE)

    monkeypatch.setattr(dbs.engine, "raw_connection", boom)
    monkeypatch.setattr(dbs.engine.pool, "dispose", boom)
    shrink, dispose = release._shrink_sqlite(), release._dispose_idle_pool()
    assert shrink["error"] == "_Boom" and dispose["error"] == "_Boom"

    class _Serve:
        class _Lock:
            def acquire(self, blocking=True):
                raise _Boom(_HOSTILE)

            def release(self):  # pragma: no cover
                pass

        _LOCK = _Lock()
        _STATE: dict = {}

    import sys
    import types

    monkeypatch.setitem(sys.modules, "src.analytics.rollup_serve", types.SimpleNamespace(_LOCK=_Serve._LOCK, _STATE={}))
    assert release._close_serves()["errors"] == {"rollup_serve": "_Boom"}
    import gc

    monkeypatch.setattr(gc, "collect", boom)
    assert release._collect_garbage(False)["error"] == "_Boom"
    import ctypes

    monkeypatch.setattr(ctypes, "CDLL", boom)
    assert release._malloc_trim()["error"] == "_Boom"
    monkeypatch.setattr(release, "_dispose_idle_pool", boom)
    monkeypatch.setattr(release, "_shrink_sqlite", lambda: {"step": "shrink_memory", "ok": True})
    monkeypatch.setattr(release, "_close_serves", lambda **k: {"step": "close_serves", "ok": True})
    monkeypatch.setattr(release, "_malloc_trim", lambda: {"step": "malloc_trim", "ok": True})
    rec = release.release_residents()
    assert rec["steps"][0] == {"step": "unknown", "ok": False, "error": "_Boom", "freed_mb": rec["steps"][0]["freed_mb"]}
    for out in (shrink, dispose, rec):
        text = json.dumps(out, default=str)
        assert PASS not in text and "alice" not in text and "codec" not in text


_OLD_RECORD = {
    "rss_mb_before": 900.0, "rss_mb_after": 700.0, "freed_mb": 200.0, "process_swapping": False, "duration_ms": 12.5,
    "engagement": 1, "note": "a key the allow-list does not name", "path": "/home/alice/x",
    "steps": [
        {"step": "shrink_memory", "ok": False, "error": _HOSTILE, "freed_mb": 1.5, "stray": "/home/alice/y"},
        {"step": "close_serves", "ok": False, "closed": ["rollup_serve"], "busy": ["map_serve"], "errors": {"map_serve": _HOSTILE}},
        {"step": "dispose_idle_pool", "ok": True, "closed": 3, "freed_mb": 40.0},
        {"step": "gc_collect", "skipped": "this process has pages in swap"},
        {"step": "malloc_trim", "ok": True, "collected": 7, "freed_mb": None},
    ],
}


def _assert_clean(value: Any) -> None:
    text = json.dumps(value, default=str)
    assert PASS not in text and "alice" not in text and "codec" not in text and "PRAGMA" not in text, text


def test_the_release_view_rebuilds_the_record_from_the_allow_list():
    """LAYER 2 (``release_view.allow_listed``, which ``session_hwm._release_view`` calls)."""
    from src.monitoring.release_view import allow_listed

    got = allow_listed(_OLD_RECORD)
    _assert_clean(got)
    assert got["rss_mb_before"] == 900.0 and got["process_swapping"] is False and "note" not in got and "path" not in got
    assert got["steps"][0] == {"step": "shrink_memory", "ok": False, "error": "OperationalError", "freed_mb": 1.5}
    assert got["steps"][1]["errors"] == {"map_serve": "OperationalError"} and got["steps"][1]["busy"] == ["map_serve"]
    assert got["steps"][2]["closed"] == 3 and got["steps"][3]["skipped"] == "this process has pages in swap"
    assert got["steps"][4]["freed_mb"] is None, "absent never becomes 0"
    assert allow_listed("not a record") is None and allow_listed(None) is None
    assert allow_listed({"steps": [{"step": "x" * 200, "error": 5}]})["steps"][0] == {"step": "(unnamed)", "error": "(error)"}


def test_the_snapshots_guard_block_carries_only_the_allow_listed_record_of_this_engagement(monkeypatch):
    """LAYER 2, through ``_pressure_snapshot``: the guard's own record, hostile, and the engagement stamp."""
    from src.scheduler import memguard

    monkeypatch.setattr(session_hwm, "composition", lambda **k: {})
    monkeypatch.setattr(session_hwm, "thread_snapshot", lambda: [])
    monkeypatch.setattr(memguard.memory_guard, "_last_release", dict(_OLD_RECORD))
    snap = session_hwm._pressure_snapshot({"avail_mb": 1.0}, "t", {"engaged": True, "engagements": 1})
    _assert_clean(snap)
    assert snap["guard"]["last_release"]["steps"][0]["error"] == "OperationalError"
    older = session_hwm._pressure_snapshot({"avail_mb": 1.0}, "t", {"engaged": True, "engagements": 2})
    assert "last_release" not in older["guard"], "the first engagement's ladder is not the second one's"
    calm = session_hwm._pressure_snapshot({"avail_mb": 1.0}, "t", {"engaged": False, "engagements": 1})
    assert "guard" not in calm


def test_the_end_record_rebuilds_the_release_record_from_the_allow_list_itself():
    """LAYER 3 (``session_history._pressure_record``): fed a sidecar written by a build with no allow-list at all."""
    hwm = _hwm(900.0, "s", release=_OLD_RECORD)
    got = sh._pressure_record(hwm)
    _assert_clean(got)
    assert got["release"]["steps"][0]["error"] == "OperationalError" and "note" not in got["release"]


def test_a_hostile_release_error_reaches_neither_the_ledger_nor_boots_json(ledger, monkeypatch):
    sh.record_boot(None)
    _boot(monkeypatch, T0 + 100, _hwm(900.0, _sid(), release=_OLD_RECORD), {"state": "running", "pid": PID})
    _assert_clean(Path(sh.ledger_path()).read_text(encoding="utf-8"))
    _assert_clean(boots.diagnostics_member())


# --------------------------------------------------------------------------- #
#  Paths in a frame, the memory read, the build on the boot record
# --------------------------------------------------------------------------- #
def test_frames_hold_no_home_path(ledger, monkeypatch, tmp_path):
    home = tmp_path / "home" / "alice"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    frame = f"{home}/work/secret-case/venv/lib/x.py:12 in run"
    sh.record_boot(None)
    hwm = _hwm(900.0, _sid(), frame=frame)
    hwm["pressure"][0]["threads"][0]["name"] = f"worker {home}/job"
    _boot(monkeypatch, T0 + 100, hwm, {"state": "running", "pid": PID})
    text = json.dumps(_ends()[0], ensure_ascii=False)
    assert "alice" not in text and str(home) not in text and "<home>/…/x.py" in text


def test_holders_view_and_the_whole_snapshot_open_nothing_and_take_no_gate(monkeypatch):
    """The spies are on what exists: ``writer.write_lock``, the gate's ``acquire`` (``src/database/writer.py``) and the engine's
    connection calls, and the whole ``_pressure_snapshot`` runs under them with the REAL release view and a guard that holds a
    record of this engagement."""
    import sys
    import types

    from src.database import session as dbs
    from src.database import writer
    from src.scheduler import memguard

    opened: list[str] = []
    for owner, name in ((dbs.engine, "connect"), (dbs.engine, "raw_connection"), (dbs.engine.pool, "connect"), (writer, "write_lock")):
        monkeypatch.setattr(owner, name, lambda *a, _n=name, **k: opened.append(_n))
    monkeypatch.setattr(writer.write_gate, "acquire", lambda *a, **k: opened.append("acquire"))
    monkeypatch.setitem(sys.modules, "src.analytics.rollup_serve", types.SimpleNamespace(_STATE={"con": object(), "built_at": 1700000000.0}))
    monkeypatch.setattr(memguard.memory_guard, "_last_release", dict(_OLD_RECORD))
    snap = session_hwm._pressure_snapshot({"avail_mb": 1.0, "total_mb": 4000.0}, "t", {"engaged": True, "engagements": 1})
    assert opened == [], "the snapshot of a machine short of memory opened a connection or took the gate"
    assert snap["guard"]["last_release"]["freed_mb"] == 200.0
    assert snap["holders"]["serves"]["rollup_serve"]["connection"] is True


def test_the_boot_records_build_keys_are_pinned(ledger, monkeypatch):
    from src.monitoring import build_id

    build_id._reset_for_tests()
    rec = sh.record_boot(None)
    assert set(rec["build"]) == {"commit", "source_fingerprint", "files", "bytes", "schema_head", "took_ms"}
    assert rec["build"]["files"] > 100 and len(rec["build"]["source_fingerprint"]) == 16


def test_a_build_that_cannot_be_read_is_an_error_class_like_its_siblings(ledger, monkeypatch):
    from src.monitoring import build_id

    def boom():
        raise OSError(f"/home/alice/{PASS}")

    monkeypatch.setattr(build_id, "build_identity", boom)
    rec = sh.record_boot(None)
    assert rec["build"] == {"error": "OSError"}


# --------------------------------------------------------------------------- #
#  boots.json
# --------------------------------------------------------------------------- #
def _crash_loop(monkeypatch, n: int, **kw):
    sh.record_boot(None)
    for k in range(1, n + 1):
        _boot(monkeypatch, T0 + k * 100, _hwm(100.0 * k, _sid(), **kw), {"state": "running", "pid": PID})


def test_the_boots_member_never_exceeds_its_budget_with_realistic_rows(ledger, monkeypatch):
    _crash_loop(monkeypatch, 14, release=_OLD_RECORD, frame="é" * 150)
    full = boots.diagnostics_member()
    assert full["boots_in_ledger"] == 15 and len(full["boots"]) == boots.BOOTS_KEPT
    assert full["boots"][-1]["end"] is None, "the live session has no end yet"
    assert full["boots"][-2]["end"]["previous_peaks"]["rss_max_mb"] == 1400.0
    assert "unlock timing" in full["not_in_this_build"]
    assert boots._size(full) <= boots.DEFAULT_MAX_BYTES
    for budget in range(1500, 30 * 1024, 997):
        member = boots.diagnostics_member(max_bytes=budget)
        if "omitted" in member:
            assert member["needs_at_least_bytes"] > budget
            continue
        assert boots._size(member) <= budget, budget
        assert member["boots_not_shown"] == 15 - len(member["boots"])
        assert member["boots"] == full["boots"][len(full["boots"]) - len(member["boots"]):], "the newest stay"


def test_the_boots_member_says_when_the_budget_cannot_hold_its_fixed_part(ledger, monkeypatch):
    _crash_loop(monkeypatch, 2)
    got = boots.diagnostics_member(max_bytes=10)
    assert "omitted" in got and got["needs_at_least_bytes"] > 10


def test_the_boots_member_never_raises_and_says_only_the_class_of_a_damaged_ledger(ledger, monkeypatch):
    def damaged():
        raise UnicodeDecodeError("utf-8", f"/home/alice/{PASS}".encode(), 0, 1, "invalid start byte")

    monkeypatch.setattr(sh, "read_records", damaged)
    got = boots.diagnostics_member()
    text = json.dumps(got, default=str)
    assert PASS not in text and "alice" not in text and "/home" not in text, text
    assert got["error"].startswith("UnicodeDecodeError") and len(got["error"]) <= boots._ERROR_TEXT_MAX


def test_the_boots_member_scrubs_and_tokenises_an_ordinary_error(ledger, monkeypatch, tmp_path):
    from src.database import connect

    monkeypatch.setattr(connect, "_passphrase", PASS)
    home = tmp_path / "home" / "alice"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(sh, "read_records", lambda: (_ for _ in ()).throw(OSError(f"cannot read {home}/data/ledger.jsonl with {PASS}")))
    got = boots.diagnostics_member()
    assert PASS not in got["error"] and "alice" not in got["error"] and "ledger.jsonl" in got["error"]


def test_data_dir_env_is_isolated(ledger):
    assert os.environ["OO_DATA_DIR"].endswith("data")


# --------------------------------------------------------------------------- #
#  forensics copies the previous session's marks only when they are that session's, through the allow-list
# --------------------------------------------------------------------------- #
def _forensics_with(monkeypatch, marks, ledger_says="s-prev"):
    from src.monitoring import forensics

    monkeypatch.setattr(session_hwm, "previous_why", lambda: (marks, None if marks else "absent"))
    monkeypatch.setattr(sh, "previous_session_id", lambda: ledger_says)
    return forensics._previous_peaks()


@pytest.mark.parametrize("ident, why", [("s-other", "another session"), (None, "no identity")])
def test_forensics_takes_no_marks_of_another_session_or_of_none(monkeypatch, ident, why):
    """MUTATION TARGET: the identity match in ``forensics._previous_peaks``."""
    got = _forensics_with(monkeypatch, _hwm(900.0, ident))
    assert got["available"] is False and why in got["reason"] and "rss_max_mb" not in got


def test_forensics_takes_no_marks_when_the_ledger_names_no_previous_session(monkeypatch):
    got = _forensics_with(monkeypatch, _hwm(900.0, "s-prev"), ledger_says=None)
    assert got["available"] is False


def test_forensics_copies_a_release_record_only_through_the_allow_list(monkeypatch):
    """MUTATION TARGET: ``release_view.scrub_marks`` (the marks were copied whole, a ladder's error text included)."""
    hwm = _hwm(900.0, "s-prev", release=_OLD_RECORD)
    hwm["pressure_light"] = [{"at": "t", "guard": {"engaged": True, "last_release": _OLD_RECORD}}]
    got = _forensics_with(monkeypatch, hwm)
    assert got["available"] is True and got["rss_max_mb"] == 900.0
    _assert_clean(got["pressure"])
    _assert_clean(got["pressure_light"])
    assert got["pressure"][0]["guard"]["last_release"]["steps"][0]["error"] == "OperationalError"


def test_the_session_hwm_member_says_only_the_class_of_a_failure(monkeypatch):
    monkeypatch.setattr(session_hwm, "previous", lambda: (_ for _ in ()).throw(RuntimeError(f"/home/alice/{PASS}")))
    assert session_hwm.diagnostics_member(50_000) == {"error": "RuntimeError"}
