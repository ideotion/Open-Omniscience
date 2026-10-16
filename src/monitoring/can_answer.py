"""Which of the open questions a diagnostics report carries the evidence for, and which evidence is missing and why.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A bundle that is silent on a question reads the same whether the evidence was collected and showed nothing, or was never collected. This
block says which. It is a statement about EVIDENCE, never about the answer: ``present`` means the witness answered (and says nothing about
what it answered), ``missing`` names the reason it could not. Built only from the previous-session report's own fields.
"""

from __future__ import annotations

from typing import Any

PRESENT = "present"
MISSING = "missing"


def _item(present: bool, reason: str) -> dict[str, str]:
    return {"evidence": PRESENT if present else MISSING, "reason": reason}


def _count_present(block: Any) -> tuple[bool, str]:
    if isinstance(block, int) and not isinstance(block, bool):
        return True, "counted between the two readings"
    if isinstance(block, dict) and "unknown" in block:
        return False, str(block["unknown"])[:200]
    return False, "no reading"


def _kill_counters(report: dict[str, Any]) -> dict[str, str]:
    between = (report.get("oom_counters") or {}).get("between")
    if not isinstance(between, dict):
        return _item(False, "the counters block is absent from this report")
    if "unknown" in between:
        return _item(False, str(between["unknown"])[:200])
    machine_ok, machine_why = _count_present(between.get("machine_oom_kill"))
    cg = between.get("cgroup")
    cg_ok, cg_why = (False, "no cgroup block")
    if isinstance(cg, dict) and "unknown" not in cg:
        cg_ok, cg_why = _count_present(cg.get("oom_kill"))
    elif isinstance(cg, dict):
        cg_why = str(cg["unknown"])[:200]
    if machine_ok or cg_ok:
        return _item(True, f"machine: {'counted' if machine_ok else machine_why}; cgroup: {'counted' if cg_ok else cg_why}")
    return _item(False, f"machine: {machine_why}; cgroup: {cg_why}")


def _memory_limit(report: dict[str, Any]) -> dict[str, str]:
    start = (report.get("oom_counters") or {}).get("this_session_start")
    cg = start.get("cgroup") if isinstance(start, dict) else None
    values = cg.get("values") if isinstance(cg, dict) else None
    if not isinstance(values, dict):
        why = cg.get("unreadable") if isinstance(cg, dict) else "no reading at this start"
        return _item(False, f"the cgroup memory limit could not be read: {why}"[:240])
    limit = values.get("memory.max", values.get("memory.limit_in_bytes"))
    if isinstance(limit, (int, str)) and not isinstance(limit, bool):
        return _item(True, "the cgroup's memory limit was read (the word max means no limit is set on this cgroup)")
    return _item(False, "the cgroup's memory limit file could not be read")


def _kernel_log(report: dict[str, Any]) -> dict[str, str]:
    kernel = report.get("kernel_evidence")
    verdict = kernel.get("verdict") if isinstance(kernel, dict) else None
    if verdict in (None, "not-read", "no-journal", "no-journalctl", "disabled"):
        return _item(False, f"the kernel log was not read ({verdict or 'no verdict'})")
    return _item(True, "the kernel log was read")


def _crash_trace(report: dict[str, Any]) -> dict[str, str]:
    exit_seen = report.get("exit_evidence")
    if report.get("previous_session") == "clean":
        return _item(False, "the previous session ended cleanly, so there is no crash to trace")
    trace = exit_seen.get("crash_trace") if isinstance(exit_seen, dict) else None
    if not isinstance(trace, dict):
        return _item(False, "the previous session left no crash trace (a SIGKILL leaves none; nothing runs after it)")
    if trace.get("withheld"):
        return _item(False, "a crash trace exists but its text was withheld (" + str(trace.get("summary"))[:120] + ")")
    return _item(True, "a crash trace was kept for the previous session")


def _native_libs(report: dict[str, Any]) -> dict[str, str]:
    libs = report.get("previous_session_native_libs")
    if isinstance(libs, dict) and isinstance(libs.get("mapped"), dict) and "files" in libs["mapped"]:
        return _item(True, "the libraries the previous session ran on were recorded at its start")
    why = libs.get("unreadable") if isinstance(libs, dict) else None
    return _item(False, str(why or "the previous session's sentinel holds no native-library reading")[:200])


def _question(items: dict[str, dict[str, str]]) -> dict[str, Any]:
    missing = [name for name, it in items.items() if it["evidence"] == MISSING]
    return {"evidence": MISSING if missing else PRESENT, "missing": missing, "items": items}


def assess(report: dict[str, Any]) -> dict[str, Any]:
    """The evidence state of each open question, from a previous-session report. Never raises."""
    try:
        return {
            "meaning": (
                "Per question, whether the witnesses that could answer it are in this report (present) or could not be read (missing, with the "
                "reason). Present is not an answer: it says the evidence exists, not what it shows."
            ),
            "q22_killed_or_stopped_on_its_limit": _question({
                "kill_counters": _kill_counters(report),
                "memory_limit": _memory_limit(report),
                "kernel_log": _kernel_log(report),
            }),
            "native_abort_which_library": _question({
                "crash_trace": _crash_trace(report),
                "native_libraries": _native_libs(report),
            }),
            "stall_lock_wait_or_cpu": {
                "evidence": "not assessed here",
                "reason": "the per-statement CPU and lock-wait evidence is carried by the slow-query and thread-usage members, which this block does not read",
            },
        }
    except Exception as exc:  # noqa: BLE001 - a report section never raises
        return {"unavailable": f"unreadable ({type(exc).__name__})"}
