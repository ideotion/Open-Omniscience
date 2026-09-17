"""Per-mention article language (Q414 = a, 2026-09-15, gate row M, brief S04-06).

Adds ``keyword_mentions.language`` -- the NORMALISED language of the article the
mention was extracted from. ``Keyword.language`` stays, demoted from a
first-write-wins fact to a CACHE of the per-mention majority, which
``reconcile_keyword_language`` derives and writes back.

Additive, nullable, NO BACKFILL. A pre-existing mention row reads NULL, which means
"never measured here" and is a different fact from "language unknown" -- the majority
derivation skips NULLs rather than counting them. The rows fill forward as the
re-index reaches each article, which is the same path that produced them.

ON THE ``create_all``-HAS-ALREADY-RUN PATH, AND WHAT THE GUARD IS ACTUALLY FOR. The
2026-09-16 ledger entry records a migration dying with "table keyword_translations
already exists" because the RESTORE path runs alembic straight at a staged artifact
copy and never calls ``create_all``, while the ordinary boot does the opposite. That
entry is about CREATE TABLE. For ADD COLUMN the answer here is different, and it was
MEASURED rather than assumed: ``migrations/env.py`` configures
``render_as_batch=True``, so on SQLite an ``op.add_column`` is a reflect-and-recreate,
and adding a column the table already carries is a clean no-op -- driven with the guard
deleted, over a store built by ``Base.metadata.create_all``, the upgrade SUCCEEDED and
``PRAGMA table_info`` showed ``language`` exactly once with all ten indexes intact.

So the ``_has_column`` guard below is NOT what makes the restore path work, and this
note exists so no future reader infers that it is. It is kept because it is two lines,
because it states the intent at the point of the operation, and because it stays
correct if ``render_as_batch`` is ever turned off or a non-SQLite backend appears --
neither of which the batch-mode behaviour would survive. The sibling idiom is
``4fc4be4dffef_source_last_crawled_at``.

Revision ID: 3b7e91c4d28a
Revises: 5adfcc0ed33e
Create Date: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3b7e91c4d28a"
down_revision: str | None = "5adfcc0ed33e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "keyword_mentions"
_COLUMN = "language"


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    try:
        return column in {c["name"] for c in insp.get_columns(table)}
    except Exception:  # noqa: BLE001 - a store without the table at all: nothing to add
        return True


def upgrade() -> None:
    if not _has_column(_TABLE, _COLUMN):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=10), nullable=True))


def downgrade() -> None:
    if _has_column(_TABLE, _COLUMN):
        op.drop_column(_TABLE, _COLUMN)
