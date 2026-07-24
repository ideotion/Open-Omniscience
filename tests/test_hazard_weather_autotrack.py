"""
Tests for the background hazard-snapshot + weather-signal refresh pass (Wave 4 J).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The scheduler now keeps the LOCAL hazard snapshot (the severity alert tier's data) and the
weather SIGNAL store fresh, so both are non-empty in a normal collect run instead of only
after an explicit manual POST. Freshness-gated, best-effort, airplane-safe BY CONSTRUCTION:
the hazard pass short-circuits BEFORE any socket when the kill switch is engaged.
"""

from __future__ import annotations

from types import SimpleNamespace

# A minimal, VALID USGS earthquake GeoJSON -> one parsed record.
_USGS_ONE = (
    '{"features":[{"id":"us-test-1","properties":{"title":"M 5.0 - Testland","mag":5.0,'
    '"place":"Testland","time":1700000000000,"url":"https://earthquake.usgs.gov/x"},'
    '"geometry":{"type":"Point","coordinates":[10.0,20.0]}}]}'
)


class FakeFetcher:
    """Records every URL it is asked to fetch; returns crafted content per host (so we can
    prove the injected fetcher is used online, and never touched offline)."""

    def __init__(self, content_by_host: dict[str, str] | None = None):
        self.calls: list[str] = []
        self._content = content_by_host or {}

    def fetch(self, url, require_html=False):
        self.calls.append(url)
        for host, content in self._content.items():
            if host in url:
                return SimpleNamespace(content=content)
        raise RuntimeError(f"unexpected fetch: {url}")


# --------------------------- hazard snapshot pass --------------------------- #


def test_auto_snapshot_saves_via_injected_fetcher(tmp_path, monkeypatch):
    from src.hazards import store, track
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    snap_path = tmp_path / "haz.json"
    monkeypatch.setattr(store, "_snapshot_path", lambda: snap_path)

    fake = FakeFetcher({"earthquake.usgs.gov": _USGS_ONE, "gdacs.org": '{"features":[]}'})
    res = track.auto_snapshot_due(fake)

    assert res["snapshotted"] == 1
    assert any("earthquake.usgs.gov" in u for u in fake.calls)  # injected fetcher used
    loaded = store.load_snapshot()
    assert loaded["available"] is True
    assert [r["source"] for r in loaded["records"]] == ["usgs"]


def test_airplane_refuses_without_attempting_a_socket(tmp_path, monkeypatch):
    from src.hazards import store, track
    from src.ingest import activate_kill_switch, clear_kill_switch

    snap_path = tmp_path / "haz.json"
    monkeypatch.setattr(store, "_snapshot_path", lambda: snap_path)
    fake = FakeFetcher({"earthquake.usgs.gov": _USGS_ONE})  # would be recorded if called

    activate_kill_switch()
    try:
        res = track.auto_snapshot_due(fake)
    finally:
        clear_kill_switch()

    assert res == {"skipped_offline": True}
    assert fake.calls == []  # airplane mode -> NO socket attempted, by construction
    assert not snap_path.exists()  # nothing written


def test_freshness_gate_skips_a_recent_snapshot(tmp_path, monkeypatch):
    from src.hazards import store, track
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    snap_path = tmp_path / "haz.json"
    monkeypatch.setattr(store, "_snapshot_path", lambda: snap_path)
    store.save_snapshot([{"source": "usgs", "id": "x", "severity": "minor"}])  # just now

    fake = FakeFetcher()  # must NOT be fetched from
    res = track.auto_snapshot_due(fake, refresh_interval_hours=6.0)

    assert res["skipped"] == "fresh"
    assert fake.calls == []


