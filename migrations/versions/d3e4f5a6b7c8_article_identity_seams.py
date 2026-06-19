"""K1/K2 identity seams: articles.content_multihash + canon_version.

Data-architecture build Slice 5. Additive, never reformat the dedup-load-bearing
``articles.hash``:
  * content_multihash -- the self-describing content hash (``sha2-256:<hex>``) so a
    future hash-algorithm change is unambiguous per article;
  * canon_version -- which canonicalization produced ``canonical_url``.

Both nullable. Backfilled here: content_multihash = ``sha2-256:`` || hash for rows whose
hash is a 64-char SHA-256 digest (a pure string op, no content re-hash); canon_version =
the current ``url-v1`` for existing rows (they were canonicalised by the current rules).
Self-healed identically at boot for stores that don't run alembic
(src.database.maintenance.ensure_article_identity_columns). Idempotent.

Revision ID: d3e4f5a6b7c8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3e4f5a6b7c8"
down_revision: str | None = "b2c3d4e5f6a7"
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
    added: list[str] = []
    with op.batch_alter_table("articles", schema=None) as batch_op:
        if "content_multihash" not in cols:
            batch_op.add_column(sa.Column("content_multihash", sa.String(length=80), nullable=True))
            added.append("content_multihash")
        if "canon_version" not in cols:
            batch_op.add_column(sa.Column("canon_version", sa.String(length=16), nullable=True))
            added.append("canon_version")
    if "content_multihash" in added:
        op.execute(
            "UPDATE articles SET content_multihash = 'sha2-256:' || hash "
            "WHERE content_multihash IS NULL AND length(hash) = 64"
        )
    if "canon_version" in added:
        op.execute("UPDATE articles SET canon_version = 'url-v1' WHERE canon_version IS NULL")


def downgrade() -> None:
    cols = _columns("articles")
    with op.batch_alter_table("articles", schema=None) as batch_op:
        if "canon_version" in cols:
            batch_op.drop_column("canon_version")
        if "content_multihash" in cols:
            batch_op.drop_column("content_multihash")
