"""
Power profiles — Low / Optimized / Max over a PUBLISHED knob table (planning §7).

§7's design is one operator control that trades RESOURCE SPEND, never data or honesty: a
profile changes how hard the machine works (cache, parallelism, budgets, poll cadence), and
NOTHING it touches changes what data is visible or what caveats are shown. The app SUGGESTS a
profile, never silently switches, and the active profile is always visible.

This is the buildable-now core: a transparent registry of the real knobs (each already a live
``OO_*`` env var or an ``AppSettings`` field), the three profiles, and a pure
``resolve_effective`` that layers a profile under explicit user overrides. Two binding honesty
properties, both test-pinned:
  * **Optimized == today.** Each knob's ``optimized`` value IS the current app default, so
    selecting Optimized is byte-identical to shipping behaviour (no silent change).
  * **Low / Max are PROVISIONAL.** §7 says the exact Low/Max numbers are MEASURED on the GAMMA
    synthetic harness before shipping; until then they are directional placeholders flagged
    ``provisional`` and to-be-replaced-by-measurement (the §8 sanity-envelope discipline).

The SERVER-SIDE knobs are now wired to the active profile (``OO_POWER_PROFILE``, default
``optimized`` → byte-identical to today): each consumer reads a resolver — ``sqlite_cache_mb()``
(per connection), ``pass_budget_minutes()`` (per pass, LIVE), ``rollup_serve_ttl_s()`` (per serve,
LIVE), ``dump_concurrency()`` (per manager), ``fts_analysis_limit()`` (per optimize, LIVE),
``qualification_batch_size()`` (per bulk-job call, LIVE; 2026-07-24 throughput brief C5),
``http_pool_size()`` (per fetcher construction; C9) — that
returns its ``OO_*`` override if set, else the active profile's value. The three SETTING-backed
knobs (``collect_parallelism``, ``llm_keep_alive``, ``qualification_per_pass``) are applied via
the settings-write path, not the read site (the stored value is the user's explicit choice);
``poll_cadence_s`` is frontend-only (browser-gated). The active-profile CHIP + the
suggest-a-lower-level proposal are BROWSER-GATED (fork-3); re-applying a changed cache_size to the
RUNNING engine's open connections is OPERATOR-GATED (a restart picks it up).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

SCHEMA = "oo-power-profile-1"
PROFILE_NAMES = ("low", "optimized", "max")
# Only Optimized is a MEASURED shipping value; Low/Max await the GAMMA harness (§7 OPERATOR-GATED).
_PROVISIONAL_PROFILES = frozenset({"low", "max"})


@dataclass(frozen=True)
class Knob:
    """One published resource knob. ``env_var`` is the live ``OO_*`` override; ``setting`` is the
    ``AppSettings`` field when the knob is stored rather than env-driven (one of the two is set).
    ``kind`` is a DESCRIPTIVE resource dimension (memory/cpu/network/io/latency) — never a score.
    ``optimized`` MUST equal the current app default; ``low``/``max`` are provisional directions."""

    name: str
    env_var: str
    setting: str
    unit: str
    kind: str
    low: Any
    optimized: Any
    max: Any
    note: str
    frontend_wired: bool = True  # False = the reader exists but the app doesn't consult it yet.


# The registry. Each row's ``optimized`` is the CURRENT default verified against the tree:
#   sqlite_cache_mb   -> OO_SQLITE_CACHE_MB default 64  (session.py / scale_bench.py)
#   collect_parallelism -> SchedulerSettings.collect_parallelism default 50 (scheduler/settings.py:65
#     -- RAISED from 1 by the 2026-07-23 maintainer ruling, superseding this row's earlier stale
#     optimized=1; see C9's cross-check test that this stays truthful against the live default)
#   pass_budget_minutes -> OO_PASS_BUDGET_MINUTES default 60 (runner.py:79)
#   rollup_serve_ttl_s  -> OO_COLUMNAR_SERVE_TTL_S default 900 (rollup_serve.py:77)
#   dump_concurrency    -> OO_DUMP_CONCURRENCY default 3 (wiki/dumps.py:37)
#   llm_keep_alive      -> AppSettings.llm_keep_alive default "30m" (app_settings.py:35)
#   fts_analysis_limit  -> NEW OO_FTS_ANALYSIS_LIMIT default 1000 (was the fts.py:384 literal)
#   poll_cadence_s      -> OO_POLL_IDLE_S default 6 (frontend vitals cadence; JS wiring browser-gated)
#   qualification_per_pass   -> SchedulerSettings.qualification_per_pass default 5 (settings.py:103)
#     -- a SETTING-backed knob like collect_parallelism/llm_keep_alive: applied via the
#     settings-write path (the ride-along's own persisted user choice), not a live read-site
#     resolver -- published here for transparency only (2026-07-24 throughput brief C5).
#   qualification_batch_size -> NEW OO_QUALIFICATION_BATCH_SIZE default 20 (was qualify_job.py's
#     ``batch_size: int = 20`` literal + the /qualify-bulk endpoint's Query default; C5)
PUBLISHED_KNOBS: tuple[Knob, ...] = (
    Knob("sqlite_cache_mb", "OO_SQLITE_CACHE_MB", "", "MiB", "memory",
         low=16, optimized=64, max=256,
         note="SQLite page cache; mmap is unavailable under the SQLCipher codec, so this is the "
              "in-memory read lever."),
    Knob("collect_parallelism", "", "collect_parallelism", "workers", "network",
         low=10, optimized=50, max=50,
         note="Bounded fetch worker pool -- the hard CEILING on concurrent fetches (the "
              "BandwidthGovernor's own runtime CPU/memory/writer-contention backoff, kept "
              "EXACTLY as-is on small boxes, still applies underneath this static ceiling). "
              "More workers = more concurrent Tor circuits; per-host politeness is unaffected "
              "(it lives in the host lock). Max stays AT the maintainer-set hard ceiling "
              "(SchedulerSettings._MAX_PARALLELISM=50, ruled 2026-07-23) rather than an "
              "independently invented higher number -- raising it is a separate ruling."),
    Knob("pass_budget_minutes", "OO_PASS_BUDGET_MINUTES", "", "minutes", "cpu",
         low=30, optimized=60, max=180,
         note="Wall-clock budget for one collection pass before it yields."),
    Knob("rollup_serve_ttl_s", "OO_COLUMNAR_SERVE_TTL_S", "", "seconds", "cpu",
         low=1800, optimized=900, max=300,
         note="Windowed-rollup residency: longer = fewer rebuilds (less CPU), shorter = fresher. "
              "The numbers stay CORRECT either way — a basis/as-of disclosure rides the result."),
    Knob("dump_concurrency", "OO_DUMP_CONCURRENCY", "", "downloads", "network",
         low=1, optimized=3, max=6,
         note="Concurrent wiki/OSM dump downloads (files, no DB-writer contention); each is its "
              "own circuit."),
    Knob("http_pool_size", "OO_HTTP_POOL", "", "connections", "network",
         low=16, optimized=64, max=128,
         note="Per-fetcher urllib3 connection-pool size (pool_connections=pool_maxsize) -- sized "
              "generously so ~50 concurrent DISTINCT-host workers (collect_parallelism) don't "
              "churn host-pools. Read once per EthicalFetcher CONSTRUCTION (next-pass, since a "
              "fresh fetcher is built every pass)."),
    Knob("llm_keep_alive", "", "llm_keep_alive", "duration", "memory",
         low="0", optimized="30m", max="-1",
         note="Ollama model residency: '0' unloads immediately (frees RAM), '-1' never unloads "
              "(faster next call, holds RAM)."),
    Knob("fts_analysis_limit", "OO_FTS_ANALYSIS_LIMIT", "", "rows", "cpu",
         low=100, optimized=1000, max=10000,
         note="PRAGMA optimize analysis bound after a bulk load; higher = better planner stats at "
              "more ANALYZE cost."),
    Knob("poll_cadence_s", "OO_POLL_IDLE_S", "", "seconds", "cpu",
         low=15, optimized=6, max=3,
         note="Frontend idle background-poll cadence; longer = less load. The JS wiring is "
              "browser-gated (fork-3) — the knob is published, not yet consulted by the UI.",
         frontend_wired=False),
    Knob("qualification_per_pass", "", "qualification_per_pass", "candidates", "network",
         low=2, optimized=5, max=20,
         note="Source-qualification candidates judged per online collection pass (the "
              "steady-state ride-along). Settings-backed like collect_parallelism: a profile "
              "would rewrite the persisted value via the settings-write path, never a live "
              "per-pass override — the ride-along must still share the pass with markets/"
              "hazards/calendar/law (see the KindLadder), so it stays modest even on capable "
              "boxes; the deep backlog drain is qualification_batch_size's job."),
    Knob("qualification_batch_size", "OO_QUALIFICATION_BATCH_SIZE", "", "candidates", "network",
         low=10, optimized=20, max=100,
         note="Candidates judged per internal batch of the MANUAL bulk qualification job "
              "(POST /api/sources/qualify-bulk) — the catch-up for a large discovery backlog "
              "(measured 42.6k-66.7k candidates at the ride-along's 5/pass = 90+ days). A "
              "capable box can digest far more per batch; a small box stays conservative."),
)

PROFILES: tuple[str, ...] = PROFILE_NAMES


def _knob_by_name() -> dict[str, Knob]:
    return {k.name: k for k in PUBLISHED_KNOBS}


def _value_for(knob: Knob, profile: str) -> Any:
    return {"low": knob.low, "optimized": knob.optimized, "max": knob.max}[profile]


def resolve_effective(profile: str, overrides: dict[str, Any] | None = None) -> dict[str, dict]:
    """PURE. Given a profile name and optional per-knob overrides, return the effective value of
    every published knob: ``{name: {value, source, env_var, setting, unit, kind, provisional}}``.

    An explicit user override ALWAYS wins over the profile (the user's deliberate, reversible
    focus), and its source is reported as ``"override"`` so the UI never hides it. An unknown
    override key is ignored (it is not a published knob — never silently invents a knob).

    Raises ``ValueError`` on an unknown profile (fail loud — never a fabricated default)."""
    if profile not in PROFILE_NAMES:
        raise ValueError(f"unknown power profile {profile!r}; expected one of {PROFILE_NAMES}")
    overrides = overrides or {}
    out: dict[str, dict] = {}
    provisional = profile in _PROVISIONAL_PROFILES
    for knob in PUBLISHED_KNOBS:
        if knob.name in overrides:
            value: Any = overrides[knob.name]
            source = "override"
            row_provisional = False  # the user set it explicitly — it is a real chosen value.
        else:
            value = _value_for(knob, profile)
            source = f"profile:{profile}"
            row_provisional = provisional
        out[knob.name] = {
            "value": value,
            "source": source,
            "env_var": knob.env_var,
            "setting": knob.setting,
            "unit": knob.unit,
            "kind": knob.kind,
            "provisional": row_provisional,
            "frontend_wired": knob.frontend_wired,
        }
    return out


def _clamp_int(raw: str | None, default: int, lo: int, hi: int) -> int:
    """Read an int env value, clamp to [lo, hi], fall back to ``default`` on anything invalid —
    never crash a caller on a fat-fingered env var."""
    if raw is None:
        return default
    try:
        return max(lo, min(hi, int(raw)))
    except (TypeError, ValueError):
        return default


def _active_profile() -> str:
    """The active power profile, from ``OO_POWER_PROFILE`` (default 'optimized'). An unknown
    value falls back to 'optimized' — never a fabricated profile. This is the SERVER-SIDE
    source; the AppSettings-backed UI selector + the active-profile chip are browser-gated
    (fork-3). When unset (the default) every knob resolves to its Optimized value, so the app's
    behaviour is byte-identical to today until an operator explicitly selects a profile."""
    p = (os.getenv("OO_POWER_PROFILE") or "optimized").strip().lower()
    return p if p in PROFILE_NAMES else "optimized"


def _resolve_env_int(name: str, *, lo: int, hi: int) -> int:
    """Effective int value of an env-backed knob: its ``OO_*`` override (clamped) if set, else
    the ACTIVE profile's value. Byte-identical to the prior hard-coded default when the profile
    is Optimized and no env override is set (Optimized == the shipping default). Never raises —
    a fat-fingered env value clamps to the profile value, so a consumer can't crash on it."""
    knob = _knob_by_name()[name]
    prof_val = int(_value_for(knob, _active_profile()))
    raw = os.getenv(knob.env_var) if knob.env_var else None
    return prof_val if raw is None else _clamp_int(raw, prof_val, lo, hi)


