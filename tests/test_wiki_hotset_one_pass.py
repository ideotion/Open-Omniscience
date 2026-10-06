"""The HOT set's entity read is ONE pass over the lane, and says what the per-edition reads did.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``build_hot_sets`` runs every drain and used to select every versioned entity once PER EDITION
followed (12 full selects, each parsing every id): 2.3 s of one thread's CPU a drain at 200,000
entities, measured on 2026-10-06 against the October bundles' 2.4 to 6.1 thousand seconds of
``oo-wiki-drain`` CPU a session. The single pass must return EXACTLY what the old reads did.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.versioned.models import VersionedEntity
from src.versioned.store import create_lane, dispose_all, lane_session
from src.wiki import hotset
from src.wiki.identity import parse_external_id

EDITIONS = ("en", "fr", "de")


@pytest.fixture
def lane(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    dispose_all()
    create_lane("wiki")
    try:
        yield
    finally:
        dispose_all()


@pytest.fixture
def corpus_factory(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'corpus-hot.db'}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _reference(lane, edition):
    """The pre-change read, kept verbatim as the oracle."""
    pinned: set[int] = set()
    followed: set[int] = set()
    for external_id, is_pinned in lane.execute(
        select(VersionedEntity.external_id, VersionedEntity.pinned)
    ).all():
        try:
            ident = parse_external_id(external_id)
        except ValueError:
            continue
        if ident.wiki != edition or ident.page_id is None:
            continue
        followed.add(ident.page_id)
        if is_pinned:
            pinned.add(ident.page_id)
    return pinned, followed


def _seed(db):
    rows = [
        ("en:p100", False), ("en:p101", True), ("fr:p100", False), ("fr:p7", True),
        ("de:p5", False),
        ("es:p9", True),                      # an edition nobody follows
        ("en:Category:Physics", False),      # a title-keyed legacy id: no page id, skipped
        ("garbage", False),                  # not a lane id at all: skipped, never guessed
        (":42", False),                      # an empty edition prefix
        ("en:", False),                      # an empty rest
        ("law:ABC", True),                   # another lane's id shape
    ]
    for external_id, pinned in rows:
        db.add(VersionedEntity(external_id=external_id, title="t", pinned=pinned))
    db.flush()


def test_one_pass_returns_exactly_what_the_per_edition_reads_returned(lane):
    with lane_session("wiki") as db:
        _seed(db)
        got = hotset.followed_page_ids_by_edition(db, EDITIONS)
        for edition in EDITIONS:
            assert got[edition] == _reference(db, edition), edition
            assert hotset.followed_page_ids(db, edition) == _reference(db, edition)
    assert got["en"] == ({101}, {100, 101})
    assert got["fr"] == ({7}, {100, 7})
    assert got["de"] == (set(), {5})


def test_an_edition_with_no_entities_is_present_and_empty(lane):
    with lane_session("wiki") as db:
        _seed(db)
        got = hotset.followed_page_ids_by_edition(db, ("en", "ja"))
    assert got["ja"] == (set(), set())


def test_build_hot_sets_reads_the_entity_table_once_whatever_the_number_of_editions(
    lane, corpus_factory
):
    from sqlalchemy import event

    selects: list[str] = []
    with lane_session("wiki") as db:
        _seed(db)
        db.commit()
        engine = db.get_bind()

        def count(_conn, _cursor, statement, *_a):
            if "versioned_entities" in statement and statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        event.listen(engine, "before_cursor_execute", count)
        try:
            with corpus_factory() as corpus:
                sets, _report = hotset.build_hot_sets(
                    corpus=corpus, lane=db, editions=EDITIONS + ("es", "ja", "ru")
                )
        finally:
            event.remove(engine, "before_cursor_execute", count)
    assert len(selects) == 1, "one select over versioned_entities, not one per edition"
    assert set(sets) == {"en", "fr", "de", "es", "ja", "ru"}
