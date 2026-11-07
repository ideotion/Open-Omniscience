"""
Who owns a file that says "I am working" (R183): a process on this machine that is alive, one that is gone, or one this machine cannot judge.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Before: only a backup's staging folder could say whose it was (pid, start time, host, machine tag), and the rule lived inside the backup module. Several servers may share
one data folder (R176), and the other files that mean "a job is running" (a corpus lease, the rollup build marker) could not tell a live second server from a dead one.

Now one record and one verdict. ``owner_record()`` is written beside the claim; ``record_state(record)`` answers ``alive`` / ``dead`` / ``unknown``:

* ``alive``: a process on THIS machine with that pid and that start time. Skip it (never take its work over).
* ``dead``: no such process, or the pid belongs to a later process (a recycled pid is told apart by the start time). Take over: the claim is a leftover.
* ``unknown``: another host or machine (a shared drive: its pid means nothing here), an unreadable record, or this process itself. Never taken over; the caller names it
  and fails closed.

**Clock steps (S2 = b, gate item 41, R261).** psutil's ``create_time()`` is the process's start ticks PLUS the current ``/proc/stat`` ``btime``, so a step of the wall clock of a second or more (NTP, ``date -s``, a VM resume) turned a live owner into "dead". On Linux the record therefore also carries boot-relative ``ticks`` (``/proc/<pid>/stat`` field 22 over ``SC_CLK_TCK``, which does not move with the clock), the kernel ``boot_id`` and the pid-namespace inode. Same boot: compare ticks. A different ``boot_id`` on the same host: the machine rebooted, the owner is dead. A different pid namespace: the pid means something else there, so ``unknown``. A record without the new fields, and macOS/Windows, keep the psutil comparison (still exposed to a step; stated, not fixed). Any doubt is ``unknown`` (fail closed).

The machine tag is a one-way hash under this app's own label, never the raw ``/etc/machine-id``, because the record may be written to a drive that is shared.
"""

from __future__ import annotations

import hashlib
import math
import os
import platform
from pathlib import Path
from typing import Any


def machine_tag() -> str | None:
    """A stable tag of THIS machine, beside its hostname: two machines that share a default name (``raspberrypi``, ``ubuntu``) and one folder on a NAS would otherwise
    judge each other's pids. ``None`` where the system keeps no machine id (Windows, macOS), where the hostname alone applies."""
    for name in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            raw = Path(name).read_text(encoding="ascii").strip()
        except (OSError, ValueError):
            continue
        if raw:
            return hashlib.sha256(f"open-omniscience-backup-owner:{raw}".encode()).hexdigest()[:16]
    return None


_PROC = "/proc"


