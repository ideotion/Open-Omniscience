"""Row 92 (field test 2026-11-14): a repair of damaged scheduler settings must not silently pause the lane.

The replacement used to write ``wiki_lane_state = "halted"`` every time. It now keeps a recorded
halted or stopped state (with its record), and pauses a lane last known running on purpose,
recording the pause as the repair's: the replacement resets the lane's editions and storage
budget to defaults, and running on them would widen what the operator chose. It logs loudly and
names every switch it wrote OFF in ``written_off`` rather than only in ``reset``.
"""

from __future__ import annotations

import logging

import pytest

import src.config.kv_store as kv_store
from src.scheduler import settings as S
from src.wiki import lane_state_record as R


@pytest.fixture
def damaged(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(kv_store, "kv_get_json", lambda key: store.get(key))
    monkeypatch.setattr(kv_store, "kv_set_json", lambda key, value: store.__setitem__(key, value))
    monkeypatch.setattr(kv_store, "kv_invalidate", lambda key=None: None)
    monkeypatch.setattr(S, "_use_kv", lambda: True)

    def broken(strict=False):
        raise S._DamagedSchedulerSettingsError("damaged")

    monkeypatch.setattr(S, "load_settings", broken)
    import src.wiki.service as svc

    monkeypatch.setattr(svc, "lane_service_status", lambda: {"streaming": False})
    return store


def test_a_recorded_running_lane_is_paused_by_the_repair_and_says_why(damaged, caplog):
    damaged[R.STATE_CHANGE_KEY] = {"from": "halted", "state": "running", "at": "2026-11-10T00:00:00+00:00", "by": "settings-save"}
    with caplog.at_level(logging.WARNING, logger=S._LOG.name):
        saved = S.save_settings({"crawl_per_pass": 3}, replace_damaged=True)
    # Never running on the defaults the replacement restored: all twelve editions, 150 GB.
    assert saved.wiki_lane_state == "halted"
    assert saved.wiki_lane_editions == S.SchedulerSettings().wiki_lane_editions
    assert "wiki_lane_state" in saved.written_off_fields and "wiki_lane_state" not in saved.reset_fields
    rec = R.last_change()
    assert rec["state"] == "halted" and rec["by"] == "settings-replacement"
    assert any("editions and storage budget were reset" in r.getMessage() for r in caplog.records)


def test_a_lane_streaming_in_this_process_is_not_resumed_on_defaults(damaged, monkeypatch):
    import src.wiki.service as svc

    monkeypatch.setattr(svc, "lane_service_status", lambda: {"streaming": True})
    assert S.save_settings({"crawl_per_pass": 3}, replace_damaged=True).wiki_lane_state == "halted"


@pytest.mark.parametrize("state", ["halted", "stopped"])
def test_a_recorded_pause_or_stop_is_kept_with_its_start(damaged, state):
    damaged[R.STATE_CHANGE_KEY] = {"from": "running", "state": state, "at": "2026-11-10T00:00:00+00:00", "by": "settings-save"}
    saved = S.save_settings({"crawl_per_pass": 3}, replace_damaged=True)
    assert saved.wiki_lane_state == state and "wiki_lane_state" not in saved.written_off_fields
    assert "wiki_lane_state" not in saved.reset_fields
    assert R.last_change()["at"] == "2026-11-10T00:00:00+00:00" and R.last_change()["by"] == "settings-save"


def test_an_unknown_recorded_state_is_no_evidence(damaged):
    damaged[R.STATE_CHANGE_KEY] = {"from": None, "state": "flying", "at": "2026-11-10T00:00:00+00:00", "by": "settings-save"}
    saved = S.save_settings({"crawl_per_pass": 3}, replace_damaged=True)
    assert saved.wiki_lane_state == "halted" and "wiki_lane_state" in saved.written_off_fields


def test_without_evidence_the_repair_pauses_records_and_says_so(damaged, caplog):
    with caplog.at_level(logging.WARNING, logger=S._LOG.name):
        saved = S.save_settings({"crawl_per_pass": 3}, replace_damaged=True)
    assert saved.wiki_lane_state == "halted"
    assert "wiki_lane_state" in saved.written_off_fields
    rec = R.last_change()
    assert rec["state"] == "halted" and rec["by"] == "settings-replacement"
    loud = [r for r in caplog.records if r.levelno == logging.WARNING and "replaced by a save" in r.getMessage()]
    assert len(loud) == 1 and "not recorded" in loud[0].getMessage()


def test_every_switch_written_off_is_named(damaged):
    saved = S.save_settings({"crawl_per_pass": 3, "auto_track_law": True}, replace_damaged=True)
    assert set(saved.written_off_fields) >= set(S._ONLINE_OFF_ON_REPLACE) - {"auto_track_law"}
    assert "auto_track_law" not in saved.written_off_fields
    for name in saved.written_off_fields:
        if name != "wiki_lane_state":
            assert getattr(saved, name) is False, name


def test_a_save_that_names_the_state_is_obeyed(damaged):
    saved = S.save_settings({"wiki_lane_state": "stopped"}, replace_damaged=True)
    assert saved.wiki_lane_state == "stopped" and "wiki_lane_state" not in saved.written_off_fields


def test_the_route_answers_written_off_beside_reset():
    import inspect

    from src.api import scheduler as api

    src = inspect.getsource(api.scheduler_update_config)
    assert '"written_off"' in src and '"reset"' in src
