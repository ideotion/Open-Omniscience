"""``GET /api/sources`` reads the eight columns it serves and builds no ``Source`` entity (audit 0.5.0 A-025, item 30).

``Source`` has 24 columns and the route serves eight of them. It used to load a full ORM entity per row and read eight attributes off each:
at 86,000 sources 2.7-4.4 s and a 184 MB peak, against 0.65-0.73 s and 46 MB for the eight columns (a synthetic scratch store, tracemalloc on,
so the times run high and real source text is longer). These tests pin the two things the change must not move: the response, row for row,
and the SELECT's shape (the column list and no entity load), so a later edit cannot quietly put the entity back.
"""

from __future__ import annotations

import re

import pytest

_ROW = ("id", "name", "domain", "rss_url", "rate_limit_ms", "enabled", "priority", "tags")


@pytest.fixture
def sources_client(tmp_path, monkeypatch):
    """A TestClient over a throwaway store whose sources differ in every field the route reads, plus a stand-in source it must leave out."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.database.models import Base, Source, engine, get_session
    from src.database.stand_in import SOURCE_DOMAIN_PREFIX

    Base.metadata.create_all(engine)
    session = get_session()
    try:
        if session.query(Source).count() == 0:
            shapes = [
                ("a", "a.example", "https://a.example/feed", 2000, True, 1, "news,world"),
                ("b", "b.example", None, 500, False, 3, ""),
                ("c", "c.example", "https://c.example/feed", 1000, True, 2, None),
                ("d", "d.example", None, 0, False, 0, "one"),
                ("e", "e.example", "https://e.example/atom", 7500, True, 9, "x,y,z"),
            ]
            for name, domain, rss, rate, enabled, prio, tags in shapes:
                session.add(Source(name=name, domain=domain, rss_url=rss, rate_limit_ms=rate, enabled=enabled, priority=prio, tags=tags))
            session.add(Source(name="stand-in", domain=f"{SOURCE_DOMAIN_PREFIX}lost", rss_url=None, enabled=False))
            session.commit()
    finally:
        session.close()
    with TestClient(app) as client:
        yield client


def _expected_from_entities() -> list[dict]:
    """The rows the route served before the change, built the way it built them: the entity, then the eight attributes."""
    from src.database.models import Source, get_session
    from src.database.stand_in import not_a_stand_in_source

    session = get_session()
    try:
        return [
            {
                "id": s.id,
                "name": s.name,
                "domain": s.domain,
                "rss_url": s.rss_url,
                "rate_limit_ms": s.rate_limit_ms,
                "enabled": s.enabled,
                "priority": s.priority,
                "tags": s.tags.split(",") if s.tags else [],
            }
            for s in session.query(Source).filter(not_a_stand_in_source()).order_by(Source.id.asc()).all()
        ]
    finally:
        session.close()


def test_the_response_is_row_for_row_what_the_entity_read_served(sources_client) -> None:
    got = sources_client.get("/api/sources")
    assert got.status_code == 200
    expected = _expected_from_entities()
    assert len(expected) == 5, "the stand-in source is not a source the user saved"
    assert got.json() == expected
    assert [list(r) for r in got.json()] == [list(_ROW)] * 5, "the same keys in the same order"
    # the shapes the fixture holds on purpose: no feed, an empty tag string, a missing tag value, a disabled source
    by_name = {r["name"]: r for r in got.json()}
    assert by_name["b"]["rss_url"] is None and by_name["b"]["tags"] == [] and by_name["b"]["enabled"] is False
    assert by_name["c"]["tags"] == [] and by_name["e"]["tags"] == ["x", "y", "z"]


def test_limit_offset_and_fields_still_cut_the_same_rows(sources_client) -> None:
    expected = _expected_from_entities()
    assert sources_client.get("/api/sources?limit=2").json() == expected[:2]
    assert sources_client.get("/api/sources?limit=2&offset=1").json() == expected[1:3]
    assert sources_client.get("/api/sources?offset=3").json() == expected[3:]
    thin = sources_client.get("/api/sources?fields=id,name,rss_url").json()
    assert thin == [{k: r[k] for k in ("id", "name", "rss_url")} for r in expected]


def test_the_select_names_exactly_the_eight_columns_and_builds_no_source_entity(sources_client) -> None:
    from sqlalchemy import event

    from src.database.models import Source, engine

    statements: list[str] = []
    loaded: list[object] = []

    def _on_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    def _on_load(target, _context):
        loaded.append(target)

    event.listen(engine, "before_cursor_execute", _on_statement)
    event.listen(Source, "load", _on_load)
    try:
        assert sources_client.get("/api/sources").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", _on_statement)
        event.remove(Source, "load", _on_load)

    selects = [s for s in statements if re.search(r"\bFROM sources\b", s) and s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1, f"one SELECT on sources, not {len(selects)}: {selects}"
    select_list = re.match(r"\s*SELECT\s+(.*?)\s+FROM sources\b", selects[0], re.S | re.I).group(1)
    columns = sorted(re.sub(r"\s+AS\s+\w+$", "", c.strip(), flags=re.I).split(".")[-1] for c in select_list.split(","))
    assert columns == sorted(_ROW), f"the SELECT names {columns}, the row serves {sorted(_ROW)}"
    assert not loaded, "a Source entity was built for the list: the route reads columns, not objects"


def test_nothing_the_entity_read_ran_is_skipped_by_reading_columns() -> None:
    """Reading columns bypasses the ORM's instance events, so the premise is pinned: ``Source`` has no ``load`` or ``refresh`` listener (its only
    two, ``before_insert`` and ``before_update``, derive ``feed_key`` on a WRITE and this route never writes), no hybrid property, validator or
    synonym on the eight columns, and none of the eight has a column type that converts on read (``CountryCode`` and ``CompressedText`` sit on
    other columns). A listener or conversion added later fails here, naming what the list route would then skip."""
    from sqlalchemy.types import TypeDecorator

    from src.database.models import Source

    for name in ("load", "refresh", "refresh_flush", "expire"):
        assert not len(getattr(Source.__mapper__.class_manager.dispatch, name)), f"Source has a {name!r} listener: the list route reads columns and would skip it"
    assert len(Source.__mapper__.dispatch.before_insert) == 1 and len(Source.__mapper__.dispatch.before_update) == 1, "the write-side listeners changed: read them"
    for name in _ROW:
        attr = Source.__mapper__.attrs[name]
        assert type(attr).__name__ == "ColumnProperty", f"Source.{name} is a {type(attr).__name__}, not a plain column"
        assert not isinstance(attr.columns[0].type, TypeDecorator), f"Source.{name} converts on read ({attr.columns[0].type!r})"
