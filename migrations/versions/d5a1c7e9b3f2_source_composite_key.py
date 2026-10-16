"""a source is keyed on (domain, feed): UNIQUE (domain, feed_key) replaces UNIQUE (domain)

Row J (S05-10), Q1102 = b. ``sources.domain`` was UNIQUE, so one domain held one feed and 475 catalogue entries
(BBC's, DW's and the other language services, the lean-tagged spectrum catalogue) could never be registered.
``domain`` stays part of the identity (52 feeds are carried by several domains' separate rows already, so a key on the
feed alone cannot be installed on a real store without merging rows); ``feed_key`` is the normalised feed URL
(``src/database/feed_key.py``), ``''`` for a source with no feed.

SQLite cannot drop a UNIQUE constraint, so this rebuilds ``sources``. The rebuild is the dangerous step: four tables
reference ``sources.id`` ``ON DELETE CASCADE`` and the app runs with foreign keys ON, so a plain ``DROP TABLE`` deletes
their rows. ``src.database.source_identity`` is SQLite's documented twelve-step procedure (enforcement OFF outside a
transaction and read back, one transaction around create/copy/drop/rename, every id carried over and compared before
the drop); the live app takes the same path at boot, so an already-migrated store is a no-op here.

Downgrade is a no-op: the old UNIQUE (domain) could not be restored on a store that now holds two feeds of a domain,
and a downgrade that refuses on real data is the worse default. The extra rows and the column stay.

Revision ID: d5a1c7e9b3f2
Revises: c3a91f5e7b24
Create Date: 2026-10-16

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5a1c7e9b3f2"
down_revision: str | None = "c3a91f5e7b24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from src.database.source_identity import (
        SourceIdentityRefused,
        source_identity_state,
        upgrade_sources_to_composite_key,
    )

    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    if source_identity_state(bind) in {"absent", "composite"}:
        return
    # The rebuild needs enforcement OFF *outside* a transaction; alembic's connection has none open for SQLite
    # (no transactional DDL there) and the step reads the pragma back and refuses if it did not take.
    try:
        upgrade_sources_to_composite_key(bind)
    except SourceIdentityRefused:
        raise


def downgrade() -> None:
    # Not restorable once a domain holds two feeds; the column and rows stay.
    pass