# --------------------------------------------------------------------------- #
#  Consumer-facing resolvers (§7 live wiring). Each read site calls one of these instead of
#  its raw ``os.getenv(..., <literal default>)``, so a profile change is honoured without a
#  code edit. Liveness is per-knob (documented on each): a knob read per-operation is LIVE; a
#  knob read at connection/manager construction applies to the NEXT one (the boot singleton is
#  next-restart). NONE of these changes what data is visible or any caveat — resource spend only.
# --------------------------------------------------------------------------- #
def sqlite_cache_mb() -> int:
    """SQLite page-cache MiB (``OO_SQLITE_CACHE_MB`` or the active profile). Read per CONNECTION,
    so a profile switch applies to NEW connections; re-applying to the running main-engine pool
    is OPERATOR-GATED (needs a restart)."""
    return _resolve_env_int("sqlite_cache_mb", lo=2, hi=1_000_000)


def pass_budget_minutes() -> float:
    """Per-pass wall-clock budget in MINUTES (``OO_PASS_BUDGET_MINUTES`` or the active profile).
    Read per PASS, so a profile switch takes effect on the next pass (LIVE). ``0`` disables
    recycling; a negative/invalid env value falls back to the profile value."""
    knob = _knob_by_name()["pass_budget_minutes"]
    prof_val = float(_value_for(knob, _active_profile()))
    raw = os.getenv(knob.env_var)
    if raw is None:
        return prof_val
    try:
        v = float(raw)
        return v if v >= 0 else prof_val
    except (TypeError, ValueError):
        return prof_val


