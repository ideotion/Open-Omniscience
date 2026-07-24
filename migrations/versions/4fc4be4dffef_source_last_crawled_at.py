"""Crawl-supplement rotation marker (§8 crawl-by-default ruling, 2026-07-24
throughput brief, C3).

Adds ``sources.last_crawled_at`` -- when the bounded crawl sub-pass last
visited this source (NEVER the explicit whole-source ``mode="crawl"`` run,
which is orthogonal). Additive, nullable, no backfill: an existing source
simply reads as "never crawled by the supplement" and sorts FIRST in the
least-recently-crawled rotation (ordering, never exclusion). The live store
is never auto-migrated by alembic (the boot self-heal
``ensure_source_last_crawled_column`` is the real upgrade path for it); this
migration keeps alembic-managed / staged-upgrade stores consistent.

Revision ID: 4fc4be4dffef
Revises: cdf441950256
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4fc4be4dffef"
down_revision: str | None = "cdf441950256"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCE_TABLE = "sources"
_COLUMN = "last_crawled_at"
_INDEX = "idx_source_last_crawled"


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return column in {c["name"] for c in insp.get_columns(table)}


def _has_index(table: str, name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return name in {ix["name"] for ix in insp.get_indexes(table)}


def upgrade() -> None:
    if not _has_column(_SOURCE_TABLE, _COLUMN):
        op.add_column(_SOURCE_TABLE, sa.Column(_COLUMN, sa.DateTime(), nullable=True))
    if not _has_index(_SOURCE_TABLE, _INDEX):
        op.create_index(_INDEX, _SOURCE_TABLE, [_COLUMN])


def downgrade() -> None:
    if _has_index(_SOURCE_TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_SOURCE_TABLE)
    if _has_column(_SOURCE_TABLE, _COLUMN):
        op.drop_column(_SOURCE_TABLE, _COLUMN)
