"""The admission audit trail, and the retirement of the ``scrape_unqualified`` hatch
(Q1101 = a, 2026-09-15; brief ``S04-12`` S1).

TWO THINGS, and they are one ruling. Q1101 makes a ``qualified`` verdict flip
``enabled=True`` -- qualification IS the admission gate -- and in the same breath retires
the ``scrape_unqualified`` hatch, which had let collection reach sources the engine had
not judged. A gate that admits automatically owes a record of every admission, so
``source_admission_events`` is created here: append-only, carrying the source's state
BEFORE each flip so the audit view's undo can restore it exactly.

(``create_all`` already creates the table on fresh stores; this migration keeps
alembic-managed databases consistent. It is guarded, because the ordinary boot path calls
``create_all`` BEFORE any stamp moves while the RESTORE path runs alembic straight at a
staged copy and never calls it -- the recorded 2026-09-16 lesson.)

THE HATCH'S PERSISTED VALUE IS DROPPED HERE, ONCE, AND SAID OUT LOUD. The setting lived in
the scheduler settings JSON, not in a column, so there is nothing to ALTER -- the drop
happens where that file is read (``src.scheduler.settings``), which also emits the
one-time disclosure. This migration records the retirement in the schema history so the
change is visible to anyone reading the migration chain rather than only to someone
reading the settings loader.

Revision ID: 7c3ea19b4d02
Revises: a71c3e8b45d2
Create Date: 2026-09-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "7c3ea19b4d02"
down_revision = "a71c3e8b45d2"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if _has_table("source_admission_events"):  # create_all may have already made it
        return
    op.create_table(
        "source_admission_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("verdict", sa.String(length=20), nullable=False),
        sa.Column("criteria_version", sa.String(length=40), nullable=False),
        # Nullable on purpose: Source.enabled is itself nullable, and a NULL there means
        # "never set", which is a different fact from False. An undo restores the exact
        # value rather than a plausible one.
        sa.Column("prior_enabled", sa.Boolean(), nullable=True),
        sa.Column("prior_status", sa.String(length=20), nullable=True),
        sa.Column("undone_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_admission_event_time", "source_admission_events", ["occurred_at"])
    op.create_index(
        "idx_admission_event_source_time", "source_admission_events", ["source_id", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_admission_event_source_time", table_name="source_admission_events")
    op.drop_index("idx_admission_event_time", table_name="source_admission_events")
    op.drop_table("source_admission_events")
