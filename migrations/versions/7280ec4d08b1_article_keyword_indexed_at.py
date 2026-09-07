"""articles.keyword_indexed_at — the keyword pass's ATTEMPT record (PRH-01).

One additive NULLABLE column, on the detected_language / quarantined /
top_keyword_* pattern: no backfill, so an existing article reads NULL, which
means "keyword indexing has never been attempted here" and is exactly how a
pre-column article should be treated (worth trying).

WHY. ``backfill_corpus`` selected articles by "has no KeywordMention row" and
ordered them by id with no cursor. An article that legitimately produces zero
kept terms never leaves that set, so it was re-selected on every pass forever
and everything behind it in id order was never reached -- live-reproduced in
``scripts/analysis/repro_backfill_wedge.py`` (four passes, indexed=4 every
time, zero articles gaining a single mention). This column lets the queue
order by LEAST-RECENTLY-ATTEMPTED instead, so a structurally-unresolvable
article rotates out of the way after one try rather than blocking the queue --
the same repair the 2026-07-23 qualification livelock needed.

It records that the pass RAN, never what it found: an article with a stamp and
no mentions was judged and yielded nothing, which is a different fact from
"never examined" and must not be folded into it.

Revision ID: 7280ec4d08b1
Revises: a8cbf5556b39
Create Date: 2026-09-07

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "7280ec4d08b1"
down_revision: str | None = "a8cbf5556b39"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("keyword_indexed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("articles", "keyword_indexed_at")
