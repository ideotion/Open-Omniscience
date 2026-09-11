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
# S1.4 (2026-09-02): a pass relaxes the ceiling when pressure was RARE, not only when it
# was absent. The relax half already existed and could never fire in the field, because
# it required mem_low_ticks == 0 exactly: with tens of workers some tick nearly always
# brushes the floor, so a machine that dipped once stayed pinned for the rest of its
# life. Machine A was running ONE worker with 1,239 MB available and the guard not
# engaged; machine C had 499 mem-low ticks out of 11,799 samples — 4.2% — and was pinned
# at 1. This is the share above which a pass counts as genuinely pressured.
_RELAX_SHARE = 0.10


def _is_sustained(ticks: int, samples: int | None) -> bool:
    """RARE pressure (below ``_RELAX_SHARE`` of the pass's own samples) reads as
    healthy; anything else — including "no usable denominator", the old strict
    behaviour — reads as sustained. Shared by every pressure SOURCE record_pass
    folds in, so mem_low and the memory guard are judged by the identical rule.
    """
    if ticks <= 0:
        return False
    if isinstance(samples, int) and not isinstance(samples, bool) and samples > 0:
        return (ticks / samples) > _RELAX_SHARE
    return True


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


def seed_for(w_max: int, state_path: Path | None = None) -> int | None:
    """The permit count the next pass should start from, clamped to ``[1, w_max]``, or
    ``None`` when this machine has never shown memory pressure.

    ``None`` means "no opinion", NOT ``w_max``. The distinction is load-bearing: the
    governor's own default depends on its rate mode (``maximum`` opens at ``w_max``,
    ``target`` eases in from ``DEFAULT_SEED``), so returning ``w_max`` here would have
    silently started target mode wide open -- a real behaviour change on machines this
    module is supposed to leave completely alone. Handing back ``None`` lets the caller
    keep its own default and makes the no-op property true by construction rather than
    by coincidence.
    """
    w_max = max(1, int(w_max))
    stored = load_ceiling(state_path)
    if stored is None:
        return None
    return max(1, min(stored, w_max))


