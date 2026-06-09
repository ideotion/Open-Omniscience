"""
Tests for source-catalog CSV import/export.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Round-trip, validation (bad rows reported not dropped), upsert-by-domain, and the
/api/catalog endpoints (export round-trips through import; bad numerics rejected).
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.csv_io import (
    parse_sources_csv,
    template_csv,
    upsert_sources,
    write_csv,
)
from src.database.models import Base, Source


def _db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_parse_good_and_bad_rows():
    csv_text = (
        "name,domain,country,tags,priority,enabled\n"
        'Good Paper,https://www.good.example/,US,"politics,world",1,true\n'
        ",no-name.example,US,,2,true\n"  # missing name -> error
        "Bad Priority,bad.example,US,,9,true\n"  # priority out of range -> error
        "Off Source,off.example,fr,sports,3,no\n"
    )
    rows, errors = parse_sources_csv(csv_text)
    domains = {r["domain"] for r in rows}
    assert domains == {"good.example", "off.example"}  # URL reduced to host
    assert any("row 3" in e for e in errors)  # missing name
    assert any("row 4" in e for e in errors)  # priority range
    good = next(r for r in rows if r["domain"] == "good.example")
    assert good["country"] == "us" and good["priority"] == 1 and good["enabled"] is True
    off = next(r for r in rows if r["domain"] == "off.example")
    assert off["enabled"] is False


def test_upsert_creates_then_updates():
    s = _db()
    rows, _ = parse_sources_csv("name,domain,priority\nAcme,acme.example,2\n")
    r1 = upsert_sources(s, rows)
    assert r1["created"] == 1 and r1["updated"] == 0

    rows2, _ = parse_sources_csv("name,domain,priority,tags\nAcme Renamed,acme.example,1,news\n")
    r2 = upsert_sources(s, rows2)
    assert r2["created"] == 0 and r2["updated"] == 1
    row = s.query(Source).filter_by(domain="acme.example").one()
    assert row.name == "Acme Renamed" and row.priority == 1 and row.tags == "news"
    s.close()


def test_template_round_trips_through_parser():
    rows, errors = parse_sources_csv(template_csv())
    assert not errors
    assert {r["domain"] for r in rows} == {"example.com", "exchange.example"}


def test_write_csv_has_all_columns():
    text = write_csv([{"name": "X", "domain": "x.example"}])
    header = text.splitlines()[0]
    for col in ("name", "domain", "tags", "enabled", "reliability_score"):
        assert col in header


def test_catalog_api_export_import_roundtrip(tmp_path):
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'cat.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(
            Source(
                name="Seed One",
                domain=f"seed-{uuid.uuid4().hex}.example",
                country="us",
                tags="politics",
                source_type="news",
            )
        )
        s.commit()

    def _override():
        db = Sess()
        try:
            yield db
        finally:
            db.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _override
    try:
        with TestClient(app) as client:
            # Columns endpoint advertises the format.
            cols = client.get("/api/catalog/columns").json()
            assert "name" in cols["columns"] and cols["required"] == ["name", "domain"]

            # Export current catalog as CSV.
            exported = client.get("/api/catalog/export.csv")
            assert exported.status_code == 200
            assert exported.headers["content-type"].startswith("text/csv")
            assert "Seed One" in exported.text

            # Import a brand-new source via CSV upload.
            new_domain = f"imported-{uuid.uuid4().hex}.example"
            payload = f"name,domain,country,tags\nImported,{new_domain},ke,africa\n"
            up = client.post(
                "/api/catalog/import",
                files={"file": ("new.csv", payload, "text/csv")},
            )
            assert up.status_code == 200, up.text
            assert up.json()["created"] == 1
            assert client.get("/api/catalog/template.csv").status_code == 200

            # The imported source is now in the catalog.
            with Sess() as s:
                assert s.query(Source).filter_by(domain=new_domain).first() is not None
    finally:
        app.dependency_overrides.clear()
