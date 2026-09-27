"""How the previous session ENDED — the witnesses the kernel log cannot be.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY (2026-09-26, the daily-crash field reports). Two instances on 4 GB machines died
within a minute of running out of memory (the memory guard logged 99 MB free on one,
swap full on both), and the boot read of the kernel log found NO line about either
death. The kernel's own OOM killer always writes one, so the killer was something
the app never looked at. Three witnesses were missing, and this module adds them:

1. THE PARENT'S EXIT STATUS. A process killed with SIGKILL runs no code of its own, so
   nothing inside it can record the death; only its parent can. ``scripts/launch.sh``
   now appends one line per exit it did not cause itself (closing its window is
   excluded) to ``diagnostics/launcher_exits.jsonl``, and this module reads the line
   naming the previous session's pid and boot. Before, the launcher window closed as
   the server died and took the answer with it.
2. THE USER-SPACE MEMORY KILLERS. systemd-oomd (enabled by default on Fedora), earlyoom
   and nohang kill from user space and log to the ordinary journal, never to the kernel
   log; systemd-coredump records native crashes there too. systemd-oomd names the
   CGROUP it killed, not a pid, so the session records its own cgroup at boot.
3. A NATIVE CRASH TRACE. ``faulthandler`` writes every thread's Python stack to
   ``diagnostics/crash_trace.log`` on SIGSEGV/SIGABRT/SIGBUS/SIGILL/SIGFPE -- the one
   record a native abort (a failed allocation in C code, damaged memory) can leave.

THE SAME RULES AS THE KERNEL READ (ruling R3, 2026-09-02: always, local-only). Only
lines naming this app's own process or cgroup are kept; nothing is transmitted; the
output rides the diagnostics export the operator sends by hand; ``OO_NO_KERNEL_LOG=1``
turns the journal read off with the kernel one. An empty result is never "clean".
"""

from __future__ import annotations

import faulthandler
import json
import logging
import os
import re
import shutil
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from src.monitoring.kernel_log import _kernel_lines, _run, journal_boot_arg
from src.paths import data_dir

_LOG = logging.getLogger(__name__)

LAUNCHER_EXITS = "launcher_exits.jsonl"
CRASH_TRACE = "crash_trace.log"
# Rotated to ``crash_trace.log.1`` at arm time once past this size: one header line per
# session, plus a trace only when a session crashed, so this is years of headers.
_TRACE_MAX_BYTES = 1_000_000
# The header names the machine's boot as well as the pid: an app started the same way at
# every login gets much the same pid each time, so a pid alone would match another
# boot's session after a reboot.
_TRACE_HEADER = "=== open-omniscience session pid={pid} boot={boot} started={at} ==="
_TRACE_HEADER_RE = re.compile(
    r"^=== open-omniscience session pid=(\d+)(?: boot=(\S+))? started=(\S+) ===$"
)
# How much of a previous session's trace the report carries. faulthandler writes a
# bounded stack per thread (100 frames at most), so a crashed 40-thread process can
# still run to a few thousand lines; the head names the fatal error and the crashing
# thread first.
_TRACE_REPORT_LINES = 120

# The journal identifiers of the user-space killers and of the core-dump handler.
_KILLER_TAGS = ("systemd-oomd", "earlyoom", "nohang", "systemd-coredump")
_KILLER_UNITS = ("systemd-oomd", "earlyoom", "nohang")
# systemd-oomd names the cgroup it killed: "Killed /user.slice/.../app-x.scope due to ...".
_OOMD_KILLED = re.compile(r"\bKilled (/\S+)")
_HINT_NO_ACCESS = "not seeing messages from other users and the system"

_TRACE_HANDLE: IO[str] | None = None

