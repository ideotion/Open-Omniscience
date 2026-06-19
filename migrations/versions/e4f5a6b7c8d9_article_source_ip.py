"""Source IP provenance: articles.server_ip + ip_observed_at + server_ip_reason.

Data-architecture build Slice 6a. The server IP we connected to at fetch -- OUR
vantage point (usually a CDN edge / anycast), NOT proof of the publisher's origin.
Captured only on a direct clearnet connection; over a SOCKS proxy / Tor it is honestly
unavailable (server_ip NULL + server_ip_reason). All nullable, additive, NO backfill:
existing articles simply have no captured IP. Self-healed identically at boot
(src.database.maintenance.ensure_article_ip_columns). Idempotent.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-06-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: str | None = "d3e4f5a6b7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    cols = _columns("articles")
    if not cols:
        return  # no articles table yet (a brand-new store; create_all builds it)
    with op.batch_alter_table("articles", schema=None) as batch_op:
        if "server_ip" not in cols:
            batch_op.add_column(sa.Column("server_ip", sa.String(length=45), nullable=True))
        if "ip_observed_at" not in cols:
            batch_op.add_column(sa.Column("ip_observed_at", sa.DateTime(), nullable=True))
        if "server_ip_reason" not in cols:
            batch_op.add_column(sa.Column("server_ip_reason", sa.String(length=64), nullable=True))


def downgrade() -> None:
    cols = _columns("articles")
    with op.batch_alter_table("articles", schema=None) as batch_op:
        if "server_ip_reason" in cols:
            batch_op.drop_column("server_ip_reason")
        if "ip_observed_at" in cols:
            batch_op.drop_column("ip_observed_at")
        if "server_ip" in cols:
            batch_op.drop_column("server_ip")
