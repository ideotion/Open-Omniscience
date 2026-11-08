"""process_owner follows boot-relative ticks, not the wall clock (S2 = b, gate item 41)."""

from __future__ import annotations

import subprocess
import sys

import pytest

from src.safety import process_owner as po

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="boot ticks are Linux-only")


@pytest.fixture()
def child():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    yield p
    p.kill()
    p.wait()


def _rec(pid):
    return {"pid": pid, "started": 1.0, "host": __import__("platform").node(), "machine": po.machine_tag(), **po._boot_fields(pid)}


def test_record_carries_boot_fields():
    rec = po.owner_record()
    if "ticks" not in rec:
        pytest.skip("this sandbox hides /proc/self/ns/pid; the record degrades to the psutil fields")
    assert {"ticks", "boot_id", "pidns"} <= set(rec)


def test_wall_clock_step_does_not_kill_a_live_owner(child, monkeypatch):
    import psutil

    rec = _rec(child.pid)
    rec["started"] = psutil.Process(child.pid).create_time() + 2.0  # the wall clock moved: the legacy comparison would say dead
    assert po.record_state(rec, machine=po.machine_tag()) == "alive"


def test_changed_boot_id_is_dead(child):
    rec = _rec(child.pid)
    rec["boot_id"] = "not-this-boot"
    assert po.record_state(rec, machine=po.machine_tag()) == "dead"


def test_other_pid_namespace_is_unknown(child):
    rec = _rec(child.pid)
    rec["pidns"] += 1
    assert po.record_state(rec, machine=po.machine_tag()) == "unknown"


def test_recycled_pid_and_gone_pid_are_dead(child):
    rec = _rec(child.pid)
    rec["ticks"] += 5
    assert po.record_state(rec, machine=po.machine_tag()) == "dead"
    pid = child.pid
    rec = _rec(pid)
    child.kill()
    child.wait()
    assert po.record_state(rec, machine=po.machine_tag()) == "dead"


def test_own_record_is_unknown_and_unreadable_boot_fails_closed(monkeypatch):
    rec = po.owner_record()
    assert po.record_state(rec, machine=po.machine_tag()) == "unknown"
    monkeypatch.setattr(po, "_boot_id", lambda: None)
    assert po.record_state(rec, machine=po.machine_tag()) == "unknown"


def test_record_without_new_fields_uses_legacy_comparison(child):
    import psutil

    rec = {"pid": child.pid, "started": round(psutil.Process(child.pid).create_time(), 3), "host": __import__("platform").node(), "machine": po.machine_tag()}
    assert po.record_state(rec, machine=po.machine_tag()) == "alive"


def test_stat_parser_handles_parentheses_in_comm(tmp_path, monkeypatch):
    (tmp_path / "7").mkdir()
    (tmp_path / "7" / "stat").write_text("7 (a) b (c) S " + " ".join(["0"] * 18) + " 4200 0\n", encoding="utf-8")
    monkeypatch.setattr(po, "_PROC", str(tmp_path))
    import os

    assert po._start_ticks(7) == 4200 / os.sysconf("SC_CLK_TCK")


@pytest.mark.parametrize("path", ["src/database/corpus_lease.py", "src/analytics/rollup_marker.py", "src/backup/stream_backup.py"])
def test_callers_use_the_shared_verdict(path):
    text = __import__("pathlib").Path(path).read_text(encoding="utf-8")
    assert "process_owner" in text and "record_state(" in text


def test_boot_id_change_without_machine_tag_is_unknown(child):
    rec = _rec(child.pid)
    if "ticks" not in rec:
        pytest.skip("this sandbox hides /proc/self/ns/pid")
    rec["boot_id"] = "not-this-boot"
    rec["machine"] = None
    assert po.record_state(rec, machine=None) == "unknown"


@pytest.mark.parametrize("field,value", [("ticks", float("nan")), ("pidns", float("inf")), ("pid", 0), ("pid", -3), ("pid", 2**40)])
def test_garbled_boot_record_is_unknown_never_dead_or_raising(child, field, value):
    rec = _rec(child.pid)
    if "ticks" not in rec:
        pytest.skip("this sandbox hides /proc/self/ns/pid")
    rec[field] = value
    assert po.record_state(rec, machine=po.machine_tag()) == "unknown"
