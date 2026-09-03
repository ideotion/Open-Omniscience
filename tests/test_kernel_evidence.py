"""The host kernel log must name the crash kind — and must never invent one (S0.3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Four field sessions ended uncleanly and the app could not say how, because an OOM
kill, a host reset, a SIGHUP from a closed terminal and a native fault all leave the
identical app-side record. The kernel is the only witness that distinguishes them.

The vocabulary is what these guard. "We looked and found nothing" and "we could not
look" are opposite facts, and reporting either as the other is the failure mode: one
would hide a real OOM, the other would raise a false alarm about a machine that is
fine. So every unavailability has its OWN verdict with its own reason.
"""

from __future__ import annotations

import subprocess

import pytest

from src.monitoring import forensics, kernel_log

_OOM = (
    "Sep 02 09:37:20 box kernel: Out of memory: Killed process 12345 "
    "(open-omniscien) total-vm:7000000kB, anon-rss:6700000kB"
)
_SEGV = "Sep 02 09:37:20 box kernel: open-omniscien[12345]: segfault at 0 ip 00007f rsp 00007f error 4"
_NOISE = "Sep 02 09:00:00 box kernel: Linux version 6.1.0\nSep 02 09:00:01 box kernel: ACPI: Early table"


def _fake_run(mapping):
    """Replace the subprocess with canned (rc, text) per command shape."""

    def _run(cmd, **kw):
        key = "prev" if "-1" in cmd else "cur"
        rc, text = mapping.get(key, (0, ""))
        if isinstance(rc, Exception):
            raise rc
        return subprocess.CompletedProcess(cmd, rc, text, "")

    return _run


@pytest.fixture(autouse=True)
def _have_journalctl(monkeypatch):
    monkeypatch.setattr(kernel_log.shutil, "which", lambda _n: "/usr/bin/journalctl")
    monkeypatch.delenv("OO_NO_KERNEL_LOG", raising=False)


def test_an_oom_line_is_classified_and_quoted_verbatim(monkeypatch):
    monkeypatch.setattr(
        kernel_log.subprocess, "run", _fake_run({"cur": (0, _NOISE + "\n" + _OOM)})
    )
    got = kernel_log.read_kernel_evidence(12345)
    assert got["verdict"] == "oom-kill"
    assert any("Killed process 12345" in ln for ln in got["lines"])


def test_a_segfault_is_a_native_fatal_not_an_oom(monkeypatch):
    monkeypatch.setattr(kernel_log.subprocess, "run", _fake_run({"cur": (0, _SEGV)}))
    assert kernel_log.read_kernel_evidence(12345)["verdict"] == "native-fatal"


def test_the_truncated_process_name_is_what_matches(monkeypatch):
    """The kernel truncates comm to 15 chars, so the full name finds nothing on every
    machine, forever — which would read as 'no evidence' rather than as a bug."""
    # What the kernel actually prints: the name cut to TASK_COMM_LEN-1 characters.
    truncated = "open-omniscience"[: kernel_log._COMM_MAX]
    assert truncated == "open-omniscienc", "16-char name, 15-char comm"
    line = f"kernel: Out of memory: Killed process 999 ({truncated})"
    monkeypatch.setattr(kernel_log.subprocess, "run", _fake_run({"cur": (0, line)}))
    # no pid supplied: the match must come from the truncated name alone
    assert kernel_log.read_kernel_evidence(None)["verdict"] == "oom-kill"

    # The constant is DERIVED, not hand-written — the brief specifying this slice
    # counted it wrong by one, and a wrong needle never fires in the field.
    assert kernel_log._APP_COMM == truncated
    assert len(kernel_log._APP_COMM) == kernel_log._COMM_MAX
    assert all(len(n) <= kernel_log._COMM_MAX or n == kernel_log._APP_NAME
               for n in kernel_log._PROCESS_NAMES)

    # A shebang console script means the kernel may report the INTERPRETER's comm.
    py = "kernel: Out of memory: Killed process 999 (python3.13) anon-rss:6700000kB"
    monkeypatch.setattr(kernel_log.subprocess, "run", _fake_run({"cur": (0, py)}))
    assert kernel_log.read_kernel_evidence(None)["verdict"] == "oom-kill"


def test_an_empty_but_real_read_is_no_kernel_evidence_never_clean(monkeypatch):
    """MUTATION TARGET. Make the reader return 'clean' on empty output and this fails.
    A kernel that recorded nothing rules out an OOM; it does not establish a clean end."""
    monkeypatch.setattr(kernel_log.subprocess, "run", _fake_run({"cur": (0, _NOISE)}))
    got = kernel_log.read_kernel_evidence(12345)
    assert got["verdict"] == "no-kernel-evidence"
    assert "does not establish a clean end" in got["reason"]
    assert got["verdict"] != "clean"


