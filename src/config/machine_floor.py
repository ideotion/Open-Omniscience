"""
S1.3: below the floor, REDUCE *and* DECLINE (2026-09-02 crash analysis, ruling 1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``memory_budget`` already shrinks what the app HOLDS on a small machine. This
answers the other half of the ruling: on a machine below the floor the app also
stops DOING, by default, the thing that pushes it over — the whole-corpus
background scans (bulk qualification and the ratio audit it runs).

THE VERDICT IS A FACT ABOUT THE MACHINE, and the override is a separate field:

    below       — is this machine below the floor (unchanged by the override)
    overridden  — the operator asked to proceed anyway
    declines    — the EFFECTIVE answer callers gate on: below AND NOT overridden

Keeping them apart is what makes the override honest. Folding the override into
``below`` would erase the measurement it was overriding, so a report could no
longer say "this machine is small AND the operator chose to run anyway" — which
is exactly what a reader needs when the run then fails.

THREE STATES, not two. A machine whose RAM cannot be read is ``below: None``,
never ``False``: those are opposite facts, and refusing on a measurement nobody
made is the fabricated-failure mirror of the fabricated pass. An unmeasurable
machine therefore does NOT decline — the same rule ``inference_capability`` uses
when ``psutil`` is absent on a core install.

NEVER A HARD BLOCK. ``declines: True`` means the background scans default to off
with the numbers stated; the operator turns them back on with ``OO_ALLOW_BIG_SCANS=1``
(or the Settings toggle), and the verdict then reports ``overridden: True``.

THE NEED ESTIMATE IS MEASURED, NOT GUESSED. ``per_source_metrics`` materialises
one stat object per article plus the outlier/pathology id sets and the per-source
tallies. Measured with ``tracemalloc`` over the real function on a plaintext
fixture (40 sources, 8 mentions per article):

    2,000 articles ->  1.96 MB peak  = 1,025 B/article
    8,000 articles ->  8.02 MB peak  = 1,051 B/article
   20,000 articles -> 19.62 MB peak  = 1,029 B/article

Flat and linear, so the per-article term is real. ``_BYTES_PER_ARTICLE`` is
rounded UP to 1,200 for one stated reason: ``tracemalloc`` sees Python
allocations only, not the C-extension buffers sqlite3 allocates underneath, so
the measurement is a FLOOR. Rounding up errs toward declining, which is the safe
direction here — a wrong decline is a stated refusal with an override beside it,
while a wrong proceed is the crash this whole slice exists to stop.

SAY THE COST OUT LOUD (the ruling requires it, and the caveat carries it): on a
machine with a large corpus and little free memory the estimate can exceed what
is available, so bulk qualification may effectively never run there by default.
That is the honest consequence of the ruling, not a bug in the estimate.
"""

from __future__ import annotations

import os
from typing import Any

# The floor, both halves. A machine is below it on EITHER count.
MIN_TOTAL_MB = 4096.0
"""Total RAM under 4 GB — machine A (3,924 MiB) sits here."""

MIN_AVAILABLE_MB = 1024.0
"""Measured available under 1 GB — a box already in trouble whatever its total."""

_OVERRIDE_ENV = "OO_ALLOW_BIG_SCANS"

# Measured; see the module docstring for the three data points it comes from.
_BYTES_PER_ARTICLE = 1200
_SCAN_CACHE_MB = 64.0
"""The page cache one whole-corpus pass warms (the shipped ``cache_size``)."""
_SCAN_HEADROOM_MB = 100.0
"""Interpreter, ORM and result-set overhead beyond the per-article term."""


def _mem_readings() -> tuple[float | None, float | None]:
    """(total_mb, available_mb) — either may be ``None`` when unreadable."""
    try:
        import psutil

        vm = psutil.virtual_memory()
        return (
            round(vm.total / (1024 * 1024), 1),
            round(vm.available / (1024 * 1024), 1),
        )
    except Exception:  # noqa: BLE001 - psutil is an optional [analysis] extra
        return (None, None)


