"""market extraction rules

Revision ID: b7c1d2e3f4a5
Revises: 6ae5766d3136
Create Date: 2026-06-06 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c1d2e3f4a5"
down_revision: str | None = "6ae5766d3136"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_extraction_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("url", sa.String(length=1000), nullable=False),
        sa.Column("selector", sa.String(length=500), nullable=False),
        sa.Column("attribute", sa.String(length=100), nullable=True),
        sa.Column("value_regex", sa.String(length=300), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("market", sa.String(length=100), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("market_extraction_rules", schema=None) as batch_op:
        batch_op.create_index("ix_market_extraction_rules_source_id", ["source_id"], unique=False)
        batch_op.create_index("ix_market_extraction_rules_symbol", ["symbol"], unique=False)
        batch_op.create_index("ix_market_rule_source", ["source_id"], unique=False)
        batch_op.create_index("ix_market_rule_category", ["category"], unique=False)
        batch_op.create_index("ix_market_rule_symbol", ["symbol"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("market_extraction_rules", schema=None) as batch_op:
        batch_op.drop_index("ix_market_rule_symbol")
        batch_op.drop_index("ix_market_rule_category")
        batch_op.drop_index("ix_market_rule_source")
        batch_op.drop_index("ix_market_extraction_rules_symbol")
        batch_op.drop_index("ix_market_extraction_rules_source_id")
    op.drop_table("market_extraction_rules")
