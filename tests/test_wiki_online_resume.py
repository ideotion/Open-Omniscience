"""One click on the airplane button resumes the Wikipedia run, and what was on stays on (R117).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer's rule (2026-10-01, answer 21): the app always starts offline, one click on the
airplane button brings it online, and whether Wikipedia scraping was on or off when the app last
went offline or shut down stays as it was -- a run that was on resumes with that one click, one
that was off stays off. That is three separate facts and each is pinned here: the settings are not
touched by the toggle, the click is what starts the lane, and the lane starts only when its
setting says running.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.scheduler.settings import load_settings, save_settings

_KEYS = ("wiki_lane_state", "wiki_walk_enabled", "wiki_warm_enabled")


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.delenv("OO_NO_SCHEDULER", raising=False)  # the toggle's lane seam is skipped under it
    return tmp_path


@pytest.fixture
def toggle(data_dir, monkeypatch):
    """The real /api/system/network route, with the scheduler and the lane replaced by recorders."""
    import src.ingest as ingest
    import src.scheduler.runner as runner_mod
    import src.wiki.service as svc
    from src.api.system import router

    calls: list[str] = []

    class _FakeScheduler:
        def start(self):
            calls.append("scheduler.start")

        def stop(self):
            calls.append("scheduler.stop")

    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: _FakeScheduler())
    monkeypatch.setattr(svc, "start_wiki_lane", lambda: calls.append("lane.start") or True)
    monkeypatch.setattr(svc, "stop_wiki_lane", lambda **_k: calls.append("lane.stop"))
    app = FastAPI()
    app.include_router(router)
    try:
        yield TestClient(app), calls
    finally:
        ingest.activate_kill_switch()  # leave the process as every other test expects it


def _read():
    s = load_settings()
    return {k: getattr(s, k) for k in _KEYS}


@pytest.mark.parametrize(
    "chosen",
    [
        {"wiki_lane_state": "running", "wiki_walk_enabled": True, "wiki_warm_enabled": True},
        {"wiki_lane_state": "stopped", "wiki_walk_enabled": False, "wiki_warm_enabled": False},
        {"wiki_lane_state": "halted", "wiki_walk_enabled": True, "wiki_warm_enabled": False},
    ],
)
def test_going_offline_and_online_never_touches_what_was_chosen(toggle, chosen):
    client, _calls = toggle
    save_settings(chosen)
    for online in (False, True, False, True):
        assert client.post("/api/system/network", json={"online": online}).status_code == 200
        assert _read() == chosen, f"the airplane button changed a Wikipedia setting (online={online})"


def test_the_click_online_is_what_starts_the_lane_and_offline_stops_it(toggle):
    client, calls = toggle
    save_settings({"wiki_lane_state": "running"})
    client.post("/api/system/network", json={"online": True})
    assert "lane.start" in calls and "lane.stop" not in calls
    client.post("/api/system/network", json={"online": False})
    assert calls[-1] == "lane.stop"


class _Runner:
    streaming = False

    def __init__(self):
        self.started = 0

    def start(self):
        self.started += 1
        self.streaming = True
        return True

    def run_until_stopped(self, **_k):
        return 0

    def stop(self, **_k):
        self.streaming = False


@pytest.mark.parametrize(
    ("state", "starts"),
    [("running", True), ("halted", False), ("stopped", False)],
)
def test_the_lane_starts_only_when_its_setting_says_running(data_dir, monkeypatch, state, starts):
    import src.wiki.service as svc

    built: list[_Runner] = []
    monkeypatch.setattr(svc, "_build", lambda: built.append(_Runner()) or built[-1])
    save_settings({"wiki_lane_state": state})
    try:
        assert svc.start_wiki_lane() is starts
        assert bool(built) is starts, "a lane that is not chosen must not even be built"
    finally:
        svc.stop_wiki_lane(timeout=1.0)


def test_choosing_the_stream_alone_never_switches_the_walk_or_warm_on(data_dir):
    """What was chosen stays, and what was never chosen stays off (R51): the settings are stored
    in the corpus database, so an update reads back exactly what the last run saved and a key it
    never saved reads as its default, which for the walk and WARM is OFF."""
    save_settings({"wiki_lane_state": "running"})
    now = _read()
    assert now["wiki_lane_state"] == "running"
    assert now["wiki_walk_enabled"] is False and now["wiki_warm_enabled"] is False
