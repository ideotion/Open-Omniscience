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
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from src.monitoring.kernel_log import (
    HINT_NO_ACCESS,
    _kernel_lines,
    _run,
    journal_boot_arg,
    journal_notice,
    published_lines,
)
from src.paths import data_dir

_LOG = logging.getLogger(__name__)

LAUNCHER_EXITS = "launcher_exits.jsonl"
#: The abort messages the launcher's stderr filter recorded (scripts/launch.sh ``stderr_filter``), one JSON line each plus a summary per launch.
LAUNCHER_STDERR = "launcher_stderr.jsonl"
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
_TRACE_REPORT_LINES = 400
# A trace line is cut at this many characters. faulthandler writes one line per frame (about 100
# characters), so the cut only ever touches an exception's message, which can be a page of text;
# without it a report of ten earlier ends could run to several hundred KB. The summary is one of these
# lines, so it is held to the same.
_TRACE_LINE_CHARS = 200
# A trace line is ALSO cut at this many bytes of UTF-8 (the cut line, with its ellipsis, in ASCII): the
# member is written as UTF-8 (``ensure_ascii=False``), so the characters alone would let a line of Chinese
# or of astral characters take three or four times the room the slot is sized for (measured: 233 KB for
# accented text, 346 KB for CJK, 458 KB for astral characters at 120,000 characters). A trace line is ASCII
# but for an exception's message, so this costs a real report nothing.
_TRACE_LINE_BYTES = _TRACE_LINE_CHARS - 1 + len("\u2026".encode("utf-8"))
# How much of an exception that ended the server is written to the crash trace log, from its END:
# the end of a traceback is the exception itself, the part a reader needs; 8,000 characters keeps the log's
# growth per crash small against ``_TRACE_MAX_BYTES``.
_FATAL_TEXT_CHARS = 8000
# The reason ``arm_crash_trace`` gives when it could not arm: a type and one sentence.
_ARM_REASON_CHARS = 200
# The block of one thread in a faulthandler dump, and the file named in one frame of it.
_THREAD_HEAD = re.compile(r"^(?:Current thread|Thread) 0x")
_FILE_IN_FRAME = re.compile(r'(File ")([^"]+)(")')
# How far BEFORE a session's boot record (or sentinel) its trace header may lie: the trace is armed
# first thing in ``_serve``, the boot record is written once the data is unlocked and the database
# prepared, and a first start with migrations is slow. Half an hour protects only against taking
# the header of some OTHER session that had the same pid, which matters where the machine's boot
# id is unknown (every platform without ``/proc/sys/kernel/random/boot_id``); a header further back
# than this is another session's.
_HEADER_LEAD_S = 1800.0
# How far AFTER it a header may lie: the header, the sentinel and the boot record are stamped by
# three clock reads at one-second resolution, so a header can read a second later than the record.
_HEADER_LAG_S = 5.0
# The sentinel and the boot record of one session are written one call apart: their times differ by
# a second at most. Beyond this a boot record with the previous session's pid is another session.
_SAME_START_S = 5.0

# The journal identifiers of the user-space killers and of the core-dump handler.
_KILLER_TAGS = ("systemd-oomd", "earlyoom", "nohang", "systemd-coredump")

#: How many serialised bytes of the session-forensics headroom the core-dump stack may use, the whole ``stack`` member included. It is the
#: REMAINDER of WAL's 2,415 B headroom after this thread's other worst-case members (crashing_thread_kind 440, launcher_stderr about 1,000,
#: died_into_phase 74, native_in_flight 162, the thread census 150 = 1,826), so the worst case fits by construction. Raising it needs WAL's measurement first.
COREDUMP_STACK_BYTES = 589
_COREDUMP_HEAD = re.compile(r"systemd-coredump\S*:\s+Process\s+(\d+)\s+\(")
_COREDUMP_KEEP = re.compile(r"^(?:Stack trace of thread \d+:|#\d+\s)")
_COREDUMP_FRAME = re.compile(r"^#\d+\s")
_KILLER_UNITS = ("systemd-oomd", "earlyoom", "nohang")
# systemd-oomd names the cgroup it killed: "Killed /user.slice/.../app-x.scope due to ...".
_OOMD_KILLED = re.compile(r"\bKilled (/\S+)")
_HINT_NO_ACCESS = HINT_NO_ACCESS  # one sentence for both journal readers (see kernel_log)

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