def record_pass(
    *,
    w_max: int,
    mem_low_ticks: int | None,
    mem_low_min_permits: int | None,
    samples: int | None = None,
    guard_pressure_ticks: int | None = None,
    guard_pressure_min_permits: int | None = None,
    state_path: Path | None = None,
) -> int | None:
    """Fold one finished pass into the ceiling; return the new ceiling (``None`` = cleared).

    ``mem_low_ticks`` and ``mem_low_min_permits`` come straight from the collection
    monitor's own summary -- this function measures nothing itself.

    D2 (2026-09-11) -- A SECOND, INDEPENDENT PRESSURE SOURCE. ``mem_low_ticks`` is the
    GOVERNOR's own check (available memory under a fixed 512 MB), and it is not the
    only thing this machine may have backed off under: ``scheduler.memguard`` trips at
    its OWN thresholds (RSS >= 85% of total, or available <= 256 MB), and on any
    machine above roughly 3.4 GB total RAM the guard's RSS-relative trip point is
    reached at a LOWER RSS than the governor's mem_low floor -- so the guard engages
    (or comes close: it needs three consecutive over-threshold samples to fully
    latch, where a hovering machine can cross the line on many ticks without ever
    holding it for three straight) while mem_avail_mb never drops far enough for
    mem_low to fire at all. A learner reading only mem_low_ticks then sees zero
    pressure, pass after pass, on a machine that is visibly straining -- exactly the
    field symptom (``learned_ceiling`` null, ``ramp_capped_at`` == ``w_max``, after
    seven armed runs on a 4 GB box sitting at 85% RSS).

    ``guard_pressure_ticks``/``guard_pressure_min_permits`` carry that second signal
    (``CollectionMonitor``'s ``guard_pressure_ticks``/``guard_pressure_min_permits``,
    via :func:`guard_pressure_from_summary`) -- the UNLATCHED per-sample reading
    (:meth:`~src.scheduler.memguard.MemoryGuard.raw_pressure`), not the latched
    ``engaged`` state, precisely so a hovering-but-never-fully-engaged machine still
    registers. It is judged by the identical rare-vs-sustained rule as mem_low
    (:func:`_is_sustained`) and can independently trigger every branch below --
    including the P4b ineffective-descent escape -- but it is NEVER folded into
    ``mem_low_ticks`` itself: they are different facts (a different threshold, and
    the guard does not itself cut permits the way a mem-low tick does), and this
    function's own ``reason`` records which source actually supplied the floor
    rather than blurring "the governor saw low memory" with "the guard did". When
    BOTH sources see sustained pressure and both offer a usable floor, the LOWER of
    the two wins (whichever demonstrably required fewer workers), and its label is
    what gets recorded.

    A GUARD-SOURCED FLOOR CAN BE A NO-OP, and that is honest rather than a bug: the
    guard does not reduce permits, so ``guard_pressure_min_permits`` is only whatever
    OTHER back-off (mem_low, the writer gate, CPU, loop-lag) happened to leave in
    force while the guard was also under pressure -- on a pass where nothing else
    ever cut permits, that number equals ``w_max`` and clears the ceiling exactly as
    "no pressure" would, because this function genuinely has no evidence that fewer
    workers would have helped. It never invents a number the pass did not measure.

    A pass that saw SUSTAINED pressure lowers the ceiling to the floor the governor
    actually reached (never raises it: pressure is not evidence of headroom). A pass
    that saw none — or saw it only rarely, below ``_RELAX_SHARE`` of its samples —
    relaxes it, and clearing the record at ``w_max`` keeps a healthy machine carrying no
    state at all. A pass that reported no usable numbers leaves the ceiling untouched --
    an absent measurement is not a measurement of zero pressure.

    ``samples`` is the pass's own tick count. Without it a single brushed tick counts as
    pressure, which is what pinned machine A at one worker while 1,239 MB was free: with
    tens of workers some tick nearly always touches the floor, so "ticks == 0" is a
    condition a busy machine can essentially never meet again. With it, RARE pressure
    relaxes and SUSTAINED pressure still pins. An absent ``samples`` keeps the old
    strict behaviour rather than guessing a denominator.

    THE INEFFECTIVE DESCENT (P4, 2026-09-10) -- the escape this record was missing.
    ``mem_low`` is a reading about the WHOLE MACHINE: available memory under a fixed
    512 MB, which on a box also running a local model can sit true no matter what the
    collector does. Under the rule above that is a trap with no exit: every pass is
    sustained, the floor walks to 1, ``min(current, floor)`` re-pins it at 1, and the
    relax branch needs a pass below ``_RELAX_SHARE`` that can never arrive. Measured
    over a 1.5 s/fetch transport, that is 1.91 -> 0.45 articles/s -- a 4.2x slowdown
    with no code change, no visible cause, and it survives restarts because this file
    does.

    So: a pass that ALREADY RAN AT A CEILING OF 1 and still saw sustained pressure has
    demonstrated that concurrency is not the lever. Its evidence is about the machine,
    not about the worker count, and re-recording 1 would only pin a box on a condition
    it cannot influence. Such a pass takes the RELAX branch instead -- one geometric
    step, not a jump to the top -- so a machine whose pressure really is ours simply
    trips again next pass and settles into a 1<->2 oscillation rather than a permanent
    pin.

    This does NOT weaken the protection, and the separation is the whole reason it is
    safe: the ceiling is a CONCURRENCY TUNING hint, while the thing that protects the
    machine is ``scheduler.memguard`` -- a different mechanism, with its own thresholds
    (RSS >= 85% of total, or available <= 256 MB, three consecutive samples), which
    PAUSES collection outright and is not a permit count at all. Nothing here changes
    it, and it remains in force at every worker count.
    """
    w_max = max(1, int(w_max))
    path = state_path or _default_state_path()
    current = load_ceiling(path)

    if mem_low_ticks is None and guard_pressure_ticks is None:
        return current  # the pass never ran the monitor; it says nothing either way.

    mem_low_sustained = _is_sustained(mem_low_ticks or 0, samples)
    guard_sustained = _is_sustained(guard_pressure_ticks or 0, samples)
    sustained = mem_low_sustained or guard_sustained

    ineffective_descent = sustained and current == 1
    if ineffective_descent:
        # The pass ran the whole way at one worker and the pressure did not clear, so
        # this pass says nothing about our concurrency — see the docstring. Relax.
        sustained = False
        mem_low_sustained = False
        guard_sustained = False
        _LOG.info(
            "collect capacity: a pass at 1 worker still saw sustained memory pressure "
            "(mem-low %s/%s ticks; memory guard %s/%s ticks); the ceiling is not the "
            "lever, relaxing it",
            mem_low_ticks if mem_low_ticks is not None else "?",
            samples if samples is not None else "?",
            guard_pressure_ticks if guard_pressure_ticks is not None else "?",
            samples if samples is not None else "?",
        )

    if sustained:
        # Each source offers its own floor only when IT judged the pass sustained
        # and actually recorded one — a source that stayed quiet, or that saw
        # pressure but never measured a floor, contributes nothing rather than a
        # fabricated number. The lower of whatever is offered wins.
        candidates: list[tuple[int, str]] = []
        if (
            mem_low_sustained
            and isinstance(mem_low_min_permits, int)
            and not isinstance(mem_low_min_permits, bool)
            and mem_low_min_permits >= 1
        ):
            candidates.append((min(mem_low_min_permits, w_max), "memory pressure"))
        if (
            guard_sustained
            and isinstance(guard_pressure_min_permits, int)
            and not isinstance(guard_pressure_min_permits, bool)
            and guard_pressure_min_permits >= 1
        ):
            candidates.append(
                (min(guard_pressure_min_permits, w_max), "memory pressure (memory guard)")
            )
        if not candidates:
            # Pressure was seen but no source recorded a usable floor: refuse to
            # invent one.
            return current
        floor, reason = min(candidates, key=lambda c: c[0])
        new = floor if current is None else min(current, floor)
    else:
        if current is None:
            return None  # healthy and unrecorded -- nothing to write.
        new = min(w_max, max(1, current) * _RELAX_FACTOR)
        # The two ways to reach this branch are DIFFERENT FACTS and the stored record
        # must not blur them: one pass saw no pressure worth the name, the other saw
        # plenty and proved the worker count was not what caused it. Writing "no
        # memory pressure" for the second would be a false statement in the very file
        # an operator opens to find out why their collector is slow.
        reason = (
            "sustained memory pressure that one worker did not relieve, so the "
            "worker count is not what is causing it"
            if ineffective_descent
            else "a pass with no memory pressure"
        )

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


