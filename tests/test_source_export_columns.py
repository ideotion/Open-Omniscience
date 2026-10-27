"""``GET /api/catalog/export.csv`` asks the database for the twelve columns it writes, not the 24-column entity.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEFECT (entity-load sweep of ``src/api``, 2026-10-27; the A-025 class, ``GET /api/sources`` being the first, #1522). The export
loaded every ``Source`` as a mapped instance to read twelve of its columns: 86,000 instances on the field catalogue. Measured on
86,000 synthetic sources with nothing else running: 2.7 to 4.7 s before and 1.7 to 2.3 s after (min to max over five GETs per run; five runs each side, two in the measuring process that seeded and three in a second process that did not), body byte-identical (10,084,877 bytes, one sha256). The export also
orders by `(name, id)` so that sources sharing a name come out in a defined order.

WHAT THIS FILE HOLDS. (1) The column tuple cannot drift from the row builder: a recording stand-in is handed to
``_source_to_row`` and the attributes it read are the tuple, in order, so a thirteenth value added to the builder without the tuple
would write an empty cell, and this fails first. (2) The bytes are the entity path's bytes: a catalogue with every shape the
builder meets (no country, an aggregate country, a tag list with commas and quotes, a disabled source, non-ASCII, an unset
operator score) is exported by the route and by the old entity path and the two bodies are equal. (3) The route builds no
``Source`` instance, so a later edit back to ``.query(Source)`` is caught here rather than at the next field catalogue.
"""

from __future__ import annotations

import pytest


class _Recorder:
    """Answers every attribute with None and remembers the order they were asked in."""

    def __init__(self):
        self.asked: list[str] = []

    def __getattr__(self, name):
        self.asked.append(name)
        return None


def test_the_column_tuple_is_exactly_what_the_row_builder_reads():
    from src.api.source_io import _EXPORT_ATTRS, _source_to_row

    rec = _Recorder()
    _source_to_row(rec)

    assert tuple(dict.fromkeys(rec.asked)) == _EXPORT_ATTRS


def test_the_tuple_names_the_csv_columns():
    from src.api.source_io import _EXPORT_ATTRS
    from src.catalog.csv_io import EXPORT_COLUMNS

    assert list(_EXPORT_ATTRS) == EXPORT_COLUMNS


@pytest.fixture()
def client(tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.api.main import app
    from src.database.models import Base, Source
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'x.db'}", future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add_all([
            Source(name="Alpha", domain="alpha.test", rss_url="https://alpha.test/f.xml", country="fr", language="fr",
                   tags="news,eu", priority=2, rate_limit_ms=1500, enabled=True, reliability_score=7, source_type="rss"),
            Source(name="Bulk", domain="bulk.test", country="WLD", tags='say "hi", ok', enabled=False),
            Source(name="Nowhere", domain="nowhere.test", country=None),
            Source(name="Alpha", domain="alpha-twin.test", country="de"),  # a duplicate name: the export order must be defined for ties
            Source(name="Zürich Zeitung — «ö»", domain="zz.test", country="ch", language="de", region="eu"),
        ])
        s.commit()

    seen: dict = {}

    def _db():
        d = Sess()
        seen["session"] = d
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            yield c, Sess, seen
    finally:
        app.dependency_overrides.clear()


def test_the_body_is_the_entity_paths_body(client):
    from src.api.source_io import _source_to_row
    from src.catalog.csv_io import write_csv
    from src.database.models import Source
    from src.database.stand_in import not_a_stand_in_source

    c, Sess, _ = client
    r = c.get("/api/catalog/export.csv")
    assert r.status_code == 200

    with Sess() as s:
        want = write_csv([_source_to_row(x) for x in s.query(Source).filter(not_a_stand_in_source()).order_by(Source.name, Source.id).all()])
    assert r.text == want
    assert r.text.count("\n") >= 5, "the catalogue the test seeded did not reach the export"


def test_the_route_builds_no_source_instance(client):
    from sqlalchemy import event

    from src.database.models import Source

    c, _, _ = client
    loaded: list[object] = []

    def _on_load(target, context):
        loaded.append(target)

    event.listen(Source, "load", _on_load)
    try:
        assert c.get("/api/catalog/export.csv").status_code == 200
    finally:
        event.remove(Source, "load", _on_load)

    assert loaded == [], "export.csv built Source instances again"
