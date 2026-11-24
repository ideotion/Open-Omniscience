"""stage_versions_and_engine_registry -- which stage version wrote a stamp, which import carried it, and what each engine is (R824).

Row 405, R824 step 1, built on R412/R415. Three additive changes, no backfill:

* ``article_index_stamps.stage_version`` and ``article_www_stamps.stage_version`` (nullable integer): the hand-bumped version of the
  stage (``INDEXER_VERSION`` / ``WWW_INDEXER_VERSION``) that produced the rows. NULL on every existing stamp, which a restore reads
  through the engine id alone, as before (the id already hashes the version);
* ``carried_from_batch`` (nullable integer) on both: the import batch whose carry wrote the stamp. NULL means the rows were extracted on
  this machine; a re-index here writes NULL again. Never a foreign key: a batch row may be pruned and the provenance must not go with it;
* ``index_engines``: one row per engine id this store has stamped, with the readable components the id is a hash of, so a restore can
  say WHICH component differs when an incoming stamp is not this machine's, instead of an opaque hash.

GUARDED like the other steps: the boot path's ``create_all`` may have built the table or the columns first. A plain ``ADD COLUMN``,
never ``batch_alter_table``, which would rebuild the two stamp tables.

Revision ID: e4b7c1d9a2f6
Revises: d7e3a9b2c5f1
Create Date: 2026-11-24

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4b7c1d9a2f6"
down_revision: str | None = "d7e3a9b2c5f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STAMPS = ("article_index_stamps", "article_www_stamps")
_REGISTRY = "index_engines"
_COLUMNS = ("stage_version", "carried_from_batch")


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _tables()
    for table in _STAMPS:
        if table not in tables:
            continue
        have = _columns(table)
        for name in _COLUMNS:
            if name not in have:
                op.add_column(table, sa.Column(name, sa.Integer(), nullable=True))
    if _REGISTRY not in tables:
        op.create_table(
            _REGISTRY,
            sa.Column("engine", sa.String(length=40), primary_key=True),
            sa.Column("stage", sa.String(length=8), nullable=False),
            sa.Column("components", sa.Text(), nullable=False),
            sa.Column("recorded_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    tables = _tables()
    if _REGISTRY in tables:
        op.drop_table(_REGISTRY)
    for table in _STAMPS:
        if table not in tables:
            continue
        have = _columns(table)
        for name in _COLUMNS:
            if name in have:
                op.execute(f'ALTER TABLE "{table}" DROP COLUMN "{name}"')  # noqa: S608  # nosec B608 # module-local literals
