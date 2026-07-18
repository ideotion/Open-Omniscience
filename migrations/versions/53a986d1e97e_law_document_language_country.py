"""law_documents.language/.country: the catalog's own asserted per-document language/
country (the Cambodia fix, law-vertical brief 2026-07-17).

A tracked legal document's catalog entry may state its OWN language (e.g. a French-
language Cambodian code) — this used to be dropped at registration, so the corpus
Article it feeds never got the right language/stoplist treatment. Additive, nullable,
no backfill: a pre-existing document heals forward the next time
``src.law.catalog.register_documents`` re-reads the catalog (which also heals the
already-ingested corpus Article in the same pass); a document the catalog states no
language for stays honestly NULL, never guessed from the jurisdiction alone. The boot
self-heal ``ensure_law_document_language_columns`` adds these on an existing DB (the
live store is never auto-migrated by alembic); this migration keeps alembic-managed
stores consistent.

Revision ID: 53a986d1e97e
Revises: d2f8a9df7168
Create Date: 2026-07-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "53a986d1e97e"
down_revision = "d2f8a9df7168"
branch_labels = None
depends_on = None

_ADD = (
    ("law_documents", "language", sa.String(8)),
    ("law_documents", "country", sa.String(8)),
)


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    for table, col, typ in _ADD:
        if not _has_column(table, col):
            op.add_column(table, sa.Column(col, typ, nullable=True))


def downgrade() -> None:
    for table, col, _typ in reversed(_ADD):
        if _has_column(table, col):
            op.drop_column(table, col)
