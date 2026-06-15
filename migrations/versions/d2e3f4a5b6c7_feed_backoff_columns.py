"""Per-feed de-churn backoff columns on feed_fetch_state.

Field log 2026-06-13 finding F: some servers IGNORE conditional-GET headers and
return a full ``200`` every pass even when nothing changed (~93% duplicate rate
at 1-minute intervals). Two columns on ``feed_fetch_state`` record a CAPPED,
TEMPORARY, SELF-RESETTING backoff so the collect loop stops hammering an
unchanged feed every minute:

  * ``consecutive_unchanged`` -- count of consecutive 200 fetches that yielded
    ZERO new articles.
  * ``skip_until`` -- the UTC deadline before which the feed is skipped this
    pass. Always bounded (~6 h cap), so the feed is never starved; ANY new
    article, a 304, or a fetch error clears both.

This is a de-churn, NEVER an exclusion (maintainer: "no source starved, no
selection made"). (create_all + the boot self-heal ``ensure_feed_backoff_columns``
already add these on existing databases; this migration keeps alembic-managed
stores consistent.)

Revision ID: d2e3f4a5b6c7
Revises: c8d9e0f1a2b3
Create Date: 2026-06-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d2e3f4a5b6c7"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    # Idempotent: the boot self-heal may have already added these.
    if not _has_column("feed_fetch_state", "consecutive_unchanged"):
        op.add_column(
            "feed_fetch_state",
            sa.Column("consecutive_unchanged", sa.Integer(), nullable=True),
        )
    if not _has_column("feed_fetch_state", "skip_until"):
        op.add_column(
            "feed_fetch_state",
            sa.Column("skip_until", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("feed_fetch_state", "skip_until")
    op.drop_column("feed_fetch_state", "consecutive_unchanged")