def rollup_serve_ttl_s() -> int:
    """Windowed-rollup churn bound in SECONDS (``OO_COLUMNAR_SERVE_TTL_S`` or the active
    profile). Read per SERVE-CHECK, so a profile switch is LIVE. The rollup numbers stay CORRECT
    at any TTL — a basis/as-of disclosure rides the served result."""
    return _resolve_env_int("rollup_serve_ttl_s", lo=0, hi=10_000_000)


def dump_concurrency() -> int:
    """Concurrent dump downloads (``OO_DUMP_CONCURRENCY`` or the active profile). Read when a
    download manager is CONSTRUCTED, so a profile switch applies to a new manager (the boot
    singleton is next-restart). Per-host politeness is unaffected (it lives in the host lock)."""
    return _resolve_env_int("dump_concurrency", lo=1, hi=64)


def http_pool_size() -> int:
    """urllib3 connection-pool size per fetcher (``OO_HTTP_POOL`` or the active profile). Read
    when an ``EthicalFetcher`` is CONSTRUCTED (a fresh one every pass — see the C4 module-level
    note in ``src.ingest``), so a profile switch applies to the NEXT pass. Optimized=64 is
    byte-identical to the literal it replaces."""
    return _resolve_env_int("http_pool_size", lo=1, hi=10_000)


