"""The app's resident floor, scaled to the machine (S1.1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY (2026-09-02). Idle RSS on the 3.3 GB field machine was 1,047-1,170 MB before any
work happened, and every constant that composes it is RAM-blind:

* ``session.py`` builds a QueuePool of 8 + 64 connections;
* each connection carries ``PRAGMA cache_size=-65536`` -- 64 MiB, PER CONNECTION, so
  the file's own comment puts the worst case at ``cache_mb x (pool_size +
  max_overflow)`` = 4.6 GB;
* ``rollup_serve``/``map_serve`` turn themselves on whenever ``duckdb`` is importable
  ("no flag to flip"), and the columnar config sets neither ``memory_limit`` nor
  ``threads``, so DuckDB uses its documented default of 80% of RAM;
* the boot warm kicks the rollup build, a streamed scan of every keyword mention.

On a 16 GB box nobody notices. On 3.3 GB it is a third of RAM before the first fetch,
and it is the floor that 50 collector workers then overrun.

THE RULING (maintainer, 2026-09-02): below ~4 GB, REDUCE and DECLINE -- with the real
numbers stated, a visible caveat, and an override. Never a hard block. This module is
the "reduce" half: it resolves hardware-aware DEFAULTS for knobs that already exist,
and it is emphatically NOT an automatic power-profile switch (the 2026-07-12 ruling:
profiles are user-activated, suggest-never-silently-switch). An operator's explicit
value always wins and is reported as an override.

AN UNMEASURED MACHINE IS NOT A SMALL ONE. When total RAM cannot be read, the budget
returns today's values unchanged and says so. Refusing capability for want of a
measurement is the mirror defect -- it would slow every install whose psutil is absent,
which is the inference-hardware-gate lesson (a detected accelerator is positive
evidence and must never be refused because something else could not be counted).
"""

from __future__ import annotations

import os
from typing import Any

# The tier boundaries. Named, not inline, because the caveat quotes them.
SMALL_RAM_MB = 4 * 1024
MEDIUM_RAM_MB = 8 * 1024

# Today's shipped values — the "large machine" tier is byte-identical to them, so a
# machine with headroom is untouched by this module.
_LARGE = {"db_pool_size": 8, "db_max_overflow": 64, "sqlite_cache_mb": 64}
_MEDIUM = {"db_pool_size": 4, "db_max_overflow": 16, "sqlite_cache_mb": 16}
_SMALL = {"db_pool_size": 2, "db_max_overflow": 6, "sqlite_cache_mb": 16}

# DuckDB's own default is 80% of system RAM, which on a laptop is a promise the machine
# cannot keep while the app, the browser and the desktop are also resident. Capped as a
# SHARE of RAM at every size (the ruling says "always", not "on small machines").
_DUCKDB_SHARE = 0.15
_DUCKDB_MIN_MB = 128
_DUCKDB_MAX_MB = 4096


def total_ram_mb() -> float | None:
    """Total physical RAM in MiB, or None when it cannot be measured."""
    try:
        import psutil

        return psutil.virtual_memory().total / (1024 * 1024)
    except Exception:  # noqa: BLE001 - psutil is an optional extra
        return None


def _tier(total_mb: float | None) -> str:
    if total_mb is None:
        return "unmeasured"
    if total_mb < SMALL_RAM_MB:
        return "small"
    if total_mb < MEDIUM_RAM_MB:
        return "medium"
    return "large"


