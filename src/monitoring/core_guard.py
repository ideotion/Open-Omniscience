"""
Keep a crash of this process from leaving a core dump that holds the passphrase.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY IT EXISTS (release run, 2026-10-06). Once the store is unlocked its passphrase and its key are in the memory of the
process that opened it (``docs/SECURITY.md``: the at-rest threat model says so), and a native crash (SIGSEGV, SIGABRT,
SIGBUS) asks the kernel to write that memory out as a core dump. Where it goes is not the app's choice: a file in the
working directory, or a pipe to a handler (systemd-coredump, apport, abrt) that keeps it for weeks under a path nobody
looks at. Machines of this project have been crashing; a dump of one of them is the passphrase, in a file, on a drive.

WHAT IT DOES. :func:`engage` sets ``RLIMIT_CORE`` to exactly ``(1, 1)``, soft and hard, in THIS process. The value is 1
and not 0 for a measured reason (kernel 6.18.44, a piped handler against a file pattern, the same child killed by SIGSEGV
at each limit)::

    RLIMIT_CORE      0        1        2     4096    1 MiB   unlimited
    piped handler    full     nothing  full  full    full    full
    file pattern     none     none     none  3,929 B 1.5 MB full

The kernel ignores the limit for a piped pattern except at exactly 1, which it takes for its own recursion guard and
aborts the dump, logging ``coredump: 9390(python): RLIMIT_CORE is set to 1, aborting core`` (that kernel's words; older
ones write ``Process 9390(python) has RLIMIT_CORE set to 1``). So ``ulimit -c 0``, the usual advice,
leaves a full dump in a handler's hands, and a shell cannot set 1 at all (bash's ``ulimit -c 1`` is 1024 bytes, dash's
is 512). A file pattern writes nothing below a page. systemd-coredump honours the limit it is handed; apport does not
for the report it builds, which is why a limit that stops the handler from being run at all is the only one that works.
An rlimit is inherited through ``fork`` and ``exec`` and only ever lowered, so every child of this process (a worker,
an LLM server, the restore child) is covered the moment it exists, with no code of its own.

WHERE THE LIMIT CANNOT BE SET. A launcher that ran ``ulimit -c 0`` (soft and hard) leaves a hard limit of 0, and a limit
is only lowered: ``setrlimit`` then fails and nothing in this process can raise it. :func:`engage` then falls back to
``prctl(PR_SET_DUMPABLE, 0)``, which makes the kernel write no dump of THIS process whatever the pattern says. That is
weaker in three ways, each stated in :func:`status` rather than hidden: it is reset by ``exec`` (a child must call
:func:`engage` itself, and is dumpable until it does; ``secret_scrub.guard_process`` and the restore child do), a child that
is not Python never does, and a process that is not dumpable cannot be read through ``/proc`` by its own user the way it
was (``/proc/<pid>/io``, ``fd``, ``environ`` and ``mem`` become root's; ``status``, ``statm``, ``maps`` and ``stat`` stay
readable, which is what the app's own vitals use) and cannot be attached to by a debugger of the same user. A caller that
cannot accept that (the OSM reference run, whose children hold the passphrase from their first instruction)
asks for ``strict=True`` and is refused instead.

WHAT IT DOES NOT COVER, and says so wherever it is shown: a crash dump the OS kept before this version ran (the
lister below names what is on this machine), a hibernation image, swap and a crash kernel's capture, a hypervisor's
snapshot of the machine, root raising the limit, and a process that holds a passphrase and reaches none of the places
that call this. The boot record
(``session_history.record_boot``, key ``core_guard``) names which mechanism a session ran under, so "no dump" is never
read as "no crash": the launcher's exit record and ``faulthandler``'s trace still say a process died of a signal, and
the kernel logs the line quoted above for a piped pattern, which ``kernel_log`` matches as a native crash (a handler's
own "dumped core" line, systemd-coredump's, no longer exists for a process held to 1: the handler is never run).

Stdlib only, importable before anything else, so the first line of an entry point can call it, and never imports the
store: ``src/database/connect.py`` calls it (through ``secret_scrub.guard_process``), not the other way round.
"""

from __future__ import annotations

import contextlib
import fnmatch
import os
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: The one value that stops every kind of dump (the table above): 0 leaves a piped handler a full dump.
CORE_LIMIT = 1

#: ``prctl`` option numbers from ``<linux/prctl.h>``; ctypes has no names for them.
_PR_GET_DUMPABLE = 3
_PR_SET_DUMPABLE = 4
_CORE_PATTERN = Path("/proc/sys/kernel/core_pattern")

_REFUSED = (
    "core dumps cannot be limited in this process (the hard core limit is already 0, or this system has no such limit)"
)


class CoreGuardError(RuntimeError):
    """The guard could not be engaged where the caller required it (``engage(strict=True)``). The message is fixed text:
    no path, no environment and no secret is in it."""


def _resource() -> Any:
    """The ``resource`` module, or ``None`` where there is none (Windows has no per-process core limit to set)."""
    try:
        import resource
    except ImportError:
        return None
    return resource


