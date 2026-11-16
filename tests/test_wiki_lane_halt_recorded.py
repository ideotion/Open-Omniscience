"""Field test 2026-11-14 row 73: a halted Wikipedia lane must read as halted, with since when.

One machine's lane sat halted for days, across two restarts, while the soak reading said
"0 rows a day, no gap", which is also what a quiet lane says. The settings save now records
when the run state changed and through which door, and the soak reading publishes the
held-off stretch beside the gap history. A halt is deliberately NOT a versioned_gaps row:
a resume continues from the stored cursor, and a real hole is recorded then as retention.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import src.config.kv_store as kv_store
from src.monitoring import soak_window as sw
from src.scheduler import settings as S
from src.wiki import lane_state_record as R


@pytest.fixture
def kv(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(kv_store, "kv_get_json", lambda key: store.get(key))
    monkeypatch.setattr(kv_store, "kv_set_json", lambda key, value: store.__setitem__(key, value))
    monkeypatch.setattr(S, "_use_kv", lambda: True)
    return store


def _current(state: str):
    return lambda strict=False: S.SchedulerSettings(wiki_lane_state=state)


def test_a_save_that_halts_the_lane_records_when(kv, monkeypatch):
    monkeypatch.setattr(S, "load_settings", _current("running"))
    S.save_settings({"wiki_lane_state": "halted"})
    rec = R.last_change()
    assert rec["from"] == "running" and rec["state"] == "halted" and rec["by"] == "settings-save"
    assert abs(datetime.fromisoformat(rec["at"]) - datetime.now(UTC)) < timedelta(minutes=1)


def test_a_save_that_does_not_change_the_state_records_nothing(kv, monkeypatch):
    monkeypatch.setattr(S, "load_settings", _current("halted"))
    S.save_settings({"wiki_lane_state": "halted"})
    S.save_settings({"crawl_per_pass": 3})
    assert R.last_change() is None


def test_the_damaged_settings_replacement_names_its_own_door(kv, monkeypatch):
    def damaged(strict=False):
        raise S._DamagedSchedulerSettingsError("damaged")

    monkeypatch.setattr(S, "load_settings", damaged)
    monkeypatch.setattr("src.config.kv_store.kv_invalidate", lambda key: None, raising=False)
    S.save_settings({"crawl_per_pass": 3}, replace_damaged=True)
    rec = R.last_change()
    assert rec["state"] == "halted" and rec["from"] is None and rec["by"] == "settings-replacement"


def test_a_failed_record_never_fails_the_save(kv, monkeypatch):
    monkeypatch.setattr(S, "load_settings", _current("running"))
    real = kv_store.kv_set_json

    def picky(key, value):
        if key == R.STATE_CHANGE_KEY:
            raise RuntimeError("disk")
        real(key, value)

    monkeypatch.setattr(kv_store, "kv_set_json", picky)
    assert S.save_settings({"wiki_lane_state": "stopped"}).wiki_lane_state == "stopped"


def test_soak_reading_publishes_the_halted_stretch(kv):
    since = datetime(2026, 11, 12, 17, 8, tzinfo=UTC)
    kv[R.STATE_CHANGE_KEY] = {"from": "running", "state": "halted", "at": since.isoformat(), "by": "settings-save"}
    got = sw._not_running("halted", now=since + timedelta(hours=50))
    assert got["state"] == "halted" and got["since"] == since.isoformat()
    assert got["hours"] == 50.0 and got["by"] == "settings-save" and got["previous"] == "running"
    assert "retention gap" in got["caveat"]


def test_soak_reading_says_when_the_start_was_not_recorded(kv):
    # OOS-3's own case: halted before this record existed.
    got = sw._not_running("halted")
    assert got["since"] is None and got["hours"] is None and "did not record" in got["reason"]
    # A record of a DIFFERENT state does not date this one.
    kv[R.STATE_CHANGE_KEY] = {"from": "halted", "state": "stopped", "at": datetime.now(UTC).isoformat(), "by": "settings-save"}
    assert sw._not_running("halted")["since"] is None


def test_a_running_lane_has_no_not_running_stretch(kv):
    assert sw._not_running("running") is None
    assert sw._not_running(None) is None
