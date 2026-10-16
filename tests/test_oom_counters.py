"""The kernel's kill counters, read at each session start (question 22). Fake /proc and /sys/fs/cgroup trees; nothing real is read.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.monitoring import oom_counters as oc


def _tree(tmp: Path, *, oom_kill: int | None = 3, v2: bool = True, events: str | None = None):
    proc, cg = tmp / "proc", tmp / "cg"
    (proc / "self").mkdir(parents=True)
    if oom_kill is not None:
        (proc / "vmstat").write_text(f"nr_free_pages 5\noom_kill {oom_kill}\n")
    if v2:
        (proc / "self" / "cgroup").write_text("0::/app.slice/oo.service\n")
        d = cg / "app.slice" / "oo.service"
        d.mkdir(parents=True)
        (d / "memory.events").write_text(events or "low 0\nhigh 0\nmax 12\noom 2\noom_kill 1\noom_group_kill 0\n")
        (d / "memory.max").write_text("5153960755\n")
        (d / "memory.high").write_text("max\n")
        (d / "memory.current").write_text("1000\n")
        (d / "memory.peak").write_text("4000\n")
    else:
        (proc / "self" / "cgroup").write_text("4:memory:/docker/abc\n")
    return proc, cg


def test_a_cgroup_v2_reading_carries_the_limit_the_peak_and_the_kill_counts(tmp_path):
    proc, cg = _tree(tmp_path)
    r = oc.read(proc=proc, cgroup_root=cg)
    assert r["vmstat"] == {"oom_kill": 3}
    c = r["cgroup"]
    assert c["version"] == 2 and c["path"] == "/app.slice/oo.service"
    assert c["values"]["memory.max"] == 5153960755 and c["values"]["memory.high"] == "max" and c["values"]["memory.peak"] == 4000
    assert c["events"]["oom_kill"] == 1 and c["events"]["oom"] == 2 and c["events"]["max"] == 12


def test_an_unreadable_counter_is_named_with_its_reason_and_is_never_zero(tmp_path):
    proc, cg = _tree(tmp_path, oom_kill=None)  # no vmstat file at all
    r = oc.read(proc=proc, cgroup_root=cg)
    assert r["vmstat"]["oom_kill"] == {"unreadable": "absent (the file does not exist)"}
    d = cg / "app.slice" / "oo.service"
    (d / "memory.peak").unlink()  # older kernels have no memory.peak
    r = oc.read(proc=proc, cgroup_root=cg)
    assert r["cgroup"]["values"]["memory.peak"] == {"unreadable": "absent (the file does not exist)"}
    (d / "memory.events").write_text("low 0\n")  # a key the file does not list
    assert oc.read(proc=proc, cgroup_root=cg)["cgroup"]["events"]["oom_kill"] == {"unreadable": "absent (the key is not listed)"}


def test_a_vmstat_without_the_counter_names_the_kernel_age(tmp_path):
    proc, cg = _tree(tmp_path)
    (proc / "vmstat").write_text("nr_free_pages 5\n")
    assert "no oom_kill counter" in oc.read(proc=proc, cgroup_root=cg)["vmstat"]["oom_kill"]["unreadable"]


def test_where_there_is_no_cgroup_file_the_reading_says_so(tmp_path):
    proc, cg = _tree(tmp_path, v2=False)  # a v1 line, and no v1 tree
    r = oc.read(proc=proc, cgroup_root=cg)
    assert r["cgroup"]["version"] == 1
    assert r["cgroup"]["events"] == {"unreadable": "absent (the file does not exist)"}
    (proc / "self" / "cgroup").unlink()
    assert oc.read(proc=proc, cgroup_root=cg)["cgroup"] == {"unreadable": "absent (the file does not exist)"}


def _restart_cgroup(cg: Path) -> None:
    """A unit or container killed and restarted: the cgroup is recreated at the SAME path, with counters at zero."""
    import shutil

    d = cg / "app.slice" / "oo.service"
    files = {p.name: p.read_text() for p in d.iterdir()}
    shutil.rmtree(d)
    d.mkdir(parents=True)
    for name, text in files.items():
        (d / name).write_text(text)
    (d / "memory.events").write_text("low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\noom_group_kill 0\n")


def test_a_recreated_cgroup_at_the_same_path_is_not_counted_as_zero_kills(tmp_path):
    """MUTATION TARGET: the ``id`` comparison in ``compare``. Before and after both read 0, but they are two cgroups."""
    proc, cg = _tree(tmp_path, events="low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\noom_group_kill 0\n")
    before = oc.read(proc=proc, cgroup_root=cg)
    _restart_cgroup(cg)
    after = oc.read(proc=proc, cgroup_root=cg)
    # (a directory recreated in place can reuse an inode on some filesystems; force the case the kernel guarantees)
    after["cgroup"]["id"] = before["cgroup"]["id"] + 1
    got = oc.compare(before, after, same_boot=True)["cgroup"]
    assert "not the same instance" in got["unknown"], got
    assert "not known to share" in oc.compare(before, before, same_boot=None)["cgroup"]["unknown"]


def test_an_unparseable_counter_is_named_not_stored_as_a_number(tmp_path):
    proc, cg = _tree(tmp_path, events="low 0\nhigh 0\nmax 1\noom 2\noom_kill many\noom_group_kill 0\n")
    ev = oc.read(proc=proc, cgroup_root=cg)["cgroup"]["events"]
    assert ev["oom_kill"] == {"unreadable": "unparseable (ValueError)"} and "-1" not in json.dumps(ev)


def test_a_cgroup_v1_reading_counts_oom_kill_and_names_the_counters_it_does_not_have(tmp_path):
    proc, cg = tmp_path / "proc", tmp_path / "cg"
    (proc / "self").mkdir(parents=True)
    (proc / "vmstat").write_text("oom_kill 1\n")
    (proc / "self" / "cgroup").write_text("5:cpu,cpuacct:/x\n4:memory:/docker/abc\n")
    d = cg / "memory" / "docker" / "abc"
    d.mkdir(parents=True)
    (d / "memory.oom_control").write_text("oom_kill_disable 0\nunder_oom 0\noom_kill 2\n")
    (d / "memory.limit_in_bytes").write_text("1000\n")
    before = oc.read(proc=proc, cgroup_root=cg)
    assert before["cgroup"]["version"] == 1 and before["cgroup"]["events"]["oom_kill"] == 2
    after = json.loads(json.dumps(before))
    after["cgroup"]["events"]["oom_kill"] = 3
    got = oc.compare(before, after, same_boot=True)["cgroup"]
    assert got["oom_kill"] == 1 and "no such counter" in got["oom"]["unknown"]


def test_a_count_is_claimed_only_between_readings_of_one_boot_and_one_cgroup(tmp_path):
    proc, cg = _tree(tmp_path)
    before = oc.read(proc=proc, cgroup_root=cg)
    (proc / "vmstat").write_text("oom_kill 5\n")
    (cg / "app.slice" / "oo.service" / "memory.events").write_text("low 0\nhigh 0\nmax 12\noom 3\noom_kill 2\noom_group_kill 0\n")
    after = oc.read(proc=proc, cgroup_root=cg)
    got = oc.compare(before, after, same_boot=True)
    assert got["machine_oom_kill"] == 2 and got["cgroup"]["oom_kill"] == 1 and got["cgroup"]["oom"] == 1
    assert "unknown" in oc.compare(before, after, same_boot=False)["machine_oom_kill"]
    assert "unknown" in oc.compare(before, after, same_boot=None)["machine_oom_kill"]
    assert "DOWN" in oc.compare(after, before, same_boot=True)["machine_oom_kill"]["unknown"]
    other = json.loads(json.dumps(after))
    other["cgroup"]["path"] = "/other"
    assert "different cgroups" in oc.compare(before, other, same_boot=True)["cgroup"]["unknown"]
    assert "unknown" in oc.compare(None, after, same_boot=True)


def test_the_worst_case_reading_is_small(tmp_path):
    """The reading rides the session sentinel and the forensics member; its worst case is every counter present at full width."""
    proc, cg = _tree(tmp_path, oom_kill=2**62, events="".join(f"{k} {2**62}\n" for k in oc._V2_EVENTS))
    one = len(json.dumps(oc.read(proc=proc, cgroup_root=cg), separators=(",", ":")))
    assert one < 1500, one


def test_the_previous_sessions_report_carries_the_counters_and_the_kills_between(tmp_path, monkeypatch):
    from src.monitoring import forensics

    before = {"vmstat": {"oom_kill": 4}, "cgroup": {"version": 2, "path": "/a", "id": 7, "events": {"oom_kill": 0, "oom": 0, "max": 0}}}
    now = {"vmstat": {"oom_kill": 6}, "cgroup": {"version": 2, "path": "/a", "id": 7, "events": {"oom_kill": 1, "oom": 1, "max": 3}}}
    monkeypatch.setattr(forensics, "_OOM_AT_BOOT", now)
    monkeypatch.setattr(forensics, "_BOOT_ID_AT_BOOT", "boot-1")
    out = forensics._oom_counters_between({"oom_counters": before, "boot_id": "boot-1"})
    assert out["between"]["machine_oom_kill"] == 2 and out["between"]["cgroup"]["oom_kill"] == 1
    assert out["previous_session_start"] == before
    # a previous session of an older build left no reading: said so, not zero
    assert "unknown" in forensics._oom_counters_between({"boot_id": "boot-1"})["between"]


def test_the_forensics_report_and_the_session_sentinel_carry_the_counters(tmp_path, monkeypatch):
    """The wiring: the sentinel written at a start holds the reading, and the report built at the next start has the block even when
    there is no previous sentinel. MUTATION TARGETS: the two lines in ``forensics.py`` that add them."""
    from src.monitoring import forensics

    for name in ("_PREV_AT_BOOT", "_PREV_LOADED", "_WAL_AT_BOOT", "_PAGES_AT_BOOT", "_SESSION_STARTED_AT", "_SESSION_STARTED_MONO", "_OOM_AT_BOOT", "_BOOT_ID_AT_BOOT"):
        monkeypatch.setattr(forensics, name, getattr(forensics, name), raising=False)  # restored at teardown: the start rewrites them
    monkeypatch.setattr(forensics, "_state_path", lambda: tmp_path / "session_state.json")
    monkeypatch.setattr(forensics, "kernel_evidence", lambda: {"verdict": "not-run"})
    forensics.record_session_start()
    state = json.loads((tmp_path / "session_state.json").read_text())
    assert "vmstat" in state["oom_counters"] and "cgroup" in state["oom_counters"]
    assert "oom_counters" in forensics.previous_session_report()
