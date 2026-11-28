"""record the names of the criteria that failed on a qualification attempt (row 450, R850)

THE GAP. ``source_qualification_attempts`` kept the verdict and the criteria version, never the reason: the
2026-11 field analysis could tell which criterion disqualified a source only by elimination, and R850's one-time
re-check found that main keeps no verdict reasons at all. Every later check of that kind needs them.

WHAT IT HOLDS. The NAMES of the failing criteria, sorted and comma-separated, each one a name from
``src.analytics.source_audit.CRITERIA`` (``qualification.failing_criteria_names`` drops anything else). Never
article text, never a measured value. ``""`` means judged with nothing failing; NULL means not recorded.

NULLABLE, NO BACKFILL: an attempt from before this column kept no reasons, and none is guessed. Additive ADD
COLUMN, no row rewrite, no index, no re-processing. Mirrored into the boot self-heal
(``ensure_qualification_attempt_failing_column``), because ``create_all`` never ALTERs an existing table.

Guarded like ``b8d4f2a6c1e9_corpus_segment_generation``: the boot path's ``create_all`` or self-heal and the
restore path's chain may either reach the column first.

Revision ID: c4f1a9e27b53
Revises: b8d4f2a6c1e9
Create Date: 2026-11-28

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4f1a9e27b53"
down_revision: str | None = "b8d4f2a6c1e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE = "source_qualification_attempts"
_COLUMN = "failing_criteria"


def _has_table(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def _has_column(table: str, column: str) -> bool:
    return column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # A store without the table at all: nothing to add (the table, when created, carries the column).
    if _has_table(_TABLE) and not _has_column(_TABLE, _COLUMN):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=400), nullable=True))


def downgrade() -> None:
    if _has_table(_TABLE) and _has_column(_TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