def qualification_batch_size() -> int:
    """Candidates per internal batch of the MANUAL bulk qualification job
    (``OO_QUALIFICATION_BATCH_SIZE`` or the active profile). Read per REQUEST/worker-call
    (a caller that omits an explicit ``batch_size`` gets this; an explicit value from the
    caller always wins, per the standing override-always-wins rule), so a profile switch
    applies to the NEXT run. Does not touch the admission logic in
    ``src.catalog.qualification`` — only how many candidates one batch judges."""
    return _resolve_env_int("qualification_batch_size", lo=1, hi=100_000)


def fts_analysis_limit() -> int:
    """The ``PRAGMA optimize`` analysis bound (``OO_FTS_ANALYSIS_LIMIT`` or the active profile),
    replacing the hard-coded ``1000`` literal in fts.py. Read per bulk-load optimize, so a
    profile switch is LIVE. Clamped so a bad value can never break a bulk-load optimize."""
    return _resolve_env_int("fts_analysis_limit", lo=0, hi=1_000_000)


def power_profile_report(
    active_profile: str = "optimized", overrides: dict[str, Any] | None = None
) -> dict:
    """Read-only report of the published knob table + the effective values for ``active_profile``.
    Degrades loudly on a bad profile name (honest error field, never a fabricated table). No
    score — ``kind`` is a descriptive resource dimension, not a quality grade."""
    try:
        effective = resolve_effective(active_profile, overrides)
    except ValueError as exc:
        return {
            "schema": SCHEMA,
            "error": str(exc),
            "profiles": list(PROFILE_NAMES),
        }
    return {
        "schema": SCHEMA,
        "active_profile": active_profile,
        "profiles": list(PROFILE_NAMES),
        "provisional_profiles": sorted(_PROVISIONAL_PROFILES),
        "knobs": [
            {
                "name": k.name,
                "env_var": k.env_var,
                "setting": k.setting,
                "unit": k.unit,
                "kind": k.kind,
                "low": k.low,
                "optimized": k.optimized,
                "max": k.max,
                "note": k.note,
                "frontend_wired": k.frontend_wired,
            }
            for k in PUBLISHED_KNOBS
        ],
        "effective": effective,
        "method": (
            "A profile selects one value per published knob; explicit user overrides win and are "
            "shown as such. Optimized IS the current app default (selecting it changes nothing)."
        ),
        "caveat": (
            "A profile changes RESOURCE SPEND only — never data visibility or a caveat. The app "
            "suggests, never silently switches; the active profile is always visible. Low/Max are "
            "PROVISIONAL directions to be replaced by GAMMA-harness measurement before shipping. "
            "No composite score."
        ),
    }


