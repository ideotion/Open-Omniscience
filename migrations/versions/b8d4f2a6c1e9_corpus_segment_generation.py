"""corpus_segments.generation -- the registry's half of a segment's generation number (R826 stage 3a, row 409).

A segment file records its own generation (``segment_meta.generation``), raised in the FILE first each time the app opens
it for writing and then here, so a copy of the file older than the registry (an old backup put back in its place) is
refused as an older copy. A crash between the two writes leaves the file NEWER than the registry: that is recovered (the
registry is raised to the file's number) and never refused.

Additive, nullable, NO BACKFILL, no row written: NULL means "no generation recorded yet" and is never compared. No segment
file exists in the field yet (segment writing stays behind an unreachable switch), so every registry is empty or holds
only legacy segment 0, and nothing is re-extracted or rebuilt (R755 F2; the import hold).

Guarded like ``3b7e91c4d28a_keyword_mention_language``: the boot path's ``create_all`` and the restore path's chain may
either reach the column first.

Revision ID: b8d4f2a6c1e9
Revises: e4c1a7f3b9d2
Create Date: 2026-11-25

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8d4f2a6c1e9"
down_revision: str | None = "e4c1a7f3b9d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "corpus_segments"
_COLUMN = "generation"


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    try:
        return column in {c["name"] for c in insp.get_columns(table)}
    except Exception:  # noqa: BLE001 - a store without the table at all: nothing to add
        return True


def upgrade() -> None:
    if not _has_column(_TABLE, _COLUMN):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Integer(), nullable=True))


def downgrade() -> None:
    if _has_column(_TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