def _prctl(option: int, arg: int = 0) -> int | None:
    """``prctl(option, arg)``'s result, or ``None`` where it cannot be called (not Linux, no ctypes, no such symbol).
    Only the two dumpable options are ever passed, both with arguments the kernel ignores beyond the first."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
        libc.prctl.restype = ctypes.c_int
        return int(libc.prctl(option, arg, 0, 0, 0))
    except (OSError, AttributeError, ImportError, ValueError):
        return None


def _shown(resource: Any, value: int) -> int | str:
    return "unlimited" if value == resource.RLIM_INFINITY else int(value)


def _read_pattern() -> str | None:
    """The kernel's ``core_pattern`` (Linux), or ``None`` where it cannot be read."""
    try:
        return _CORE_PATTERN.read_text(encoding="utf-8", errors="replace").strip() or None
    except OSError:
        return None


def pattern_handler() -> str | None:
    """Where the kernel sends a dump of this machine, as one word: ``"file"`` for a pattern that writes a file, else the
    name of the program a piped pattern hands it to (``systemd-coredump``, ``apport``, ``abrt-hook-ccpp``), by its file
    name alone, never its path or its arguments. ``None`` where the pattern is not readable (not Linux, or not allowed)."""
    pattern = _read_pattern()
    if pattern is None:
        return None
    if not pattern.startswith("|"):
        return "file"
    program = pattern[1:].strip().split(None, 1)
    return os.path.basename(program[0]) if program else "unreadable"


def _held() -> dict[str, Any]:
    """The part of :func:`status` that is the process's own and is read with a syscall each: the limit, the dumpable flag
    and the mechanism they add up to."""
    out: dict[str, Any] = {"mechanism": "none", "soft": None, "hard": None, "dumpable": None, "inherited_by_children": False}
    resource = _resource()
    if resource is not None:
        with contextlib.suppress(ValueError, OSError):
            soft, hard = resource.getrlimit(resource.RLIMIT_CORE)
            out["soft"], out["hard"] = _shown(resource, soft), _shown(resource, hard)
    dumpable = _prctl(_PR_GET_DUMPABLE)  # -1 is the call's own failure: unread, not a value
    out["dumpable"] = dumpable if dumpable in (0, 1, 2) else None
    if out["soft"] == CORE_LIMIT and out["hard"] == CORE_LIMIT:
        out["mechanism"] = "rlimit"
        out["inherited_by_children"] = True
    elif out["dumpable"] == 0:
        out["mechanism"] = "dumpable"
    elif resource is None and out["dumpable"] is None:
        out["mechanism"] = "unsupported"
    return out


def status() -> dict[str, Any]:
    """What THIS process's dumps are held to, read live (nothing is remembered, so a record cannot go stale):

    * ``mechanism``: ``"rlimit"`` (``RLIMIT_CORE`` is exactly 1, soft and hard: no dump of this process or of any
      descendant, whatever the pattern), ``"dumpable"`` (the limit could not be set and this process asked the kernel
      not to dump it: a descendant is not covered), ``"none"`` (neither), ``"unsupported"`` (no per-process core limit
      here, and no other mechanism);
    * ``soft`` and ``hard``: the limit as the kernel holds it (a number of bytes or ``"unlimited"``), ``None`` where it
      cannot be read;
    * ``dumpable``: ``prctl(PR_GET_DUMPABLE)`` (0 not, 1 yes, 2 root only), ``None`` where it cannot be read;
    * ``inherited_by_children``: whether a process this one starts is covered with no code of its own;
    * ``handler``: :func:`pattern_handler`; ``platform``: ``sys.platform``.

    Compact enough for the boot record, and never raises."""
    out = _held()
    out["handler"] = None
    with contextlib.suppress(Exception):  # a record of the guard is never the thing that breaks a boot
        out["handler"] = pattern_handler()
    out["platform"] = sys.platform
    return out


def engage(*, strict: bool = False) -> dict[str, Any]:
    """Set the guard in THIS process and return :func:`status`. Idempotent: a process already held to ``(1, 1)`` is left
    alone. Called first by every entry point that can hold the passphrase, and by ``secret_scrub.guard_process`` (with the
    log filter) wherever a process comes to hold one or hands one to the engine: the server's lifespan, ``connect.set_passphrase``
    and the store's key-handing functions (the net for an entry point that forgot, and for a key that is typed into a request
    and reaches the engine before anything holds it), before the passphrase is read or used.

    Not strict (the default), it never raises: it sets ``RLIMIT_CORE`` to ``(1, 1)``, and where that is refused it
    makes the process non-dumpable, and ``status()["mechanism"]`` says which of them held. Strict, it requires the
    ``rlimit`` mechanism, because that is the one a child inherits: it raises :class:`CoreGuardError` otherwise,
    and tries nothing weaker."""
    now = _held()
    if now["mechanism"] != "rlimit":
        resource = _resource()
        if resource is not None:
            # ValueError: "not allowed to raise maximum limit", the hard limit is already 0 (``ulimit -c 0``).
            with contextlib.suppress(ValueError, OSError):
                resource.setrlimit(resource.RLIMIT_CORE, (CORE_LIMIT, CORE_LIMIT))
            now = _held()
        if now["mechanism"] != "rlimit" and not strict:
            _prctl(_PR_SET_DUMPABLE, 0)
            now = _held()
    if strict and now["mechanism"] != "rlimit":
        raise CoreGuardError(_REFUSED)
    return status()


