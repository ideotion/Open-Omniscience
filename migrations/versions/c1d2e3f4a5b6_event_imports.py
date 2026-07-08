"""event_imports table (DB-reliability D1: move imported calendar events into the DB).

Creates ``event_imports`` — the durable, encrypted home for imported calendar events that
used to live in the loose cleartext ``calendar_feed_imports.json`` side-file. A brand-new
TABLE needs no boot self-heal (``create_all`` materialises it on fresh + existing stores,
and the event_store lazy layer self-creates it too), but the migration is provided for the
alembic-managed staged-upgrade / cross-version restore path (an older backup is brought to
head before the merge runs). The merge deliberately IGNORES this table for now (Wave 4 J
conservative slice: the JSON side-file stays the read source of truth + merge target, and
this table is a dual-write mirror — see src/database/models.py::EventImport).

Revision ID: c1d2e3f4a5b6
Revises: b3d4e5f6a7c8
Create Date: 2026-07-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | None = "b3d4e5f6a7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "event_imports"
_INDEX = "ix_event_imports_family_fp"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _TABLE in insp.get_table_names():
        return  # create_all / event_store self-heal already built it -- idempotent
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("family_key", sa.String(length=191), nullable=False),
        sa.Column("fingerprint", sa.String(length=255), nullable=False),
        sa.Column("family_name", sa.String(length=300), nullable=True),
        sa.Column("family_user", sa.Boolean(), nullable=True),
        sa.Column("imported_at", sa.String(length=40), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("date", sa.String(length=20), nullable=True),
        sa.Column("sources", sa.Text(), nullable=True),
        sa.Column("uids", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(_INDEX, _TABLE, ["family_key", "fingerprint"], unique=True)


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
