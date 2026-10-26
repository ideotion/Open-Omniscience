"""host_mismatch_confirmed -- the (source, article site) pairs an operator confirmed (R193, R195).

One small table keyed by an integer source id and the article's registrable site; it holds a person's decision, so a
restore carries it (``src.backup.merge._merge_host_confirmations``). Additive and empty until a person confirms a pair; it
scales with the pairs someone read, never with articles.

GUARDED like the other table steps: the boot path's ``create_all`` may have built it first, and a store with no ``sources``
table has nothing to reference.

Revision ID: a1c4e7b9d2f6
Revises: e6b2d8f0a4c3
Create Date: 2026-10-26

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c4e7b9d2f6"
down_revision: str | None = "e6b2d8f0a4c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "host_mismatch_confirmed"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "sources" not in tables or _TABLE in tables:
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("article_site", sa.String(length=255), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=False),
        sa.Column("note", sa.Text()),
        sa.UniqueConstraint("source_id", "article_site", name="uq_host_confirmed_pair"),
    )


def downgrade() -> None:
    if _TABLE in _tables():
        op.drop_table(_TABLE)