# What a Windows exit status means, by its unsigned 32-bit value (the launcher records .NET's signed ExitCode; 0xC0000005 arrives as
# -1073741819). The names and values are ntstatus.h's (mingw-w64-headers/include/ntstatus.h, read 2026-10-17). A classification, like the
# signals above: Windows ends a process that crashed with the NTSTATUS of the fault as its exit code and writes nothing to stderr.
_NT_STATUS_MEANING: dict[int, tuple[str, str]] = {
    0xC0000005: ("crashed", "STATUS_ACCESS_VIOLATION: a native-code crash, an invalid memory access"),
    0xC0000374: ("crashed", "STATUS_HEAP_CORRUPTION: the Windows heap found damaged memory"),
    0xC0000409: ("crashed", "STATUS_STACK_BUFFER_OVERRUN: a fast-fail, which is how abort() ends a process on Windows"),
    0xC00000FD: ("crashed", "STATUS_STACK_OVERFLOW"),
    0xC000001D: ("crashed", "STATUS_ILLEGAL_INSTRUCTION"),
    0xC0000094: ("crashed", "STATUS_INTEGER_DIVIDE_BY_ZERO"),
    0xC0000006: ("crashed", "STATUS_IN_PAGE_ERROR: a mapped file page could not be read"),
    0xC0000017: ("crashed", "STATUS_NO_MEMORY: an allocation failed"),
    0xC0000135: ("failed to start", "STATUS_DLL_NOT_FOUND: a library the app needs was not found"),
    0xC0000142: ("failed to start", "STATUS_DLL_INIT_FAILED: a library could not initialise"),
    0xC000013A: ("stopped", "STATUS_CONTROL_C_EXIT: interrupted with Ctrl-C"),
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


# --------------------------------------------------------------------------- #
#  1b. What the C library said as the process aborted (the launcher's stderr filter)
# --------------------------------------------------------------------------- #

#: Lines of the launcher's stderr record shown per session (the launcher keeps up to 20): 2. WHAT IT PROTECTS: the report's byte budget
#: (a real abort is one or two messages; a crash loop is what could repeat them), not a view of how many there were: ``lines_recorded``
#: is always the full count the launcher kept. Worst case per session about 245 B, 11 sessions about 2.7 KB, typical about 100 B.
STDERR_LINES_SHOWN = 2
#: Earlier unclean ends that carry a ``launcher_stderr`` (the newest 3, beside the previous session's own). WHAT IT PROTECTS: the report's byte
#: room (R119, measured by WAL): 4 sessions x about 245 B worst case is 1 KB where all 11 would be 2.7 KB.
STDERR_ROWS_SHOWN = 3
#: The fixed messages the launcher's stderr filter admits (scripts/launch.sh ``STDERR_MESSAGES``, which a test pins equal to this set):
#: glibc 2.41's heap-corruption messages and the interpreter's fatal-error headers. A line is shown only when it IS one of these, whole
#: (no pattern, no tail), checked AGAIN here because the file is on disk and anything may have written to it; any other line is not
#: shown, only counted in ``rejected_lines``. musl has NO message to add: its allocator detects corruption with ``assert`` redefined to
#: ``a_crash()`` (src/malloc/mallocng/glue.h; ``hlt`` on x86_64), so the process dies of a signal with nothing printed and the signal is
#: what the launcher's exit record already holds. macOS libmalloc prints its messages with the program name, pid, thread and object
#: address in them, so those are matched as TEMPLATES (:data:`MAC_ABORT_TAILS`), never as fixed lines.
ABORT_MESSAGES = frozenset({
    "malloc(): unaligned fastbin chunk detected",
    "malloc(): unaligned fastbin chunk detected 2",
    "malloc(): unaligned fastbin chunk detected 3",
    "malloc(): memory corruption",
    "malloc(): memory corruption (fast)",
    "malloc(): unaligned tcache chunk detected",
    "malloc(): smallbin double linked list corrupted",
    "malloc(): invalid size (unsorted)",
    "malloc(): invalid next size (unsorted)",
    "malloc(): mismatching next->prev_size (unsorted)",
    "malloc(): unsorted double linked list corrupted",
    "malloc(): largebin double linked list corrupted (nextsize)",
    "malloc(): largebin double linked list corrupted (bk)",
    "malloc(): corrupted top size",
    "malloc_consolidate(): unaligned fastbin chunk detected",
    "malloc_consolidate(): invalid chunk size",
    "munmap_chunk(): invalid pointer",
    "realloc(): invalid pointer",
    "realloc(): invalid next size",
    "realloc(): invalid old size",
    "free(): invalid pointer",
    "free(): invalid size",
    "free(): too many chunks detected in tcache",
    "free(): unaligned chunk detected in tcache 2",
    "free(): double free detected in tcache 2",
    "free(): invalid next size (fast)",
    "free(): invalid next size (normal)",
    "free(): corrupted unsorted chunks",
    "double free or corruption (fasttop)",
    "double free or corruption (top)",
    "double free or corruption (out)",
    "double free or corruption (!prev)",
    "corrupted size vs. prev_size",
    "corrupted size vs. prev_size while consolidating",
    "corrupted double-linked list",
    "corrupted double-linked list (not small)",
    "Fatal Python error: Aborted",
    "Fatal Python error: Segmentation fault",
    "Fatal Python error: Bus error",
    "Fatal Python error: Illegal instruction",
    "Fatal Python error: Floating point exception",
})


#: macOS libmalloc abort messages, each a TEMPLATE because the line carries the program name, the pid, the thread and an object address:
#: ``<progname>(<pid>,0x<thread>) malloc: <tail>`` (src/malloc_printf.c ``malloc_vreport``: ``"%s(%d,%p) malloc: "`` with getprogname(), getpid(),
#: the thread). ``%p`` in a tail stands for ``0x`` and lower-case hex. Every tail is the format string of a ``malloc_zone_error`` /
#: ``malloc_report`` call in apple-oss-distributions/libmalloc (``main`` as read on 2026-10-17): malloc_common.c (the default zone's
#: ``*** error for object %p: pointer being freed was not allocated``), malloc_printf.c (``*** set a breakpoint in malloc_error_break to
#: debug``, printed after every error that stops the process), magazine_malloc.c, magazine_large.c, magazine_small.c, magazine_medium.c (the
#: rest). The variable parts are character-class limited (a program name of ``[A-Za-z0-9._+-]``, digits, hex), so no free text can ride in: a
#: line with anything else in those places does not match. NOT RUN ON macOS (this was written on Linux against the source text and tested
#: with the awk implementations that ship there or descend from it); an older macOS words some of these differently and is not matched.
MAC_ABORT_TAILS = (
    "*** set a breakpoint in malloc_error_break to debug",
    "*** error for object %p: pointer being freed was not allocated",
    "pointer %p being freed was not allocated",
    "pointer %p being freed already on death-row",
    "pointer %p being reallocated was not allocated",
    "pointer %p of size zero being freed",
    "large entry %p reallocated is not properly in table",
    "Non-aligned pointer %p being freed",
    "Non-aligned pointer %p being freed (2)",
    "Pointer %p to metadata being freed",
    "Pointer %p to metadata being freed (2)",
    "non-page-aligned, non-allocated pointer %p being freed",
    "double free for ptr %p",
)
#: A line longer than this is never a template match (the launcher checks the same figure): the longest tail with a long program name is far below it.
MAC_LINE_MAX = 200
_MAC_PREFIX_ERE = r"[A-Za-z0-9._+-]+\([0-9]+,0x[0-9a-f]+\) malloc: "
_PTR_ERE = "0x[0-9a-f]+"


def _ere_escape(text: str) -> str:
    return re.sub(r"([\\^$.\[\]|()*+?{}])", r"\\\1", text)


def mac_abort_ere() -> str:
    """The one extended regular expression the launcher's awk and this reader both apply to a whole line (POSIX ERE, no intervals, so
    mawk, gawk, the one-true-awk that macOS ships and busybox awk all read it the same way)."""
    alts = "|".join(_ere_escape(t).replace("%p", _PTR_ERE) for t in MAC_ABORT_TAILS)
    return "^" + _MAC_PREFIX_ERE + "(" + alts + ")$"


_MAC_ABORT_RE = re.compile(mac_abort_ere())


def accepted_abort_line(text: object) -> bool:
    """Is this line one the launcher's filter would have kept: one of the fixed messages, or a whole-line macOS template match."""
    return isinstance(text, str) and (text in ABORT_MESSAGES or (len(text) <= MAC_LINE_MAX and _MAC_ABORT_RE.fullmatch(text) is not None))


#: The most of the launcher's stderr record the reader looks at: 256 KiB, the file's own tail. WHAT IT PROTECTS: the boot (the launcher
#: trims the file to 100 lines of at most about 200 bytes, so the real file is a tenth of this; a file grown past it by something else is
#: read from its end, where the newest launches are).
_STDERR_READ_BYTES = 256 * 1024


def _count(value: Any) -> int | None:
    """A count from the untrusted file: a real, non-negative integer (not a boolean), else None."""
    return value if type(value) is int and value >= 0 else None


def _tail_text(path: Path, limit: int) -> str:
    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - limit))
        data = fh.read(limit)
    text = data.decode("utf-8", errors="replace")
    return text.split("\n", 1)[1] if size > limit and "\n" in text else text  # drop the line the cut fell inside


