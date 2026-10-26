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

The machine tag is a one-way hash under this app's own label, never the raw ``/etc/machine-id``, because the record may be written to a drive that is shared.
"""

from __future__ import annotations

import hashlib
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


def owner_record() -> dict[str, Any]:
    """This process: pid, start time, host and machine tag. ``{}`` when the process cannot be inspected (the reader then judges the claim ``unknown``)."""
    try:
        import psutil

        proc = psutil.Process()
        return {"pid": proc.pid, "started": round(proc.create_time(), 3), "host": platform.node(), "machine": machine_tag()}
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
        return "unknown"  # another machine's job on a shared drive
    if theirs is not None and theirs != machine:
        return "unknown"  # the same name on another machine, or a tag this one cannot read
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
