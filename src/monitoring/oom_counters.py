"""The kernel's own kill counters, read at each session start (question 22: killed, or stopped on its own limit?).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A process the kernel kills leaves no line of its own, and the log that would name it is not always readable (the journal needs
group membership; a container has no ``dmesg``). The kernel also keeps COUNTERS, and counters can be read by anyone and survive the
process they count: ``oom_kill`` in ``/proc/vmstat`` (every OOM kill on the machine since it booted) and, where the process runs in a
memory cgroup, ``memory.events`` (``oom``, ``oom_kill``, ``max``, ``high``) with the cgroup's limit and peak. Read once at each session
start and kept in the session sentinel, the NEXT start can say how many kills happened between the two readings.

THE RULES. A counter that cannot be read is NAMED with its reason (the file is absent, permission was denied, ...) and is never a zero:
a zero means the kernel counted none, and these readings are the only place that distinction lives. A delta is computed only between
two readings of the same machine boot (a counter restarts at zero with the boot) and, for a cgroup counter, the same cgroup; where it
cannot be, the reading says why. ``vmstat`` is machine-wide: a rise there does not say the app was the victim, and the cgroup counters
do. Integers and the cgroup's own path only; no file content is copied as text.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_PROC = Path("/proc")
_CGROUP_ROOT = Path("/sys/fs/cgroup")

#: cgroup v2 files whose value is one integer or the word ``max``.
_V2_VALUES = ("memory.max", "memory.high", "memory.current", "memory.peak", "memory.swap.max", "memory.swap.current")
#: the keys of ``memory.events`` that bear on a kill or a limit.
_V2_EVENTS = ("low", "high", "max", "oom", "oom_kill", "oom_group_kill")
_V1_VALUES = ("memory.limit_in_bytes", "memory.usage_in_bytes", "memory.max_usage_in_bytes", "memory.failcnt")
_V1_OOM_CONTROL = ("under_oom", "oom_kill_disable", "oom_kill")


def _why(kind: type[BaseException]) -> str:
    """The reason a file could not be read, as a fixed word per cause, from the exception's CLASS (and errno): never its text."""
    if issubclass(kind, FileNotFoundError):
        return "absent (the file does not exist)"
    if issubclass(kind, PermissionError):
        return "permission denied"
    if issubclass(kind, OSError):
        return "unreadable (OSError)"
    return f"unparseable ({kind.__name__})"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="ascii", errors="replace")


def _int_or_max(path: Path) -> int | str | dict[str, str]:
    try:
        raw = _read_text(path).strip()
        return raw if raw == "max" else int(raw)
    except (OSError, ValueError) as exc:
        return {"unreadable": _why(type(exc))}


def _key_values(path: Path, wanted: tuple[str, ...]) -> dict[str, Any]:
    """The wanted ``key value`` lines of a flat-keyed file; a wanted key the file does not list is named as absent."""
    try:
        text = _read_text(path)
    except OSError as exc:
        return {"unreadable": _why(type(exc))}
    found: dict[str, int] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in wanted:
            try:
                found[parts[0]] = int(parts[1])
            except ValueError:
                found[parts[0]] = -1  # present and not a number; -1 is never a count
    return {k: found.get(k, {"unreadable": "absent (the key is not listed)"}) for k in wanted}


def _vmstat(proc: Path) -> dict[str, Any]:
    try:
        text = _read_text(proc / "vmstat")
    except OSError as exc:
        return {"oom_kill": {"unreadable": _why(type(exc))}}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "oom_kill":
            try:
                return {"oom_kill": int(parts[1])}
            except ValueError:
                return {"oom_kill": {"unreadable": "unparseable (ValueError)"}}
    return {"oom_kill": {"unreadable": "absent (this kernel lists no oom_kill counter; it is older than 4.13)"}}


def _own_paths(proc: Path) -> tuple[str | None, str | None, str | None]:
    """``(v2 path, v1 memory path, reason)`` from ``/proc/self/cgroup``."""
    try:
        text = _read_text(proc / "self" / "cgroup")
    except OSError as exc:
        return None, None, _why(type(exc))
    v2 = v1 = None
    for line in text.splitlines():
        head, _, rest = line.partition(":")
        _hier, _, path = rest.partition(":")
        if head == "0" and rest.startswith(":"):
            v2 = path.strip() or "/"
        elif "memory" in _hier.split(","):
            v1 = path.strip() or "/"
    return v2, v1, None


