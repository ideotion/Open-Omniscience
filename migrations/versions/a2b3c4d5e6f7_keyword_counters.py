"""Denormalised keyword counters: keywords.mention_count + article_count.

Perf workstream 2026-06-18 (the structural cold-cost win): the hot whole-corpus
keyword aggregations (top_terms, super-groups) GROUP BY'd every keyword joined to the
800k+-row keyword_mentions table, dragging article pages through the SQLCipher codec.
Maintaining a per-keyword ``mention_count`` (SUM of occurrence counts) and
``article_count`` (DISTINCT articles) AT INDEX TIME lets those reads become an
index-only counter scan instead of a mention join.

Honest COUNTS, never a score. NOT NULL DEFAULT 0 so existing rows get a value the
instant the column exists; the column is then POPULATED from the live mentions in this
migration (and self-healed identically at boot for stores that don't run alembic — see
``src.database.maintenance.ensure_keyword_counter_columns``). Idempotent.

Revision ID: a2b3c4d5e6f7
Revises: e1f2a3b4c5d6
Create Date: 2026-06-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _indexes(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {i["name"] for i in insp.get_indexes(table)}


def upgrade() -> None:
    cols = _columns("keywords")
    if not cols:
        return  # no keywords table yet (a brand-new store; create_all builds it)
    added = False
    with op.batch_alter_table("keywords", schema=None) as batch_op:
        if "mention_count" not in cols:
            batch_op.add_column(
                sa.Column(
                    "mention_count", sa.Integer(), nullable=False, server_default="0"
                )
            )
            added = True
        if "article_count" not in cols:
            batch_op.add_column(
                sa.Column(
                    "article_count", sa.Integer(), nullable=False, server_default="0"
                )
            )
            added = True
    if "idx_keyword_mention_count" not in _indexes("keywords"):
        op.create_index("idx_keyword_mention_count", "keywords", ["mention_count"])
    if added:
        # Populate from the live mentions (portable correlated subqueries; runs only
        # when a column was just added). Mirrors backfill_keyword_counters.
        op.execute(
            "UPDATE keywords SET "
            "mention_count = COALESCE("
            "(SELECT SUM(count) FROM keyword_mentions WHERE keyword_id = keywords.id), 0), "
            "article_count = COALESCE("
            "(SELECT COUNT(DISTINCT article_id) FROM keyword_mentions WHERE keyword_id = keywords.id), 0)"
        )


def downgrade() -> None:
    if "idx_keyword_mention_count" in _indexes("keywords"):
        op.drop_index("idx_keyword_mention_count", table_name="keywords")
    with op.batch_alter_table("keywords", schema=None) as batch_op:
        cols = _columns("keywords")
        if "article_count" in cols:
            batch_op.drop_column("article_count")
        if "mention_count" in cols:
            batch_op.drop_column("mention_count")
