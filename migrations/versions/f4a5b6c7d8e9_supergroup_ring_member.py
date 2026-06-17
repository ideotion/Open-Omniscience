"""keyword_supergroup_members.ring_id: a super-group member can be a RING (super-rings)

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-06-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4a5b6c7d8e9"
down_revision: str | None = "e3f4a5b6c7d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("keyword_supergroup_members", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ring_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("keyword_supergroup_members", schema=None) as batch_op:
        batch_op.drop_column("ring_id")