def read(*, proc: Path | None = None, cgroup_root: Path | None = None) -> dict[str, Any]:
    """The machine's and this process's cgroup's kill counters now. Never raises."""
    proc = proc or _PROC
    root = cgroup_root or _CGROUP_ROOT
    out: dict[str, Any] = {"vmstat": _vmstat(proc)}
    try:
        v2, v1, why = _own_paths(proc)
        if why:
            out["cgroup"] = {"unreadable": why}
        elif v2 is not None and (root / v2.lstrip("/") / "memory.events").exists():
            base = root / v2.lstrip("/")
            out["cgroup"] = {
                "version": 2,
                "path": v2,
                "values": {name: _int_or_max(base / name) for name in _V2_VALUES},
                "events": _key_values(base / "memory.events", _V2_EVENTS),
            }
        elif v1 is not None:
            base = root / "memory" / v1.lstrip("/")
            out["cgroup"] = {
                "version": 1,
                "path": v1,
                "values": {name: _int_or_max(base / name) for name in _V1_VALUES},
                "events": _key_values(base / "memory.oom_control", _V1_OOM_CONTROL),
            }
        else:
            out["cgroup"] = {"unreadable": "no memory cgroup in /proc/self/cgroup (v2 without memory.events, and no v1 memory line)"}
    except Exception as exc:  # noqa: BLE001 - evidence-gathering never raises into a boot
        out["cgroup"] = {"unreadable": f"unparseable ({type(exc).__name__})"}
    return out


def _delta(before: Any, after: Any) -> int | dict[str, str]:
    if not isinstance(before, int) or not isinstance(after, int) or before < 0 or after < 0:
        return {"unknown": "one of the two readings is not a number"}
    if after < before:
        return {"unknown": "the counter went DOWN: it was reset (another cgroup instance or a reboot), so no count is claimed"}
    return after - before


def compare(before: dict[str, Any] | None, after: dict[str, Any] | None, *, same_boot: bool | None) -> dict[str, Any]:
    """Kills counted between two readings: ``{machine_oom_kill, cgroup_oom_kill, cgroup_oom, cgroup_max_events, notes}``.

    ``same_boot`` is whether both readings were taken in one machine boot (None: not known). A count is claimed only when it can be;
    otherwise the field is ``{"unknown": reason}``."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return {"unknown": "no reading from the previous session's start" if not isinstance(before, dict) else "no reading from this start"}
    out: dict[str, Any] = {}
    if same_boot is False:
        out["machine_oom_kill"] = {"unknown": "the two readings are from different machine boots, and the counter restarts at each boot"}
    elif same_boot is None:
        out["machine_oom_kill"] = {"unknown": "whether the two readings share a machine boot is not known"}
    else:
        out["machine_oom_kill"] = _delta((before.get("vmstat") or {}).get("oom_kill"), (after.get("vmstat") or {}).get("oom_kill"))
    bc, ac = before.get("cgroup") or {}, after.get("cgroup") or {}
    if not isinstance(bc, dict) or not isinstance(ac, dict) or "events" not in bc or "events" not in ac:
        out["cgroup"] = {"unknown": "no cgroup counters in one of the two readings (see each reading's cgroup.unreadable)"}
    elif (bc.get("version"), bc.get("path")) != (ac.get("version"), ac.get("path")):
        out["cgroup"] = {"unknown": "the two readings are of different cgroups"}
    else:
        be, ae = bc["events"], ac["events"]
        out["cgroup"] = {
            "oom_kill": _delta(be.get("oom_kill"), ae.get("oom_kill")),
            "oom": _delta(be.get("oom"), ae.get("oom")),
            "max": _delta(be.get("max"), ae.get("max")),
        }
    out["reading"] = (
        "the machine counter is every OOM kill on the host since boot (not only this app's); the cgroup counters are this app's cgroup "
        "alone. A count says a kill happened between the readings; it does not say which session or process was the victim."
    )
    return out




__all__ = ["compare", "read"]
