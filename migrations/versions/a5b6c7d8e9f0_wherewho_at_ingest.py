"""When x Where x Who at ingest (T12): place + entity persistence tables.

The extractors (dateextract/locextract/entextract) were reader-only; their
output now persists at ingest with snippet provenance + rule notes (deduced,
never promoted to fact). Dates already had article_mentioned_dates; this
adds article_mentioned_places and article_entities.

Revision ID: a5b6c7d8e9f0
Revises: f4b5c6d7e8a9
Create Date: 2026-06-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a5b6c7d8e9f0"
down_revision = "f4b5c6d7e8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "article_mentioned_places",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("article_id", sa.Integer,
                  sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("country", sa.String(2)),
        sa.Column("kind", sa.String(20)),
        sa.Column("mentions", sa.Integer, nullable=False),
        sa.Column("snippet", sa.String(400)),
        sa.Column("lat", sa.Float),
        sa.Column("lon", sa.Float),
        sa.Column("note", sa.String(300)),
        sa.Column("extractor", sa.String(40)),
        sa.Column("created_at", sa.DateTime),
    )
    op.create_index("ix_amp_article_place", "article_mentioned_places",
                    ["article_id", "name"], unique=True)
    op.create_index("ix_amp_country", "article_mentioned_places", ["country"])
    op.create_table(
        "article_entities",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("article_id", sa.Integer,
                  sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("entity_class", sa.String(16), nullable=False),
        sa.Column("mentions", sa.Integer, nullable=False),
        sa.Column("snippet", sa.String(400)),
        sa.Column("note", sa.String(300)),
        sa.Column("extractor", sa.String(40)),
        sa.Column("created_at", sa.DateTime),
    )
    op.create_index("ix_ae_article_name_class", "article_entities",
                    ["article_id", "name", "entity_class"], unique=True)
    op.create_index("ix_ae_class_name", "article_entities", ["entity_class", "name"])


def downgrade() -> None:
    op.drop_table("article_entities")
    op.drop_table("article_mentioned_places")
