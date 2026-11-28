"""keep what the last passes did with each feed (row 465, the field report's Q3 and Q11)

THE GAP. ``feed_fetch_state`` kept the feed's last HTTP status and nothing about its entries, so a feed that answers 200
every pass and has never stored an article could not say why (every entry a duplicate, a non-article, a refused fetch, a
failed extraction).

WHAT IT HOLDS. ``recent_outcomes``: a compact JSON text of counts for the feed's last 8 checked passes, written and read
only by ``src.ingest.outcome_history``. Counts only, never an address or any text. This instance's own observation:
a restore never adopts another instance's value (``src/backup/fetch_history.py``).

NULLABLE, NO BACKFILL: a feed has no recorded pass until its next one. Additive ADD COLUMN, no row rewrite, no index, no
re-processing. Mirrored into the boot self-heal (``ensure_feed_backoff_columns``, which heals every added feed_fetch_state column), because ``create_all`` never
ALTERs an existing table. Guarded like ``c4f1a9e27b53``: the boot path and the restore path's chain may either reach the
column first.

Revision ID: d7e3b1a9c4f2
Revises: c2f6a8e4d1b7
Create Date: 2026-11-28

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7e3b1a9c4f2"
down_revision: str | None = "c2f6a8e4d1b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE = "feed_fetch_state"
_COLUMN = "recent_outcomes"


def _has_table(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def _has_column(table: str, column: str) -> bool:
    return column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # A store without the table at all: nothing to add (the table, when created, carries the column).
    if _has_table(_TABLE) and not _has_column(_TABLE, _COLUMN):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Text(), nullable=True))


def downgrade() -> None:
    if _has_table(_TABLE) and _has_column(_TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
