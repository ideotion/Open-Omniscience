"""Row 254 (follows R766 and row 250): the Wikipedia walk and WARM pause name settings that could not be read.

The walk and WARM wait with ``transport_unavailable`` when protected mode has nothing to route through, and the
Living sources view and the task manager said "Protected mode has no usable proxy". When the settings could not be
read, nobody chose protected mode (R766). ``lane_service_status`` now marks that pause ``stored: "unreadable"``
(``transport_summary``'s mark, row 250), the overview passes it on, and both surfaces say the settings could not be
read. What waits, and that it never goes direct, is unchanged. The view's lines run as real code in
``living_sources_node_test.js``.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WALK = "The settings could not be read, so the walk is refused as if protected mode were on, and never goes direct."
LANE = "The settings could not be read, so the lane is refused as if protected mode were on, and never goes direct."


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("OO_FETCH_MODE", "OO_HTTP_PROXY", "OO_HTTP_PROXIES", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(k, raising=False)
        monkeypatch.delenv(k.lower(), raising=False)


def _read_fails(monkeypatch):
    import src.safety.settings as settings
    from src.config.kv_store import KvReadError

    def boom():
        raise KvReadError("locked")

    monkeypatch.setattr(settings, "_read_raw", boom)


def _status():
    return {"walk": {"state": "paused", "reason": "transport_unavailable"},
            "warm": {"state": "paused", "reason": "transport_unavailable"}, "index": None}


def test_the_pause_is_marked_only_when_the_settings_could_not_be_read(monkeypatch):
    from src.wiki import service

    _read_fails(monkeypatch)
    out = service._mark_unreadable(_status())
    assert out["walk"]["stored"] == "unreadable" and out["warm"]["stored"] == "unreadable"
    monkeypatch.setenv("OO_HTTP_PROXIES", "socks5h://127.0.0.1:9150,http://127.0.0.1:8118")  # the environment-pool case
    assert service._mark_unreadable(_status())["walk"]["stored"] == "unreadable"


def test_a_chosen_protected_mode_and_other_reasons_carry_no_mark(monkeypatch):
    import src.safety.settings as settings
    from src.wiki import service

    st = settings.SafetySettings(fetch_mode="protected")
    monkeypatch.setattr(settings, "load_settings", lambda: st)
    out = service._mark_unreadable(_status())
    assert "stored" not in out["walk"] and "stored" not in out["warm"]


def test_the_mark_never_rides_another_reason(monkeypatch):
    from src.wiki import service

    _read_fails(monkeypatch)
    other = service._mark_unreadable({"walk": {"reason": "network_off"}, "warm": None})
    assert other == {"walk": {"reason": "network_off"}, "warm": None}


def test_the_running_lane_status_carries_the_mark(monkeypatch):
    """Through ``lane_service_status`` itself, with a stand-in runner."""
    from src.wiki import service

    class Runner:
        streaming, drains, last_drain = False, 0, None

        def stream_counters(self):
            return {}

        def drain_status(self):
            return None

        def walk_status(self):
            return {"state": "paused", "reason": "transport_unavailable"}

        def warm_status(self):
            return {"state": "paused", "reason": "transport_unavailable"}

        def index_status(self):
            return None

    monkeypatch.setattr(service, "_RUNNER", Runner())
    _read_fails(monkeypatch)
    st = service.lane_service_status()
    assert st["walk"]["stored"] == "unreadable" and st["warm"]["stored"] == "unreadable"


def test_the_overview_passes_the_mark_on(monkeypatch):
    import src.api.living as living
    import src.wiki.service as service

    live = {"walk": {"state": "paused", "reason": "transport_unavailable", "stored": "unreadable"},
            "warm": {"state": "paused", "reason": "transport_unavailable", "stored": "unreadable"}}
    monkeypatch.setattr(service, "lane_service_status", lambda: live)
    assert living._wiki_walk()["stored"] == "unreadable"
    assert living._wiki_warm()["stored"] == "unreadable"
    live["walk"].pop("stored")
    assert "stored" not in living._wiki_walk()


def test_the_task_manager_says_it_too(monkeypatch):
    import src.api.jobs as jobs
    import src.wiki.service as service

    live = {"walk": {"state": "paused", "reason": "transport_unavailable", "stored": "unreadable"}}
    monkeypatch.setattr(service, "lane_service_status", lambda: live)
    (job,) = jobs._wiki_walk_jobs()
    assert job["detail"] == WALK == jobs._WALK_WHY_UNREADABLE and "Protected mode" not in job["detail"]
    live["walk"].pop("stored")
    (job,) = jobs._wiki_walk_jobs()
    assert job["detail"] == "Protected mode has no usable proxy, and the walk never goes direct."


def test_both_lines_are_said_in_twelve_languages():
    living_js = (ROOT / "src/static/app-living.js").read_text(encoding="utf-8")
    assert f'"{WALK}"' in living_js and f'"{LANE}"' in living_js
    locales = sorted((ROOT / "src/static/locales").glob("*.json"))
    assert len(locales) == 12
    for path in locales:
        table = json.loads(path.read_text(encoding="utf-8"))
        for key in (WALK, LANE):
            assert table.get(key), f"{path.name} lacks: {key[:50]}"
