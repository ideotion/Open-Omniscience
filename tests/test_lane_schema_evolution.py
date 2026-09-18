"""A lane file written by an older build must be readable by this one.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``models.py`` records that there is "deliberately NO alembic history for lane files
in 0.4: these tables are born here, so there is nothing to migrate". That was true for
exactly as long as ONE build had declared them. S04-09 added
``VersionedEntity.deleted_at``, a facts table and ``admitted_reason`` — and
``create_all`` creates missing TABLES while never touching an existing table's
COLUMNS, so a lane file created by S04-08's build raised ``no such column`` on its
first read under S04-09's.

The defect is REPRODUCED here before the fix is asserted, on a file built to look
exactly like the older build's, and the refusal path is exercised too: this is an
additive reconciliation, not a migration framework, and the difference has to be
visible rather than assumed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, String, create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from src.versioned.models import LaneBase, VersionedEntity
from src.versioned.store import LaneSchemaError, add_missing_columns


@pytest.fixture
def older_build(tmp_path):
    """A lane file with every table but without the columns S04-09 added."""
    engine = create_engine(f"sqlite:///{tmp_path / 'older.db'}")
    LaneBase.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE versioned_entities DROP COLUMN deleted_at"))
        conn.execute(text("ALTER TABLE versioned_entities DROP COLUMN admitted_reason"))
        conn.execute(text("DROP TABLE versioned_entity_facts"))
    return engine


def test_the_defect_REPRODUCES_before_anything_is_fixed(older_build):
    session = sessionmaker(bind=older_build)
    with pytest.raises(Exception) as exc, session() as db:  # noqa: PT011 - the driver's own type
        db.query(VersionedEntity).first()
    assert "no such column" in str(exc.value)
    assert "deleted_at" in str(exc.value)


def test_create_all_alone_does_NOT_close_it(older_build):
    """The premise. If this ever stops being true, delete the reconciliation."""
    LaneBase.metadata.create_all(older_build)
    columns = {c["name"] for c in inspect(older_build).get_columns("versioned_entities")}
    assert "deleted_at" not in columns, "create_all restored the TABLE and not the COLUMN"
    assert "versioned_entity_facts" in inspect(older_build).get_table_names()


def test_the_reconciliation_adds_exactly_the_missing_columns(older_build):
    LaneBase.metadata.create_all(older_build)
    added = add_missing_columns(older_build)
    assert sorted(added) == [
        "versioned_entities.admitted_reason",
        "versioned_entities.deleted_at",
    ]
    session = sessionmaker(bind=older_build)
    with session() as db:
        db.query(VersionedEntity).first()  # no longer raises


def test_it_is_idempotent_and_a_second_run_changes_nothing(older_build):
    LaneBase.metadata.create_all(older_build)
    add_missing_columns(older_build)
    assert add_missing_columns(older_build) == []


def test_an_UP_TO_DATE_file_is_untouched(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'current.db'}")
    LaneBase.metadata.create_all(engine)
    assert add_missing_columns(engine) == []


def test_a_column_present_in_the_FILE_and_absent_from_the_model_is_LEFT_ALONE(older_build):
    """The file may have been written by a build NEWER than this one. Destroying its
    data to match an older model is the worst thing this function could do."""
    with older_build.begin() as conn:
        conn.execute(text("ALTER TABLE versioned_entities ADD COLUMN from_the_future TEXT"))
        conn.execute(
            text(
                "INSERT INTO versioned_entities (external_id, pinned, watching, "
                "first_seen_at, from_the_future) VALUES ('x:p1', 0, 1, "
                "'2026-09-18T00:00:00', 'kept')"
            )
        )
    LaneBase.metadata.create_all(older_build)
    add_missing_columns(older_build)
    with older_build.connect() as conn:
        value = conn.execute(text("SELECT from_the_future FROM versioned_entities")).scalar()
    assert value == "kept"


def test_a_NOT_NULL_column_with_no_default_is_REFUSED_by_name_rather_than_guessed(tmp_path):
    """Filling one for existing rows is a decision about their contents that only a
    real migration can make. The refusal names the column."""
    engine = create_engine(f"sqlite:///{tmp_path / 'strict.db'}")
    LaneBase.metadata.create_all(engine)
    table = LaneBase.metadata.tables["versioned_entities"]
    column = Column("must_be_filled", String(8), nullable=False)
    table.append_column(column)
    try:
        with pytest.raises(LaneSchemaError) as exc:
            add_missing_columns(engine)
        assert "must_be_filled" in str(exc.value)
        assert "migration" in str(exc.value)
    finally:
        table._columns.remove(column)  # noqa: SLF001 - restoring shared metadata


def test_the_refusal_leaves_the_FILE_untouched(tmp_path):
    """A half-applied schema change is worse than none: it would be invisible."""
    engine = create_engine(f"sqlite:///{tmp_path / 'strict2.db'}")
    LaneBase.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE versioned_entities DROP COLUMN admitted_reason"))
    table = LaneBase.metadata.tables["versioned_entities"]
    column = Column("must_be_filled2", Integer, nullable=False)
    table.append_column(column)
    try:
        with pytest.raises(LaneSchemaError):
            add_missing_columns(engine)
    finally:
        table._columns.remove(column)  # noqa: SLF001
    columns = {c["name"] for c in inspect(engine).get_columns("versioned_entities")}
    assert "must_be_filled2" not in columns, "the refused column"
    assert "admitted_reason" not in columns, (
        "AND the addable one that comes before it in declaration order -- this is the "
        "assertion that makes the test's name true. An implementation that applied as "
        "it went would have added this one and then refused, leaving a file that is "
        "neither shape."
    )