def _override_requested() -> bool:
    return (os.getenv(_OVERRIDE_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}


def machine_floor(
    *,
    override: bool | None = None,
    total_mb: float | None = None,
    available_mb: float | None = None,
) -> dict[str, Any]:
    """Is this machine below the floor? See the module docstring for the contract.

    ``total_mb``/``available_mb`` are injectable so the verdict can be tested
    against a machine this one is not.
    """
    read_total, read_avail = (None, None)
    if total_mb is None or available_mb is None:
        read_total, read_avail = _mem_readings()
    total = total_mb if total_mb is not None else read_total
    avail = available_mb if available_mb is not None else read_avail

    overridden = _override_requested() if override is None else bool(override)

    below: bool | None
    if total is None and avail is None:
        below = None
        reason = (
            "this machine's memory could not be read (psutil is an optional extra), "
            "so the floor was not applied — an unmeasured machine is never refused"
        )
    else:
        low_total = total is not None and total < MIN_TOTAL_MB
        low_avail = avail is not None and avail < MIN_AVAILABLE_MB
        below = bool(low_total or low_avail)
        # The three numbers the reason must carry: what this machine has, what is
        # free on it right now, and the floor it is being judged against.
        shape = (
            f"{total:.0f} MB of RAM" if total is not None else "an unreadable RAM total",
            f"{avail:.0f} MB available" if avail is not None else "an unreadable available reading",
        )
        if below:
            which = []
            if low_total:
                which.append(f"total under the {MIN_TOTAL_MB:.0f} MB floor")
            if low_avail:
                which.append(f"available under the {MIN_AVAILABLE_MB:.0f} MB floor")
            reason = (
                f"this machine has {shape[0]} with {shape[1]} — "
                + " and ".join(which)
            )
        else:
            reason = (
                f"this machine has {shape[0]} with {shape[1]} — at or above the "
                f"{MIN_TOTAL_MB:.0f} MB / {MIN_AVAILABLE_MB:.0f} MB floor"
            )

    declines = bool(below) and not overridden
    return {
        "below": below,
        "overridden": overridden,
        "declines": declines,
        "total_mb": total,
        "available_mb": avail,
        "min_total_mb": MIN_TOTAL_MB,
        "min_available_mb": MIN_AVAILABLE_MB,
        "reason": reason,
        "override_env": _OVERRIDE_ENV,
        "method": (
            "psutil virtual_memory(); the floor is applied on EITHER the total or "
            "the available reading, and an unreadable machine is never refused"
        ),
        "caveat": (
            "Below the floor the whole-corpus background scans are declined by "
            "default, with the numbers stated. On a machine with a large corpus and "
            "little free memory that can mean bulk source qualification never runs "
            f"unless you turn it back on ({_OVERRIDE_ENV}=1) — that is the cost of "
            "the setting, not a failure."
        ),
    }


FLOOR_MAX_WORKERS = 8
"""The fetch fan-out a machine below the floor is allowed to USE.

WHAT THIS CAP IS AND IS NOT ABOUT, stated because the obvious reason is now
WRONG: it is not the pooled connections. S1.0 releases a worker's session BEFORE
its network call, so checked-out connections track DB work in flight rather than
the worker count, and ``memory_budget`` bounds the pool independently. What still
scales with the worker count is the number of DOCUMENTS in flight — each worker
holds a fetched body and its parse tree — and that is what this bounds.

The value is 8 because it is the small tier's own pool bound (6 + 2): more
workers than connections queue on the DB anyway, so it is the largest fan-out
that buys anything on such a box. It is written out rather than derived from the
tier so that changing a pool size can never silently move a throughput cap.
"""


def capped_workers(
    w_max: int,
    *,
    override: bool | None = None,
    total_mb: float | None = None,
    available_mb: float | None = None,
) -> tuple[int, dict[str, Any]]:
    """``(workers, verdict)`` — the fan-out a pass may use, and why.

    The operator's stored ``collect_parallelism`` is NEVER rewritten: this caps
    what one pass is allowed to use, reports it, and is lifted by the same
    documented override as the rest of the floor.
    """
    verdict = machine_floor(override=override, total_mb=total_mb, available_mb=available_mb)
    w = max(1, int(w_max))
    if verdict["declines"] and w > FLOOR_MAX_WORKERS:
        return FLOOR_MAX_WORKERS, verdict
    return w, verdict


def scan_need_mb(articles: int) -> float:
    """What one whole-corpus qualification scan needs, from the measurement.

    ``64 MiB page cache + 1.2 KB x articles + 100 MB`` — see the module docstring
    for the three measured points behind the per-article term and for why it is
    rounded up rather than taken at the measured 1,030 B.
    """
    n = max(0, int(articles))
    return round(
        _SCAN_CACHE_MB + (n * _BYTES_PER_ARTICLE) / (1024 * 1024) + _SCAN_HEADROOM_MB,
        1,
    )


def scan_budget(
    articles: int,
    *,
    override: bool | None = None,
    total_mb: float | None = None,
    available_mb: float | None = None,
) -> dict[str, Any]:
    """Can this machine afford a whole-corpus scan right now?

    Returns the floor verdict plus ``need_mb``/``affordable``, and — when it
    cannot — the exact ``{skipped, available_mb, need_mb}`` a caller records so
    the refusal reads as a measurement rather than as a silent nothing.
    """
    verdict = machine_floor(override=override, total_mb=total_mb, available_mb=available_mb)
    need = scan_need_mb(articles)
    avail = verdict["available_mb"]
    # Unmeasurable available -> None, never True/False: "we could not tell" is a
    # third answer, and the floor above already refuses to decline on it.
    affordable: bool | None = None if avail is None else bool(avail >= need)

    out = dict(verdict)
    out.update(
        {
            "articles": max(0, int(articles)),
            "need_mb": need,
            "affordable": affordable,
            "need_method": (
                f"{_SCAN_CACHE_MB:.0f} MB page cache + {_BYTES_PER_ARTICLE} B x "
                f"{max(0, int(articles))} articles + {_SCAN_HEADROOM_MB:.0f} MB overhead; "
                "the per-article term is measured, not assumed"
            ),
        }
    )
    if out["declines"]:
        out["skipped"] = "memory"
    return out
