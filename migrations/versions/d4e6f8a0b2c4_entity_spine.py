"""entity spine -- the Wikidata item cache and the Place entity (S05-03, Q724 + Q818).

Two tables in the corpus database:

* ``wikidata_items`` -- one row per QID the corpus mentions, as this machine last read it
  (labels, descriptions, the P31/P17/P625/P571 claims subset), written only by the
  consented, rate-gated fetch.
* ``places`` -- a place keyed on its OpenStreetMap object (``node/123``), materialised
  from the gazetteer for the places the corpus mentions.

Both are empty until their jobs run, which is exactly what they mean.

GUARDED like the head migration: the boot path's ``create_all`` may have built them first.

Revision ID: d4e6f8a0b2c4
Revises: c8e2a4f6b1d3
Create Date: 2026-09-28

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "d4e6f8a0b2c4"
down_revision: str | None = "c8e2a4f6b1d3"
branch_labels: str | None = None
depends_on: str | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "articles" not in tables:
        return
    if "wikidata_items" not in tables:
        op.create_table(
            "wikidata_items",
            sa.Column("qid", sa.String(length=16), primary_key=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("resolved_qid", sa.String(length=16), nullable=True),
            sa.Column("labels_json", sa.Text(), nullable=True),
            sa.Column("descriptions_json", sa.Text(), nullable=True),
            sa.Column("claims_json", sa.Text(), nullable=True),
            sa.Column("lastrevid", sa.Integer(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(), nullable=True),
        )
    if "places" not in tables:
        op.create_table(
            "places",
            sa.Column("id", sa.String(length=40), primary_key=True),
            sa.Column("qid", sa.String(length=16), nullable=True),
            sa.Column("kind", sa.String(length=32), nullable=True),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("names_json", sa.Text(), nullable=True),
            sa.Column("country", sa.String(length=2), nullable=True),
            sa.Column("country_alpha3", sa.String(length=3), nullable=True),
            sa.Column("admin_path_json", sa.Text(), nullable=True),
            sa.Column("geometry_ref", sa.String(length=64), nullable=True),
            sa.Column("lat", sa.Float(), nullable=True),
            sa.Column("lon", sa.Float(), nullable=True),
            sa.Column("population", sa.Integer(), nullable=True),
            sa.Column("gazetteer_vintage", sa.String(length=32), nullable=True),
            sa.Column(
                "article_id",
                sa.Integer(),
                sa.ForeignKey("articles.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("as_of", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_places_qid", "places", ["qid"])
        op.create_index("ix_places_name_country", "places", ["name", "country"])


def downgrade() -> None:
    tables = _tables()
    if "places" in tables:
        op.drop_index("ix_places_name_country", table_name="places")
        op.drop_index("ix_places_qid", table_name="places")
        op.drop_table("places")
    if "wikidata_items" in tables:
        op.drop_table("wikidata_items")
