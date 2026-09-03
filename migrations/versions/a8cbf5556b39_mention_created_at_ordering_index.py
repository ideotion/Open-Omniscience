"""An ordering index for the columnar rollup's full build.

S3.5 of the 2026-09-02 crash analysis. The rollup's full build streams every
mention in (created_at, id) order. That sort key is deliberate and is NOT the
rowid: ``KeywordMention.id`` carries no AUTOINCREMENT, so a DELETEd rowid can be
reused, and combined with index_article's delete-then-bulk-insert re-index idiom
a rowid keyset was live-reproduced double-counting and silently dropping rows
(build_keyword_daily's PR-D / W2 correction records both directions). The
single-writer gate makes ``created_at`` monotonic, so it is the reuse-immune key.

Nothing indexed that order, so each 50k batch was a bare ``SCAN
keyword_mentions`` plus a ``USE TEMP B-TREE FOR ORDER BY`` -- EXPLAIN-confirmed
-- which is why a full rebuild cost 109-194 s a batch over 187 batches on the
field corpus.

The index alone is not the fix and was measured not to be: the old predicate
wrapped the column in ``COALESCE(created_at, '1970-01-01 00:00:00')``, and an
expression over an indexed column is not indexable, so the plan did not move.
The build now streams the NULL-created_at rows as their own phase and leaves the
predicate as a plain range, which this index serves as a SEARCH with no sort.

A plain two-column index on purpose, never an expression index: alembic's
autogenerate cannot compare those, which would leave a permanent spurious
"changed index" and an ``alembic_stamp_align`` schema-behind verdict.

Index-only and additive: no column added, no data written, no existing query's
results changed. if_not_exists on both directions because the boot self-heal
(src/database/maintenance.py HOT_INDEXES) creates the same index on installs
that never run `make migrate`, so either half may already have run.

Revision ID: a8cbf5556b39
Revises: 6933c8d7c7b0
Create Date: 2026-09-03
"""

from __future__ import annotations

from alembic import op

revision = "a8cbf5556b39"
down_revision = "6933c8d7c7b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_mention_created_id",
        "keyword_mentions",
        ["created_at", "id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_mention_created_id", table_name="keyword_mentions", if_exists=True)
