"""Learned collector concurrency — the memory ceiling this machine has DEMONSTRATED.

``BandwidthGovernor`` backs off under memory pressure, and on a constrained box it walks
the permit count down to what the machine can actually sustain. That descent IS a
measurement, and ``CollectionMonitor`` already records its floor as
``mem_low_min_permits``. Nothing read it: the governor was rebuilt at ``w_max`` at the
top of every pass (``seed = w_max`` in ``maximum`` mode), so a memory-bound machine
re-walked the same descent every pass, forever, thrashing on the way down each time.

Field evidence that motivated this (2026-08-13, a 4-core / 3.65 GiB box, permits from the
collector's own perf log)::

    06:37:54  50->48  mem-low
    06:38:13  50->48  mem-low     <- a new pass; back at 50
    06:39:03  50->48  mem-low     <- and again
    06:39:10  48->46 ... 43 seconds ... 2->1
    10:05:59  50->48  mem-low     <- and again

This module carries that measurement across passes AND restarts. It stores exactly one
number: the permit count the next pass should START from.

BLAST RADIUS -- the property that makes this safe on every other machine. A machine that
never trips ``mem_low`` never records a floor, so ``seed_for`` returns ``w_max`` and the
governor is constructed byte-identically to before. The whole mechanism is unreachable on
hardware that has never actually shown memory pressure, and it is pinned that way by test.

It is NOT a hardware guess. Nothing here reads total RAM or core count to PREDICT a
capacity -- that would be a fabricated capability claim of exactly the kind the perf
log's own comment warns against. The only input is what this machine really did.

RECOVERY. A ceiling is a memory of pressure, not a verdict. A pass that completes with no
mem-low tick RELAXES it geometrically toward ``w_max``, and once it reaches ``w_max`` the
record is CLEARED -- so a transient pressure event, or a data dir carried to a larger
machine, heals within a few passes instead of pinning the box forever. The ceiling never
touches the operator's stored ``collect_parallelism``: that setting remains their explicit
choice and the hard upper bound, and this only ever declines to spend all of it right now.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

_LOG = logging.getLogger(__name__)

STATE_FILENAME = "collect_capacity.json"
SCHEMA = "oo-collect-capacity-1"

#: Multiplier applied to the stored ceiling after a pass that saw NO memory pressure.
#: Geometric so a machine that dipped once climbs back in a handful of passes rather
#: than one permit at a time; the governor's own per-tick back-off is what catches it
#: again if the climb was premature.
_RELAX_FACTOR = 2


def _default_state_path() -> Path:
    from src.paths import data_dir

    return data_dir() / STATE_FILENAME


def load_ceiling(state_path: Path | None = None) -> int | None:
    """The stored ceiling, or ``None`` when this machine has never shown memory pressure.

    ``None`` is the normal, healthy state and is DISTINCT from a stored ``1``: the first
    means "never measured, spend freely", the second means "measured, and this box could
    only sustain one worker". A missing or unreadable file degrades to ``None`` -- losing
    the memory costs one re-descent, and must never break a collection pass.
    """
    p = state_path or _default_state_path()
    try:
        data = json.loads(p.read_text("utf-8"))
    except FileNotFoundError:
        return None
    except Exception:  # noqa: BLE001 - a corrupt hint is worth exactly one re-descent
        _LOG.debug("collect capacity: unreadable state at %s; starting fresh", p)
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("ceiling")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return None
    return value


def _save(state_path: Path, payload: dict | None) -> None:
    """Atomic write, or remove the file when ``payload`` is ``None`` (back to healthy).

    Best-effort by contract: a read-only or full volume must cost the next pass a
    re-descent, never the pass itself.
    """
    try:
        if payload is None:
            state_path.unlink(missing_ok=True)
            return
        tmp = state_path.with_name(state_path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=1, sort_keys=True), "utf-8")
        os.replace(tmp, state_path)
    except Exception:  # noqa: BLE001 - see the docstring
        _LOG.debug("collect capacity: could not persist state at %s", state_path)


def seed_for(w_max: int, state_path: Path | None = None) -> int:
    """The permit count the next pass should start from, clamped to ``[1, w_max]``.

    Returns ``w_max`` unchanged when nothing was ever recorded, which is what makes this
    a no-op on any machine that has not demonstrated memory pressure.
    """
    w_max = max(1, int(w_max))
    stored = load_ceiling(state_path)
    if stored is None:
        return w_max
    return max(1, min(stored, w_max))


def record_pass(
    *,
    w_max: int,
    mem_low_ticks: int | None,
    mem_low_min_permits: int | None,
    state_path: Path | None = None,
) -> int | None:
    """Fold one finished pass into the ceiling; return the new ceiling (``None`` = cleared).

    ``mem_low_ticks`` and ``mem_low_min_permits`` come straight from the collection
    monitor's own summary -- this function measures nothing itself.

    A pass that saw pressure lowers the ceiling to the floor the governor actually
    reached (never raises it: pressure is not evidence of headroom). A pass that saw none
    relaxes it, and clearing the record at ``w_max`` keeps a healthy machine carrying no
    state at all. A pass that reported no usable numbers leaves the ceiling untouched --
    an absent measurement is not a measurement of zero pressure.
    """
    w_max = max(1, int(w_max))
    path = state_path or _default_state_path()
    current = load_ceiling(path)

    if mem_low_ticks is None:
        return current  # the pass never ran the monitor; it says nothing either way.

    if mem_low_ticks > 0:
        if not isinstance(mem_low_min_permits, int) or mem_low_min_permits < 1:
            # Pressure was seen but the floor was not recorded: refuse to invent one.
            return current
        floor = min(mem_low_min_permits, w_max)
        new = floor if current is None else min(current, floor)
        reason = "memory pressure"
    else:
        if current is None:
            return None  # healthy and unrecorded -- nothing to write.
        new = min(w_max, max(1, current) * _RELAX_FACTOR)
        reason = "a pass with no memory pressure"

    if new >= w_max:
        _save(path, None)
        return None
    if new == current:
        return current
    _save(
        path,
        {
            "schema": SCHEMA,
            "ceiling": int(new),
            "w_max_at_record": w_max,
            "reason": reason,
            "method": (
                "The lowest worker count this machine sustained under memory pressure, "
                "measured by the collector's own back-off (never predicted from RAM or "
                "core count). Relaxes toward the configured maximum after passes that "
                "see no pressure, and is removed once it reaches it."
            ),
        },
    )
    return int(new)


def from_summary(summary: dict | None) -> tuple[int | None, int | None]:
    """Pull ``(mem_low_ticks, mem_low_min_permits)`` out of a collection-pass summary.

    The shape lives HERE, in one place a test can pin against a real
    ``CollectionMonitor.stop()`` payload, because reading it wrong is invisible: both
    numbers arrive nested under ``bottleneck``, and a top-level ``.get`` returns ``None``
    for each -- which ``record_pass`` correctly treats as "this pass said nothing", so the
    ceiling would simply never be recorded and every test of the logic would still pass.
    Returns ``(None, None)`` for a missing or unrecognised summary: an unreadable pass is
    not a pass that saw no pressure.
    """
    if not isinstance(summary, dict):
        return (None, None)
    block = summary.get("bottleneck")
    if not isinstance(block, dict):
        return (None, None)
    ticks = block.get("mem_low_ticks")
    floor = block.get("mem_low_min_permits")
    return (
        ticks if isinstance(ticks, int) and not isinstance(ticks, bool) else None,
        floor if isinstance(floor, int) and not isinstance(floor, bool) else None,
    )


def state_report(w_max: int, state_path: Path | None = None) -> dict:
    """Read-only view for diagnostics. No score -- one measured count and its provenance."""
    stored = load_ceiling(state_path)
    return {
        "schema": SCHEMA,
        "configured_max_workers": max(1, int(w_max)),
        "learned_ceiling": stored,
        "seed_next_pass": seed_for(w_max, state_path),
        "measured": stored is not None,
        "method": (
            "learned_ceiling is null until this machine has actually backed off under "
            "memory pressure; until then the collector starts every pass at the "
            "configured maximum, exactly as it always has."
        ),
    }
