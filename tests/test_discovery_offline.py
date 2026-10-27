"""The two discovery routes in airplane mode ask NOTHING and say so (invariant #14e's corollary; coordinator ruling R313, G2).

Before, ``POST /api/sources/discover/rss`` answered 200 "Discovered RSS feeds for 0 sources" for sources it never asked about (the DuckDuckGo wrapper
swallows the kill switch's refusal into an empty answer), and ``POST /api/sources/discover/topic`` (with its opt-in setting on) answered 200
"Discovered 0 sources for topic ...". Both read the person's airplane mode as a finding about the WORLD. Now a kill switch that is engaged before the
call answers without calling the search at all, with ``skipped_offline`` (present only then: the number of sources, or the one search, not asked)
and a message that names the kill switch; one engaged DURING the run (the Stop button) is flagged ``stopped_by_kill_switch`` on whatever the run
found. The opt-in refusal (403) stays first. Every other answer keeps its old shape, which the control tests pin.
"""

from __future__ import annotations

import contextlib
import uuid

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.database.models import Source
from src.database.session import SessionLocal, init_db
from src.ingest import activate_kill_switch, clear_kill_switch, kill_switch_active
from src.safety.settings import SafetySettings

client = TestClient(app, base_url="http://127.0.0.1")
_H = {"Sec-Fetch-Site": "same-origin", "Referer": "http://127.0.0.1/", "Origin": "http://127.0.0.1"}


@contextlib.contextmanager
def airplane_mode():
    was = kill_switch_active()
    activate_kill_switch()
    try:
        yield
    finally:
        (activate_kill_switch if was else clear_kill_switch)()


@pytest.fixture(autouse=True)
def _online_and_opted_in(monkeypatch):
    clear_kill_switch()
    monkeypatch.setattr(
        "src.safety.settings.load_settings", lambda: SafetySettings(discovery_external_enabled=True)
    )
    yield
    clear_kill_switch()


def _never(*_a, **_kw):
    raise AssertionError("the search was called while the kill switch was engaged")


@pytest.fixture()
def feedless_source():
    init_db()
    with SessionLocal() as s:
        src = Source(name="Feedless", domain=f"feedless-{uuid.uuid4().hex[:8]}.example", rss_url=None)
        s.add(src)
        s.commit()
        sid = src.id
    try:
        yield sid
    finally:
        with SessionLocal() as s:
            s.query(Source).filter_by(id=sid).delete()
            s.commit()


# --- topic ----------------------------------------------------------------------------------------------------------


def test_topic_discovery_offline_is_refused_not_empty(monkeypatch):
    monkeypatch.setattr("src.database.source_manager.SourceManager.discover_sources_by_topic", _never)
    with airplane_mode():
        r = client.post("/api/sources/discover/topic?topic=energy", headers=_H)
    j = r.json()
    assert r.status_code == 200 and j["count"] == 0 and j["sources"] == []
    assert j["skipped_offline"] == 1
    assert "kill switch" in j["message"] and "airplane mode" in j["message"]


def test_topic_discovery_online_has_no_skipped_offline_key(monkeypatch):
    monkeypatch.setattr(
        "src.database.source_manager.SourceManager.discover_sources_by_topic",
        lambda self, topic, max_sources, region="wt-wt": [],
    )
    j = client.post("/api/sources/discover/topic?topic=energy", headers=_H).json()
    assert j["count"] == 0 and "skipped_offline" not in j and "stopped_by_kill_switch" not in j
    assert j["message"] == "Discovered 0 sources for topic 'energy'"


def test_topic_discovery_stopped_during_the_run_is_flagged(monkeypatch):
    def _stop_midway(self, topic, max_sources, region="wt-wt"):
        activate_kill_switch()
        return []

    monkeypatch.setattr("src.database.source_manager.SourceManager.discover_sources_by_topic", _stop_midway)
    j = client.post("/api/sources/discover/topic?topic=energy", headers=_H).json()
    assert j["stopped_by_kill_switch"] is True and "skipped_offline" not in j
    assert "kill switch" in j["message"]


def test_the_opt_in_refusal_still_comes_first(monkeypatch):
    monkeypatch.setattr(
        "src.safety.settings.load_settings", lambda: SafetySettings(discovery_external_enabled=False)
    )
    with airplane_mode():
        r = client.post("/api/sources/discover/topic?topic=energy", headers=_H)
    assert r.status_code == 403


# --- RSS ------------------------------------------------------------------------------------------------------------


def test_rss_discovery_offline_asks_nobody_and_counts_who_was_not_asked(monkeypatch, feedless_source):
    monkeypatch.setattr("src.services.duckduckgo.DuckDuckGoSearch.find_missing_rss_feeds", _never)
    with airplane_mode():
        r = client.post("/api/sources/discover/rss", headers=_H)
    j = r.json()
    assert r.status_code == 200 and j["total_checked"] == 0 and j["with_rss_found"] == 0 and j["results"] == []
    assert j["skipped_offline"] >= 1
    assert "kill switch" in j["message"] and "airplane mode" in j["message"]


def test_rss_discovery_offline_counts_exactly_the_listed_sources(monkeypatch, feedless_source):
    monkeypatch.setattr("src.services.duckduckgo.DuckDuckGoSearch.find_missing_rss_feeds", _never)
    with airplane_mode():
        r = client.post("/api/sources/discover/rss", json=[feedless_source], headers=_H)
    assert r.json()["skipped_offline"] == 1


def test_rss_discovery_online_has_no_skipped_offline_key(monkeypatch, feedless_source):
    monkeypatch.setattr(
        "src.services.duckduckgo.DuckDuckGoSearch.find_missing_rss_feeds", lambda sources, timeout=10: []
    )
    j = client.post("/api/sources/discover/rss", json=[feedless_source], headers=_H).json()
    assert j["total_checked"] == 0 and "skipped_offline" not in j and "stopped_by_kill_switch" not in j
    assert j["message"] == "Discovered RSS feeds for 0 sources"


def test_rss_discovery_stopped_during_the_run_is_flagged(monkeypatch, feedless_source):
    def _stop_midway(sources, timeout=10):
        activate_kill_switch()
        return []

    monkeypatch.setattr("src.services.duckduckgo.DuckDuckGoSearch.find_missing_rss_feeds", _stop_midway)
    j = client.post("/api/sources/discover/rss", json=[feedless_source], headers=_H).json()
    assert j["stopped_by_kill_switch"] is True and "skipped_offline" not in j