def samples_from_summary(summary: dict | None) -> int | None:
    """The pass's own tick count, the denominator ``record_pass`` needs to tell rare
    pressure from sustained pressure.

    NESTED UNDER ``bottleneck``, exactly like the other two — this is the trap
    ``from_summary``'s docstring names, and the first cut of this function walked
    straight into it by reading the top level. A top-level ``.get`` returns None,
    ``record_pass`` correctly treats None as "no denominator" and keeps the strict
    behaviour, so the relaxation would never have fired in production while every unit
    test of the logic passed. Read from the same block, pinned against a REAL
    CollectionMonitor summary."""
    if not isinstance(summary, dict):
        return None
    block = summary.get("bottleneck")
    if not isinstance(block, dict):
        return None
    got = block.get("samples")
    return got if isinstance(got, int) and not isinstance(got, bool) else None


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


def guard_pressure_from_summary(summary: dict | None) -> tuple[int | None, int | None]:
    """Pull ``(guard_pressure_ticks, guard_pressure_min_permits)`` out of a pass summary.

    D2's second signal, mirroring :func:`from_summary` exactly (same nesting trap,
    same ``(None, None)`` refusal on an unreadable summary) but reading the memory
    GUARD's own unlatched pressure reading rather than the governor's mem_low check
    -- see ``record_pass``'s docstring for why the two are kept apart.
    """
    if not isinstance(summary, dict):
        return (None, None)
    block = summary.get("bottleneck")
    if not isinstance(block, dict):
        return (None, None)
    ticks = block.get("guard_pressure_ticks")
    floor = block.get("guard_pressure_min_permits")
    return (
        ticks if isinstance(ticks, int) and not isinstance(ticks, bool) else None,
        floor if isinstance(floor, int) and not isinstance(floor, bool) else None,
    )