def _boot_id() -> str | None:
    """The kernel's per-boot random id (Linux), or ``None`` where it cannot be read."""
    try:
        raw = Path(_PROC, "sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except (OSError, ValueError):
        return None
    return raw or None


def _pidns() -> int | None:
    """Inode of this process's pid namespace (Linux), or ``None``."""
    try:
        return os.stat(Path(_PROC, "self/ns/pid")).st_ino
    except OSError:
        return None


def _start_ticks(pid: int) -> float | None:
    """Seconds since boot at which ``pid`` started, from ``/proc/<pid>/stat`` field 22 over ``SC_CLK_TCK``. Unaffected by the wall clock. ``None`` when unreadable;
    raises ``FileNotFoundError`` when the process does not exist."""
    raw = Path(_PROC, str(pid), "stat").read_text(encoding="ascii", errors="replace")
    try:
        fields = raw[raw.rindex(")") + 2 :].split()  # the comm field may hold spaces and parentheses
        ticks = int(fields[19])  # field 22 overall; the list starts at field 3
        hz = os.sysconf("SC_CLK_TCK")
    except (ValueError, IndexError, OSError):
        return None
    return ticks / hz if hz > 0 else None


def _boot_fields(pid: int) -> dict[str, Any]:
    """``ticks``/``boot_id``/``pidns`` for ``pid`` when all three are readable (Linux), else ``{}`` (the psutil comparison then applies)."""
    try:
        ticks, boot, ns = _start_ticks(pid), _boot_id(), _pidns()
    except OSError:
        return {}
    if ticks is None or boot is None or ns is None:
        return {}
    return {"ticks": round(ticks, 3), "boot_id": boot, "pidns": ns}


def owner_record() -> dict[str, Any]:
    """This process: pid, start time, host and machine tag. ``{}`` when the process cannot be inspected (the reader then judges the claim ``unknown``)."""
    try:
        import psutil

        proc = psutil.Process()
        return {"pid": proc.pid, "started": round(proc.create_time(), 3), "host": platform.node(), "machine": machine_tag(), **_boot_fields(proc.pid)}
    except Exception:  # noqa: BLE001 - a claim with no owner record is judged "unknown", never "dead"
        return {}


def record_state(data: Any, *, machine: str | None = None) -> str:
    """``alive`` / ``dead`` / ``unknown`` for a record from :func:`owner_record`. ``machine`` is this machine's tag (default: :func:`machine_tag`)."""
    try:
        pid, started = int(data["pid"]), float(data["started"])
        host = data.get("host")
        theirs = data.get("machine")
    except (KeyError, TypeError, ValueError, AttributeError):
        return "unknown"
    if host is not None and str(host) != platform.node():
        return "unknown"  # another machine's job on a shared drive (a matching machine tag does not override this: machine ids are copied with cloned images)
    if theirs is not None and theirs != machine:
        return "unknown"  # the same name on another machine, or a tag this one cannot read
    if "ticks" in data and "boot_id" in data and "pidns" in data:
        return _boot_state(data, pid)
    try:
        import psutil

        if pid == os.getpid():
            if abs(psutil.Process().create_time() - started) < 1.0:
                return "unknown"  # this process itself: its own claims are judged by its registry, not here
            return "dead"  # the same pid with another start time: this process's dead predecessor (a container is given the same pid at every start)
        if not psutil.pid_exists(pid):
            return "dead"
        return "alive" if abs(psutil.Process(pid).create_time() - started) < 1.0 else "dead"
    except Exception as exc:  # noqa: BLE001 - psutil.NoSuchProcess is "dead", the rest "unknown"
        return "dead" if type(exc).__name__ == "NoSuchProcess" else "unknown"


def _boot_state(data: Any, pid: int) -> str:
    """The verdict from boot-relative fields. Never consults the wall clock; every doubt is ``unknown``."""
    try:
        pid = int(data["pid"])
        theirs_ticks, theirs_boot, theirs_ns = float(data["ticks"]), str(data["boot_id"]), int(data["pidns"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return "unknown"
    if pid <= 0 or not math.isfinite(theirs_ticks):
        return "unknown"  # a garbled record is never "dead"
    boot = _boot_id()
    if boot is None:
        return "unknown"
    if theirs_boot != boot:
        # Same host name and the same machine tag: another boot means the machine rebooted. Without a machine tag the name alone cannot tell a reboot from a second
        # machine that shares the name and the folder, so that case stays unknown.
        return "dead" if data.get("machine") is not None else "unknown"
    ns = _pidns()
    if ns is None or ns != theirs_ns:
        return "unknown"  # another pid namespace (a container): this pid means something else here
    try:
        ticks = _start_ticks(pid)
    except FileNotFoundError:
        try:
            os.kill(pid, 0)  # /proc mounted with hidepid hides another user's live process too
        except ProcessLookupError:
            return "dead"
        except OSError:
            return "unknown"
        return "unknown"
    except OSError:
        return "unknown"
    if ticks is None:
        return "unknown"
    same = abs(ticks - theirs_ticks) < 0.05
    if pid == os.getpid():
        return "unknown" if same else "dead"  # itself, or its dead predecessor under the same pid
    return "alive" if same else "dead"  # another start time: a recycled pid