def launcher_stderr(pid: int | None, boot_id: str | None = None) -> dict[str, Any] | None:
    """The abort messages the launcher's stderr filter recorded for process ``pid``, or None when it holds no record for it.

    None means the launcher left nothing for this pid and boot: the app was started some other way, the launcher predates the filter, awk
    or tee was missing, the run was ephemeral, or the launcher was killed before it wrote anything. It is NOT "the process printed
    nothing": that is a record with a summary and ``lines_recorded`` 0. ``dropped_lines`` is how many other lines the filter saw and did
    not keep (it counts, it never stores); it is None when the filter ended before it could write its summary (``no_summary``).
    ``lines_recorded`` is what the launcher says it kept (the summary), or the lines found when there is no summary; a gap between the two
    is ``lines_not_found`` (a line written before the launcher knew the pid, or cut by the file's trim). ``pid_only_match`` says the
    boot id was unknown on one side, so the pid is all that ties the record to the session."""
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    try:
        raw = _tail_text(_diag_dir() / LAUNCHER_STDERR, _STDERR_READ_BYTES)
    except OSError:
        return None
    from src.monitoring.secret_scrub import scrubbed

    shown: list[str] = []
    summary: dict[str, Any] | None = None
    found = rejected = 0
    pid_only = False
    for line in raw.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or type(rec.get("pid")) is not int or rec["pid"] != pid or not _same_boot(rec.get("boot_id"), boot_id):
            continue
        if not isinstance(rec.get("boot_id"), str) or not isinstance(boot_id, str):
            pid_only = True
        if rec.get("summary") is True:
            summary = rec
            continue
        text = rec.get("line")
        if not accepted_abort_line(text):
            rejected += 1
            continue
        found += 1
        shown.append(scrubbed(str(text)))
    if summary is None and not shown and not rejected:
        return None
    kept = _count(summary.get("kept_lines")) if summary else None
    recorded = max(found, kept) if kept is not None else found
    out: dict[str, Any] = {"lines": shown[-STDERR_LINES_SHOWN:], "lines_recorded": recorded}
    if recorded > found:
        out["lines_not_found"] = recorded - found
    out["dropped_lines"] = _count(summary.get("dropped_lines")) if summary else None
    over = _count(summary.get("over_cap_lines")) if summary else None
    if over:
        out["over_cap_lines"] = over
    if rejected:
        out["rejected_lines"] = rejected
    if summary is None:
        out["no_summary"] = True
    if pid_only:
        out["pid_only_match"] = True
    return out


#: Signal numbers with one meaning on Linux and macOS. SIGBUS (7 on Linux, 10 on macOS), SIGUSR and the rest are left out: the number alone would name the wrong one.
_SHELL_SIGNALS = {1: "SIGHUP", 2: "SIGINT", 3: "SIGQUIT", 6: "SIGABRT", 9: "SIGKILL", 11: "SIGSEGV", 13: "SIGPIPE", 14: "SIGALRM", 15: "SIGTERM"}


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
    elif isinstance(status, int) and not isinstance(status, bool) and (status & 0xFFFFFFFF) in _NT_STATUS_MEANING and (status < 0 or status > 0xFFFF):
        out["kind"], out["meaning"] = _NT_STATUS_MEANING[status & 0xFFFFFFFF]
    elif isinstance(status, int) and 0 < status <= 128:
        out["kind"] = "exited"
        out["meaning"] = (
            f"the process exited on its own with status {status}: the app stopped with "
            "an error, and its last messages went to the launcher window"
        )
    elif isinstance(status, int) and not isinstance(status, bool) and (status - 128) in _SHELL_SIGNALS:
        # The launcher's own shell gave no name (its ``kill -l`` is not the same everywhere); a shell reports death by signal N as 128+N.
        # Inferred, so the ``signal`` field stays null and the words say so. Only the numbers that mean the same on Linux and macOS.
        out["kind"], out["meaning"] = "signalled", f"status {status} is 128+{status - 128}: {_SHELL_SIGNALS[status - 128]}"
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


def _jlen(text: str) -> int:
    """Serialised bytes of one list member: the JSON string, its quotes and the comma after it."""
    return len(json.dumps(text, ensure_ascii=False).encode("utf-8")) + 1


