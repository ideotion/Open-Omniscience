"""The evidence state of the open questions: present or missing with the reason, never a verdict on the answer.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json

from src.monitoring.can_answer import assess

_READ = {"vmstat": {"oom_kill": 1}, "cgroup": {"version": 2, "path": "/a", "values": {"memory.max": 5000}, "events": {"oom_kill": 0, "oom": 0, "max": 0}}}


def _full():
    return {
        "previous_session": "unclean-end",
        "oom_counters": {"between": {"machine_oom_kill": 2, "cgroup": {"oom_kill": 1, "oom": 1, "max": 0}}, "this_session_start": _READ},
        "kernel_evidence": {"verdict": "no-oom"},
        "exit_evidence": {"crash_trace": {"summary": "Fatal Python error: Aborted", "lines": ["x"]}},
        "previous_session_native_libs": {"mapped": {"files": ["libxml2.so.2"]}},
    }


def test_a_report_with_every_witness_says_present_for_each_question():
    out = assess(_full())
    assert out["q22_killed_or_stopped_on_its_limit"]["evidence"] == "present"
    assert out["native_abort_which_library"]["evidence"] == "present"
    assert "not assessed" in out["stall_lock_wait_or_cpu"]["evidence"]


def test_each_missing_witness_is_named_with_its_reason():
    r = _full()
    r["oom_counters"] = {"between": {"unknown": "no reading from the previous session's start"}, "this_session_start": {"vmstat": {}, "cgroup": {"unreadable": "absent (the file does not exist)"}}}
    r["kernel_evidence"] = {"verdict": "no-journal"}
    out = assess(r)["q22_killed_or_stopped_on_its_limit"]
    assert out["evidence"] == "missing" and set(out["missing"]) == {"kill_counters", "memory_limit", "kernel_log"}
    assert "previous session's start" in out["items"]["kill_counters"]["reason"]
    assert "absent" in out["items"]["memory_limit"]["reason"] and "no-journal" in out["items"]["kernel_log"]["reason"]


def test_a_sigkill_session_has_no_trace_and_the_reason_says_why():
    r = _full()
    r["exit_evidence"] = {"crash_trace": None}
    out = assess(r)["native_abort_which_library"]
    assert out["items"]["crash_trace"]["evidence"] == "missing" and "SIGKILL" in out["items"]["crash_trace"]["reason"]
    r["exit_evidence"] = {"crash_trace": {"withheld": True, "summary": "text withheld"}}
    assert assess(r)["native_abort_which_library"]["items"]["crash_trace"]["evidence"] == "missing"


def test_a_clean_previous_session_has_no_crash_to_trace():
    r = _full()
    r["previous_session"] = "clean"
    assert "ended cleanly" in assess(r)["native_abort_which_library"]["items"]["crash_trace"]["reason"]


def test_a_count_of_zero_is_present_but_an_unreadable_one_is_not():
    r = _full()
    r["oom_counters"]["between"] = {"machine_oom_kill": 0, "cgroup": {"unknown": "the two readings are of different cgroups"}}
    item = assess(r)["q22_killed_or_stopped_on_its_limit"]["items"]["kill_counters"]
    assert item["evidence"] == "present" and "different cgroups" in item["reason"]


def test_the_report_carries_the_block_and_the_block_never_raises(tmp_path, monkeypatch):
    from src.monitoring import forensics

    monkeypatch.setattr(forensics, "_state_path", lambda: tmp_path / "session_state.json")
    monkeypatch.setattr(forensics, "kernel_evidence", lambda: {"verdict": "not-read"})
    assert "q22_killed_or_stopped_on_its_limit" in forensics.previous_session_report()["can_answer"]
    assert "unavailable" not in json.dumps(assess({}))


def test_the_worst_case_block_is_small():
    """Every reason at its clip: the block rides ``session-forensics.json`` (no member of its own)."""
    long = "x" * 5000
    r = _full()
    r["oom_counters"] = {"between": {"unknown": long}, "this_session_start": {"cgroup": {"unreadable": long}}}
    r["kernel_evidence"] = {"verdict": "not-read"}
    r["exit_evidence"] = {"crash_trace": {"withheld": True, "summary": long}}
    r["previous_session_native_libs"] = {"unreadable": long}
    assert len(json.dumps(assess(r), separators=(",", ":"))) < 3000
