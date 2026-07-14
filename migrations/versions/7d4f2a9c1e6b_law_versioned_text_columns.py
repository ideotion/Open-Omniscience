"""Law versioned-text columns: materialised latest + per-revision full text.

The versioned-sources ruling ("a law is an Article + a linked revision/audit trail") needs
the CURRENT law text shown without replaying diffs, and ANY past version reconstructable —
not just a lossy capped diff. Mirrors the wiki columns: LawDocument gains ``latest_text``
(+ ``latest_text_revid``) and LawRevision gains ``full_text`` (all ``CompressedText``,
nullable). Additive, no backfill (populates forward as the tracker stores full text).
(create_all + the boot self-heal ``ensure_law_text_columns`` already add these on existing
databases; this migration keeps alembic-managed stores consistent.)

Revision ID: 7d4f2a9c1e6b
Revises: 9c3e7a2f1b4d
Create Date: 2026-07-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "7d4f2a9c1e6b"
down_revision = "9c3e7a2f1b4d"
branch_labels = None
depends_on = None

_ADD = (
    ("law_documents", "latest_text", sa.LargeBinary()),  # CompressedText.impl is LargeBinary
    ("law_documents", "latest_text_revid", sa.Integer()),
    ("law_revisions", "full_text", sa.LargeBinary()),
)


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    for table, col, typ in _ADD:
        if not _has_column(table, col):
            op.add_column(table, sa.Column(col, typ, nullable=True))


def downgrade() -> None:
    for table, col, _typ in reversed(_ADD):
        if _has_column(table, col):
            op.drop_column(table, col)
