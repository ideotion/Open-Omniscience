"""law_format_changes -- a tracked law document's move from one published format to another (R753).

One row per (document, from_url, to_url): when a German federal act moved from the portal's HTML page
to its own XML, both addresses, both text hashes, and the HTML reading the move replaced (kept so the
move can be audited and undone). Never an amendment. A restore carries it
(``src.backup.merge._merge_law_format_changes``). Additive and empty until a document moves; it scales
with tracked law documents, never with articles.

GUARDED like the other table steps: the boot path's ``create_all`` may have built it first.

Revision ID: d7e3a9b2c5f1
Revises: c2a6e8f1d4b7
Create Date: 2026-11-19

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7e3a9b2c5f1"
down_revision: str | None = "c2a6e8f1d4b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "law_format_changes"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if _TABLE in _tables():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("changed_at", sa.DateTime(), nullable=True),
        sa.Column("from_url", sa.String(length=1000), nullable=False),
        sa.Column("to_url", sa.String(length=1000), nullable=False),
        sa.Column("from_format", sa.String(length=40), nullable=False),
        sa.Column("to_format", sa.String(length=40), nullable=False),
        sa.Column("from_hash", sa.String(length=64), nullable=False),
        sa.Column("to_hash", sa.String(length=64), nullable=False),
        sa.Column("from_baseline_hash", sa.String(length=64), nullable=True),
        sa.Column("from_baseline_text", sa.LargeBinary(), nullable=True),
        sa.Column("from_latest_text", sa.LargeBinary(), nullable=True),
        sa.Column("from_latest_text_revid", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["law_documents.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_law_format_changes_document_id", _TABLE, ["document_id"])
    op.create_index("ix_lawfmt_doc_from_to", _TABLE, ["document_id", "from_url", "to_url"], unique=True)


def downgrade() -> None:
    if _TABLE in _tables():
        op.drop_index("ix_lawfmt_doc_from_to", table_name=_TABLE)
        op.drop_index("ix_law_format_changes_document_id", table_name=_TABLE)
        op.drop_table(_TABLE)
