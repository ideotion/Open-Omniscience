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
    try:
        assert sched.start() is True
        deadline = time.time() + 5
        while calls["n"] < 3 and time.time() < deadline:
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