# What each signal means for a process that died of it. A classification, never a
# finding: the journal lines below are what can NAME the sender.
_SIGNAL_MEANING: dict[str, tuple[str, str]] = {
    "SIGKILL": (
        "killed",
        "ended from outside without warning; a SIGKILLed process runs no code of its "
        "own. The usual senders are a low-memory killer (the kernel's, systemd-oomd, "
        "earlyoom) or a manual kill -9",
    ),
    "SIGABRT": (
        "crashed",
        "the process aborted itself: native code (a C library or the interpreter) hit a "
        "fatal error, often a failed memory allocation or damaged memory",
    ),
    "SIGSEGV": ("crashed", "a native-code crash: an invalid memory access"),
    "SIGBUS": ("crashed", "a native-code crash: a bus error (e.g. a mapped file page vanished)"),
    "SIGILL": ("crashed", "a native-code crash: an illegal instruction"),
    "SIGFPE": ("crashed", "a native-code crash: an arithmetic fault"),
    "SIGTERM": (
        "stopped",
        "asked to stop by a signal the launcher did not send: a logout, a service "
        "manager, earlyoom's first step, or a manual kill",
    ),
    "SIGINT": ("stopped", "interrupted by a signal the launcher did not send"),
    "SIGHUP": ("stopped", "hung up by something other than the launcher"),
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _diag_dir() -> Path:
    return data_dir() / "diagnostics"


# --------------------------------------------------------------------------- #
#  1. The launcher's record of the exit
# --------------------------------------------------------------------------- #


def _same_boot(recorded: Any, boot_id: str | None) -> bool:
    """False only when BOTH boots are known and differ. Pids are reused across reboots
    (an app started the same way at every login gets much the same pid each time), so
    a record from another boot of the machine is never this session's."""
    if not boot_id or not isinstance(recorded, str) or recorded in ("", "-"):
        return True
    return recorded == boot_id


def launcher_exit(pid: int | None, boot_id: str | None = None) -> dict[str, Any] | None:
    """The launcher's record of how process ``pid`` ended, or None when it holds none.

    ``boot_id`` is the machine boot the session ran in (its sentinel records it); a
    record from another boot is skipped. None is the common case and means nothing by
    itself: the app was started some other way (a terminal, a service, the release-run
    harness), the launcher predates this record, or the launcher asked it to stop."""
    if not isinstance(pid, int):
        return None
    try:
        raw = (_diag_dir() / LAUNCHER_EXITS).read_text(encoding="utf-8")
    except OSError:
        return None
    for line in reversed(raw.splitlines()):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("pid") == pid and _same_boot(rec.get("boot_id"), boot_id):
            return describe_exit(rec)
    return None


def describe_exit(rec: dict[str, Any]) -> dict[str, Any]:
    """A launcher record put into words. The status is the fact; ``meaning`` is the
    textbook reading of it, stated as such."""
    status = rec.get("status")
    sig = rec.get("signal")
    out: dict[str, Any] = {
        "seen_by": "the launcher (scripts/launch.sh), the process's parent",
        "at": rec.get("at"),
        "started_at": rec.get("started_at"),
        "status": status,
        "signal": sig,
    }
    if isinstance(sig, str) and sig in _SIGNAL_MEANING:
        out["kind"], out["meaning"] = _SIGNAL_MEANING[sig]
    elif isinstance(sig, str) and sig:
        out["kind"], out["meaning"] = "signalled", f"ended by {sig}"
    elif isinstance(status, int) and 0 < status <= 128:
        out["kind"] = "exited"
        out["meaning"] = (
            f"the process exited on its own with status {status}: the app stopped with "
            "an error, and its last messages went to the launcher window"
        )
    else:
        out["kind"] = "unknown"
        out["meaning"] = f"an exit status the launcher could not name ({status!r})"
    return out


# --------------------------------------------------------------------------- #
#  2. The user-space killers' own account, from the journal
# --------------------------------------------------------------------------- #


def own_cgroup() -> str | None:
    """This process's cgroup-v2 path (the ``0::`` line), or None where there is none.

    systemd-oomd kills a whole cgroup and logs its path, never a pid, so this is the
    only handle that ties an oomd line to this app."""
    try:
        text = Path("/proc/self/cgroup").read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("0::"):
            path = line[3:].strip()
            # The root cgroup is no handle at all: systemd-oomd never kills "/", and
            # a container that shows only "/" gives nothing to match.
            return path if path and path != "/" else None
    return None


def _names_us(line: str, pid: int | None, cgroup: str | None) -> bool:
    if pid is not None and re.search(rf"(?i)\b(?:process|pid:?)\s+{pid}\b", line):
        return True
    if cgroup:
        m = _OOMD_KILLED.search(line)
        if m:
            killed = m.group(1).rstrip("/")
            if cgroup == killed or cgroup.startswith(killed + "/"):
                return True
    return False


def _classify_killer(lines: list[str]) -> str:
    joined = "\n".join(lines)
    for tag, verdict in (
        ("systemd-oomd", "userspace-oom-kill"),
        ("earlyoom", "userspace-oom-kill"),
        ("nohang", "userspace-oom-kill"),
        ("systemd-coredump", "core-dump"),
    ):
        if tag in joined:
            return verdict
    return "journal-lines-found"


def running_killers() -> dict[str, Any]:
    """Which user-space memory killers are ACTIVE on this machine right now.

    A killer that is running is a candidate even when its line about us was not found
    (a rotated journal, a volatile one): the report can then name it as present rather
    than leave the reader to guess."""
    if shutil.which("systemctl") is None:
        return {"known": False, "reason": "systemctl is not installed"}
    rc, text = _run(["systemctl", "is-active", *_KILLER_UNITS])
    states = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # One state per unit, in order. Anything else (no systemd, no bus) is an error text.
    if len(states) != len(_KILLER_UNITS) or not all(s.isalpha() for s in states):
        return {"known": False, "reason": f"systemctl could not report unit states (exit {rc})"}
    return {
        "known": True,
        "active": [u for u, s in zip(_KILLER_UNITS, states, strict=True) if s == "active"],
    }


def read_userspace_killers(
    pid: int | None, *, since: str | None = None, boot: str | None = None, cgroup: str | None = None
) -> dict[str, Any]:
    """The journal lines in which systemd-oomd, earlyoom, nohang or systemd-coredump
    name this app's previous process (by pid) or its cgroup (systemd-oomd)."""
    out: dict[str, Any] = {
        "checked_at": _now(),
        "verdict": "no-userspace-evidence",
        "lines": [],
        "method": (
            "journalctl -t systemd-oomd -t earlyoom -t nohang -t systemd-coredump for the "
            "boot the previous session ran in, since it started, filtered to lines naming "
            "its pid or (systemd-oomd, which kills a cgroup) its cgroup. Read-only, local, "
            "never transmitted. An empty result is never 'clean'."
        ),
    }
    if os.getenv("OO_NO_KERNEL_LOG", "0") == "1":
        out["verdict"] = "disabled"
        out["reason"] = "OO_NO_KERNEL_LOG=1 — the operator opted out of the journal reads"
        return out
    if shutil.which("journalctl") is None:
        out["verdict"] = "no-journalctl"
        out["reason"] = "journalctl is not installed, so the user-space killers' log cannot be read"
        return out
    cmd = ["journalctl", "-b", journal_boot_arg(boot), "--no-pager", "-o", "short-iso"]
    for tag in _KILLER_TAGS:
        cmd += ["-t", tag]
    if since:
        cmd += ["--since", since]
    rc, text = _run(cmd)
    if rc != 0:
        out["verdict"] = "no-journal"
        out["reason"] = (
            f"journalctl exited {rc} reading the boot the previous session ran in"
            + (" (the read timed out)" if rc == 124 else "")
        )
        return out
    if _HINT_NO_ACCESS in text:
        # journalctl says so itself, then shows only this user's own journal: the
        # killers' lines are in the SYSTEM journal, which this user cannot see.
        out["verdict"] = "no-journal"
        out["reason"] = (
            "this user cannot read the system journal (not in 'adm' or "
            "'systemd-journal'), which is where these daemons log -- a permission gap, "
            "not an absence of evidence"
        )
        return out
    lines = [ln for ln in _kernel_lines(text) if not ln.startswith("Hint:")]
    matched = [ln for ln in lines if _names_us(ln, pid, cgroup)]
    out["lines"] = matched[-20:]
    if matched:
        out["verdict"] = _classify_killer(matched)
        return out
    out["reason"] = (
        "the journal was read and none of these daemons named this app's previous "
        "process or cgroup. That rules out a kill they LOGGED; a daemon with a rotated "
        "or volatile journal, or a plain kill -9, leaves nothing here."
    )
    if not cgroup:
        out["cgroup_note"] = (
            "the previous session recorded no cgroup, so a systemd-oomd kill (which names "
            "a cgroup, not a pid) could not be matched"
        )
    return out


# --------------------------------------------------------------------------- #
#  3. The native crash trace
# --------------------------------------------------------------------------- #


def crash_trace_path() -> Path:
    return _diag_dir() / CRASH_TRACE


def arm_crash_trace() -> dict[str, Any]:
    """Point ``faulthandler`` at ``diagnostics/crash_trace.log`` for this process.

    On SIGSEGV, SIGABRT, SIGBUS, SIGILL and SIGFPE it writes every thread's Python
    stack there before the process dies -- the one record a native abort can leave.
    Each session first writes a header naming its pid, which is how the next boot
    finds the trace that belongs to the session that died. ``OO_CRASH_TRACE=0``
    turns it off. It cannot see a SIGKILL: nothing can, from inside."""
    global _TRACE_HANDLE
    if os.getenv("OO_CRASH_TRACE", "1") == "0":
        return {"armed": False, "reason": "OO_CRASH_TRACE=0"}
    path = crash_trace_path()
    if _TRACE_HANDLE is not None:
        return {"armed": True, "path": str(path)}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.stat().st_size > _TRACE_MAX_BYTES:
                os.replace(path, path.with_name(CRASH_TRACE + ".1"))
        except FileNotFoundError:
            pass
        # Line-buffered and kept open for the life of the process: faulthandler writes
        # to the file DESCRIPTOR from inside a signal handler, where no Python code runs.
        from src.monitoring.session_history import machine_boot_id

        fh = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - held open on purpose
        header = _TRACE_HEADER.format(pid=os.getpid(), boot=machine_boot_id() or "-", at=_now())
        fh.write("\n" + header + "\n")
        faulthandler.enable(file=fh, all_threads=True)
        _TRACE_HANDLE = fh
        return {"armed": True, "path": str(path)}
    except Exception as exc:  # noqa: BLE001 - a crash recorder never blocks a boot
        _LOG.debug("could not arm the crash trace", exc_info=True)
        return {"armed": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}


def note_fatal_exception(exc: BaseException) -> None:
    """Record an exception that escaped the server's run loop and is ending the process.

    A Python-level death (a MemoryError in the event loop, say) is not a signal, so
    faulthandler never sees it, and its traceback otherwise goes only to the launcher
    window. Best-effort and bounded."""
    try:
        text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-8000:]
        with open(crash_trace_path(), "a", encoding="utf-8") as fh:
            fh.write(f"Uncaught exception ended the server at {_now()}:\n{text}\n")
    except Exception:  # noqa: BLE001 - never mask the exception being reported
        _LOG.debug("could not record the fatal exception", exc_info=True)