# --------------------------------------------------------------------------- #
#  What a crash left behind
# --------------------------------------------------------------------------- #

#: Where a dump of a process of this user can be on each system, by a label that says what the place is: the listing
#: carries the label and never the path (a path names a user and a home). ``(label, glob of the file names)``.
_PLACES: tuple[tuple[str, str, str], ...] = (
    ("crash-report directory", "/var/crash", "*.crash"),
    ("crash-report directory", "/var/crash", "core*"),
    ("systemd-coredump store", "/var/lib/systemd/coredump", "core.*"),
    ("cores directory", "/cores", "core.*"),
)
#: The names a kernel pattern writes by default, in the working directory of the process that crashed.
_DEFAULT_NAMES = ("core", "core.*", "*.core", "vgcore.*")


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _pattern_places() -> list[tuple[str, Path, str]]:
    """The directory and the file names a FILE pattern of this machine writes to (a pipe has none): ``%e``, ``%p`` and
    the like become wildcards. A relative pattern (the kernel's own ``core``) is written in the crashed process's working
    directory, so it is not placed here: the caller names the directories it runs from."""
    pattern = _read_pattern()
    if not pattern or not os.path.isabs(pattern):  # a pipe starts with "|", which is not a path either
        return []
    glob = re.sub(r"%[a-zA-Z%]", "*", os.path.basename(pattern)) or "core"
    return [("core-pattern directory", Path(os.path.dirname(pattern)), glob)]


def _scan(label: str, directory: Path, globs: tuple[str, ...]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """One directory, by name and by the file's own metadata, never by what is in it: nothing is opened. A directory that
    cannot be listed is reported as not readable, never as empty."""
    summary: dict[str, Any] = {"where": label, "readable": False, "files": 0, "bytes": 0}
    found: list[dict[str, Any]] = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if not any(fnmatch.fnmatchcase(entry.name, g) for g in globs):
                    continue
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                found.append({"where": label, "name": entry.name, "bytes": int(st.st_size), "modified": _iso(st.st_mtime)})
    except OSError:
        return summary, []
    summary.update(readable=True, files=len(found), bytes=sum(d["bytes"] for d in found))
    return summary, found


def list_core_dumps(extra_dirs: Mapping[str, str | os.PathLike[str]] | None = None) -> dict[str, Any]:
    """The core dumps and crash reports this machine holds where a crash of this app would have left them: each
    one's file name, size and modification time under a label for its directory (``crash-report directory``,
    ``systemd-coredump store``, ``core-pattern directory``, ``working directory``, ...), newest first. NOTHING is opened
    and no content is read; a directory that cannot be listed is named in ``places`` as not readable, not as empty.

    ``extra_dirs`` maps a label to a directory the caller knows a crash would write into (the working directory and
    the data directory are always tried first). Returns ``{"handler", "places": [{where, readable, files, bytes}],
    "dumps": [{where, name, bytes, modified}]}``. A file's NAME can carry a program path or a user id (apport writes
    ``_usr_bin_python3.1000.crash``), so a caller that ships this scrubs paths as it does the rest of its report."""
    wanted: list[tuple[str, Path, tuple[str, ...]]] = []
    seen: set[tuple[str, str]] = set()

    def add(label: str, directory: str | os.PathLike[str], globs: tuple[str, ...]) -> None:
        key = (str(directory), ",".join(globs))
        if key not in seen:
            seen.add(key)
            wanted.append((label, Path(directory), globs))

    with contextlib.suppress(OSError):
        add("working directory", os.getcwd(), _DEFAULT_NAMES)
    for label, directory in (extra_dirs or {}).items():
        add(label, directory, _DEFAULT_NAMES)
    for label, directory, glob in _pattern_places():
        add(label, directory, (glob, *_DEFAULT_NAMES))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if sys.platform == "win32" and local_app_data:
        add("crash-dump directory", Path(local_app_data) / "CrashDumps", ("*.dmp",))
    for label, directory, glob in _PLACES:
        add(label, directory, (glob,))
    places: list[dict[str, Any]] = []
    dumps: list[dict[str, Any]] = []
    for label, directory, globs in wanted:
        if not directory.is_dir():
            continue
        summary, found = _scan(label, directory, globs)
        places.append(summary)
        dumps += found
    dumps.sort(key=lambda d: d["modified"], reverse=True)
    return {"handler": pattern_handler(), "places": places, "dumps": dumps}


def main(argv: list[str] | None = None) -> int:
    """``python -m src.monitoring.core_guard``: what this machine holds from a crash, as JSON. It reports the machine's own
    pattern and the files listed above and nothing about this command's own limits, which are not the app's (the
    app's are in its boot record)."""
    import json

    json.dump(list_core_dumps(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - the command line
    raise SystemExit(main())
