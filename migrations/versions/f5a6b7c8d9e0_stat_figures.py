"""Official-statistics figures table (Group N — figure-level provenance + vintages).

Group N (official-statistics ingestion). Stores one durable row per observed value
fetched from a documented official machine endpoint (World Bank API / SDMX-JSON,
parsed by ``src.stats.sdmx``), with its full provenance trail and a first-class
VINTAGE marker (``extracted_at``). A re-fetch at a later vintage is a NEW row (never
an overwrite), so a revision is preserved as evidence — the law/wiki versioning model
applied to statistics. The unique key therefore includes ``extracted_at``.

NO score/rating/verdict column exists, by design (the no-composite-score
non-negotiable). A published gap is stored as ``value=NULL`` (degrade loudly).
Comparability fields (unit / adjustment SA-NSA / base_year) are NULL unless the
response stated them, so a later side-by-side triangulation can flag incomparable
denominators instead of averaging across them.

(``create_all`` already creates this on fresh stores; this migration keeps
alembic-managed databases consistent.)

Revision ID: f5a6b7c8d9e0
Revises: f4a5b6c7d8e9
Create Date: 2026-06-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f5a6b7c8d9e0"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if _has_table("stat_figures"):  # create_all may have already made it
        return
    op.create_table(
        "stat_figures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency", sa.String(length=40), nullable=False),
        sa.Column("series_id", sa.String(length=120), nullable=False),
        sa.Column("ref_area", sa.String(length=24), nullable=False),
        sa.Column("time_period", sa.String(length=24), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("methodology_ref", sa.Text(), nullable=True),
        sa.Column("adjustment", sa.String(length=16), nullable=True),
        sa.Column("base_year", sa.String(length=24), nullable=True),
        sa.Column("extracted_at", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "agency", "series_id", "ref_area", "time_period", "extracted_at",
            name="uq_stat_figure_vintage",
        ),
    )
    op.create_index("ix_stat_figures_series", "stat_figures", ["series_id", "ref_area", "time_period"])
    op.create_index("ix_stat_figures_agency", "stat_figures", ["agency"])


def downgrade() -> None:
    op.drop_index("ix_stat_figures_agency", table_name="stat_figures")
    op.drop_index("ix_stat_figures_series", table_name="stat_figures")
    op.drop_table("stat_figures")
