"""Secondary/deduced language column on articles: detected_language.

Field §2.6 (maintainer ruling Q3, 2026-06-23): articles the source/extractor left
untagged get an OFFLINE confidence-gated detected language (src/analytics/langdetect.py)
so a foreign untagged article extracts under the right stoplist instead of leaking its
function words. It is SECONDARY/DEDUCED metadata: it NEVER overwrites the authoritative
``language``. Additive nullable column; self-healed identically at boot
(src.database.maintenance.ensure_article_detected_language_column). Idempotent.

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-06-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: str | None = "b4c5d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "articles"
_COLUMN = "detected_language"


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table: str, name: str) -> bool:
    if not _has_table(table):
        return False
    return any(c["name"] == name for c in sa.inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    if _has_table(_TABLE) and not _has_column(_TABLE, _COLUMN):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=10), nullable=True))


def downgrade() -> None:
    if _has_column(_TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