def previous_trace(pid: int | None, boot_id: str | None = None) -> dict[str, Any] | None:
    """What the crash trace holds for the session with ``pid`` (in machine boot
    ``boot_id``, when known), or None when it holds nothing: that session did not die of
    a native fault or a Python exception (or predates the trace), which is itself worth
    knowing beside a SIGKILL."""
    if not isinstance(pid, int):
        return None
    path = crash_trace_path()
    for candidate in (path, path.with_name(CRASH_TRACE + ".1")):
        try:
            lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        start = None
        for i, line in enumerate(lines):
            m = _TRACE_HEADER_RE.match(line.strip())
            if m and int(m.group(1)) == pid and _same_boot(m.group(2), boot_id):
                start = i
        if start is None:
            continue
        body: list[str] = []
        for line in lines[start + 1 :]:
            if _TRACE_HEADER_RE.match(line.strip()):
                break
            body.append(line)
        while body and not body[-1].strip():
            body.pop()
        while body and not body[0].strip():
            body.pop(0)
        if not body:
            return None
        head = next(
            (ln.strip() for ln in body if ln.startswith(("Fatal Python error", "Uncaught exception"))),
            body[0].strip(),
        )
        return {
            "summary": head[:300],
            "lines": body[:_TRACE_REPORT_LINES],
            "lines_total": len(body),
            "source": str(candidate),
        }
    return None


