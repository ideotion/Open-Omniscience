"""spell_deletes -- the "did you mean" deletion table (S05-01 S6, Q605 = b).

One WITHOUT ROWID table keyed on (term_delete, keyword_id), filled whole by the
did-you-mean build job from the keyword vocabulary. Empty until the first build, which
is exactly what it means: no suggestions have been computed yet, and the surface says so.

GUARDED like the head migration: the boot path's ``create_all`` may have built it first.

Revision ID: b3d7f1a9c5e2
Revises: a9e5c1d7b3f2
Create Date: 2026-09-28

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "b3d7f1a9c5e2"
down_revision: str | None = "a9e5c1d7b3f2"
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = "spell_deletes"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "keywords" not in tables or _TABLE in tables:
        return
    op.create_table(
        _TABLE,
        sa.Column("term_delete", sa.String(length=64), primary_key=True),
        sa.Column("keyword_id", sa.Integer(), primary_key=True),
        sqlite_with_rowid=False,
    )


def downgrade() -> None:
    if _TABLE in _tables():
        op.drop_table(_TABLE)
