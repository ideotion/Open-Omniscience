"""Live-DB upgrade self-heal holes (release-0.1 blocker).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The live DB is BY DESIGN never alembic-migrated (only staged restore copies are);
upgrades rest entirely on the boot ensure_* self-heal battery. The 0.1 upgrade
audit found 0.09-cycle migrations that added columns with NO self-heal, so a
0.0.8/early-0.09 store opened by 0.1 code raised "no such column" on the first
ORM query:

  * keywords.extractor                       (migration c3d4e5f6a7b8)
  * wiki_pages.latest_text / latest_text_revid (migration b6c7d8e9f0a1)
  * wiki_revisions.full_text                 (migration b6c7d8e9f0a1)
  * wiki_pages.missing / wiki_categories     (migration c9d8e7f6a5b4)
  * keyword_supergroup_members.ring_id       (migration f4a5b6c7d8e9)

This suite builds an OLD-schema store (current tables minus exactly those
columns, rows seeded through the old schema), runs the battery, and proves the
columns exist and the ORM queries work — the field failure mode, end to end.
The companion drift guard (tests/test_migration_self_heal_drift.py) keeps the
hole from ever reopening for a future migration.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.database.maintenance import (
    ensure_keyword_extractor_column,
    ensure_supergroup_ring_column,
    ensure_wiki_text_columns,
)
from src.database.models import (
    Base,
    Keyword,
    KeywordSuperGroupMember,
    WikiPage,
    WikiRevision,
)

# The exact 0.09-cycle holes the battery must heal (table -> dropped columns).
_HOLES: dict[str, list[str]] = {
    "keywords": ["extractor"],
    "wiki_pages": ["latest_text", "latest_text_revid", "missing", "wiki_categories"],
    "wiki_revisions": ["full_text"],
    "keyword_supergroup_members": ["ring_id"],
}


def _run_battery(engine) -> list[str]:
    added: list[str] = []
    added += ensure_keyword_extractor_column(engine)
    added += ensure_wiki_text_columns(engine)
    added += ensure_supergroup_ring_column(engine)
    return added


@pytest.fixture()
def old_engine():
    """A 0.0.8/early-0.09-shaped store: current schema MINUS the hole columns,
    with one row per affected table inserted through the OLD schema."""
    eng = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(eng)
    with eng.begin() as c:
        for table, cols in _HOLES.items():
            for col in cols:
                c.execute(text(f"ALTER TABLE {table} DROP COLUMN {col}"))
        c.execute(
            text("INSERT INTO keywords (id, term, normalized_term) VALUES (1, 'Budget', 'budget')")
        )
        c.execute(text("INSERT INTO wiki_pages (id, wiki, title) VALUES (1, 'en', 'Water')"))
        c.execute(text("INSERT INTO wiki_revisions (id, page_id, revid) VALUES (1, 1, 42)"))
        c.execute(text("INSERT INTO keyword_supergroups (id, name) VALUES (1, 'Energy')"))
        c.execute(
            text(
                "INSERT INTO keyword_supergroup_members (id, supergroup_id, normalized_term) "
                "VALUES (1, 1, 'budget')"
            )
        )
    return eng


def test_old_schema_reproduces_the_field_failure(old_engine):
    """Sanity: without the heal, the ORM raises 'no such column' (the real bug)."""
    s = sessionmaker(bind=old_engine, future=True)()
    with pytest.raises(Exception, match="no such column"):
        s.query(Keyword).all()
    s.close()


def test_battery_heals_every_hole_and_orm_queries_work(old_engine):
    added = _run_battery(old_engine)
    assert set(added) == {
        "extractor",
        "wiki_pages.latest_text",
        "wiki_pages.latest_text_revid",
        "wiki_pages.missing",
        "wiki_pages.wiki_categories",
        "wiki_revisions.full_text",
        "ring_id",
    }
    # The columns physically exist.
    with old_engine.connect() as c:
        for table, cols in _HOLES.items():
            have = {r[1] for r in c.execute(text(f"PRAGMA table_info({table})"))}
            missing = set(cols) - have
            assert not missing, f"{table} still lacks {missing} after the self-heal"
    # And the ORM works end to end — the exact query class that failed in the field.
    s = sessionmaker(bind=old_engine, future=True)()
    kw = s.query(Keyword).one()
    assert kw.normalized_term == "budget"
    assert kw.extractor is None  # honest NULL: provenance unrecorded for old rows
    page = s.query(WikiPage).one()
    assert (page.latest_text, page.latest_text_revid) == (None, None)
    assert (page.missing, page.wiki_categories) == (None, None)
    rev = s.query(WikiRevision).one()
    assert rev.full_text is None
    member = s.query(KeywordSuperGroupMember).one()
    assert member.ring_id is None  # NULL = a plain family member (pre-ring meaning)
    s.close()


def test_battery_is_idempotent(old_engine):
    assert _run_battery(old_engine)  # first pass heals
    assert _run_battery(old_engine) == []  # second pass adds nothing


def test_fresh_db_is_a_noop():
    """create_all already builds the columns — the heal must not touch a fresh DB."""
    eng = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(eng)
    assert _run_battery(eng) == []


def test_missing_tables_are_a_noop():
    """A store that never had wiki/keyword tables (create_all will build them
    later in init_db) must not crash the battery."""
    eng = create_engine("sqlite:///:memory:", future=True)
    assert _run_battery(eng) == []


def test_boot_path_wires_the_new_heals():
    """init_db must call the three new heals alongside the existing battery, so
    every boot (app lifespan / installer / tests) inherits them."""
    src = (
        Path(__file__).resolve().parents[1] / "src" / "database" / "session.py"
    ).read_text(encoding="utf-8")
    body = src.split("def init_db", 1)[1].split("\ndef ", 1)[0]
    for fn in (
        "ensure_keyword_extractor_column",
        "ensure_wiki_text_columns",
        "ensure_supergroup_ring_column",
    ):
        assert f"{fn}(engine)" in body, f"init_db no longer wires {fn}"
