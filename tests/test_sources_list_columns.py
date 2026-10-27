"""``GET /api/sources`` reads the eight columns it serves and builds no ``Source`` entity (audit 0.5.0 A-025, item 30).

``Source`` has 24 columns and the route serves eight of them. It used to load a full ORM entity per row and read eight attributes off each:
at 86,000 sources 2.7-4.4 s and a 184 MB peak, against 0.65-0.73 s and 46 MB for the eight columns (a synthetic scratch store, tracemalloc on,
so the times run high and real source text is longer). These tests pin the two things the change must not move: the response, row for row and
type for type, and the SELECT's shape (the column list and no entity load), so a later edit cannot quietly put the entity back.

The suite shares one store (the conftest binds the engine once), so the fixture seeds rows of its own with a distinctive domain on EVERY run,
whatever an earlier test left behind, finds them by that domain, and deletes them afterwards. The expected rows are the whole table read the old
way, so the comparison holds with any other rows present.
"""

from __future__ import annotations

import json
import re

import pytest

_ROW = ("id", "name", "domain", "rss_url", "rate_limit_ms", "enabled", "priority", "tags")
_MARK = "colstest-"  # the domain prefix of the rows this file owns


@pytest.fixture
def sources_client(tmp_path, monkeypatch):
    """A TestClient over the suite's store with five sources of this file's own that differ in every field the route reads, and a stand-in it must leave out."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.database.models import Base, Source, engine, get_session
    from src.database.stand_in import SOURCE_DOMAIN_PREFIX

    Base.metadata.create_all(engine)
    shapes = [
        ("a", f"{_MARK}a.example", "https://a.example/feed", 2000, True, 1, "news,world"),
        ("b", f"{_MARK}b.example", None, 500, False, 3, ""),
        ("c", f"{_MARK}c.example", "https://c.example/feed", 1000, True, 2, None),
        ("d", f"{_MARK}d.example", None, 0, False, 0, "one"),
        ("e", f"{_MARK}e.example", "https://e.example/atom", 7500, True, 9, "x,y,z"),
    ]
    stand_in_domain = f"{SOURCE_DOMAIN_PREFIX}{_MARK}lost"

    def _delete_mine() -> None:
        session = get_session()
        try:
            session.query(Source).filter(Source.domain.in_([s[1] for s in shapes] + [stand_in_domain])).delete(synchronize_session=False)
            session.commit()
        finally:
            session.close()

    _delete_mine()  # a run that died half way leaves rows behind; seed from none
    session = get_session()
    try:
        for name, domain, rss, rate, enabled, prio, tags in shapes:
            session.add(Source(name=name, domain=domain, rss_url=rss, rate_limit_ms=rate, enabled=enabled, priority=prio, tags=tags))
        session.add(Source(name="stand-in", domain=stand_in_domain, rss_url=None, enabled=False))
        session.commit()
    finally:
        session.close()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        _delete_mine()


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


def _types(rows: list[dict]) -> list[dict]:
    return [{k: type(v).__name__ for k, v in r.items()} for r in rows]


def test_the_response_is_row_for_row_and_type_for_type_what_the_entity_read_served(sources_client) -> None:
    got = sources_client.get("/api/sources")
    assert got.status_code == 200
    expected = _expected_from_entities()
    body = json.loads(got.content)
    assert body == expected
    # ``1 == True`` in Python: equality alone would pass a body that served 1 where it served true, so the types are compared too
    assert _types(body) == _types(expected)
    assert all(type(r["enabled"]) is bool for r in body if r["enabled"] is not None)
    assert [list(r) for r in body] == [list(_ROW)] * len(body), "the same keys in the same order"
    mine = {r["name"]: r for r in body if r["domain"].startswith(_MARK)}
    assert sorted(mine) == ["a", "b", "c", "d", "e"], "the five rows this file seeded, and not the stand-in"
    assert not any(r["name"] == "stand-in" for r in body), "a stand-in source is not a source the user saved"
    # the shapes seeded on purpose: no feed, an empty tag string, a missing tag value, a disabled source
    assert mine["b"]["rss_url"] is None and mine["b"]["tags"] == [] and mine["b"]["enabled"] is False
    assert mine["c"]["tags"] == [] and mine["e"]["tags"] == ["x", "y", "z"]


def test_limit_offset_and_fields_still_cut_the_same_rows(sources_client) -> None:
    expected = _expected_from_entities()
    assert len(expected) >= 5
    assert sources_client.get("/api/sources?limit=2").json() == expected[:2]
    assert sources_client.get("/api/sources?limit=2&offset=1").json() == expected[1:3]
    assert sources_client.get(f"/api/sources?offset={len(expected) - 3}").json() == expected[-3:]
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

    # the engine-wide listener sees every thread: keep the statements that read what this route reads (the id, the feed and the tags of ``sources``)
    selects = [
        s for s in statements
        if s.lstrip().upper().startswith("SELECT") and re.search(r"\bFROM sources\b", s) and all(f"sources.{c}" in s for c in ("id", "rss_url", "tags"))
    ]
    assert len(selects) == 1, f"one SELECT of the list on sources, not {len(selects)}: {selects}"
    select_list = re.match(r"\s*SELECT\s+(.*?)\s+FROM sources\b", selects[0], re.S | re.I).group(1)
    columns = sorted(re.sub(r"\s+AS\s+\w+$", "", c.strip(), flags=re.I).split(".")[-1] for c in select_list.split(","))
    assert columns == sorted(_ROW), f"the SELECT names {columns}, the row serves {sorted(_ROW)}"
    assert not loaded, "a Source entity was built for the list: the route reads columns, not objects"


def test_nothing_the_entity_read_ran_is_skipped_by_reading_columns() -> None:
    """Reading columns bypasses the ORM's INSTANCE events, so that premise is pinned: ``Source`` has no ``load`` or ``refresh`` listener (its only two,
    ``before_insert`` and ``before_update``, derive ``feed_key`` on a WRITE and this route never writes), no session-level ``loaded_as_persistent``
    listener, and each of the eight is a plain mapped column (no hybrid property, validator or synonym stands in for it). A column's TYPE conversion is
    NOT among the things skipped (a ``TypeDecorator`` runs for a column query as for an entity load), so it is not asserted here. A listener added
    later fails here, naming what the list route would then skip."""
    from src.database.models import Source, get_session

    for name in ("load", "refresh", "refresh_flush", "expire"):
        assert not len(getattr(Source.__mapper__.class_manager.dispatch, name)), f"Source has a {name!r} listener: the list route reads columns and would skip it"
    session = get_session()  # an instance's dispatch joins the class-level listeners with its own, so a session the app builds shows what it would run
    try:
        session_listeners = len(session.dispatch.loaded_as_persistent)
    finally:
        session.close()
    assert not session_listeners, "a session-level loaded_as_persistent listener: the list route builds no persistent object and would skip it"
    assert len(Source.__mapper__.dispatch.before_insert) == 1 and len(Source.__mapper__.dispatch.before_update) == 1, "the write-side listeners changed: read them"
    for name in _ROW:
        attr = Source.__mapper__.attrs[name]
        assert type(attr).__name__ == "ColumnProperty", f"Source.{name} is a {type(attr).__name__}, not a plain mapped column"
