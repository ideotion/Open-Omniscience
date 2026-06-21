"""Covering index for time-windowed trending: keyword_mentions(observed_on, keyword_id, count).

Perf brief §3.E (the #1 hotspot: /api/insights/trending-windows, polled from Home —
~20s idle / ~98s under load on a 2.4M-mention corpus). ``trending()._counts`` runs
``SELECT keyword_id, SUM(count) WHERE observed_on IN [lo,hi) GROUP BY keyword_id``;
the existing keyword_id-leading covering index cannot serve an observed_on RANGE,
and the plain observed_on index forces a heap page read (a SQLCipher decrypt) per
in-range row. Leading with observed_on + carrying keyword_id, count makes it an
index-only ("USING COVERING INDEX") range scan — zero drift (it's an index, always
correct), query code unchanged. Self-healed identically at boot
(src.database.maintenance.ensure_hot_indexes / HOT_INDEXES). Idempotent.

Revision ID: b4c5d6e7f8a9
Revises: e4f5a6b7c8d9
Create Date: 2026-06-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: str | None = "e4f5a6b7c8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_mention_date_keyword"
_TABLE = "keyword_mentions"


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table: str, name: str) -> bool:
    if not _has_table(table):
        return False
    return any(i["name"] == name for i in sa.inspect(op.get_bind()).get_indexes(table))


def upgrade() -> None:
    if _has_table(_TABLE) and not _has_index(_TABLE, _INDEX):
        op.create_index(_INDEX, _TABLE, ["observed_on", "keyword_id", "count"])


def downgrade() -> None:
    if _has_index(_TABLE, _INDEX):
        op.drop_index(_INDEX, table_name=_TABLE)