def concurrency_report(w_max: int, state_path: Path | None = None) -> dict:
    """Why a pass may be running fewer workers than the operator configured.

    P5 (2026-09-10). Every input to this already existed and NONE of it reached the
    place an operator watches collection: ``state_report`` is rendered only inside the
    diagnostics report payload, and the machine-floor worker cap was reported to a log
    line at most. So a pass running one worker of a configured fifty — measured at
    1.91 -> 0.45 articles/s over a slow transport, and persisting across restarts — was
    indistinguishable, from the task manager, from "the app got slow".

    THE TWO CAPS ARE KEPT APART because they are different facts with different
    remedies. ``learned_ceiling`` is a MEASUREMENT: what this machine sustained under
    memory pressure, recorded by the collector's own back-off, and it heals on its own
    (delete ``collect_capacity.json`` to forget it immediately -- it is a cache of a
    measurement, never operator state). ``floor_cap`` is a POLICY: a machine below the
    RAM floor is held to ``FLOOR_MAX_WORKERS`` until the operator overrides it. Folding
    them into one "effective" number would leave a reader unable to tell which lever
    they are looking at.

    ``effective_max`` is the smaller of the two, i.e. what a pass may actually reach --
    NOT a prediction of the permit count it will run at. Where a pass STARTS is the
    governor's own rate-mode default, which this module does not know and will not
    guess (see ``seed_for``).

    THE MACHINE-FLOOR READ degrades on its own (``floor_read: False``, never a quiet
    absence of a cap). The rest is not separately wrapped, and that is deliberate rather
    than an omission: ``load_ceiling`` already swallows everything it can hit, and the
    ONE guarantee that matters -- that a panel reading can never break the polled status
    -- belongs at the caller, in ``runner._concurrency_block``, where it exists and is
    tested. A second try/except here would be an unfalsifiable guard over a function
    that already cannot fail that way.
    """
    configured = max(1, int(w_max))
    out = dict(state_report(configured, state_path))
    floor_cap: int | None = None
    floor_reason: str | None = None
    override_env: str | None = None
    try:
        from src.config.machine_floor import capped_workers

        capped, verdict = capped_workers(configured)
        override_env = verdict.get("override_env")
        if capped < configured:
            floor_cap, floor_reason = capped, verdict.get("reason")
    except Exception as exc:  # noqa: BLE001 - a panel reading never breaks a poll
        _LOG.debug("collect capacity: machine-floor cap unreadable: %s", exc)
        out["floor_read"] = False
    ceiling = out.get("ramp_capped_at") or configured
    out.update(
        {
            "configured": configured,
            "learned_ceiling": out.get("learned_ceiling"),
            "floor_cap": floor_cap,
            "floor_reason": floor_reason,
            "override_env": override_env,
            "effective_max": min(ceiling, floor_cap) if floor_cap else ceiling,
            # The one thing a reader wants first: is anything holding this back?
            "capped": bool(floor_cap) or out.get("learned_ceiling") is not None,
        }
    )
    return out


def state_report(w_max: int, state_path: Path | None = None) -> dict:
    """Read-only view for diagnostics. No score -- one measured count and its provenance."""
    stored = load_ceiling(state_path)
    configured = max(1, int(w_max))
    return {
        "schema": SCHEMA,
        "configured_max_workers": configured,
        "learned_ceiling": stored,
        # What the collector's upward ramp may actually reach next pass. Deliberately
        # NOT a predicted starting permit count: with no ceiling recorded the starting
        # point is the governor's own rate-mode default, which this module does not
        # know and will not guess.
        "ramp_capped_at": configured if stored is None else min(stored, configured),
        "measured": stored is not None,
        "method": (
            "learned_ceiling is null until this machine has actually backed off under "
            "memory pressure; until then the collector runs exactly as it always has, "
            "starting and ramping to the configured maximum. Once measured, it both "
            "starts each pass there AND may not ramp above it — the ceiling rises one "
            "doubling after any pass that sees no pressure."
        ),
    }