def _env_int(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return None
    return val if val >= 0 else None


def resolve() -> dict[str, Any]:
    """The resident budget for THIS machine (measures RAM, then delegates)."""
    return resolve_for(total_ram_mb())


def resolve_for(total_mb: float | None) -> dict[str, Any]:
    """The resident budget for a machine of ``total_mb``, with its reasoning attached.

    ``None`` means UNMEASURABLE, not "go and measure": the two are different facts and
    a single parameter that meant both would make the unmeasured tier untestable —
    which is the tier whose whole point is that it must not narrow anything."""
    measured = total_mb
    tier = _tier(measured)
    base = {"small": _SMALL, "medium": _MEDIUM, "large": _LARGE, "unmeasured": _LARGE}[tier]

    overrides: dict[str, int] = {}
    values = dict(base)
    for key, env in (
        ("db_pool_size", "OO_DB_POOL_SIZE"),
        ("db_max_overflow", "OO_DB_MAX_OVERFLOW"),
        ("sqlite_cache_mb", "OO_SQLITE_CACHE_MB"),
    ):
        got = _env_int(env)
        if got is not None:
            values[key] = got
            overrides[key] = got

    # DuckDB must never be left on its 80%-of-RAM default, at ANY size.
    if measured is None:
        duck_mb = _DUCKDB_MIN_MB * 4  # a stated, bounded guess rather than 80% of unknown
    else:
        duck_mb = int(max(_DUCKDB_MIN_MB, min(_DUCKDB_MAX_MB, measured * _DUCKDB_SHARE)))

    # The number nothing computed before: what the pool can hold in page cache alone.
    connections = values["db_pool_size"] + values["db_max_overflow"]
    worst_case_cache_mb = connections * values["sqlite_cache_mb"]

    out: dict[str, Any] = {
        "total_ram_mb": round(measured, 1) if measured is not None else None,
        "tier": tier,
        "db_pool_size": values["db_pool_size"],
        "db_max_overflow": values["db_max_overflow"],
        "sqlite_cache_mb": values["sqlite_cache_mb"],
        "duckdb_memory_limit_mb": duck_mb,
        "duckdb_threads": _duckdb_threads(tier),
        # Below the floor the in-memory columnar rollup is off by default: it is a
        # streamed scan of every keyword mention into RAM, and it was still building on
        # both field machines with the biggest corpora at export time.
        "columnar_serve_default": tier not in ("small",),
        "worst_case_pool_cache_mb": worst_case_cache_mb,
        "overrides": overrides,
        "method": (
            "Hardware-aware DEFAULTS for knobs that already exist, resolved once from "
            "total RAM. An operator's explicit environment value always wins and is "
            "listed under 'overrides'. This is NOT a power-profile switch: profiles "
            "stay user-activated (2026-07-12 ruling)."
        ),
    }
    if tier == "unmeasured":
        out["reason"] = (
            "total RAM could not be read (psutil absent), so the shipped values are "
            "kept unchanged. An unmeasured machine is not a small one — refusing "
            "capability for want of a measurement would slow every install whose "
            "psutil is missing."
        )
    elif tier == "small":
        out["reason"] = (
            f"{measured:,.0f} MiB of RAM is below the {SMALL_RAM_MB:,} MiB floor, so the "
            f"pool is {values['db_pool_size']}+{values['db_max_overflow']} connections at "
            f"{values['sqlite_cache_mb']} MiB of page cache each (worst case "
            f"{worst_case_cache_mb:,} MiB, against {connections * _LARGE['sqlite_cache_mb']:,} "
            "MiB before) and the in-memory columnar rollup is off by default. Collection "
            "keeps running; every refusal states its numbers and can be overridden."
        )
    else:
        out["reason"] = (
            f"{measured:,.0f} MiB of RAM is at or above the {SMALL_RAM_MB:,} MiB floor "
            f"({tier} tier); worst-case pool page cache {worst_case_cache_mb:,} MiB."
        )
    return out


def _duckdb_threads(tier: str) -> int:
    """DuckDB thread count. Two cores is the field's smallest machine, and DuckDB's
    default (one thread per core) competes with the collector for exactly those cores."""
    try:
        cores = os.cpu_count() or 2
    except Exception:  # noqa: BLE001
        cores = 2
    if tier == "small":
        return 1
    return max(1, min(4, cores // 2))


_CACHE: dict[str, Any] | None = None


def budget() -> dict[str, Any]:
    """The resolved budget, computed once per process."""
    global _CACHE
    if _CACHE is None:
        _CACHE = resolve()
    return _CACHE


def reset_for_tests() -> None:
    global _CACHE
    _CACHE = None


def worker_cache_ceiling_mb(workers: int) -> int:
    """What ``workers`` concurrent collector workers can hold in page cache alone.

    The arithmetic nothing performed before S1.0: on the field's machine B, 50 workers
    each held a pooled connection across a Tor fetch, and 50 x 64 MiB is 3.2 GB of page
    cache that the governor's back-off cannot reclaim -- it throttles NEW work, and its
    own semantics say holders in excess are never preempted."""
    return max(0, int(workers)) * int(budget()["sqlite_cache_mb"])
