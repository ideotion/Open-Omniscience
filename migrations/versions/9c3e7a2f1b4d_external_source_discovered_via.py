"""External-source discovery provenance column (Q4a: wire the dormant external_sources).

The discovery funnel's RESOLUTION table: a cited/discovered domain now resolves to an
``external_sources`` row carrying WHICH offline channel first found it
(``discovered_via`` -- "citation" | "wikipedia" | "catalog"). Additive, nullable, no
backfill (populates forward as discovery resolves domains); descriptive, never a score.
(create_all + the boot self-heal ``ensure_external_source_discovery_columns`` already add
this on existing databases; this migration keeps alembic-managed stores consistent.)

Revision ID: 9c3e7a2f1b4d
Revises: 5ea842778603
Create Date: 2026-07-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "9c3e7a2f1b4d"
down_revision = "5ea842778603"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    # Idempotent: the boot self-heal may have already added it.
    if not _has_column("external_sources", "discovered_via"):
        op.add_column("external_sources", sa.Column("discovered_via", sa.String(length=60), nullable=True))


def downgrade() -> None:
    if _has_column("external_sources", "discovered_via"):
        op.drop_column("external_sources", "discovered_via")
