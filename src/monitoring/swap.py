"""
Swap readings — the one measurement that separates a kill from a thrash.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Before the 2026-09-02 crash analysis, swap was sampled NOWHERE in the app. It is
what tells the two field deaths apart: the 3.9 GB machine with 1 GB of swap is
the one that can genuinely be OOM-killed, while the machine with 7.25 GB of swap
converts the same pressure into a multi-hour freeze. It is also what stops the
memory guard mistaking a swap-out for a recovery — pages moving to disk raise
``available`` and lower RSS at the same time, which reads as exactly the healthy
turn the guard is waiting for.

TWO different facts, kept apart because they answer different questions:

* ``swap_used_mb`` — the MACHINE's swap in use, including every other process.
  It says the box is under pressure; it does not say we are the cause.
* ``proc_swap_mb`` — OUR OWN pages that have been swapped out, read from
  ``/proc/self/status`` ``VmSwap``. Linux-only, and the one that attributes.

Every field is OMITTED when it cannot be read, never reported as 0: a machine
with no swap configured and a machine whose swap we could not measure are
opposite facts, and a zero would let a reader conclude "nothing is swapping".
"""

from __future__ import annotations

_PROC_STATUS = "/proc/self/status"


def swap_readings() -> dict[str, float]:
    """Machine and process swap in MiB. Unreadable fields are ABSENT, never 0."""
    out: dict[str, float] = {}
    try:
        import psutil

        out["swap_used_mb"] = round(psutil.swap_memory().used / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001 - psutil is an optional extra
        pass
    try:
        with open(_PROC_STATUS, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmSwap:"):
                    out["proc_swap_mb"] = round(int(line.split()[1]) / 1024.0, 1)
                    break
    except Exception:  # noqa: BLE001 - not Linux, or an unreadable procfs
        pass
    return out


def process_swapping() -> bool | None:
    """Is THIS process holding pages in swap? ``None`` when unmeasurable.

    Three states on purpose: a caller that reads an unmeasurable answer as False
    would take the swapping-box branch off a measurement it never made.
    """
    v = swap_readings().get("proc_swap_mb")
    return None if v is None else v > 0.0
