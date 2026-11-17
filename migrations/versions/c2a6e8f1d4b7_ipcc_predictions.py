"""ipcc_predictions -- the sentences of an IPCC SPM an operator kept as predictions or set aside (row 121, G4).

One small table keyed by the SPM catalog key and the sentence's hash; it holds a person's decision, so a restore carries
it (``src.backup.merge._merge_ipcc_predictions``). Additive and empty until a person decides on a suggestion; it scales
with the sentences someone read, never with articles.

GUARDED like the other table steps: the boot path's ``create_all`` may have built it first.

Revision ID: c2a6e8f1d4b7
Revises: f61a2b3c4d5e
Create Date: 2026-11-17

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2a6e8f1d4b7"
down_revision: str | None = "f61a2b3c4d5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "ipcc_predictions"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if _TABLE in _tables():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("spm_key", sa.String(length=16), nullable=False),
        sa.Column("sentence_hash", sa.String(length=64), nullable=False),
        sa.Column("sentence", sa.Text(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("method_version", sa.Integer(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("spm_key", "sentence_hash", name="uq_ipcc_prediction_sentence"),
    )


def downgrade() -> None:
    if _TABLE in _tables():
        op.drop_table(_TABLE)
