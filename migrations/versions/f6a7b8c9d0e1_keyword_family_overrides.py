"""keyword family overrides (manual merge/split)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-09 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "keyword_family_overrides",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("normalized_term", sa.String(length=255), nullable=False),
        sa.Column("family_key", sa.String(length=255), nullable=False),
        sa.Column("canonical_label", sa.String(length=255), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("keyword_family_overrides", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_keyword_family_overrides_normalized_term"),
            ["normalized_term"], unique=True)
        batch_op.create_index("ix_kwfam_family_key", ["family_key"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("keyword_family_overrides", schema=None) as batch_op:
        batch_op.drop_index("ix_kwfam_family_key")
        batch_op.drop_index(batch_op.f("ix_keyword_family_overrides_normalized_term"))
    op.drop_table("keyword_family_overrides")
