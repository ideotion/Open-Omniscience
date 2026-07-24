"""Tests for the hazard map layer (src.api.timemap._hazard_signals) and the
hazards-snapshot endpoint's corpus-ingest side effect.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-07-24 field-feedback Session A §6 (ruled: hazards ingested as Articles). Two
surfaces changed and both were previously UNTESTED:
  * src.api.timemap._hazard_signals -- reads the LOCAL snapshot (zero network on
    render) and now resolves each event's internal Article id, when the record has
    already been ingested (src.hazards.ingest), so the map can deep-link to the
    local reader;
  * POST /api/signals/hazards/snapshot -- every saved snapshot is ALSO ingested as
    corpus Articles, best-effort (never breaks the snapshot save itself).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


@pytest.fixture()
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    return tmp_path


def _usgs_rec(**kw) -> dict:
    rec = {
        "source": "usgs", "id": "us7000abcd", "type": "earthquake", "severity": "major",
        "title": "M 7.1 - 120km SSW of Town", "magnitude": 7.1, "lat": 38.1, "lon": 142.5,
        "place": "120km SSW of Town", "time": "2026-06-01T00:00:00Z",
        "url": "https://earthquake.usgs.gov/x",
    }
    rec.update(kw)
    return rec


# --------------------------------------------------------------------------- #
#  _hazard_signals — zero-network map layer
# --------------------------------------------------------------------------- #


def test_hazard_signals_absent_is_honest_empty(data_dir):
    from src.api.timemap import _hazard_signals

    sigs, failures = _hazard_signals()
    assert sigs == []
    assert failures and "no local hazard snapshot" in failures[0]


def test_hazard_signals_resolves_the_internal_article_id(data_dir, session):
    """An event that has ALREADY been ingested as a corpus Article (e.g. via the
    snapshot endpoint's ingest side effect, or the scheduler ride-along) carries its
    real article_id here -- so the map's click-detail can deep-link to the local
    reader."""
    from src.hazards.ingest import ingest_hazard_record
    from src.hazards.store import save_snapshot

    rec = _usgs_rec()
    ingest_hazard_record(session, rec)
    save_snapshot([rec])

    from src.api.timemap import _hazard_signals

    sigs, failures = _hazard_signals(session)
    assert failures == []
    assert len(sigs) == 1
    s = sigs[0]
    assert s["kind"] == "hazard"
    assert s["hazard_type"] == "earthquake"
    assert s["magnitude"] == 7.1
    assert s["lat"] == 38.1 and s["lon"] == 142.5
    art = session.query(Article).one()
    assert s["article_id"] == art.id


def test_hazard_signals_never_ingested_degrades_to_no_article_id(data_dir, session):
    """A record that was snapshotted but never routed through ingest (e.g. the
    ingest step failed, or ran before this feature existed) must degrade to
    article_id=None -- never a fabricated/guessed link."""
    from src.hazards.store import save_snapshot

    save_snapshot([_usgs_rec()])

    from src.api.timemap import _hazard_signals

    sigs, _ = _hazard_signals(session)
    assert len(sigs) == 1
    assert sigs[0]["article_id"] is None
    assert session.query(Article).count() == 0  # confirms: genuinely never ingested


def test_hazard_signals_without_a_session_never_crashes(data_dir):
    """db=None (e.g. the /range endpoint, which only needs the time extent) must
    degrade gracefully -- every article_id stays None, never a crash."""
    from src.hazards.store import save_snapshot

    save_snapshot([_usgs_rec()])

    from src.api.timemap import _hazard_signals

    sigs, failures = _hazard_signals(None)
    assert failures == []
    assert len(sigs) == 1
    assert sigs[0]["article_id"] is None


def test_hazard_signals_reports_staleness(data_dir):
    from datetime import UTC, datetime, timedelta

    from src.hazards.store import save_snapshot

    old = datetime.now(UTC) - timedelta(hours=100)
    save_snapshot([_usgs_rec()], now=old)

    from src.api.timemap import _hazard_signals

    sigs, failures = _hazard_signals()
    assert len(sigs) == 1  # records still shown ("silence is not safety")
    assert any("stale" in f for f in failures)  # but the staleness is disclosed


def test_hazard_signals_skips_records_missing_a_coordinate_or_date(data_dir):
    """Never plotted at (0,0) or "now" -- a record with no coord/date is absent
    from the map, not fabricated in."""
    from src.hazards.store import save_snapshot

    save_snapshot([
        _usgs_rec(id="ok"),
        _usgs_rec(id="no-coord", lat=None, lon=None),
        _usgs_rec(id="no-date", time=None),
    ])

    from src.api.timemap import _hazard_signals

    sigs, _ = _hazard_signals()
    assert len(sigs) == 1
    assert sigs[0]["id"] == "hazard:ok"


# --------------------------------------------------------------------------- #
#  POST /api/signals/hazards/snapshot -- corpus-ingest side effect
# --------------------------------------------------------------------------- #


def test_snapshot_endpoint_also_ingests_as_corpus_articles(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from fastapi.testclient import TestClient

    from src.api.main import app

    # A hazard://usgs/... canonical_url can never collide with any other test's
    # seeded articles -- safe to run against the shared TestClient DB.
    body = {"records": [_usgs_rec(id="oo-a6-snapshot-endpoint-test")]}
    with TestClient(app) as c:
        out = c.post("/api/signals/hazards/snapshot", json=body).json()
        assert out["saved"] is True
        assert out["ingested"] == {
            "total": 1, "created": 1, "updated": 0, "unchanged": 0, "skipped": 0,
        }
        # And the map layer picks up the freshly-ingested article_id, end to end.
        rng = c.get("/api/timemap?hazards=true").json()
        haz = next(s for s in rng["signals"] if s["id"] == "hazard:oo-a6-snapshot-endpoint-test")
        assert haz["article_id"] is not None


def test_snapshot_endpoint_ingest_failure_never_fails_the_save(tmp_path, monkeypatch):
    """A broken ingest must degrade honestly -- the snapshot save itself (the thing the
    alert layer depends on) must still succeed."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from fastapi.testclient import TestClient

    from src.api.main import app

    def _boom(db, records):
        raise RuntimeError("ingest boom")

    # The endpoint imports ingest_hazard_records lazily FROM src.hazards.ingest at
    # call time -- patch the module attribute it actually resolves.
    import src.hazards.ingest as ingest_mod

    monkeypatch.setattr(ingest_mod, "ingest_hazard_records", _boom)

    body = {"records": [_usgs_rec(id="oo-a6-snapshot-endpoint-ingest-failure")]}
    with TestClient(app) as c:
        out = c.post("/api/signals/hazards/snapshot", json=body).json()
    assert out["saved"] is True  # the snapshot write itself is unaffected
    assert out["ingested"] == {}  # the failed attempt left it at its honest default
    assert any("corpus ingest" in f for f in out["failures"])