def coredump_stack(text: str, pid: int | None) -> dict[str, Any] | None:
    """The stack systemd-coredump logged for process ``pid``, cut to :data:`COREDUMP_STACK_BYTES` from the front, or None.

    In ``journalctl -o short-iso`` only the first line of a core-dump entry names the process; the thread headers and the frames
    (``Stack trace of thread N:`` / ``#0  0x... name (lib + 0x...)``) are INDENTED CONTINUATION lines that name no pid, so they are
    read here from the entry that follows a header naming the pid. The whole block is taken through the passphrase scrub BEFORE it is
    cut. Lines are kept in the order the journal wrote them (thread by thread, ``#0`` upward) until the next whole line would pass the
    budget; the rest is counted, not stored: ``frames_dropped`` (``#n`` lines) and ``bytes_dropped`` (serialised bytes of every line
    left out). Module lists and other continuation lines are ignored and not counted. Tested on the documented systemd-coredump format
    only; it has not been run against a real journal."""
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    block: list[str] | None = None
    current: list[str] | None = None
    for line in text.splitlines():
        m = _COREDUMP_HEAD.search(line)
        if m and not line[:1].isspace():
            current = [] if int(m.group(1)) == pid else None
            if current is not None:
                block = current
            continue
        if current is not None:
            if line[:1] in (" ", "\t"):
                current.append(line.strip())
            else:
                current = None
    if block is None:
        return None
    from src.monitoring.secret_scrub import scrubbed

    kept_src = [ln for ln in scrubbed("\n".join(block)).split("\n") if _COREDUMP_KEEP.match(ln)]
    if not kept_src:
        return {"result": "no-stack-in-entry"}
    overhead = len(json.dumps({"result": "stack", "lines": [], "frames_dropped": 10**9, "bytes_dropped": 10**9}, separators=(",", ":")))
    room = COREDUMP_STACK_BYTES - overhead
    kept: list[str] = []
    used = 0
    cut = False
    frames_dropped = bytes_dropped = 0
    for ln in kept_src:
        n = _jlen(ln)
        if not cut and used + n <= room:
            kept.append(ln)
            used += n
            continue
        cut = True
        bytes_dropped += n
        if _COREDUMP_FRAME.match(ln):
            frames_dropped += 1
    out: dict[str, Any] = {"result": "stack", "lines": kept}
    if cut:
        out["frames_dropped"] = frames_dropped
        out["bytes_dropped"] = bytes_dropped
    return out


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
    notice = journal_notice(text)
    if notice == "no-access":
        # journalctl says so itself, then shows only this user's own journal: the
        # killers' lines are in the SYSTEM journal, which this user cannot see.
        out["verdict"] = "no-journal"
        out["reason"] = (
            "this user cannot read the system journal (not in 'adm' or "
            "'systemd-journal'), which is where these daemons log -- a permission gap, "
            "not an absence of evidence"
        )
        return out
    if notice == "no-files":
        # `No journal files were found.` with exit 0 and `-- No entries --`: nothing was read, and
        # "none of these daemons named this process" would be a statement about a log that was
        # never opened. The cause is NOT named as a permission gap: there may be no journal at all.
        out["verdict"] = "no-journal"
        out["reason"] = (
            "journalctl found no journal file it could open (none exist, or this user may not "
            "read them), so the memory killers' log was not observed -- not an absence of evidence"
        )
        return out
    lines = _kernel_lines(text)
    matched = [ln for ln in lines if _names_us(ln, pid, cgroup)]
    out["lines"] = published_lines(matched, 20)
    if matched:
        out["verdict"] = _classify_killer(matched)
        if out["verdict"] == "core-dump":
            stack = coredump_stack(text, pid)
            if stack is not None:
                out["stack"] = stack
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
        from src.monitoring.diagnostics_runs import tidy_error

        reason = tidy_error(exc, _ARM_REASON_CHARS)
        _LOG.debug("could not arm the crash trace: %s", reason)
        return {"armed": False, "reason": reason}


def note_fatal_exception(exc: BaseException) -> None:
    """Record an exception that escaped the server's run loop and is ending the process.

    A Python-level death (a MemoryError in the event loop, say) is not a signal, so
    faulthandler never sees it, and its traceback otherwise goes only to the launcher
    window. Best-effort and bounded.

    The trace file is carried by the debug bundle, and an engine's error can quote the statement that held a key, so the
    text is scrubbed of every passphrase the process holds BEFORE the cut (a text cut first can split a passphrase and
    keep half of it), and when it cannot be checked the class is written and none of the exception's words."""
    try:
        # The traceback is written by ``secret_scrub.record_traceback`` (a database driver's last line is its class only): the passphrases the process holds taken
        # out of the WHOLE text (the cause chain included), the class and the frames and none of the words
        # when a ``UnicodeError`` is reachable (its message names a character and its offset). Then a key
        # literal and the person's folders are taken out, and only then is the text cut: an exception that ends
        # the server can carry the engine's statement in its message, and this file is read into the
        # diagnostics zip. Withheld, not kept, when it cannot be checked. The same function the trace read uses.
        from src.monitoring.diagnostics_runs import WITHHELD, scrubbed_text
        from src.monitoring.secret_scrub import record_traceback

        clean = scrubbed_text(record_traceback(exc))
        text = clean[-_FATAL_TEXT_CHARS:] if clean is not None else f"{type(exc).__name__}: {WITHHELD}"
        with open(crash_trace_path(), "a", encoding="utf-8") as fh:
            fh.write(f"Uncaught exception ended the server at {_now()}:\n{text}\n")
    except Exception as err:  # noqa: BLE001 - never mask the exception being reported
        # The reason, not the traceback: this runs inside the handler of the fatal exception, so a logged traceback would
        # print the fatal exception's message through ``__context__``, unscrubbed, next to a body that scrubs the same text.
        from src.monitoring.diagnostics_runs import tidy_error

        _LOG.debug("could not record the fatal exception: %s", tidy_error(err))


def _when(text: Any) -> float | None:
    """An ISO time of the ledger, the sentinel or a trace header as epoch seconds; None when ``text``
    is not one (the callers then fall back to matching by pid and boot alone)."""
    if not isinstance(text, str):
        return None
    try:
        when = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return (when if when.tzinfo else when.replace(tzinfo=UTC)).timestamp()


def _trace_in(
    lines: list[str], pid: int, boot_id: str | None, started_at: str | None = None
) -> tuple[bool, list[str]]:
    """(header found, the body under the NEWEST matching header) for one read of the trace log.

    A header matches by its pid, and by its machine boot where both are known. When ``started_at``
    (the moment the session's own record says it began) is given, the header must also have been
    written within ``_HEADER_LEAD_S`` before it and ``_HEADER_LAG_S`` after: a pid is reused (an app
    started the same way at every login gets much the same one), and where the boot is unknown the
    pid alone would give one session the trace of another. The body is trimmed of blank lines at both
    ends and is empty when the header has nothing under it."""
    anchor = _when(started_at)
    start = None
    for i, line in enumerate(lines):
        m = _TRACE_HEADER_RE.match(line.strip())
        if not (m and int(m.group(1)) == pid and _same_boot(m.group(2), boot_id)):
            continue
        written = _when(m.group(3))
        if anchor is not None and written is not None and not (
            anchor - _HEADER_LEAD_S <= written <= anchor + _HEADER_LAG_S
        ):
            continue
        start = i
    if start is None:
        return False, []
    body: list[str] = []
    for line in lines[start + 1 :]:
        if _TRACE_HEADER_RE.match(line.strip()):
            break
        body.append(line)
    while body and not body[-1].strip():
        body.pop()
    while body and not body[0].strip():
        body.pop(0)
    return True, body


