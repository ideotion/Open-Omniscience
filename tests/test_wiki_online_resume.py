"""One click on the airplane button resumes the Wikipedia run, and what was on stays on (R117).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer's rule (2026-10-01, answer 21): the app always starts offline, one click on the
airplane button brings it online, and whether Wikipedia scraping was on or off when the app last
went offline or shut down stays as it was -- a run that was on resumes with that one click, one
that was off stays off. That is three separate facts and each is pinned here: the settings are not
touched by the toggle, the click is what starts the lane, and the lane starts only when its
setting says running. "The app always starts offline" is pinned elsewhere:
tests/test_boot_airplane_never_revokes_online.py covers the boot engage.
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
    monkeypatch.delenv(
        "OO_NO_SCHEDULER", raising=False
    )  # the toggle's lane seam is skipped under it
    return tmp_path


class _Runner:
    """Stands in for the stream runner only; the service's real start and stop run around it."""

    streaming = False

    def __init__(self):
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1
        self.streaming = True
        return True

    def run_until_stopped(self, **_k):
        return 0

    def stop(self, **_k):
        self.stopped += 1
        self.streaming = False


@pytest.fixture
def toggle(data_dir, monkeypatch):
    """The real /api/system/network route and the real lane start and stop, with the scheduler and
    the stream runner replaced by recorders. Only the runner is faked, so a stop path that saved a
    setting would be seen by the settings checks."""
    import src.ingest as ingest
    import src.scheduler.runner as runner_mod
    import src.wiki.service as svc
    from src.api.system import router

    built: list[_Runner] = []

    class _FakeScheduler:
        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(runner_mod, "get_scheduler", lambda: _FakeScheduler())
    monkeypatch.setattr(svc, "_build", lambda: built.append(_Runner()) or built[-1])
    app = FastAPI()
    app.include_router(router)
    try:
        yield TestClient(app), built
    finally:
        svc.stop_wiki_lane(timeout=1.0)
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
    client, _built = toggle
    save_settings(chosen)
    for online in (False, True, False, True):
        assert client.post("/api/system/network", json={"online": online}).status_code == 200
        assert _read() == chosen, (
            f"the airplane button changed a Wikipedia setting (online={online})"
        )


def test_the_click_online_is_what_starts_the_lane_and_offline_stops_it(toggle):
    client, built = toggle
    save_settings({"wiki_lane_state": "running"})
    client.post("/api/system/network", json={"online": True})
    assert len(built) == 1 and built[0].started == 1 and built[0].stopped == 0
    client.post("/api/system/network", json={"online": False})
    assert built[0].stopped == 1
    # What was on stays on: the next click resumes it, because the setting still says running.
    client.post("/api/system/network", json={"online": True})
    assert len(built) == 2 and built[1].started == 1


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


@pytest.mark.parametrize("route", ["/api/scheduler/start", "/api/scheduler/run-now"])
@pytest.mark.parametrize(
    ("state", "builds"),
    [("running", 1), ("halted", 0), ("stopped", 0)],
)
def test_the_collection_start_buttons_resume_only_a_lane_that_was_on(
    data_dir, monkeypatch, route, state, builds
):
    """R117 on the two callers the October fix added: Start and Run-now give the lane its go with
    the REAL ``start_wiki_lane``, so a lane the operator switched off is not built by them."""
    import src.api.scheduler as sched
    import src.wiki.service as svc

    class _Scheduler:
        def start(self):
            return True

        def run_now(self):
            return True

        def status(self):
            return {"running": True, "settings": {}}

    class _ReadableRunner(_Runner):
        """The start route's status payload reads the runner's service state."""

        drains = 0
        last_drain = None

        def stream_counters(self):
            return None

        def drain_status(self):
            return {}

        def walk_status(self):
            return None

        def warm_status(self):
            return None

        def index_status(self):
            return None

    built: list[_Runner] = []
    monkeypatch.setattr(sched, "get_scheduler", lambda: _Scheduler())
    monkeypatch.setattr(svc, "_build", lambda: built.append(_ReadableRunner()) or built[-1])
    save_settings({"wiki_lane_state": state})
    app = FastAPI()
    app.include_router(sched.router)
    try:
        assert TestClient(app).post(route).status_code == 200
        assert len(built) == builds
        assert _read()["wiki_lane_state"] == state, "the button never rewrites the setting"
    finally:
        svc.stop_wiki_lane(timeout=1.0)
        import src.ingest as ingest

        ingest.activate_kill_switch()