# --------------------------------------------------------------------------- #
#  The combined account
# --------------------------------------------------------------------------- #


def how_it_ended(
    *,
    launcher: dict[str, Any] | None,
    killers: dict[str, Any] | None,
    kernel: dict[str, Any] | None,
    trace: dict[str, Any] | None,
) -> dict[str, Any]:
    """One sentence on how the previous session ended, built ONLY from the witnesses
    that answered, each named. Never a guess: with no witness it says so."""
    parts: list[str] = []
    kverdict = (kernel or {}).get("verdict")
    uverdict = (killers or {}).get("verdict")
    if kverdict == "oom-kill":
        parts.append("the kernel log records an out-of-memory kill of this process")
    if uverdict == "userspace-oom-kill":
        lines = " ".join((killers or {}).get("lines") or [])
        who = next((t for t in ("systemd-oomd", "earlyoom", "nohang") if t in lines), "a user-space memory killer")
        parts.append(f"{who} logged killing this process")
    elif uverdict == "core-dump":
        parts.append("systemd-coredump logged a core dump of this process")
    if kverdict == "native-fatal":
        parts.append("the kernel log records a native fault in this process")
    if launcher:
        sig = launcher.get("signal")
        parts.append(
            f"the launcher saw it end by {sig}" if sig else f"the launcher saw it exit with status {launcher.get('status')}"
        )
    if trace:
        parts.append(f"it left a crash trace: {trace.get('summary')}")
    if not parts:
        return {
            "known": False,
            "summary": (
                "no witness named how it ended: no launcher record, no journal line from a "
                "memory killer or the kernel, and no crash trace"
            ),
        }
    return {"known": True, "summary": "; ".join(parts)}
