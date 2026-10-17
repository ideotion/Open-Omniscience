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
        "oom_counters": {"between": {"machine_oom_kill": 2, "cgroup": {"oom_kill": 1, "oom": 1, "max": 0}}, "previous_session_start": _READ, "this_session_start": _READ},
        "kernel_evidence": {"verdict": "no-kernel-evidence"},
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
    r["oom_counters"] = {"between": {"unknown": "no reading from the previous session's start"}, "previous_session_start": {"vmstat": {}, "cgroup": {"unreadable": "absent (the file does not exist)"}}}
    r["kernel_evidence"] = {"verdict": "no-journal"}
    out = assess(r)["q22_killed_or_stopped_on_its_limit"]
    assert out["evidence"] == "missing" and set(out["missing"]) == {"kill_counters", "memory_limit", "kernel_log"}
    assert "previous session's start" in out["items"]["kill_counters"]["reason"]
    assert "absent" in out["items"]["memory_limit"]["reason"] and "no-journal" in out["items"]["kernel_log"]["reason"]


def test_a_sigkill_session_has_no_trace_and_the_reason_says_why():
    r = _full()
    r["exit_evidence"] = {"crash_trace": None}
    out = assess(r)["native_abort_which_library"]
    assert out["items"]["crash_trace"]["evidence"] == "missing" and "no trace for the previous session" in out["items"]["crash_trace"]["reason"]
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


def test_only_the_verdicts_that_mean_a_read_happened_count_as_the_kernel_log_read():
    for verdict in ("unavailable", "not-applicable", "not-read", "disabled", "no-journal", "no-journalctl", "something-new", None):
        r = _full()
        r["kernel_evidence"] = {"verdict": verdict}
        assert assess(r)["q22_killed_or_stopped_on_its_limit"]["items"]["kernel_log"]["evidence"] == "missing", verdict
    for verdict in ("no-kernel-evidence", "kernel-lines-found", "oom-kill", "native-fatal"):
        r = _full()
        r["kernel_evidence"] = {"verdict": verdict}
        assert assess(r)["q22_killed_or_stopped_on_its_limit"]["items"]["kernel_log"]["evidence"] == "present", verdict


def test_the_memory_limit_is_the_previous_sessions_not_this_ones():
    r = _full()
    r["oom_counters"]["previous_session_start"] = {"vmstat": {}, "cgroup": {"unreadable": "absent (the file does not exist)"}}
    # this start has a readable limit, but the question is about the previous session
    assert assess(r)["q22_killed_or_stopped_on_its_limit"]["items"]["memory_limit"]["evidence"] == "missing"


def test_a_machine_only_count_is_labelled_host_wide():
    r = _full()
    r["oom_counters"]["between"]["cgroup"] = {"unknown": "no cgroup counters in one of the two readings"}
    reason = assess(r)["q22_killed_or_stopped_on_its_limit"]["items"]["kill_counters"]["reason"]
    assert "host-wide only" in reason


def test_the_missing_trace_reason_offers_no_cause_unless_the_evidence_was_read():
    r = _full()
    r["exit_evidence"] = {"crash_trace": None}
    assert "no trace for the previous session" in assess(r)["native_abort_which_library"]["items"]["crash_trace"]["reason"]
    assert "SIGKILL" not in json.dumps(assess(r)["native_abort_which_library"])
    r["previous_session"] = "unknown"
    assert "could not be looked for" in assess(r)["native_abort_which_library"]["items"]["crash_trace"]["reason"]


def test_the_three_blocks_together_stay_within_the_stated_worst_case(tmp_path):
    """The figures sent to the slot table's owner: the counters block, the native-library block and this one, each at its worst."""
    from src.monitoring import native_libs as nl
    from src.monitoring import oom_counters as oc

    big = 2**62
    reading = {
        "vmstat": {"oom_kill": big},
        "cgroup": {"version": 2, "path": "/" + "u" * oc._PATH_CLIP, "id": big,
                   "values": dict.fromkeys(oc._V2_VALUES, big), "events": dict.fromkeys(oc._V2_EVENTS, big)},
    }
    between = oc.compare(reading, reading, same_boot=True)
    counters = {"previous_session_start": reading, "this_session_start": reading, "between": between, "note": "n" * 400}
    names = [f"libxml{'x' * 60}{i}.so" for i in range(400)]
    f = tmp_path / "maps"
    f.write_text("\n".join(f"7f00-7f01 r-xp 00000000 08:01 1 /x/{n}" for n in names) + "\n", encoding="utf-8")
    libs = {"runtime": nl._runtime_versions(), "installed": dict.fromkeys(nl._DISTRIBUTIONS, "9.9.99.9"), "mapped": nl._mapped(f)}
    sizes = {k: len(json.dumps(v, separators=(",", ":"))) for k, v in (("oom_counters", counters), ("native_libs", libs))}
    assert sizes["oom_counters"] < 5000 and sizes["native_libs"] < 8000, sizes
