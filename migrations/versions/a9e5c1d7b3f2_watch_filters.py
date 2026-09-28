"""watches.filters -- a saved search's full filter set (S05-01 S5, Q606 = a).

A watch stored only its query text; the advanced search's filters (languages, sources,
countries, the collected range, word counts, sentiment, mentioned dates, include
quarantined, exact, NEAR) had nowhere to live, so a search saved as a watch would have
re-run WIDER than the view it was saved from. One nullable TEXT column holding the
stored form of ``src.api.search_filters.AdvancedSearch`` (JSON, non-default fields
only). NULL -- every watch made before this column -- is "no advanced filter", which is
exactly what those watches always meant.

GUARDED like the head migration: the boot path's ``create_all`` may have built the
table (with the column) before this chain runs against it.

Revision ID: a9e5c1d7b3f2
Revises: c7015865aba2
Create Date: 2026-09-28

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "a9e5c1d7b3f2"
down_revision: str | None = "c7015865aba2"
branch_labels: str | None = None
depends_on: str | None = None


def _columns() -> set[str] | None:
    insp = sa.inspect(op.get_bind())
    if "watches" not in insp.get_table_names():
        return None
    return {c["name"] for c in insp.get_columns("watches")}


def upgrade() -> None:
    cols = _columns()
    if cols is None or "filters" in cols:
        return
    with op.batch_alter_table("watches") as batch:
        batch.add_column(sa.Column("filters", sa.Text(), nullable=True))


def downgrade() -> None:
    cols = _columns()
    if cols is None or "filters" not in cols:
        return
    with op.batch_alter_table("watches") as batch:
        batch.drop_column("filters")
