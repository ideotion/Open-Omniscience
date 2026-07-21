"""
Tests for scheduler source-selection (language/tags/type) + targets preview.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, Source
from src.scheduler.runner import select_sources
from src.scheduler.settings import SchedulerSettings, load_settings, save_settings


def _db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add_all(
        [
            Source(
                name="FR News",
                domain="fr.test",
                language="fr",
                source_type="news",
                tags="politics,world",
                enabled=True,
                status="qualified",
            ),
            Source(
                name="EN News",
                domain="en.test",
                language="en",
                source_type="news",
                tags="politics,sports",
                enabled=True,
                status="qualified",
            ),
            Source(
                name="EN Mkt",
                domain="mkt.test",
                language="en",
                source_type="financial",
                tags="markets,equities",
                enabled=True,
                status="qualified",
            ),
            Source(
                name="Disabled",
                domain="off.test",
                language="fr",
                source_type="news",
                tags="politics",
                enabled=False,
            ),
        ]
    )
    s.commit()
    return s


def test_select_by_language():
    s = _db()
    rows = select_sources(s, SchedulerSettings(select_languages=["fr"])).all()
    assert {r.domain for r in rows} == {"fr.test"}  # disabled fr excluded


def test_select_by_tag_any():
    s = _db()
    rows = select_sources(s, SchedulerSettings(select_tags=["markets"])).all()
    assert {r.domain for r in rows} == {"mkt.test"}


def test_select_by_source_type():
    s = _db()
    rows = select_sources(s, SchedulerSettings(select_source_types=["news"])).all()
    assert {r.domain for r in rows} == {"fr.test", "en.test"}


def test_no_selection_means_all_enabled():
    s = _db()
    rows = select_sources(s, SchedulerSettings()).all()
    assert {r.domain for r in rows} == {"fr.test", "en.test", "mkt.test"}


def test_settings_roundtrip_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    save_settings({"select_languages": ["FR", "en", "fr"], "select_tags": "Markets, World"})
    s = load_settings()
    assert s.select_languages == ["fr", "en"]  # lowercased + deduped
    assert s.select_tags == ["markets", "world"]


def test_targets_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    save_settings({"select_source_types": ["news"]})
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 't.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add_all(
            [
                Source(name="N1", domain="n1.test", source_type="news", enabled=True, status="qualified"),
                Source(name="N2", domain="n2.test", source_type="news", enabled=True, status="qualified"),
                Source(name="M1", domain="m1.test", source_type="financial", enabled=True, status="qualified"),
            ]
        )
        s.commit()

    def _ovr():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _ovr
    try:
        with TestClient(app) as client:
            t = client.get("/api/scheduler/targets").json()
            assert t["matched"] == 2 and t["total_enabled"] == 3
            assert t["selection"]["source_types"] == ["news"]
            assert t["by_source_type"].get("news") == 2
    finally:
        app.dependency_overrides.clear()
