"""Article quarantine: quarantined + quarantine_reason + quarantine_criteria_version
+ quarantined_at, plus their index.

S3.2 (2026-07-23 field-feedback workflow — the NAV-SOUP SPECIMEN ruling's row-5
execution scope, maintainer sign-off A2/A3). A REVERSIBLE stamp, never a delete:
quarantined rows, their keywords, and their provenance stay fully intact. Additive +
nullable, NO backfill: an existing article simply has quarantined=NULL ("never
judged"), treated identically to False by every reader
(``Article.quarantined.isnot(True)``). Self-healed identically at boot
(``src.database.maintenance.ensure_article_quarantine_columns`` /
``ensure_hot_indexes``). Idempotent; ``if_not_exists``/column-presence checks on both
directions since a store may boot-self-heal before it migrates.

Revision ID: 95120f685050
Revises: f670ae07b75e
Create Date: 2026-07-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "95120f685050"
down_revision: str | None = "f670ae07b75e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    cols = _columns("articles")
    if not cols:
        return  # no articles table yet (a brand-new store; create_all builds it)
    with op.batch_alter_table("articles", schema=None) as batch_op:
        if "quarantined" not in cols:
            batch_op.add_column(sa.Column("quarantined", sa.Boolean(), nullable=True))
        if "quarantine_reason" not in cols:
            batch_op.add_column(sa.Column("quarantine_reason", sa.String(length=255), nullable=True))
        if "quarantine_criteria_version" not in cols:
            batch_op.add_column(
                sa.Column("quarantine_criteria_version", sa.String(length=40), nullable=True)
            )
        if "quarantined_at" not in cols:
            batch_op.add_column(sa.Column("quarantined_at", sa.DateTime(), nullable=True))
    op.create_index("idx_article_quarantined", "articles", ["quarantined"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("idx_article_quarantined", table_name="articles", if_exists=True)
    cols = _columns("articles")
    with op.batch_alter_table("articles", schema=None) as batch_op:
        if "quarantined_at" in cols:
            batch_op.drop_column("quarantined_at")
        if "quarantine_criteria_version" in cols:
            batch_op.drop_column("quarantine_criteria_version")
        if "quarantine_reason" in cols:
            batch_op.drop_column("quarantine_reason")
        if "quarantined" in cols:
            batch_op.drop_column("quarantined")
