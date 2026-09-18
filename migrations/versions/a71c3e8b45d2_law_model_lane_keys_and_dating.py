"""The law metadata model's corpus-side seam: the lane keys and Q905's dating label.

Three additive, nullable columns, no backfill:

* ``law_documents.lane_key``       -- the stable link to ``law.db``'s
  ``law_document_meta`` (identity group, translation provenance, licence).
* ``law_revisions.lane_key``       -- the stable link to ``law.db``'s
  ``law_provisions``.
* ``law_revisions.valid_on_dating`` -- ``"official"`` | ``"observed"``; NULL means the
  row was recorded before the label existed, which is NOT a synonym for either.

WHY THE LINKS ARE STRINGS. ``src/backup/merge.py`` renumbers ``law_documents`` and
``law_revisions`` on an incoming merge -- ``temp.map_law_doc`` and ``temp.map_law_rev``
exist for exactly that. A row id carried into another database file would survive the
merge pointing at whatever row inherited its number, so a restored corpus could show
one law's licence and translation provenance under another law's title. A minted key
survives renumbering untouched; the worst a merge can do is leave a document with NO
metadata, which every reader reports as absent.

WHY ``valid_on_dating`` IS NOT IN ``law.db`` WITH THE REST OF THE MODEL. It qualifies
``valid_on``, which is here. A reader able to fetch the date without its label is a
reader that will print an observation date as a consolidation date, which is the
fabrication Q905's second clause exists to prevent.

NO BACKFILL, DELIBERATELY. An existing document has no minted key and no recorded
dating, and inventing either would be inventing a fact: the key is minted the next time
the tracker runs, and a NULL dating is the honest record of a row written before anyone
wrote the label down.

Revision ID: a71c3e8b45d2
Revises: d5ff266d567a
Create Date: 2026-09-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a71c3e8b45d2"
down_revision: str | None = "d5ff266d567a"
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
    if not _has_column(_DOC_TABLE, "lane_key"):
        op.add_column(_DOC_TABLE, sa.Column("lane_key", sa.String(length=36), nullable=True))
    if not _has_column(_REV_TABLE, "lane_key"):
        op.add_column(_REV_TABLE, sa.Column("lane_key", sa.String(length=36), nullable=True))
    if not _has_column(_REV_TABLE, "valid_on_dating"):
        op.add_column(
            _REV_TABLE, sa.Column("valid_on_dating", sa.String(length=16), nullable=True)
        )


def downgrade() -> None:
    for column in ("valid_on_dating", "lane_key"):
        if _has_column(_REV_TABLE, column):
            op.drop_column(_REV_TABLE, column)
    if _has_column(_DOC_TABLE, "lane_key"):
        op.drop_column(_DOC_TABLE, "lane_key")
