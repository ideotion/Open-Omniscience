"""Hazard event details -- hazards ingest AS Articles (2026-07-24 field-feedback A6).

Adds ``hazard_event_details`` -- a LINKED layer over ``articles`` (one row per hazard
Article, mirroring ``law_revision_summaries``'s linked-layer shape) holding the
PROVIDER-ASSERTED event metadata (magnitude/coordinates/severity/place/time) a hazard
record carries. TWO-CLASS discipline the OTHER way round from ``article_mentioned_
places``/``article_entities`` (which are DEDUCED from text): this is asserted, never
inferred, never a score.

(``create_all`` already creates this on fresh stores; this migration keeps
alembic-managed databases consistent.)

Revision ID: cdf441950256
Revises: 286c5087fb13
Create Date: 2026-07-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "cdf441950256"
down_revision = "286c5087fb13"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if _has_table("hazard_event_details"):  # create_all may have already made it
        return
    op.create_table(
        "hazard_event_details",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("article_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("event_id", sa.String(length=120), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=True),
        sa.Column("magnitude", sa.Float(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("place", sa.String(length=300), nullable=True),
        sa.Column("event_time", sa.DateTime(), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_hazard_detail_provider_event", "hazard_event_details",
        ["provider", "event_id"], unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_hazard_detail_provider_event", table_name="hazard_event_details")
    op.drop_table("hazard_event_details")