def _crashing_thread_first(body: list[str]) -> list[str]:
    """``body`` with the block of the thread that was running when the signal came moved ahead of the
    other threads' blocks. faulthandler writes it LAST, labelled "Current thread", so a cut at the first
    lines of a many-thread dump would keep the idle threads and drop the one that crashed."""
    heads = [i for i, line in enumerate(body) if _THREAD_HEAD.match(line)]
    current = next((i for i in heads if body[i].startswith("Current thread")), None)
    if current is None or current == heads[0]:
        return body
    end = next((i for i in heads if i > current), len(body))
    return body[: heads[0]] + body[current:end] + body[heads[0] : current] + body[end:]


def _trace_line(line: str) -> str:
    """One line of a trace as the report carries it: the file a frame names shortened the way the
    stack sampler shortens it (``src/...``, ``pkg/...``, a bare name), the data and home folders of an
    exception's message replaced, and the line cut (at ``_TRACE_LINE_CHARS`` characters and at
    ``_TRACE_LINE_BYTES`` bytes). The person's folder is a name; it has no business in a report that is
    sent to someone else. The scrub has already run, on the whole text: the home folder is ``<home>`` by
    now, which ``_short_path`` knows, beside the real checkout."""
    from src.monitoring.diagnostics_runs import tokenise_paths
    from src.monitoring.session_hwm import _short_path

    line = _FILE_IN_FRAME.sub(lambda m: m.group(1) + _short_path(m.group(2)) + m.group(3), line)
    line = tokenise_paths(line)
    if len(line) > _TRACE_LINE_CHARS:
        line = line[: _TRACE_LINE_CHARS - 1] + "\u2026"
    if len(line.encode("utf-8")) > _TRACE_LINE_BYTES:
        line = line.encode("utf-8")[: _TRACE_LINE_BYTES - 3].decode("utf-8", "ignore") + "\u2026"
    return _within_json_bytes(line)


def _within_json_bytes(line: str) -> str:
    """``line`` cut so that it takes at most ``_TRACE_LINE_BYTES`` bytes AS WRITTEN IN THE MEMBER (JSON, UTF-8, not ASCII-escaped).
    Escaping multiplies a quote or a backslash by two and a control character by six, so a hostile line that fits the raw cap could
    take 1,199 bytes; counting the written bytes makes the member's worst case the line count times one figure, whatever the text."""
    import json

    if len(json.dumps(line, ensure_ascii=False).encode("utf-8")) - 2 <= _TRACE_LINE_BYTES:
        return line
    ellipsis = "\u2026"
    used, out = len(ellipsis.encode("utf-8")), []
    for ch in line:
        w = len(json.dumps(ch, ensure_ascii=False).encode("utf-8")) - 2
        if used + w > _TRACE_LINE_BYTES:
            break
        out.append(ch)
        used += w
    return "".join(out) + ellipsis


def _read_log(path: Path) -> tuple[list[str], bool]:
    """The trace log as it was WRITTEN: its bytes decoded as UTF-8 and split on LF alone, and whether they
    decoded. ``read_text().splitlines()`` rewrote what the scrub has to see: it splits on CR, VT, FF, FS,
    GS, RS, NEL and the two Unicode separators too, so a passphrase holding one of them came out as two
    lines that no form matches. A trailing CR is left on the line (a log a Windows build wrote has CR LF
    ends); it is taken off after the scrub. A log that is not valid UTF-8 is read with the bad bytes
    replaced, only to find its headers, and says it did not decode: every report made from it is withheld.
    Raises ``OSError`` when the file cannot be read."""
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8").split("\n"), True
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace").split("\n"), False


_NOT_UTF8 = "<text withheld, the trace log is not valid UTF-8 and could not be checked for the passphrase>"


#: ``crashing_thread_kind``: what the dump says about the thread that aborted. DERIVED from the first faulthandler block, nothing more.
#: ``python``: a block labelled "Current thread" exists (a thread with a Python thread state, such as a collect worker inside lxml).
#: ``non-python``: thread blocks exist and none is labelled "Current thread": faulthandler labels only a thread it holds a Python thread
#: state for, so the abort ran on a thread Python did not create (a native pool thread) -- an INFERENCE from how faulthandler labels,
#: not read from the dump. ``not-in-dump``: no thread block at all (an uncaught exception, or a header with nothing under it).
#: ``withheld`` / ``no-trace`` are the two cases with no readable dump (``why_no_trace`` says why on a row).
KIND_PYTHON, KIND_NON_PYTHON, KIND_NOT_IN_DUMP = "python", "non-python", "not-in-dump"
KIND_WITHHELD, KIND_NO_TRACE = "withheld", "no-trace"


def _withheld(body: list[str], source: Path, why: str | None = None) -> dict[str, Any]:
    from src.monitoring.diagnostics_runs import WITHHELD

    return {
        "summary": why or WITHHELD, "lines": [], "lines_total": len(body), "source": Path(source).name,
        "withheld": True,
        "crashing_thread_kind": KIND_WITHHELD,
    }


def _without_torn_starts(body: list[str]) -> list[str] | None:
    """``body`` with the front of each "Uncaught exception ended the server" block made safe: an older
    writer cut that block's text from the front BEFORE it took the passphrase out, so the block can begin
    with what is left of a passphrase the cut fell inside. ``None`` when that could not be established."""
    from src.monitoring.diagnostics_runs import without_a_torn_start

    starts = [i for i, ln in enumerate(body) if ln.startswith("Uncaught exception")]
    if not starts:
        return body
    out = body[: starts[0] + 1]
    for n, i in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(body)
        block = without_a_torn_start("\n".join(body[i + 1 : end]))
        if block is None:
            return None
        out += block.split("\n") if block else []
        if n + 1 < len(starts):
            out.append(body[end])
    return out


