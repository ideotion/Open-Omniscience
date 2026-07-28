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
    http_pool_size,
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


def test_http_pool_size_defaults_and_clamps(monkeypatch):
    """C9: the urllib3 connection-pool size is hardware-aware, byte-identical
    to the prior fixed 64 on Optimized."""
    monkeypatch.delenv("OO_HTTP_POOL", raising=False)
    monkeypatch.delenv("OO_POWER_PROFILE", raising=False)
    assert http_pool_size() == 64  # the published Optimized default
    monkeypatch.setenv("OO_HTTP_POOL", "200")
    assert http_pool_size() == 200
    monkeypatch.setenv("OO_HTTP_POOL", "not-an-int")
    assert http_pool_size() == 64  # bad value falls back, never crashes
    monkeypatch.delenv("OO_HTTP_POOL", raising=False)
    monkeypatch.setenv("OO_POWER_PROFILE", "max")
    assert http_pool_size() == 128  # a capable box gets a bigger connection pool


def test_ingest_wiring_reads_the_http_pool_knob_not_a_literal():
    # C9: the fetcher's connection-pool sizing must consult the knob, not a
    # hard-coded '64' literal (the fts_analysis_limit precedent, test_fts_wiring_*).
    from pathlib import Path

    src = Path("src/ingest/__init__.py").read_text(encoding="utf-8")
    assert "http_pool_size()" in src
    assert 'os.getenv("OO_HTTP_POOL", "64")' not in src  # the literal is gone


def test_collect_parallelism_optimized_matches_the_real_scheduler_default():
    """C9 (2026-07-24 throughput brief): this row went STALE once before (it
    published optimized=1 for months after the 2026-07-23 ruling raised the
    REAL SchedulerSettings.collect_parallelism default to 50 -- the
    'Optimized == today' invariant is only ever CHECKED against the table's
    own optimized field, never cross-checked against the live app default, so
    the drift went unnoticed). Import the real dataclass fresh and compare, so
    a future re-drift fails LOUD here instead of silently lying in the table."""
    from src.scheduler.settings import SchedulerSettings

    by_name = {k.name: k for k in PUBLISHED_KNOBS}
    knob = by_name["collect_parallelism"]
    assert knob.optimized == SchedulerSettings().collect_parallelism
    assert knob.max == SchedulerSettings().collect_parallelism  # today IS the hard ceiling


def test_setting_backed_knobs_report_the_live_persisted_value_not_the_profile_table(
    tmp_path, monkeypatch
):
    """2026-07-26 hardware diagnostics: a field export showed the /power-profile
    diagnostic reporting a stale collect_parallelism because it read the static
    profile table, never the live persisted SchedulerSettings/AppSettings value --
    for these three SETTING-backed knobs, the persisted value is ALWAYS what's
    genuinely in effect (nothing today rewrites it on a profile switch), so the
    diagnostic must reflect that, at every profile, even one whose table value
    happens to differ from the live setting."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.config.app_settings import save_settings as save_app_settings
    from src.config.power_profiles import live_setting_overrides
    from src.scheduler.settings import save_settings as save_scheduler_settings

    # Persist values that DIFFER from every profile's table entry (collect_parallelism
    # table has low=10, optimized=50, max=50 -- pick something outside that set).
    save_scheduler_settings({"collect_parallelism": 7, "qualification_per_pass": 3})
    save_app_settings({"llm_keep_alive": "5m"})

    overrides = live_setting_overrides()
    assert overrides["collect_parallelism"] == 7
    assert overrides["qualification_per_pass"] == 3
    assert overrides["llm_keep_alive"] == "5m"

    for profile in PROFILE_NAMES:
        report = power_profile_report(active_profile=profile, overrides=overrides)
        eff = report["effective"]
        assert eff["collect_parallelism"]["value"] == 7
        assert eff["collect_parallelism"]["source"] == "override"
        assert eff["qualification_per_pass"]["value"] == 3
        assert eff["llm_keep_alive"]["value"] == "5m"
        # An env-var-backed knob is UNAFFECTED and still tracks the profile.
        assert eff["dump_concurrency"]["source"] == f"profile:{profile}"


def test_live_setting_overrides_degrades_to_empty_on_a_settings_read_fault(monkeypatch):
    """A diagnostic must never break because a setting can't be read -- the caller
    then falls back to the profile-table value for that knob, same as before this
    existed. Simulate a fault in BOTH settings stores."""
    from src.config import power_profiles as pp_mod

    def _boom():
        raise RuntimeError("simulated settings-store fault")

    monkeypatch.setattr("src.scheduler.settings.load_settings", _boom)
    monkeypatch.setattr("src.config.app_settings.load_settings", _boom)
    assert pp_mod.live_setting_overrides() == {}


def test_power_profile_endpoint_matches_the_live_scheduler_setting(tmp_path, monkeypatch):
    """End-to-end: GET /api/diagnostics/power-profile must agree with the live
    scheduler setting, not the static table -- the exact discrepancy the field
    diagnostic surfaced."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.scheduler.settings import save_settings as save_scheduler_settings

    save_scheduler_settings({"collect_parallelism": 33})
    client = TestClient(app)
    diag = client.get("/api/diagnostics/power-profile?profile=optimized").json()
    assert diag["effective"]["collect_parallelism"]["value"] == 33
    assert diag["effective"]["collect_parallelism"]["source"] == "override"


def test_power_profile_selftest_stays_pure_and_ignores_persisted_settings(tmp_path, monkeypatch):
    """The selftest/resolve_effective path must NEVER read a live setting -- its whole
    value is being deterministic/no-DB/no-env (run_power_profile_selftest's own
    docstring promise). Persist a collect_parallelism that DIFFERS from every
    profile's table entry (low=10, optimized=50, max=50) and confirm the selftest's
    own internal checks (which never pass overrides) are unaffected."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.scheduler.settings import save_settings as save_scheduler_settings

    save_scheduler_settings({"collect_parallelism": 25})
    log = run_power_profile_selftest()
    assert log["passed"] is True, [c for c in log["checks"] if not c["passed"]]


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
