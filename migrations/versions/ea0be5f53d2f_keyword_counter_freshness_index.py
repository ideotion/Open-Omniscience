"""The counter-freshness index: make `counter_envelope` covering (finding F7).

WHAT THIS COSTS AND WHAT IT BUYS. `counter_envelope` runs on the Insights top path and
asks `min(keywords.last_reconciled_at) WHERE mention_count > 0`. `idx_keyword_mention_count`
covered only the predicate, so SQLite found the matching index entries and then read
**1.1 M rows** to fetch the timestamp -- measured at **50,781 ms across three calls** on the
1.34 M-article field instance (audit `docs/audit/15`, Appendix B). Putting the timestamp IN
the index makes the same query COVERING: no row lookups at all.

THE OLD INDEX IS DROPPED, and that was MEASURED rather than assumed. `EXPLAIN QUERY PLAN`
shows the composite serving every query the single-column index served -- including the hot
`ORDER BY mention_count DESC LIMIT`, since `mention_count` leads it -- as a COVERING INDEX.
Keeping both would buy nothing and charge write amplification on an 11 M-row table, on the
write-bound instance this audit is about.

BUILDING IT IS ITSELF CORPUS-SIZED, once, and that is stated rather than hidden: on a
1.34 M-article store the keywords table is ~11 M rows and the index build walks all of them.
It happens at migration time, not on a hot path, and it replaces a cost that was being paid
on every Insights load.

Revision ID: ea0be5f53d2f
Revises: 7c3ea19b4d02
Create Date: 2026-09-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "ea0be5f53d2f"
down_revision = "7c3ea19b4d02"
branch_labels = None
depends_on = None

_TABLE = "keywords"
_NEW = "idx_keyword_counter_freshness"
_OLD = "idx_keyword_mention_count"


def _has_table(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def _indexes(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes(table)}


def _columns(table: str) -> set[str]:
    if not _has_table(table):
        return set()
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # GUARDED BOTH WAYS: the ordinary boot path calls `create_all` (and the counter
    # self-heal) BEFORE any stamp moves, while the RESTORE path runs alembic straight at a
    # staged copy and never calls it -- the recorded 2026-09-16 lesson. Either may have
    # already done this.
    if not _has_table(_TABLE):
        return
    cols = _columns(_TABLE)
    if not {"mention_count", "last_reconciled_at"} <= cols:
        # An older store that has not yet gained the counter columns; the boot self-heal
        # adds them and creates this index itself. Nothing to do, and nothing to claim.
        return
    have = _indexes(_TABLE)
    if _NEW not in have:
        op.create_index(_NEW, _TABLE, ["mention_count", "last_reconciled_at"])
    if _OLD in have:
        op.drop_index(_OLD, table_name=_TABLE)


def downgrade() -> None:
    have = _indexes(_TABLE)
    if _OLD not in have and "mention_count" in _columns(_TABLE):
        op.create_index(_OLD, _TABLE, ["mention_count"])
    if _NEW in have:
        op.drop_index(_NEW, table_name=_TABLE)
