"""The host kernel log — the only source that can name the crash kind.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY (2026-09-02, S0.3; RULED by the maintainer: always, local-only). Four field
sessions across three machines ended uncleanly and the app could not say how. An OOM
kill, a host reset, a SIGHUP from a closed terminal and a native fatal all leave the
IDENTICAL app-side record: a sentinel stuck on 'running'. The kernel is the only
witness that distinguishes them, and reading its log costs one subprocess.

WHAT IS AND IS NOT COLLECTED. Only lines that name THIS APP's own process — matched
on the previous session's pid or on the process name. Nothing is transmitted: this is
a local read whose output rides the diagnostics export the operator sends by hand,
exactly like every other forensic block.

THE VOCABULARY IS THE POINT. An empty result is ``no-kernel-evidence`` and NEVER
``clean``: the journal may be volatile, the binary may be absent, the boot may have
rotated, the user may not be in the ``adm``/``systemd-journal`` group. Each of those
is a DIFFERENT reason and the report says which, because "we looked and found nothing"
and "we could not look" are opposite facts and only one of them is evidence.

A NOTE ON THE PROCESS NAME. The kernel truncates ``comm`` to 15 characters, so
``open-omniscience`` (16) appears as ``open-omniscienc``. Matching on the full name
finds nothing, every time, on every machine — which would read as "no evidence"
forever rather than as a bug. The truncation is DERIVED from the name rather than
written out, because the brief specifying this slice hand-counted it wrong by one.

And the name in the line may not be the app's at all: a console-script entry point is
a shebang script, so the kernel execs the interpreter and reports ITS comm. The pid
from the previous session's sentinel is the exact match; the names are the fallback.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess  # nosec B404 - reads the local kernel log; never a network call
from typing import Any

_LOG = logging.getLogger(__name__)

# The kernel stores a task's name in comm[TASK_COMM_LEN] with TASK_COMM_LEN = 16, so
# what it PRINTS is at most 15 characters. DERIVED, never hand-counted: the brief that
# specified this slice wrote the truncation as "open-omniscien" (14), and a matcher
# built on a wrong constant simply never fires — in the field, forever, reading as "no
# evidence" rather than as a bug. A test pins the derivation against len().
_COMM_MAX = 15
_APP_NAME = "open-omniscience"
_APP_COMM = _APP_NAME[:_COMM_MAX]  # 'open-omniscienc'
# A 14-character prefix matches BOTH the full name and any truncation of it, so it is
# strictly the safer needle; the exact truncation is listed beside it so the intent is
# readable. python/uvicorn are here because a console-script entry point has a shebang:
# the kernel execs the INTERPRETER, so an OOM line often carries the interpreter's comm
# (python3.13) rather than the script's name.
_PROCESS_NAMES = (_APP_NAME, _APP_COMM, _APP_NAME[: _COMM_MAX - 1], "python", "uvicorn")

# Kernel signatures, most specific first. A generic pattern matched before a specific
# one would classify an OOM as a plain "killed" line.
_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("oom-kill", r"oom-kill|Out of memory: Kill(ed)? process|oom_reaper"),
    ("oom-kill", r"Killed process \d+"),
    ("native-fatal", r"segfault at |general protection fault|traps: "),
    ("hung-task", r"hung_task|blocked for more than \d+ seconds"),
)

_TIMEOUT_S = 5.0


# journalctl's own banners. It prints these and exits ZERO, so a zero exit is NOT
# evidence that a journal was read (measured, not assumed: in a container
# `journalctl -k -b 0` returns rc=0 with exactly these two lines).
_BANNERS = ("No journal files were found", "-- No entries --", "-- no entries --")


def _run(cmd: list[str]) -> tuple[int, str]:
    """Run a read-only command with a hard timeout. Never raises.

    stderr is folded into the output because journalctl reports "No journal files were
    found" there while still exiting 0 — and that sentence is the difference between
    "we looked and found nothing" and "we could not look"."""
    try:
        proc = subprocess.run(  # nosec B603 - fixed argv, no shell, local read only
            cmd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError:
        return 127, ""
    except (subprocess.TimeoutExpired, OSError) as exc:
        _LOG.debug("kernel-log read failed: %s", type(exc).__name__)
        return 124, ""
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _kernel_lines(text: str) -> list[str]:
    """The real kernel lines in a journalctl read, banners excluded.

    A genuine `journalctl -k` read of any real Linux boot yields hundreds of lines, so
    ZERO of them means the kernel log was not observed — whatever the exit code was."""
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or any(b in stripped for b in _BANNERS):
            continue
        out.append(stripped)
    return out


def _mentions_us(line: str, pid: int | None) -> bool:
    """Does this kernel line name OUR process? pid first (exact), then comm."""
    if pid is not None and re.search(rf"\b{pid}\b", line):
        return True
    return any(name in line for name in _PROCESS_NAMES)


def _classify(lines: list[str]) -> str | None:
    for kind, pattern in _SIGNATURES:
        for line in lines:
            if re.search(pattern, line, re.IGNORECASE):
                return kind
    return None


def _journal_storage_note() -> str | None:
    """Whether the journal is volatile — the difference between 'no crash' and
    'the evidence was in RAM and the machine rebooted'."""
    try:
        if os.path.isdir("/var/log/journal"):
            return None  # persistent
    except OSError:
        return None
    return (
        "the systemd journal appears to be volatile (no /var/log/journal), so the "
        "PREVIOUS boot's kernel messages did not survive the reboot"
    )


def read_kernel_evidence(previous_pid: int | None = None, *, since: str | None = None) -> dict[str, Any]:
    """Kernel lines about this app's previous session, with an honest verdict.

    ``previous_pid`` is the pid from the previous session's sentinel; ``since`` its
    ``started_at`` (used to bound the CURRENT boot's search — an OOM kill does not
    reboot the machine, so the evidence is often in this boot's log, not the last
    one's)."""
    out: dict[str, Any] = {
        "checked_at": None,
        "verdict": "no-kernel-evidence",
        "lines": [],
        "method": (
            "journalctl -k for the previous boot and for this boot since the previous "
            "session started, filtered to lines naming this app's pid or process name "
            "(the kernel truncates the name to 15 characters: open-omniscien). "
            "Read-only, local, never transmitted. An empty result is "
            "'no-kernel-evidence' — never 'clean'."
        ),
    }
    from datetime import UTC, datetime

    out["checked_at"] = datetime.now(UTC).isoformat(timespec="seconds")

    if os.getenv("OO_NO_KERNEL_LOG", "0") == "1":
        out["verdict"] = "disabled"
        out["reason"] = "OO_NO_KERNEL_LOG=1 — the operator opted out of the kernel read"
        return out

    if shutil.which("journalctl") is None:
        got = _read_kern_log_fallback(previous_pid)
        if got is not None:
            out.update(got)
            return out
        out["verdict"] = "no-journalctl"
        out["reason"] = (
            "journalctl is not installed and /var/log/kern.log could not be read, so "
            "the host's own account of how the previous session ended is unavailable"
        )
        return out

    matched: list[str] = []
    reasons: list[str] = []
    read_any = False

    # An OOM kill does NOT reboot the machine, so the evidence usually sits in THIS
    # boot's log. Check it first, bounded by when the previous session started.
    cmds: list[tuple[str, list[str]]] = []
    if since:
        cmds.append(("this boot", ["journalctl", "-k", "-b", "0", "--no-pager", "--since", since]))
    else:
        cmds.append(("this boot", ["journalctl", "-k", "-b", "0", "--no-pager"]))
    cmds.append(("previous boot", ["journalctl", "-k", "-b", "-1", "--no-pager"]))

    for label, cmd in cmds:
        rc, text = _run(cmd)
        if rc == 127:
            reasons.append(f"{label}: journalctl vanished between the check and the read")
            continue
        if rc == 124:
            reasons.append(f"{label}: the read timed out after {_TIMEOUT_S:.0f}s")
            continue
        if rc != 0:
            # -b -1 fails with "Failed to look up boot" on a volatile journal, and
            # journalctl exits non-zero without group membership. Both are "could not
            # look", not "nothing happened".
            reasons.append(f"{label}: journalctl exited {rc}")
            continue
        kernel_lines = _kernel_lines(text)
        if not kernel_lines:
            # rc was 0 and there is still nothing to read: journalctl said "No journal
            # files were found" (or the boot has no kernel entries at all). Treating
            # this as an observation would report "we looked and found nothing" about
            # a log that was never available.
            reasons.append(
                f"{label}: journalctl exited 0 but returned no kernel lines "
                "(no journal files, or this boot is not in the journal)"
            )
            continue
        read_any = True
        for line in kernel_lines:
            if _mentions_us(line, previous_pid):
                matched.append(line)

    out["lines"] = matched[-40:]
    if matched:
        kind = _classify(matched)
        out["verdict"] = kind or "kernel-lines-found"
        if kind is None:
            out["reason"] = (
                "kernel lines naming this process were found but match no known fatal "
                "signature — read them rather than inferring a cause"
            )
        return out

    if not read_any:
        out["verdict"] = "no-journal"
        out["reason"] = "; ".join(reasons) or "no kernel log could be read"
        note = _journal_storage_note()
        if note:
            out["storage_note"] = note
        if not _in_journal_group():
            out["permission_note"] = (
                "this user is in neither 'adm' nor 'systemd-journal', so other boots' "
                "kernel messages are hidden from it — that is a permission gap, not an "
                "absence of evidence"
            )
        return out

    out["verdict"] = "no-kernel-evidence"
    out["reason"] = (
        "the kernel log was read and contains no line naming this app's previous "
        "session. That rules out an OOM kill and a native fault RECORDED BY THE "
        "KERNEL; it does not establish a clean end — a host reset or a signal leaves "
        "no kernel line about us."
    )
    note = _journal_storage_note()
    if note:
        out["storage_note"] = note
    return out


def _in_journal_group() -> bool:
    try:
        import grp

        names = {grp.getgrgid(g).gr_name for g in os.getgroups()}
    except Exception:  # noqa: BLE001 - not POSIX, or an unresolvable gid
        return False
    return bool(names & {"adm", "systemd-journal", "root", "wheel"})


def _read_kern_log_fallback(previous_pid: int | None) -> dict[str, Any] | None:
    """A bounded tail of /var/log/kern.log where journalctl is absent (Debian without
    systemd, some minimal images). Returns None when that file cannot be read either."""
    path = "/var/log/kern.log"
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 512 * 1024))
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        return None
    matched = [ln.strip() for ln in text.splitlines() if _mentions_us(ln, previous_pid)]
    kind = _classify(matched) if matched else None
    if matched:
        return {
            "verdict": kind or "kernel-lines-found",
            "lines": matched[-40:],
            "source": path,
        }
    return {
        "verdict": "no-kernel-evidence",
        "lines": [],
        "source": path,
        "reason": (
            f"the tail of {path} contains no line naming this app's previous session "
            "— that is not evidence of a clean end"
        ),
    }
