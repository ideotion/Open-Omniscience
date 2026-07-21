"""Source qualification lifecycle: the admission-gate STAMP columns + the append-only
attempt history (0.3 CLOSE GATE ruling, maintainer-amended + RE-QUALIFICATION RULED,
2026-07-19/20).

Adds ``sources.status`` (unqualified|qualified|disqualified -- categorical, never a
score) + ``sources.qualified_at`` + ``sources.qualification_criteria_version`` (the
"qualified by Open Omniscience on DATE, criteria version N" stamp), plus a NEW table
``source_qualification_attempts`` -- one append-only row per qualification/
re-qualification attempt (the vintage convention: a re-attempt is a new row, never an
overwrite of the last one; see src.catalog.qualification and src.database.models.
SourceQualificationAttempt).

``status`` defaults to 'unqualified' at the column level so every existing row is
honestly gated the instant the column exists; the boot self-heal
(``ensure_source_qualification_columns``) then runs the SAME one-time backfill this
migration does NOT duplicate -- promoting a source with an already-collected article to
'qualified' ("the first collect pass over the catalog IS its qualification pass"). The
live store is never auto-migrated by alembic (the boot self-heal is the real upgrade
path for it); this migration keeps alembic-managed / staged-upgrade stores consistent.
The attempts table needs no boot self-heal (create_all materialises a brand-new table on
every existing database), same reasoning as event_imports / feed_fetch_state.

Revision ID: 8249f1450472
Revises: 53a986d1e97e
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8249f1450472"
down_revision: str | None = "53a986d1e97e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCE_TABLE = "sources"
_SOURCE_COLUMNS = (
    ("status", sa.String(20)),
    ("qualified_at", sa.DateTime()),
    ("qualification_criteria_version", sa.String(40)),
)
_STATUS_INDEX = "idx_source_status"

_ATTEMPTS_TABLE = "source_qualification_attempts"
_ATTEMPTS_INDEX = "idx_qual_attempt_source_time"


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return column in {c["name"] for c in insp.get_columns(table)}


def _has_index(table: str, name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return name in {ix["name"] for ix in insp.get_indexes(table)}


def upgrade() -> None:
    if not _has_column(_SOURCE_TABLE, "status"):
        op.add_column(
            _SOURCE_TABLE,
            sa.Column("status", sa.String(20), nullable=False, server_default="unqualified"),
        )
    if not _has_column(_SOURCE_TABLE, "qualified_at"):
        op.add_column(_SOURCE_TABLE, sa.Column("qualified_at", sa.DateTime(), nullable=True))
    if not _has_column(_SOURCE_TABLE, "qualification_criteria_version"):
        op.add_column(
            _SOURCE_TABLE,
            sa.Column("qualification_criteria_version", sa.String(40), nullable=True),
        )
    if not _has_index(_SOURCE_TABLE, _STATUS_INDEX):
        op.create_index(_STATUS_INDEX, _SOURCE_TABLE, ["status"])

    insp = sa.inspect(op.get_bind())
    if _ATTEMPTS_TABLE not in insp.get_table_names():
        op.create_table(
            _ATTEMPTS_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column(
                "source_id", sa.Integer(),
                sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False,
            ),
            sa.Column("attempted_at", sa.DateTime(), nullable=False),
            sa.Column("verdict", sa.String(20), nullable=False),
            sa.Column("criteria_version", sa.String(40), nullable=False),
        )
        op.create_index(_ATTEMPTS_INDEX, _ATTEMPTS_TABLE, ["source_id", "attempted_at"])


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _ATTEMPTS_TABLE in insp.get_table_names():
        if _has_index(_ATTEMPTS_TABLE, _ATTEMPTS_INDEX):
            op.drop_index(_ATTEMPTS_INDEX, table_name=_ATTEMPTS_TABLE)
        op.drop_table(_ATTEMPTS_TABLE)
    if _has_index(_SOURCE_TABLE, _STATUS_INDEX):
        op.drop_index(_STATUS_INDEX, table_name=_SOURCE_TABLE)
    for col, _typ in reversed(_SOURCE_COLUMNS):
        if _has_column(_SOURCE_TABLE, col):
            op.drop_column(_SOURCE_TABLE, col)
