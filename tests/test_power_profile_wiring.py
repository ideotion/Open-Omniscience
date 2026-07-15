"""S11 — the power-profile knobs are LIVE-WIRED to their consumers.

Each server-side knob's consumer now reads a resolver (OO_* override, else the active profile
from OO_POWER_PROFILE, default 'optimized') instead of a hard-coded env default. This pins:

  * flipping OO_POWER_PROFILE changes every wired knob's effective value at its consumer;
  * with the profile Optimized (the default) + no env override, every resolver equals the
    prior hard-coded default (byte-identical to today);
  * an explicit OO_* override wins over the profile;
  * an unknown profile falls back to Optimized (never a fabricated profile);
  * the consumer read sites actually call the resolvers (source-pinned).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path

from src.config.power_profiles import (
    PUBLISHED_KNOBS,
    dump_concurrency,
    fts_analysis_limit,
    pass_budget_minutes,
    rollup_serve_ttl_s,
    sqlite_cache_mb,
)

# resolver -> knob name; each returns its OO_* override or the active-profile value.
_RESOLVERS = {
    "sqlite_cache_mb": sqlite_cache_mb,
    "pass_budget_minutes": pass_budget_minutes,
    "rollup_serve_ttl_s": rollup_serve_ttl_s,
    "dump_concurrency": dump_concurrency,
    "fts_analysis_limit": fts_analysis_limit,
}
_KNOB = {k.name: k for k in PUBLISHED_KNOBS}
# every knob these resolvers cover has a distinct low vs optimized value (so a flip is visible).
_ENV_VARS = (
    "OO_POWER_PROFILE", "OO_SQLITE_CACHE_MB", "OO_PASS_BUDGET_MINUTES",
    "OO_COLUMNAR_SERVE_TTL_S", "OO_DUMP_CONCURRENCY", "OO_FTS_ANALYSIS_LIMIT",
)


def _clean_env(monkeypatch):
    for v in _ENV_VARS:
        monkeypatch.delenv(v, raising=False)


def test_optimized_is_byte_identical_at_every_consumer(monkeypatch):
    _clean_env(monkeypatch)  # no profile, no overrides -> Optimized == the prior default
    for name, fn in _RESOLVERS.items():
        assert fn() == type(fn())(_KNOB[name].optimized), name


def test_flipping_the_profile_changes_every_wired_knob(monkeypatch):
    _clean_env(monkeypatch)
    opt = {name: fn() for name, fn in _RESOLVERS.items()}
    monkeypatch.setenv("OO_POWER_PROFILE", "low")
    low = {name: fn() for name, fn in _RESOLVERS.items()}
    # Every wired knob's effective value changed at its consumer (well over the "at least two").
    changed = [n for n in _RESOLVERS if low[n] != opt[n]]
    assert len(changed) == len(_RESOLVERS), (opt, low)
    for name, fn in _RESOLVERS.items():
        assert fn() == type(fn())(_KNOB[name].low), name
    # and Max is distinct again
    monkeypatch.setenv("OO_POWER_PROFILE", "max")
    for name, fn in _RESOLVERS.items():
        assert fn() == type(fn())(_KNOB[name].max), name


def test_env_override_wins_over_the_active_profile(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("OO_POWER_PROFILE", "low")  # would give 16
    monkeypatch.setenv("OO_SQLITE_CACHE_MB", "200")  # explicit override
    assert sqlite_cache_mb() == 200
    monkeypatch.setenv("OO_FTS_ANALYSIS_LIMIT", "7777")
    assert fts_analysis_limit() == 7777


def test_a_bad_env_value_falls_back_to_the_profile_value_never_crashes(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("OO_POWER_PROFILE", "low")
    monkeypatch.setenv("OO_SQLITE_CACHE_MB", "not-a-number")
    assert sqlite_cache_mb() == int(_KNOB["sqlite_cache_mb"].low)  # 16, never a crash
    monkeypatch.setenv("OO_PASS_BUDGET_MINUTES", "garbage")
    assert pass_budget_minutes() == float(_KNOB["pass_budget_minutes"].low)


def test_an_unknown_profile_falls_back_to_optimized(monkeypatch):
    _clean_env(monkeypatch)
    monkeypatch.setenv("OO_POWER_PROFILE", "turbo")  # not a real profile
    for name, fn in _RESOLVERS.items():
        assert fn() == type(fn())(_KNOB[name].optimized), name


def test_the_consumer_read_sites_call_the_resolvers():
    # Source-pinned (the wiring lesson): each read site must call its resolver, not a literal.
    wiring = {
        "src/database/session.py": "cache_mb = sqlite_cache_mb()",
        "src/testing/scale_bench.py": "cache_mb = sqlite_cache_mb()",
        "src/scheduler/runner.py": "pass_budget_minutes() * 60.0",
        "src/analytics/rollup_serve.py": "age < rollup_serve_ttl_s()",
        "src/wiki/dumps.py": "else dump_concurrency()",
    }
    for path, needle in wiring.items():
        assert needle in Path(path).read_text(encoding="utf-8"), path
    # the old hard-coded literals are gone from the read sites
    assert 'int(os.getenv("OO_SQLITE_CACHE_MB", "64"))' not in Path(
        "src/database/session.py"
    ).read_text(encoding="utf-8")
