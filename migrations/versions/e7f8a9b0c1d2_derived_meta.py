"""Canonical derived_meta key->value store (corpus-epoch guard, scaling 5A-bis / D3).

The disposable columnar rollup double-counts if it merges INCREMENTALLY across a
delete-then-reinsert (re-index) or a delete (prune): index_article deletes then
re-inserts an article's mentions, so an id-watermark tail keeps the OLD contribution
AND re-adds the reinserted higher-id rows. The fix is a CORPUS EPOCH -- a monotonic
counter bumped by exactly the non-append mutators (re-index / prune / restore-merge);
a changed epoch forces the rollup to FULL-rebuild rather than incrementally merge.

This migration materialises the canonical store of that epoch. A brand-new TABLE needs
no boot self-heal -- create_all materialises a missing table in full on both fresh and
existing stores (see src.database.session.init_db) -- but the migration is provided for
the alembic-managed staged-upgrade / cross-version restore path.

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-07-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: str | None = "d6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "derived_meta"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _TABLE in insp.get_table_names():
        return  # create_all already built it (fresh store) -- idempotent
    op.create_table(
        _TABLE,
        sa.Column("key", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table(_TABLE)
