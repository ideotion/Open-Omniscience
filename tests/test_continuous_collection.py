"""Continuous collection + per-country fair ordering + airplane-mode boot.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Group B slice 1 (SCRAPING_AUTOMATION_PLAN Step 5; maintainer 2026-06-13):
  * the app BOOTS in airplane mode (offline) — nothing scrapes until the one
    online consent;
  * when online, collection is CONTINUOUS (passes back-to-back, no interval idle);
  * sources are ordered per-country round-robin so no source-rich country
    dominates a pass (breaks the US-volume bias structurally).
"""

from __future__ import annotations

import random
import time

from src.scheduler.runner import BackgroundScheduler, round_robin_interleave
from src.scheduler.settings import SchedulerSettings, load_settings, save_settings

# --------------------------------------------------------------------------- #
# Fair ordering — per-country round-robin
# --------------------------------------------------------------------------- #


class _Src:
    def __init__(self, domain, country):
        self.domain = domain
        self.country = country


def test_round_robin_one_per_country_first_then_repeats():
    # US-heavy corpus: 3 US sources, 1 each for fr/ke. A naive priority order
    # would front-load all of US; round-robin must give each country a turn first.
    srcs = [
        _Src("us1", "us"), _Src("us2", "us"), _Src("us3", "us"),
        _Src("fr1", "fr"), _Src("ke1", "ke"),
    ]
    out = round_robin_interleave(srcs, rng=random.Random(0))
    # First round = one source per country (3 distinct countries).
    first_round = out[:3]
    assert {s.country for s in first_round} == {"us", "fr", "ke"}
    # Nothing lost, no duplication.
    assert sorted(s.domain for s in out) == ["fr1", "ke1", "us1", "us2", "us3"]
    # Within-country order preserved (us1 before us2 before us3).
    us = [s.domain for s in out if s.country == "us"]
    assert us == ["us1", "us2", "us3"]


def test_round_robin_empty_and_unknown_country():
    assert round_robin_interleave([]) == []
    # Sources with no country share one bucket — still returned, never dropped.
    srcs = [_Src("a", None), _Src("b", ""), _Src("c", "fr")]
    out = round_robin_interleave(srcs, rng=random.Random(1))
    assert sorted(s.domain for s in out) == ["a", "b", "c"]


def test_round_robin_is_a_permutation_under_many_shuffles():
    srcs = [_Src(f"d{i}", c) for i, c in enumerate(["us", "us", "fr", "de", "ke", "us"])]
    for seed in range(20):
        out = round_robin_interleave(srcs, rng=random.Random(seed))
        assert sorted(s.domain for s in out) == sorted(s.domain for s in srcs)


# --------------------------------------------------------------------------- #
# Continuous loop vs legacy interval
# --------------------------------------------------------------------------- #


_HANG_GUARD_S = 30.0


def _later_passes_margin_s(first_pass_s: float) -> float:
    """What the passes after the first are allowed: ten times what the first took (a runner as loaded as the first pass
    showed, ten times over) and never under 5 s, the fixed wait this replaces."""
    return max(5.0, 10.0 * first_pass_s)


def test_the_margin_for_the_later_passes_scales_with_the_measured_first_pass():
    assert _later_passes_margin_s(0.0) == 5.0 and _later_passes_margin_s(0.4) == 5.0  # a quick runner keeps the old wait
    assert _later_passes_margin_s(2.0) == 20.0 and _later_passes_margin_s(6.0) == 60.0  # a loaded one gets more, in proportion


def test_continuous_mode_runs_passes_back_to_back():
    calls = {"n": 0}

    def fake_run():
        calls["n"] += 1
        return {"ok": True, "run": calls["n"]}

    sched = BackgroundScheduler(
        run_once_fn=fake_run,
        settings_provider=lambda: SchedulerSettings(continuous=True, interval_minutes=60),
    )
    sched._continuous_gap_s = 0.01  # tiny gap so the test sees many passes fast
    # The loop's first idle window runs REAL off-peak maintenance (seconds on a busy database): throttle it as if it had
    # just run, so the 5 s below measure the passes and not the maintenance.
    sched._maint_interval_s = 1e9
    sched._last_maint = time.monotonic()
    try:
        started = time.monotonic()
        assert sched.start() is True
        # The first pass is the loaded part (thread start, the loop's own set-up, a busy runner): wait for it under a hang
        # guard that is not a measurement, then allow the two passes after it a margin MEASURED from how long the first took.
        # A fixed 5 s for all three failed on a loaded CI runner (2 passes in 5 s) although each pass takes microseconds.
        while calls["n"] < 1 and time.monotonic() - started < _HANG_GUARD_S:
            time.sleep(0.02)
        first_pass_s = time.monotonic() - started
        assert calls["n"] >= 1, f"no pass in {_HANG_GUARD_S} s"
        deadline = time.monotonic() + _later_passes_margin_s(first_pass_s)
        while calls["n"] < 3 and time.monotonic() < deadline:
            time.sleep(0.02)
        # Continuous: it kept going (>1 pass) despite interval_minutes=60.
        assert calls["n"] >= 3
    finally:
        sched.stop()


def test_legacy_interval_mode_runs_once_then_waits():
    calls = {"n": 0}

    sched = BackgroundScheduler(
        run_once_fn=lambda: calls.__setitem__("n", calls["n"] + 1) or {"ok": True},
        # continuous=False restores the old cadence: one pass, then a long idle.
        settings_provider=lambda: SchedulerSettings(continuous=False, interval_minutes=60),
    )
    try:
        assert sched.start() is True
        deadline = time.time() + 2
        while calls["n"] < 1 and time.time() < deadline:
            time.sleep(0.02)
        assert calls["n"] == 1  # the immediate first run
        time.sleep(0.5)
        assert calls["n"] == 1  # still 1 — it is idling interval_minutes, not looping
    finally:
        sched.stop()


def test_continuous_setting_round_trips(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    assert load_settings().continuous is True  # default on
    save_settings({"continuous": False})
    assert load_settings().continuous is False
    save_settings({"continuous": True})
    assert load_settings().continuous is True


# --------------------------------------------------------------------------- #
# Airplane-mode boot
# --------------------------------------------------------------------------- #


def test_app_boots_in_airplane_mode(monkeypatch):
    """With the scheduler enabled (production), startup engages airplane mode so
    nothing scrapes until the operator crosses online once."""
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.ingest import clear_kill_switch, kill_switch_active

    monkeypatch.delenv("OO_NO_SCHEDULER", raising=False)  # behave like production
    clear_kill_switch()
    with TestClient(app):  # lifespan runs the deferred startup
        assert kill_switch_active() is True  # booted OFFLINE (airplane engaged)
    clear_kill_switch()
