"""app_state key->value store (DB-reliability D1: orphan settings/UI state into the DB).

Creates the ``app_state`` table that replaces the loose ``*.json`` settings side-files
(app / scheduler / custody / safety) and the browser-only agenda subscription prefs.
A brand-new TABLE needs no boot self-heal — ``create_all`` materialises a missing table
on both fresh and existing stores (src.database.session.init_db), and the kv layer
(src.config.kv_store) self-creates it too — but the migration is provided for the
alembic-managed staged-upgrade / cross-version restore path (an older backup is brought
to head before the merge runs, so ``app_state`` exists there too — though the merge
deliberately ignores it: settings are per-machine, local wins).

Revision ID: b3d4e5f6a7c8
Revises: e7f8a9b0c1d2
Create Date: 2026-07-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3d4e5f6a7c8"
down_revision: str | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "app_state"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _TABLE in insp.get_table_names():
        return  # create_all / kv self-heal already built it -- idempotent
    op.create_table(
        _TABLE,
        sa.Column("key", sa.String(length=191), primary_key=True, nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table(_TABLE)
