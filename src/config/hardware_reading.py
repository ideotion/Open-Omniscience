"""Q1011: what this machine has -- cores, RAM and free disk -- read once at boot.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1011 = a, verbatim: «The app reads cores, RAM and free disk at boot (no network),
proposes budgets from a published table, and shows the reading.» This module is the
reading. The table is ``configs/lane_budgets.yml``, read by ``src.versioned.budget``;
showing both is Settings -> Storage.

THROUGH THE EXISTING READERS, NOT A THIRD SET. RAM comes from
``src.config.memory_budget.total_ram_mb`` (the reader the memory tiers already judge this
machine by), cores from ``os.cpu_count`` exactly as
``memory_budget`` reads them, and free disk from ``shutil.disk_usage`` on the data
folder, the call ``src.safety.data_location`` makes. Two readers of one machine that
disagree are two answers to one question, and the operator sees both.

NEVER A GUESS. Every figure is either measured or ``None`` with its name listed under
``unreadable``: psutil is an optional extra, ``os.cpu_count`` may return ``None``, and
``statvfs`` can fail. "Unmeasured" and "small" are opposite findings, and a reading that
rounded the first into the second would refuse room on a machine nobody measured.

IT PROPOSES NOTHING BY ITSELF, AND IT PASSES NO VERDICT. The budgets stay the published
ones until the operator changes them; this reading is SHOWN beside the reference machine
they are sized for, and the operator judges -- which is the whole of Q1010's "nothing
silently assumes the maintainer's machine", and equally nothing assumes the operator's.
There is deliberately no "this machine is below the reference" line: the reference
machine's "3.5 GB" is the size its class reports (the field's AMD 3020e boxes read 3.2 to
3.46 GB with the graphics carve-out taken), so a strict comparison would call the
reference machine smaller than itself, and any tolerance that avoided it would be a
threshold nobody ruled. The one comparison a storage budget needs -- does it fit on the
disk? -- is made against the disk actually free, in ``src.versioned.budget``.

NO NETWORK, NO DATABASE. It runs in the lifespan before the lock check, so it works on a
store that is still locked, and costs one ``statvfs`` and two psutil reads.
"""

from __future__ import annotations

import os
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_MIB = 1024 * 1024

_LOCK = threading.Lock()
_BOOT: dict[str, Any] | None = None


def cores() -> int | None:
    """Logical CPUs, as ``memory_budget`` counts them, or ``None`` when unreadable."""
    try:
        n = os.cpu_count()
    except Exception:  # noqa: BLE001 - a platform that cannot say is unmeasured, not 1
        return None
    return int(n) if n else None


def ram_bytes() -> int | None:
    """Total RAM in bytes as the operating system reports it, through
    ``memory_budget.total_ram_mb`` -- the reader the memory tiers already use."""
    from src.config.memory_budget import total_ram_mb

    total_mb = total_ram_mb()
    return None if total_mb is None else int(total_mb * _MIB)


def disk_bytes(path: Path | None = None) -> tuple[int | None, int | None]:
    """``(free, total)`` bytes on the volume holding ``path`` (default: the data folder)."""
    try:
        target = path
        if target is None:
            from src.paths import data_dir

            target = data_dir()
        # Walk up to a directory that exists: a folder that has not been created yet
        # lives on the volume of its nearest existing parent.
        while not target.exists() and target.parent != target:
            target = target.parent
        usage = shutil.disk_usage(str(target))
    except OSError:
        # An unreadable volume is unmeasured, never a fabricated 0 -- "we could not tell"
        # and "the drive is full" are opposite findings (``data_location.preflight``).
        return None, None
    return int(usage.free), int(usage.total)


def read_hardware() -> dict[str, Any]:
    """One reading of this machine. Never raises; an unreadable figure is ``None``."""
    n_cores = cores()
    ram = ram_bytes()
    free, total = disk_bytes()
    out: dict[str, Any] = {
        "taken_at": datetime.now(UTC).isoformat(),
        "cores": n_cores,
        "ram_bytes": ram,
        "disk_free_bytes": free,
        "disk_total_bytes": total,
        "unreadable": [
            name
            for name, value in (("cores", n_cores), ("ram", ram), ("disk", free))
            if value is None
        ],
        "method": (
            "cores: os.cpu_count (logical CPUs). RAM: the total psutil reports. Free disk: "
            "shutil.disk_usage on the data folder. Read on this machine; nothing is sent "
            "anywhere."
        ),
    }
    return out


def record_boot_reading() -> dict[str, Any]:
    """Take the boot reading. Called once from the lifespan; a second call re-reads."""
    global _BOOT
    reading = read_hardware()
    reading["when"] = "boot"
    with _LOCK:
        _BOOT = reading
    return dict(reading)


def boot_reading() -> dict[str, Any] | None:
    """The reading taken at boot, or ``None`` when this process never took one."""
    with _LOCK:
        return None if _BOOT is None else dict(_BOOT)


def _reset_for_tests() -> None:
    global _BOOT
    with _LOCK:
        _BOOT = None