def test_a_zero_exit_with_no_kernel_lines_is_could_not_look_not_found_nothing(monkeypatch):
    """MEASURED IN THIS SANDBOX, not assumed: `journalctl -k -b 0` exits ZERO and
    prints 'No journal files were found.' when there is no journal at all. A verdict
    keyed on the exit code alone reports 'we looked and found nothing' about a log
    that was never available — the exact conflation this slice exists to prevent."""
    banner = "No journal files were found.\n-- No entries --"
    monkeypatch.setattr(
        kernel_log.subprocess, "run", _fake_run({"cur": (0, banner), "prev": (0, banner)})
    )
    got = kernel_log.read_kernel_evidence(12345)
    assert got["verdict"] == "no-journal"
    assert "no kernel lines" in got["reason"]


def test_a_missing_binary_says_so(monkeypatch):
    monkeypatch.setattr(kernel_log.shutil, "which", lambda _n: None)
    monkeypatch.setattr(kernel_log, "_read_kern_log_fallback", lambda _pid: None)
    got = kernel_log.read_kernel_evidence(1)
    assert got["verdict"] == "no-journalctl"
    assert "not installed" in got["reason"]


def test_a_non_zero_exit_is_no_journal_with_the_code(monkeypatch):
    monkeypatch.setattr(
        kernel_log.subprocess, "run", _fake_run({"cur": (1, ""), "prev": (1, "")})
    )
    got = kernel_log.read_kernel_evidence(1)
    assert got["verdict"] == "no-journal"
    assert "exited 1" in got["reason"]


def test_a_timeout_never_hangs_the_caller_and_is_reported(monkeypatch):
    def _slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kernel_log._TIMEOUT_S)

    monkeypatch.setattr(kernel_log.subprocess, "run", _slow)
    got = kernel_log.read_kernel_evidence(1)
    assert got["verdict"] == "no-journal"
    assert "timed out" in got["reason"]


def test_lines_about_another_process_are_not_ours(monkeypatch):
    """NEGATIVE TWIN. An over-eager matcher that reports someone else's OOM as ours
    would send the operator hunting a crash the app never had."""
    other = "kernel: Out of memory: Killed process 4242 (firefox-esr) anon-rss:900000kB"
    monkeypatch.setattr(kernel_log.subprocess, "run", _fake_run({"cur": (0, other)}))
    got = kernel_log.read_kernel_evidence(12345)
    assert got["verdict"] == "no-kernel-evidence"
    assert got["lines"] == []


def test_the_operator_can_opt_out(monkeypatch):
    monkeypatch.setenv("OO_NO_KERNEL_LOG", "1")
    got = kernel_log.read_kernel_evidence(1)
    assert got["verdict"] == "disabled"


def test_the_read_never_reaches_the_network(monkeypatch):
    """The commands are a fixed argv of local reads. Pinned so a future edit cannot
    quietly turn a forensic read into an egress."""
    seen: list[list[str]] = []

    def _capture(cmd, **kw):
        seen.append(cmd)
        assert kw.get("shell") in (None, False), "never a shell"
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(kernel_log.subprocess, "run", _capture)
    kernel_log.read_kernel_evidence(1)
    assert seen, "the reader must actually run something"
    for cmd in seen:
        assert cmd[0] == "journalctl"
        assert all(not str(a).startswith(("http://", "https://")) for a in cmd)


def test_forensics_reports_not_read_before_the_thread_finishes(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(forensics, "_KERNEL_EVIDENCE", None)
    got = forensics.kernel_evidence()
    assert got["verdict"] == "not-read"
    assert "not 'clean'" in got["reason"]


def test_the_boot_read_runs_off_the_critical_path(monkeypatch, tmp_path):
    """A hung journalctl must not delay a boot: the read is dispatched to a thread and
    start_kernel_evidence_read returns immediately."""
    import threading
    import time

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(forensics, "_KERNEL_EVIDENCE", None)
    release = threading.Event()

    def _slow(pid, since=None):
        release.wait(10)
        return {"verdict": "oom-kill", "lines": [_OOM]}

    monkeypatch.setattr(
        "src.monitoring.kernel_log.read_kernel_evidence", _slow, raising=False
    )
    t0 = time.monotonic()
    forensics.start_kernel_evidence_read({"pid": 1, "started_at": "2026-09-02T09:00:00+00:00"})
    assert time.monotonic() - t0 < 1.0, "the boot must not wait on the kernel read"
    assert forensics.kernel_evidence()["verdict"] == "not-read"
    release.set()
    for _ in range(100):
        if forensics.kernel_evidence()["verdict"] != "not-read":
            break
        time.sleep(0.05)
    assert forensics.kernel_evidence()["verdict"] == "oom-kill"


def test_render_text_shows_the_verdict_and_the_kernel_lines(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(forensics, "_PREV_AT_BOOT", None)
    monkeypatch.setattr(forensics, "_PREV_LOADED", False)
    monkeypatch.setattr(
        forensics,
        "_KERNEL_EVIDENCE",
        {"verdict": "oom-kill", "lines": [_OOM], "reason": "the kernel killed it"},
    )
    forensics.record_session_start()
    txt = forensics.render_text()
    assert "host kernel evidence: oom-kill" in txt
    assert "Killed process 12345" in txt
