"""sources.outlet_id: the outlet as an integer, kept by three triggers (R177)

``coalesce(domain, source_id)`` hashes a text domain for every scanned mention row; on an encrypted store that is +16 % over
the pre-row-J query, against +2.7 % for an integer (``plan-row-j/outlet-key-design-2026-10-17`` section 9). The integer is the
lowest id among the sources of a domain, derived and never carried by a backup. The step is additive: one ``ADD COLUMN``, three
``CREATE TRIGGER IF NOT EXISTS`` and one ``UPDATE`` that fixes the rows that are wrong; it scales with ``sources`` (thousands of
rows), never with articles or mentions, and it writes only ``outlet_id`` (no verdict, no catalogue-owned field, no operator edit).
``src.database.source_identity.install_source_outlet_id`` is the shared body: the live app runs it at boot, so an
already-migrated store is a no-op here.

Downgrade is a no-op: a column and triggers that nothing older reads are harmless, and dropping a column from a table other
tables reference is the rebuild this step exists to avoid.

Revision ID: e6b2d8f0a4c3
Revises: d5a1c7e9b3f2
Create Date: 2026-10-17

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6b2d8f0a4c3"
down_revision: str | None = "d5a1c7e9b3f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from src.database.source_identity import install_source_outlet_id

    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    install_source_outlet_id(bind)


def downgrade() -> None:
    # Nothing older reads the column or the triggers; they stay.
    pass
