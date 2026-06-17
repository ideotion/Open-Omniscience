"""article_analyses.prompt_text: store the exact system prompt used (provenance)

Prompts are operator-editable (Settings -> Models), so the prompt_version alone no
longer pins what produced a summary/translation once a prompt is customised. We
record the verbatim system prompt used at generation time so provenance stays
honest. Nullable: rows written before this column keep NULL.

Revision ID: a1b2c3d4e5f6
Revises: f4a5b6c7d8e9
Create Date: 2026-06-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("article_analyses", schema=None) as batch_op:
        batch_op.add_column(sa.Column("prompt_text", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("article_analyses", schema=None) as batch_op:
        batch_op.drop_column("prompt_text")
