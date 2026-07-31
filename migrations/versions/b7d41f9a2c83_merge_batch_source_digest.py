"""record WHICH artifact a merge batch came from, so a re-import can be refused

merge_batches already carried origin_fingerprint, but that is the SIGNER's key --
every backup a given machine writes shares it, so it can never answer "have I
already merged THIS artifact?". Field logs 2026-07-31: 8 of 18 imports added ZERO
articles, and the largest spent 2.96 h merging 700,503 duplicates to leave the
corpus byte-identical. source_digest is the container manifest's whole-archive
plaintext SHA-256 -- the identity of the bytes -- so an already-merged artifact
can be refused up front instead of rediscovered after hours of staging.

Nullable by design: batches merged before this column existed have no digest, and
neither does a container whose manifest carries none. An unknown must never read
as a match, so those simply do the work again (and record it on the way through).

Revision ID: b7d41f9a2c83
Revises: 4fc4be4dffef
Create Date: 2026-07-31 04:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect, text

# revision identifiers, used by Alembic.
revision: str = "b7d41f9a2c83"
down_revision: str | None = "4fc4be4dffef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(bind, table: str, column: str) -> bool:
    try:
        return any(c["name"] == column for c in inspect(bind).get_columns(table))
    except Exception:  # noqa: BLE001 - a missing table is simply "no column"
        return False


def upgrade() -> None:
    bind = op.get_bind()
    # Idempotent: the boot self-heal may have added it already on a store that ran
    # a newer app before its migration was stamped.
    if not _has_column(bind, "merge_batches", "source_digest"):
        op.execute(text("ALTER TABLE merge_batches ADD COLUMN source_digest VARCHAR(64)"))
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_merge_batches_source_digest"
            " ON merge_batches (source_digest)"
        )
    )


def downgrade() -> None:
    # SQLite cannot DROP COLUMN before 3.35 and the column is harmless when unused;
    # drop only the index, which is the part that costs anything.
    op.execute(text("DROP INDEX IF EXISTS ix_merge_batches_source_digest"))