def test_stale_snapshot_is_refreshed(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from src.hazards import store, track
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    snap_path = tmp_path / "haz.json"
    monkeypatch.setattr(store, "_snapshot_path", lambda: snap_path)
    old = datetime.now(UTC) - timedelta(hours=10)  # older than the 6h interval
    store.save_snapshot([{"source": "usgs", "id": "old", "severity": "minor"}], now=old)

    fake = FakeFetcher({"earthquake.usgs.gov": _USGS_ONE, "gdacs.org": '{"features":[]}'})
    res = track.auto_snapshot_due(fake, refresh_interval_hours=6.0)

    assert res["snapshotted"] == 1
    assert store.load_snapshot()["records"][0]["id"] == "us-test-1"  # replaced the stale one


def test_auto_snapshot_with_session_also_ingests_as_corpus_articles(tmp_path, monkeypatch):
    """2026-07-24 field-feedback A6: when a Session is given, a freshly-saved snapshot is
    ALSO ingested as corpus Articles (src.hazards.ingest) -- session=None (every other
    caller/test above) stays byte-identical, snapshot-only."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Article, Base
    from src.hazards import store, track
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    snap_path = tmp_path / "haz.json"
    monkeypatch.setattr(store, "_snapshot_path", lambda: snap_path)

    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()

    fake = FakeFetcher({"earthquake.usgs.gov": _USGS_ONE, "gdacs.org": '{"features":[]}'})
    res = track.auto_snapshot_due(fake, session=session)

    assert res["snapshotted"] == 1
    assert res["ingested"] == {"total": 1, "created": 1, "updated": 0, "unchanged": 0, "skipped": 0}
    assert session.query(Article).count() == 1


def test_auto_snapshot_ingest_failure_never_breaks_the_pass(tmp_path, monkeypatch):
    """An ingest hiccup (a broken session, e.g.) degrades honestly -- the snapshot save
    itself must never fail because of it (the scrape pass this rides must not break)."""
    from src.hazards import store, track
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    snap_path = tmp_path / "haz.json"
    monkeypatch.setattr(store, "_snapshot_path", lambda: snap_path)

    class _BrokenSession:
        """Not a real Session -- any attribute access raises, simulating an ingest crash."""

        def __getattr__(self, item):
            raise RuntimeError("boom")

    fake = FakeFetcher({"earthquake.usgs.gov": _USGS_ONE, "gdacs.org": '{"features":[]}'})
    res = track.auto_snapshot_due(fake, session=_BrokenSession())

    assert res["snapshotted"] == 1  # the snapshot itself still saved
    assert "ingested" not in res  # the ingest attempt failed and was swallowed, not raised
    assert store.load_snapshot()["available"] is True


def test_empty_relay_keeps_the_previous_snapshot(tmp_path, monkeypatch):
    from src.hazards import store, track
    from src.ingest import clear_kill_switch

    clear_kill_switch()
    snap_path = tmp_path / "haz.json"
    monkeypatch.setattr(store, "_snapshot_path", lambda: snap_path)

    # A relay that returns nothing (all feeds failed) must never overwrite a good snapshot.
    res = track.auto_snapshot_due(None, fetch_fn=lambda: ([], ["usgs: timeout"]))
    assert res["snapshotted"] == 0
    assert res["failures"] == ["usgs: timeout"]
    assert not snap_path.exists()


# --------------------------- weather signals pass --------------------------- #


def test_weather_freshness_gate_skips_recent_store(tmp_path, monkeypatch):
    from src.analytics import weather_signals as ws

    store_path = tmp_path / "wsig.json"
    monkeypatch.setattr(ws, "_store_path", lambda: store_path)
    ws.save_signals([{"kind": "signal", "term": "signal:heatwave"}])  # derived just now

    def _boom(*a, **k):  # refresh must NOT run when the store is fresh
        raise AssertionError("refresh_weather_signals should not be called when fresh")

    monkeypatch.setattr(ws, "refresh_weather_signals", _boom)
    res = ws.auto_refresh_weather_due(None, refresh_interval_hours=24.0)
    assert res["skipped"] == "fresh"


def test_weather_refreshes_when_stale(tmp_path, monkeypatch):
    from src.analytics import weather_signals as ws

    store_path = tmp_path / "wsig.json"
    monkeypatch.setattr(ws, "_store_path", lambda: store_path)  # no existing store -> due

    def _fake_refresh(session, **k):
        return {"signals": [{"a": 1}, {"b": 2}], "derived_at": "2026-07-08T00:00:00+00:00"}

    monkeypatch.setattr(ws, "refresh_weather_signals", _fake_refresh)
    res = ws.auto_refresh_weather_due(object(), refresh_interval_hours=24.0)
    assert res["refreshed"] == 2
    assert res["derived_at"] == "2026-07-08T00:00:00+00:00"


# ------------------------------ opt-out setting ----------------------------- #


def test_auto_track_signals_setting_roundtrips(tmp_path, monkeypatch):
    from src.scheduler import settings as sch

    # Isolate to a JSON file (so _use_kv() is False -> no shared app_state DB write).
    monkeypatch.setattr(sch, "_settings_path", lambda: tmp_path / "scheduler_settings.json")

    assert sch.load_settings().auto_track_signals is True  # default on
    sch.save_settings({"auto_track_signals": False})
    assert sch.load_settings().auto_track_signals is False
    sch.save_settings({"auto_track_signals": True})
    assert sch.load_settings().auto_track_signals is True