def _fair_lines(ordered: list[str], max_lines: int, crashing: bool = True) -> tuple[list[str], dict[str, Any] | None]:
    """The lines a report keeps of a dump (``ordered`` has the crashing thread's block first) and, when it cut anything, the counts and
    the rule of the cut. A dump that fits is kept whole. Otherwise: whatever precedes the first thread, then the crashing thread's block
    (whole while it fits in the room), then every other thread to its first lines (its top frames), so a dump of 50 workers shows what
    each was doing and not only the first few. Threads the room cannot reach are COUNTED as not listed. The cut shrinks what is printed,
    never what is counted (``lines_total`` is the log's own). ``crashing`` is False when the dump labels no thread "Current thread": then
    NO block is called the crashing one, and every thread shares the room alike."""
    if len(ordered) <= max_lines:
        return ordered, None
    heads = [i for i, ln in enumerate(ordered) if _THREAD_HEAD.match(ln)]
    if not heads:
        kept = ordered[:max_lines]
        return kept, {
            "lines_kept": len(kept),
            "cut_note": f"the first {len(kept)} of {len(ordered)} lines are kept (the dump has no thread blocks to share the room between)",
        }
    pre = ordered[: heads[0]]
    ends = heads[1:] + [len(ordered)]
    blocks = [ordered[h:e] for h, e in zip(heads, ends, strict=True)]
    pre_cut = 0
    # the lines before the first thread get at most a quarter of the room, and less when the crashing block needs it whole
    pre_room = max(min(max_lines // 4, max_lines - (len(blocks[0]) if crashing else 0)), 2)
    if len(pre) > pre_room:
        # an escaped exception can precede the dump: its first lines and its LAST (the exception itself), never the room the threads need
        pre_cut = len(pre) - pre_room
        pre = pre[: pre_room // 2] + pre[len(pre) - (pre_room - pre_room // 2) :]
    if crashing:
        kept = pre + blocks[0][: max(max_lines - len(pre), 0)]
        rest = blocks[1:]
    else:
        kept, rest = list(pre), blocks
    room = max_lines - len(kept)
    takes: list[int] = []
    if rest and room > 0:
        share = max(room // len(rest), 2)  # a head line and one frame at least, while the room lasts
        for blk in rest:
            if room < 2:
                break
            take = min(len(blk), share, room)
            takes.append(take)
            room -= take
        # what the shares left over (a short thread gave some back) goes to the threads that were cut, one line at a time round the
        # list, so that no thread is given the whole of it
        grown = True
        while room > 0 and grown:
            grown = False
            for i, blk in enumerate(rest[: len(takes)]):
                if room > 0 and takes[i] < len(blk):
                    takes[i] += 1
                    room -= 1
                    grown = True
    for blk, take in zip(rest, takes, strict=False):
        kept += blk[:take]
    listed = len(takes)
    omitted = len(rest) - listed
    note = (
        f"{len(kept)} of {len(ordered)} lines are kept: "
        + ("the crashing thread's block first, then each other thread's first lines (its top frames); " if crashing
           else "no thread is marked as the crashing one, so every thread's first lines (its top frames) are kept alike; ")
        + (f"{omitted} of {len(rest)} {'other ' if crashing else ''}threads are not listed" if omitted else "every thread is listed")
        + (f"; {pre_cut} lines before the first thread are cut from the middle" if pre_cut else "")
    )
    return kept, {"lines_kept": len(kept), "threads_total": len(blocks), "threads_not_listed": omitted, "cut_note": note}


def _trace_report(
    body: list[str], source: Path, max_lines: int, *, decodable: bool = True
) -> dict[str, Any]:
    """A trace as the report carries it. The WHOLE body is taken through the one scrub before anything
    is chosen or cut (the head search, the thread order, the line limits and the per-line cut): an older
    log, written before ``note_fatal_exception`` scrubbed, can hold an exception's text with the engine's
    statement in it, and a cut that fell inside a passphrase would keep the part it left. The body is the
    log's lines exactly as written (``_read_log``), and the scrub also reads them in the form a Windows
    text-mode writer left a passphrase that holds an LF in. A body that cannot be made free of the
    passphrase, or that did not decode, is withheld whole."""
    from src.monitoring.diagnostics_runs import scrubbed_text

    if not decodable:
        return _withheld(body, source, _NOT_UTF8)
    safe = _without_torn_starts(body)
    clean = scrubbed_text("\n".join(safe), file_text=True) if safe is not None else None
    if clean is None:
        return _withheld(body, source)
    body = [ln.rstrip("\r") for ln in clean.split("\n")]
    ordered = _crashing_thread_first(body)
    head = next(
        (ln.strip() for ln in body if ln.startswith(("Fatal Python error", "Uncaught exception"))),
        body[0].strip(),
    )
    current = next((ln for ln in body if _THREAD_HEAD.match(ln) and ln.startswith("Current thread")), None)
    kept, cut = _fair_lines(ordered, max_lines, crashing=current is not None)
    out: dict[str, Any] = {
        "summary": _trace_line(head),
        "lines": [_trace_line(ln) for ln in kept],
        "lines_total": len(body),
        "source": Path(source).name,
    }
    # Which thread aborted is what faulthandler labels "Current thread"; without that label nothing says, and the busiest thread is
    # never offered in its place (an earlier reading took it for the one that aborted).
    has_blocks = any(_THREAD_HEAD.match(ln) for ln in body)
    out["crashing_thread_kind"] = KIND_PYTHON if current is not None else (KIND_NON_PYTHON if has_blocks else KIND_NOT_IN_DUMP)
    if current is not None:
        out["crashing_thread"] = _trace_line(current.strip())
    else:
        out["crashing_thread"] = None
        out["crashing_thread_reason"] = (
            "the dump marks no thread as the current one (an uncaught exception, or a dump without that label), so none is named"
        )
    if cut:
        out.update(cut)
    return out


def previous_trace(
    pid: int | None, boot_id: str | None = None, started_at: str | None = None
) -> dict[str, Any] | None:
    """What the crash trace holds for the session with ``pid`` (in machine boot ``boot_id`` and begun
    at ``started_at``, when known), or None when it holds nothing: that session did not die of a native
    fault or a Python exception (or predates the trace), which is itself worth knowing beside a SIGKILL."""
    if not isinstance(pid, int):
        return None
    path = crash_trace_path()
    for candidate in (path, path.with_name(CRASH_TRACE + ".1")):
        try:
            lines, decoded = _read_log(candidate)
        except OSError:
            continue
        found, body = _trace_in(lines, pid, boot_id, started_at)
        if not found:
            continue
        return _trace_report(body, candidate, _TRACE_REPORT_LINES, decodable=decoded) if body else None
    return None


# --------------------------------------------------------------------------- #
#  3b. The traces of the EARLIER unclean ends (finding D, 2026-10-01)
# --------------------------------------------------------------------------- #

#: How many earlier unclean ends the report carries, newest first. The newest end keeps ``NEWEST_EARLIER_TRACE_LINES`` and the others
#: ``EARLIER_TRACE_LINES`` of at most ``_TRACE_LINE_BYTES`` bytes of UTF-8 each: (400 + 9 x 120) x 206 = about 305 KB whatever the text holds (every line is cut to 202 bytes AS WRITTEN, escapes counted; 4 more for its quotes and separator)
#: (a trace line is about 100 characters of ASCII, so a real crash is nearer half of that). Where a part ends is the volume writer's business. A machine that crashed 9 times in 5 hours is the case that prompted it, and an
#: older end is still in the ledger and the chronology.
EARLIER_ENDS_LIMIT = 10
#: Lines of trace kept per earlier end: the fatal-error header, the crashing thread's block (about 103 lines at faulthandler's 100-frame
#: cap) and the top of the other threads; the one PREVIOUS session keeps ``_TRACE_REPORT_LINES`` (400).
EARLIER_TRACE_LINES = 120
#: Lines kept of the NEWEST earlier end: the one a reader opens first, and a real crash (50 collect workers, 1,336 lines) did not fit in 60.
#: Worst case of the member: (400 + 9 x 120) x 206 bytes as written = about 305 KB, whatever the text holds, against the +125 KB the plan's estimate holds for it.
NEWEST_EARLIER_TRACE_LINES = 400
#: Signals a process can leave a faulthandler trace for. SIGKILL is not among them: nothing runs after it.
_NATIVE_FAULT_SIGNALS = ("SIGSEGV", "SIGABRT", "SIGBUS", "SIGILL", "SIGFPE")


def _why_no_trace(exit_seen: dict[str, Any] | None, header_found: bool) -> str:
    """The cause of an absent trace, by what the session ended by -- an absence is a finding too,
    and "none" read the same for a SIGKILL (expected) and a SIGABRT (a gap). ``exit_seen`` is the
    launcher's record of the end, or None when it holds none."""
    signal_name = (exit_seen or {}).get("signal")
    signal_name = signal_name if isinstance(signal_name, str) and signal_name else None
    held = (
        "the trace log holds this session's header with nothing under it"
        if header_found
        else "the trace log holds nothing for its pid and boot"
    )
    if signal_name == "SIGKILL":
        return "a SIGKILL leaves no trace: nothing can write one from inside the process"
    if signal_name in _NATIVE_FAULT_SIGNALS:
        if header_found:
            return (
                f"ended by {signal_name} and the trace log holds this session's header with nothing "
                "under it: the process died before faulthandler wrote a stack"
            )
        return (
            f"ended by {signal_name}, which leaves a trace, and the trace log holds no header for this "
            "pid and boot: it was rotated away (one older generation is kept), the run predates the "
            "trace, or OO_CRASH_TRACE=0 was set"
        )
    if signal_name:
        return f"ended by {signal_name}, which is not a fault signal: no trace is expected"
    if exit_seen:
        status = exit_seen.get("status")
        return (
            f"the launcher saw it exit with status {status}; a trace is left only when an uncaught "
            f"exception ended the server, and {held}"
        )
    return f"the launcher recorded no exit for this session, and {held}"


def earlier_unclean_ends(
    prev: dict[str, Any] | None = None,
    *,
    limit: int = EARLIER_ENDS_LIMIT,
    max_lines: int = EARLIER_TRACE_LINES,
    records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The session ledger's unclean ends before the previous session, newest first, each with
    what the trace log holds for its process.

    The bundle used to read the trace of the PREVIOUS session's pid only, so on a crash loop
    every earlier crash's stack stayed on the machine (two SIGABRTs of one instance, on disk and
    in no bundle). ``prev`` is the sentinel the previous session left, so that session -- which
    has its own, fuller entry -- is not listed twice."""
    if records is None:
        try:
            from src.monitoring.session_history import read_records

            records = read_records()
        except Exception as exc:  # noqa: BLE001 - forensics degrades, never raises
            return {"available": False, "reason": f"the session ledger could not be read ({type(exc).__name__})"}
    boots: dict[str, dict[str, Any]] = {
        str(r.get("session_id")): r for r in records if r.get("kind") == "boot" and r.get("session_id")
    }
    prev_pid = (prev or {}).get("pid") if isinstance(prev, dict) else None
    prev_boot = (prev or {}).get("boot_id") if isinstance(prev, dict) else None
    prev_started = _when((prev or {}).get("started_at")) if isinstance(prev, dict) else None
    ends: list[dict[str, Any]] = []
    for r in records:
        if r.get("kind") != "end" or r.get("clean") is not False:
            continue
        b = boots.get(str(r.get("session_id")))
        if b is not None and isinstance(prev_pid, int) and b.get("pid") == prev_pid and _same_boot(
            b.get("machine_boot_id"), prev_boot if isinstance(prev_boot, str) else None
        ):
            # The previous session has its own, fuller entry. A pid is not an identity (the machine
            # reuses them, and where the boot is unknown nothing else tells two sessions apart), so
            # the moment it began is compared too, whenever both records carry one.
            began = _when(b.get("at"))
            if prev_started is None or began is None or abs(began - prev_started) <= _SAME_START_S:
                continue
        ends.append(r)
    ends.reverse()  # newest first
    log = crash_trace_path()
    rotated = log.with_name(CRASH_TRACE + ".1")

    def _size(p: Path) -> int | None:
        try:
            return p.stat().st_size
        except OSError:
            return None

    out: dict[str, Any] = {
        "method": (
            "The session ledger's unclean ends before the previous session, newest first, each looked "
            f"up in the crash trace log by the pid and machine boot its boot record carries (up to "
            f"{max_lines} lines of its trace, {max(max_lines, NEWEST_EARLIER_TRACE_LINES) if max_lines == EARLIER_TRACE_LINES else max_lines} for the newest: the crashing thread whole, then the top of "
            "every other thread; a trace that is cut says how many lines and threads it kept). A session with no trace says why, by what it ended by; "
            "a SIGKILL cannot leave one. The log keeps one rotated generation, so an old end may have "
            "lost its trace to rotation. 'launcher_stderr' is the C library's abort message the launcher filter recorded for that pid "
            "and boot for the newest " f"{STDERR_ROWS_SHOWN} ends only (null: the launcher left no record for it; absent: an older end, not looked up)."
        ),
        "limit": limit,
        "lines_per_trace": max_lines,
        "lines_newest_trace": max(max_lines, NEWEST_EARLIER_TRACE_LINES) if max_lines == EARLIER_TRACE_LINES else max_lines,
        "unclean_ends_in_ledger": len(ends),
        "shown": 0,
        "older_not_shown": 0,
        "trace_log": {"bytes": _size(log), "rotated_bytes": _size(rotated)},
        "sessions": [],
    }
    reads: dict[Path, tuple[list[str], bool] | None] = {}

    def _lines(p: Path) -> tuple[list[str], bool] | None:
        if p not in reads:
            try:
                reads[p] = _read_log(p)
            except OSError:
                reads[p] = None
        return reads[p]

    for n_end, end in enumerate(ends[:limit]):
        end_lines = max(max_lines, NEWEST_EARLIER_TRACE_LINES) if n_end == 0 and max_lines == EARLIER_TRACE_LINES else max_lines
        sid = str(end.get("session_id"))
        b = boots.get(sid)
        pid = (b or {}).get("pid")
        boot = (b or {}).get("machine_boot_id")
        row: dict[str, Any] = {
            "session_id": sid, "pid": pid, "started_at": (b or {}).get("at"), "ended_at": end.get("at"),
        }
        exit_seen = end.get("exit") if isinstance(end.get("exit"), dict) else None
        if exit_seen is None and isinstance(pid, int):
            try:
                exit_seen = launcher_exit(pid, boot if isinstance(boot, str) else None)
            except Exception:  # noqa: BLE001
                exit_seen = None
        signal_name = (exit_seen or {}).get("signal")
        row["signal"] = signal_name
        if exit_seen and not signal_name:
            # An exit by status (an error exit) has no signal to show: say what the launcher saw.
            row["status"], row["kind"] = exit_seen.get("status"), exit_seen.get("kind")
        if not isinstance(pid, int):
            row["trace"] = None
            row["why_no_trace"] = "the ledger no longer holds this session's boot record, so its pid is unknown"
            row["crashing_thread_kind"] = KIND_NO_TRACE
            out["sessions"].append(row)
            continue
        found_any = False
        trace = None
        for cand in (log, rotated):
            read = _lines(cand)
            if read is None:
                continue
            found, body = _trace_in(read[0], pid, boot if isinstance(boot, str) else None, (b or {}).get("at"))
            if found:
                found_any = True
                if body:
                    trace = _trace_report(body, cand, end_lines, decodable=read[1])
                break
        row["trace"] = trace
        if n_end < STDERR_ROWS_SHOWN:
            row["launcher_stderr"] = launcher_stderr(pid, boot if isinstance(boot, str) else None)
        if trace is None:
            row["why_no_trace"] = _why_no_trace(exit_seen, found_any)
            row["crashing_thread_kind"] = KIND_NO_TRACE
        out["sessions"].append(row)
    out["shown"] = len(out["sessions"])
    out["older_not_shown"] = max(0, len(ends) - out["shown"])
    return out


# --------------------------------------------------------------------------- #
#  The combined account
# --------------------------------------------------------------------------- #


# Verdicts of the two journal readers that mean "did not look" -- could not (`no-journal`,
# `no-journalctl`) or was told not to (`disabled`, the operator's own opt-out) -- as opposed to
# "looked and found nothing" (`no-kernel-evidence`, `no-userspace-evidence`). An opted-out read is
# still a gap: a summary built on it must not assert that no journal line named the app.
_JOURNAL_UNREAD = ("no-journal", "no-journalctl", "disabled")


def _why_unread(*witnesses: dict[str, Any] | None) -> str:
    """One short cause for a journal that was not read, from the witnesses' own reasons.

    The permission gap is named as such (it is the common one and the one an operator can fix);
    anything else keeps the first witness's own words, which already say what failed."""
    for w in witnesses:
        if w and (w.get("permission_note") or HINT_NO_ACCESS in str(w.get("reason", ""))
                  or "cannot read the system journal" in str(w.get("reason", ""))):
            return "this user is not in 'adm' or 'systemd-journal'"
    for w in witnesses:
        reason = (w or {}).get("reason")
        if reason:
            return str(reason)[:160]
    return "no reason recorded"


def how_it_ended(
    *,
    launcher: dict[str, Any] | None,
    killers: dict[str, Any] | None,
    kernel: dict[str, Any] | None,
    trace: dict[str, Any] | None,
    drive: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One sentence on how the previous session ended, built ONLY from the witnesses
    that answered, each named. Never a guess: with no witness it says so."""
    parts: list[str] = []
    gaps: list[str] = []
    if drive:
        # The data-drive incident log (R86) lives on the internal disk: the one witness
        # that can speak when the drive holding the session sentinel was the thing lost.
        parts.append(f"the data drive was reported disconnected at {drive.get('at')} ({drive.get('detected_by')})")
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
    # THE TWO JOURNAL WITNESSES IN ONE SENTENCE. They read the same journal with the same
    # permissions, so the account of one must agree with the account of the other: where
    # either could not look, say so ONCE, naming which, instead of letting one witness assure
    # ("no kernel line names us") beside the other's "cannot read the system journal". A
    # witness that could not look is a gap in the evidence, never evidence of absence.
    k_blind = kverdict in _JOURNAL_UNREAD
    u_blind = uverdict in _JOURNAL_UNREAD
    if k_blind and u_blind:
        gaps.append(
            "neither the kernel log nor the memory killers' log was read "
            f"({_why_unread(kernel, killers)}), so no account of a kill from either was "
            "observed: a gap in the witnesses, not evidence that nothing killed it"
        )
    elif k_blind:
        gaps.append(
            f"the kernel log was not read ({_why_unread(kernel)}), so a kill the kernel "
            "logged would not show here"
        )
    elif u_blind:
        gaps.append(
            f"the memory killers' log was not read ({_why_unread(killers)}), so a kill "
            "systemd-oomd or earlyoom logged would not show here"
        )
    if not parts:
        return {
            "known": False,
            "summary": (
                f"no witness named how it ended: no launcher record, no crash trace, and {'; '.join(gaps)}"
                if gaps
                else "no witness named how it ended: no launcher record, no journal line from a "
                "memory killer or the kernel, and no crash trace"
            ),
        }
    return {"known": True, "summary": "; ".join(parts + gaps)}
