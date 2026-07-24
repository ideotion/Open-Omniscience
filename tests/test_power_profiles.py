"""
Power profiles — Low / Optimized / Max over a published knob table (planning §7).

The two binding honesty properties: **Optimized == the current app defaults** (selecting it
changes nothing), and **Low / Max are flagged PROVISIONAL** until measured on the GAMMA harness
(§7 says the exact numbers are measured before shipping). Plus: an explicit override always wins
and is never mistaken for a provisional profile value; an unknown profile fails LOUD; the wired
``fts_analysis_limit`` reads the env and clamps; no score anywhere.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.config.power_profiles import (
    PROFILE_NAMES,
    PUBLISHED_KNOBS,
    fts_analysis_limit,
    power_profile_report,
    qualification_batch_size,
    resolve_effective,
    run_power_profile_selftest,
)


def test_optimized_is_byte_identical_to_current_defaults():
    eff = resolve_effective("optimized")
    for k in PUBLISHED_KNOBS:
        assert eff[k.name]["value"] == k.optimized
        assert eff[k.name]["provisional"] is False  # Optimized is the real shipping value.


def test_low_and_max_are_flagged_provisional():
    for profile in ("low", "max"):
        eff = resolve_effective(profile)
        assert all(eff[k.name]["provisional"] for k in PUBLISHED_KNOBS), profile


def test_override_wins_and_is_reported_as_such():
    eff = resolve_effective("low", {"sqlite_cache_mb": 128})
    row = eff["sqlite_cache_mb"]
    assert row["value"] == 128
    assert row["source"] == "override"
    assert row["provisional"] is False  # a user-set value is real, not a provisional placeholder.
    # other knobs remain the (provisional) low values
    assert eff["dump_concurrency"]["source"] == "profile:low"


def test_unknown_override_key_never_invents_a_knob():
    eff = resolve_effective("optimized", {"not_a_knob": 999})
    assert "not_a_knob" not in eff
    assert set(eff) == {k.name for k in PUBLISHED_KNOBS}


def test_unknown_profile_fails_loud():
    with pytest.raises(ValueError):
        resolve_effective("turbo")
    # the report degrades loudly rather than fabricating a table
    rep = power_profile_report("turbo")
    assert "error" in rep and "turbo" in rep["error"]


def test_fts_analysis_limit_defaults_and_clamps(monkeypatch):
    monkeypatch.delenv("OO_FTS_ANALYSIS_LIMIT", raising=False)
    assert fts_analysis_limit() == 1000  # the published Optimized default (was the fts.py literal)
    monkeypatch.setenv("OO_FTS_ANALYSIS_LIMIT", "5000")
    assert fts_analysis_limit() == 5000
    monkeypatch.setenv("OO_FTS_ANALYSIS_LIMIT", "-9")
    assert fts_analysis_limit() == 0  # clamped, never negative
    monkeypatch.setenv("OO_FTS_ANALYSIS_LIMIT", "not-an-int")
    assert fts_analysis_limit() == 1000  # bad value falls back to the default, never crashes


def test_fts_wiring_reads_the_knob_not_a_literal():
    # the fts optimize path must consult the §7 knob, not a hard-coded 1000.
    from pathlib import Path

    src = Path("src/database/fts.py").read_text(encoding="utf-8")
    assert "fts_analysis_limit()" in src
    assert "PRAGMA analysis_limit=1000" not in src  # the literal is gone


def test_qualification_batch_size_defaults_and_clamps(monkeypatch):
    """2026-07-24 throughput brief C5: the manual bulk-qualification job digests a
    hardware-aware batch, byte-identical to the prior fixed 20 on Optimized."""
    monkeypatch.delenv("OO_QUALIFICATION_BATCH_SIZE", raising=False)
    assert qualification_batch_size() == 20  # the published Optimized default
    monkeypatch.setenv("OO_QUALIFICATION_BATCH_SIZE", "80")
    assert qualification_batch_size() == 80
    monkeypatch.setenv("OO_QUALIFICATION_BATCH_SIZE", "not-an-int")
    assert qualification_batch_size() == 20  # bad value falls back, never crashes
    monkeypatch.setenv("OO_POWER_PROFILE", "max")
    monkeypatch.delenv("OO_QUALIFICATION_BATCH_SIZE", raising=False)
    assert qualification_batch_size() == 100  # a capable box digests far more per batch


def test_qualification_per_pass_is_a_published_settings_backed_knob():
    """The ride-along's own per-pass budget is published for transparency (like
    collect_parallelism/llm_keep_alive) but stays applied via the settings-write
    path, never a live per-call override — the ride-along must still share the
    pass with markets/hazards/calendar/law (the KindLadder)."""
    by_name = {k.name: k for k in PUBLISHED_KNOBS}
    knob = by_name["qualification_per_pass"]
    assert knob.setting == "qualification_per_pass"
    assert knob.env_var == ""
    assert knob.optimized == 5  # SchedulerSettings.qualification_per_pass's real default


def test_every_profile_resolves_every_knob():
    for profile in PROFILE_NAMES:
        eff = resolve_effective(profile)
        assert set(eff) == {k.name for k in PUBLISHED_KNOBS}


def test_selftest_all_green_and_non_vacuous():
    log = run_power_profile_selftest()
    assert log["passed"] is True, [c for c in log["checks"] if not c["passed"]]
    names = {c["check"] for c in log["checks"]}
    assert {"optimized_equals_current_defaults", "override_wins_and_is_not_provisional",
            "unknown_profile_fails_loud"} <= names


def test_no_score_field_anywhere():
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert not any(b in str(k).lower() for b in ("score", "ranking", "rating", "grade"))
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(power_profile_report("low"))
    walk(run_power_profile_selftest())
