"""What a cgroup memory limit leaves this process, for decisions that otherwise read only the machine's figure (R302).

``psutil.virtual_memory()`` reads ``/proc/meminfo``: the HOST's memory. Inside a container or a service with a memory limit the
kernel kills the process at that limit while psutil still reports the host's gigabytes, so a verdict taken from psutil alone can
never decline (measured 2026-10-27: a 2,048 MB cgroup, psutil 15,542 MB available, a build needing 3,904 MB, verdict "go").

The walk over ``/proc/self/cgroup`` and every ancestor's limit is NOT done here: :func:`src.osm.reader.cgroup_reading` already does
it (v1 and v2, nested limits, ``max`` and the 2**63 "no limit", unreadable named and never read as unlimited), and two walkers would
come to disagree. This module adds the one thing a "can this build start" verdict needs on top of that reading: the page cache the
kernel reclaims before it kills (``inactive_file`` in ``memory.stat``), since usage counts it and a headroom without it under-reports
and declines builds the cgroup can hold, the wrong direction for a verdict that exists to decline only what cannot fit.
"""

from __future__ import annotations

import os
from typing import Any

#: The ``memory.stat`` key of reclaimable file cache, per layout (v1 prefers the hierarchical total).
_INACTIVE_KEYS = {"cgroup_v2": ("inactive_file",), "cgroup_v1": ("total_inactive_file", "inactive_file")}
_SUBDIR = {"cgroup_v2": "", "cgroup_v1": "memory"}


def _inactive_file_bytes(root: str, source: str, path: str) -> int | None:
    """The reclaimable file cache of the cgroup at ``path``, or None when ``memory.stat`` cannot say (never 0 by guess)."""
    rel = [p for p in (path or "/").split("/") if p and p != ".."]
    stat = os.path.join(root, _SUBDIR.get(source, ""), *rel, "memory.stat")
    try:
        with open(stat, encoding="ascii") as fh:
            values = dict(line.split(None, 1) for line in fh if " " in line)
    except (OSError, ValueError):
        return None
    for key in _INACTIVE_KEYS.get(source, ()):
        raw = values.get(key, "").strip()
        if raw.isdigit():
            return int(raw)
    return None


def cgroup_available_mb(root: str | None = None, proc_cgroup: str | None = None) -> dict[str, Any]:
    """``{"available_mb", "limit_mb", "source", "unreadable"}`` for the tightest memory limit this process is under.

    ``available_mb`` is limit less usage plus the reclaimable file cache (capped at the usage, so it never exceeds the limit). It is
    None when no limit is set at any level (``unreadable`` False) and when a limit or its usage exists and cannot be read
    (``unreadable`` True): None is "no figure", never 0, which would read as "no memory".
    """
    from src.osm import reader

    reading = reader.cgroup_reading(root or reader.CGROUP_ROOT, proc_cgroup or reader.PROC_CGROUP)
    head = reading.get("headroom_bytes")
    limit = reading.get("limit_bytes")
    source = reading.get("source")
    out: dict[str, Any] = {"available_mb": None, "limit_mb": None, "source": source, "unreadable": bool(reading.get("unreadable"))}
    if head is None or limit is None or source is None:
        return out
    # The reclaimable cache is added PER LEVEL and the tightest result wins: the level with the smallest raw headroom is not
    # always the tightest once its cache is counted (an ancestor full of a sibling's page cache beside a process cgroup full of
    # anonymous memory), and the kernel kills at whichever limit is reached first.
    levels = reading.get("levels") or [{"source": source, "limit_bytes": limit, "used_bytes": max(0, limit - head),
                                         "path": reading.get("path") or "/"}]
    avail: int | None = None
    for lvl in levels:
        l_limit, l_used = lvl["limit_bytes"], lvl["used_bytes"]
        inactive = _inactive_file_bytes(root or reader.CGROUP_ROOT, lvl["source"], lvl["path"])
        reclaim = min(inactive, l_used) if inactive is not None else 0
        room = max(0, l_limit - l_used) + reclaim
        if avail is None or room < avail:
            avail, limit = room, l_limit
    out["available_mb"] = round((avail if avail is not None else head) / (1024 * 1024), 1)
    out["limit_mb"] = round(limit / (1024 * 1024), 1)
    return out


def smaller_available_mb(machine_mb: float | None, cgroup: dict[str, Any] | None = None) -> tuple[float | None, str]:
    """The smaller of the machine's available memory and the cgroup's, and which one it was.

    The name is ``"cgroup limit"`` or ``"machine"``; ``"machine (a cgroup limit could not be read)"`` when a limit exists that could
    not be read, so a reader is told the figure may be the blind one. A cgroup that cannot be read at all leaves the machine's figure.
    """
    try:
        cg = cgroup if cgroup is not None else cgroup_available_mb()
    except Exception:  # noqa: BLE001 - an unreadable cgroup is no figure, never a verdict of its own
        return machine_mb, "machine"
    cg_mb = cg.get("available_mb")
    if cg_mb is not None and (machine_mb is None or cg_mb < machine_mb):
        return cg_mb, "cgroup limit"
    if cg.get("unreadable"):
        return machine_mb, "machine (a cgroup limit could not be read)"
    return machine_mb, "machine"
