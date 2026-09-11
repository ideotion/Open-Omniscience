"""record what the catalogue last shipped per source, so a correction can reach an untouched row

THE GAP. ``seed_sources`` skips a domain it already holds, and
``reconcile_source_metadata`` fills only fields that are EMPTY -- the right rule for a gap
and the wrong one for a CORRECTION. So when the catalogue fixes a dead feed URL, a wrong
country, or a name whose trailing parenthetical fabricates an origin, every install that
already holds that row keeps the broken value for the life of the install. Measured before
this shipped: a row whose ``rss_url`` the catalogue had corrected still served the stale URL
after a re-seed. The only remedy was an export and re-import of the whole corpus.

WHY A COLUMN AND NOT A RULE. A two-way comparison cannot distinguish the two cases that
matter, because both look identical -- "the row's value is not the catalogue's value" is
equally true of a value we shipped and the operator never touched, and of a value the
operator deliberately set in the UI. Overwriting both is a data-loss bug wearing a
maintenance task's clothes; overwriting neither is the status quo. The third side is what
the catalogue last shipped for that row, and nothing in the schema recorded it.

WHAT IT HOLDS. A small JSON object over ``CATALOGUE_OWNED_FIELDS`` (rss_url, name, country,
language, region, source_type) -- never a copy of the row, and never read as one. The
operator's own knobs (enabled, priority, rate_limit_ms, reliability_score) are not in it and
are never touched. ``tags`` is deliberately excluded: it is a set with four writers, where a
replace drops provenance and a union cannot express the removal that correcting a wrong tag
means.

NULLABLE, NO BACKFILL, and the NULL is honest rather than absent-minded: it means "never
recorded", which is every row predating this column. Those ADOPT the current catalogue as
their baseline on the next boot and change no value at all -- because inferring whether an
untraceable value was an operator's edit is exactly the guess the column exists to avoid.
The stated cost: a correction the catalogue made BEFORE this shipped never reaches an
existing row.

ROLLOUT: additive nullable ADD COLUMN, no row rewrite, no index. Mirrored into the boot
self-heal (src/database/maintenance.py) on the source_revision precedent, because
``create_all`` never ALTERs an existing table and not every install runs alembic.

Revision ID: b3e77a91c5d4
Revises: a7c31d9e5b02
Create Date: 2026-09-11

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3e77a91c5d4"
down_revision: str | None = "a7c31d9e5b02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("catalog_baseline", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "catalog_baseline")
