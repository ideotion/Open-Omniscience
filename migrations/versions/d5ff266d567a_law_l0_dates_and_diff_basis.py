"""The law L0 defects: the adapter's dates, and the diff's anchor (Q917, brief S04-10 S1).

Four additive, nullable columns, no backfill:

* ``law_documents.enacted_on``          -- when the legislature made it, exactly as the
  document states it. A DOCUMENT-level fact: it does not change between consolidations.
* ``law_revisions.valid_on``            -- the point in time THIS consolidated text
  represents. A VERSION-level fact, which is why it is not on the document.
* ``law_revisions.diff_basis``          -- "previous" | "baseline"; NULL means the row
  was recorded before the basis was tracked, which is NOT a synonym for "baseline".
* ``law_revisions.diff_base_revision_id`` -- the revision ``diff``/``delta_bytes`` are
  measured against, when the basis is "previous".

WHY THE BASIS COLUMNS EXIST AT ALL. Before Q917, ``diff`` and ``delta_bytes`` were both
anchored on the immutable baseline, so a document that grows a little at each amendment
reported a CUMULATIVE figure on a row that reads as one amendment. Fixing the anchor
changes what the numbers mean, and a store that predates the fix still holds rows
measured the old way -- so every row now says which anchor produced it, rather than a
history silently mixing two quantities.

NO BACKFILL, DELIBERATELY. An existing row's ``delta_bytes`` really was measured against
the baseline and re-deriving it would need the previous revision's ``full_text``, which
pre-2026-07 rows do not carry. A NULL ``diff_basis`` is the honest record of "nobody
wrote it down", and the derived-baseline view in ``src/law/track.py`` is what lets a
reader compare an old row and a new one on the same footing.

ON ``create_all`` HAVING ALREADY RUN: ``migrations/env.py`` sets ``render_as_batch=True``,
so on SQLite an ``op.add_column`` over a column the table already carries is a clean
no-op (MEASURED for this exact idiom, and recorded in the 2026-09-17 ledger entry that
corrected the opposite claim). The ``_has_column`` guard is kept for the same two-line
reasons the sibling ``3b7e91c4d28a`` states, and for the same reason it is not what makes
the restore path work.

Revision ID: d5ff266d567a
Revises: 3b7e91c4d28a
Create Date: 2026-09-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5ff266d567a"
down_revision: str | None = "3b7e91c4d28a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DOC_TABLE = "law_documents"
_REV_TABLE = "law_revisions"


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    try:
        return column in {c["name"] for c in insp.get_columns(table)}
    except Exception:  # noqa: BLE001 - a store without the table at all: nothing to add
        return True


def upgrade() -> None:
    if not _has_column(_DOC_TABLE, "enacted_on"):
        op.add_column(_DOC_TABLE, sa.Column("enacted_on", sa.String(length=32), nullable=True))
    if not _has_column(_REV_TABLE, "valid_on"):
        op.add_column(_REV_TABLE, sa.Column("valid_on", sa.String(length=32), nullable=True))
    if not _has_column(_REV_TABLE, "diff_basis"):
        op.add_column(_REV_TABLE, sa.Column("diff_basis", sa.String(length=16), nullable=True))
    if not _has_column(_REV_TABLE, "diff_base_revision_id"):
        op.add_column(_REV_TABLE, sa.Column("diff_base_revision_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    for column in ("diff_base_revision_id", "diff_basis", "valid_on"):
        if _has_column(_REV_TABLE, column):
            op.drop_column(_REV_TABLE, column)
    if _has_column(_DOC_TABLE, "enacted_on"):
        op.drop_column(_DOC_TABLE, "enacted_on")
