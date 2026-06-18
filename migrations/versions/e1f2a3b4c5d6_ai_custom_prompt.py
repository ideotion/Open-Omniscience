"""User-defined AI extractor prompts (ai_custom_prompt) in the MAIN database.

Maintainer ask 2026-06-18: a managed list of user-defined prompts, each an extension of
the built-in who/where/when extractors — it declares an ``output_kind`` (the metadata
type) and its results are stored as ``AiKeyword`` rows of that kind (the unified,
prompt-related AI-metadata store). Definitions are config (no AI output here); they run
on demand and/or — per ``run_on_ingest`` — automatically.

``create_all`` makes this on fresh stores; a whole NEW table, so boot ``create_all``
adds it to existing stores too.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if _has_table("ai_custom_prompt"):
        return
    op.create_table(
        "ai_custom_prompt",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("output_kind", sa.String(length=40), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("run_on_ingest", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ai_custom_prompt")