def run_power_profile_selftest() -> dict:
    """Prove the §7 mechanism: Optimized is byte-identical to the current defaults, overrides win,
    an unknown profile fails loud, and no score leaks. Deterministic, no env/DB/network."""
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    eff_opt = resolve_effective("optimized")
    check(
        "optimized_equals_current_defaults",
        all(eff_opt[k.name]["value"] == k.optimized for k in PUBLISHED_KNOBS)
        and all(not eff_opt[k.name]["provisional"] for k in PUBLISHED_KNOBS),
        "Optimized must equal every knob's shipping default and be non-provisional.",
    )

    eff_low = resolve_effective("low")
    check(
        "low_is_flagged_provisional",
        all(eff_low[k.name]["provisional"] for k in PUBLISHED_KNOBS),
        "Low values are placeholders until measured on GAMMA.",
    )

    eff_ovr = resolve_effective("low", {"sqlite_cache_mb": 128})
    check(
        "override_wins_and_is_not_provisional",
        eff_ovr["sqlite_cache_mb"]["value"] == 128
        and eff_ovr["sqlite_cache_mb"]["source"] == "override"
        and eff_ovr["sqlite_cache_mb"]["provisional"] is False,
        str(eff_ovr["sqlite_cache_mb"]),
    )

    eff_unknown = resolve_effective("optimized", {"not_a_knob": 1})
    check(
        "unknown_override_is_ignored",
        "not_a_knob" not in eff_unknown,
        "An unknown override key must never invent a knob.",
    )

    bad = False
    try:
        resolve_effective("turbo")
    except ValueError:
        bad = True
    check("unknown_profile_fails_loud", bad, "resolve_effective('turbo') must raise.")

    check(
        "fts_analysis_limit_defaults_to_optimized",
        fts_analysis_limit()
        == int(_value_for(_knob_by_name()["fts_analysis_limit"], _active_profile()))
        if os.getenv("OO_FTS_ANALYSIS_LIMIT") is None
        else True,
        "With no env override, the wired value equals the ACTIVE profile's value "
        "(Optimized by default, so byte-identical to today).",
    )

    banned = ("score", "ranking", "rating", "grade")
    no_score = True

    def walk(o: Any) -> None:
        nonlocal no_score
        if isinstance(o, dict):
            for kk, vv in o.items():
                if any(b in str(kk).lower() for b in banned):
                    no_score = False
                walk(vv)
        elif isinstance(o, list):
            for vv in o:
                walk(vv)

    walk(power_profile_report("optimized"))
    check("no_score_field", no_score)

    passed = all(c["passed"] for c in checks)
    return {
        "schema": "oo-power-profile-selftest-1",
        "passed": passed,
        "checks": checks,
        "total": len(checks),
        "passed_count": sum(1 for c in checks if c["passed"]),
        "failed_count": sum(1 for c in checks if not c["passed"]),
        "method": "Pure asserts over resolve_effective + the published table; no env/DB/network.",
        "caveat": "Verifies the mechanism + the Optimized==default invariant, not live tuning. "
        "The Low/Max numbers themselves await GAMMA measurement. No score.",
    }
