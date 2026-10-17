"""The stack systemd-coredump logged, read from its indented continuation lines, cut from the front to a named byte budget.

The fixtures follow the DOCUMENTED systemd-coredump journal format (``journalctl -o short-iso``: one header line naming the process,
then the message's remaining lines indented, with no pid on them). The reader has NOT been run against a real journal."""

from __future__ import annotations

import json

from src.monitoring import exit_evidence as ee
from tests.test_exit_evidence import _journal

_IND = " " * 64
_HEAD = "2026-10-17T03:10:01+0000 box systemd-coredump[700]: Process 1242 (python3) of user 1000 dumped core."


def _entry(pid=1242, threads=((1242, 3),), extra=()):
    lines = [_HEAD.replace("1242", str(pid))]
    lines += [_IND, _IND + "Module libxml2.so.2 from deb libxml2-2.9.14"]
    for tid, n in threads:
        lines.append(_IND + f"Stack trace of thread {tid}:")
        for i in range(n):
            lines.append(_IND + f"#{i}  0x00007f00{i:08x} xmlParseChunk (libxml2.so.2 + 0x7a1b{i})")
    lines += [_IND + "ELF object binary architecture: AMD x86-64"]
    lines += list(extra)
    return "\n".join(lines)


def test_documented_format_yields_thread_headers_and_frames_in_order():
    got = ee.coredump_stack(_entry(), 1242)
    assert got["result"] == "stack"
    assert got["lines"][0] == "Stack trace of thread 1242:"
    assert [ln.split()[0] for ln in got["lines"][1:]] == ["#0", "#1", "#2"]
    assert "frames_dropped" not in got and "bytes_dropped" not in got


def test_only_the_entry_naming_our_pid_is_read():
    text = _entry(pid=999, threads=((999, 2),)) + "\n" + _entry()
    got = ee.coredump_stack(text, 1242)
    assert got["lines"][0] == "Stack trace of thread 1242:" and len(got["lines"]) == 4
    assert ee.coredump_stack(_entry(pid=999), 1242) is None
    assert ee.coredump_stack(_entry(), None) is None
    assert ee.coredump_stack(_entry(), True) is None


def test_the_entry_ends_at_the_next_unindented_line():
    other = "2026-10-17T03:10:02+0000 box systemd[1]: started something"
    text = _entry() + "\n" + other + "\n" + _IND + "#9  0xdead not_ours (x + 0x1)"
    got = ee.coredump_stack(text, 1242)
    assert not any("not_ours" in ln for ln in got["lines"])


def test_cut_keeps_frames_from_zero_upward_and_counts_what_was_dropped():
    got = ee.coredump_stack(_entry(threads=((1242, 40), (1250, 40))), 1242)
    assert got["lines"][0] == "Stack trace of thread 1242:"
    nums = [int(ln.split()[0][1:]) for ln in got["lines"] if ln.startswith("#")]
    assert nums == list(range(len(nums))) and 0 < len(nums) < 40
    assert got["frames_dropped"] == 80 - len(nums)
    assert got["bytes_dropped"] > 0
    assert len(json.dumps(got, separators=(",", ":"))) <= ee.COREDUMP_STACK_BYTES


def test_worst_case_serialised_size_is_within_the_budget():
    got = ee.coredump_stack(_entry(threads=((1242, 500),)).replace("xmlParseChunk", "y" * 30), 1242)
    assert len(json.dumps(got, separators=(",", ":"))) <= ee.COREDUMP_STACK_BYTES
    assert got["result"] == "stack"


def test_a_line_larger_than_the_budget_is_dropped_whole_never_cut():
    text = _entry(threads=((1242, 1),)).replace("xmlParseChunk", "z" * 2000)
    got = ee.coredump_stack(text, 1242)
    assert all("zzz" not in ln for ln in got["lines"])
    assert got["frames_dropped"] == 1


def test_scrub_runs_before_the_cut(monkeypatch):
    import src.monitoring.secret_scrub as ss

    seen: list[str] = []

    def fake(text, *a, **k):
        seen.append(text)
        return text.replace("hunter2hunter2", "[scrubbed]")

    monkeypatch.setattr(ss, "scrubbed", fake)
    text = _entry(threads=((1242, 60),)).replace("xmlParseChunk", "hunter2hunter2", 1)
    got = ee.coredump_stack(text, 1242)
    assert len(seen) == 1 and "hunter2hunter2" in seen[0] and seen[0].count("#") >= 60, "the whole block is scrubbed once, before any cut"
    assert not any("hunter2hunter2" in ln for ln in got["lines"])


def test_entry_without_a_stack_says_so():
    text = _HEAD + "\n" + _IND + "Module x from deb y"
    assert ee.coredump_stack(text, 1242) == {"result": "no-stack-in-entry"}


def test_verdict_carries_the_stack_only_for_a_core_dump(monkeypatch):
    _journal(monkeypatch, _entry())
    got = ee.read_userspace_killers(1242)
    assert got["verdict"] == "core-dump" and got["stack"]["result"] == "stack"
    _journal(monkeypatch, "2026-10-17T03:00:00+0000 box earlyoom[5]: Killed process 1242 (python3) total-vm:1kB")
    got = ee.read_userspace_killers(1242)
    assert "stack" not in got
