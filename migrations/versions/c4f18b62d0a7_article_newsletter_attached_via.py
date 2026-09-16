"""record WHICH automated decision placed an imported newsletter, so it can be undone

The 2026-06-15 ruling ("MASS LOCAL .eml NEWSLETTER IMPORT", clause (d)) pairs the
silent auto-attach with a dedicated import UI that ANNOUNCES it and an UNDO for
the automated attaches. `src/ingest/newsletter_source.py` shipped the ladder as a
pure decision and a read-only preview; the write path stayed unwired precisely
because "shipping the attach without those would be half a data-placement change,
which is worse than none". Q1151 = a is the go-ahead, and the three land together.

WHY THIS COLUMN IS WHAT THE UNDO NEEDS, and why it is still only one column.
The docket's original phrasing asked for "send-domain + attached source id".
Measured against the tree (2026-09-10, when `newsletter_list_id` shipped) that was
already one column, not three: the SEND DOMAIN is recoverable from
`Article.author`, and the ATTACHED SOURCE ID could not be recorded before an
attach existed. The attach now exists -- and the id turns out not to be the fact
worth storing either. `Article.source_id` IS the attached source; what no reader
can otherwise recover is whether the APP chose it or a human did. So the column
stores the ladder's own verdict for the placement, e.g. `attach-alias:public-suffix`.

NULL IS THE LOAD-BEARING VALUE and, unusually for this family of migrations, it is
not an ambiguity to disclose. It means "nothing automated moved this article", and
for every row predating this column that is literally true -- nothing automated had
moved any of them. So no backfill is needed and none would be honest: the undo
restores exactly the rows the app placed and cannot touch a placement a user made,
because the app never wrote a value for one.

ROLLOUT: additive nullable ADD COLUMN, no row rewrite, no index (the undo scans a
column that is NULL for almost every row, on a table the import already walks).
Mirrored into the boot self-heal (src/database/maintenance.py) on the
newsletter_list_id precedent, because create_all never ALTERs an existing table and
not every install runs alembic.

Revision ID: c4f18b62d0a7
Revises: b3e77a91c5d4
Create Date: 2026-09-16

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4f18b62d0a7"
down_revision: str | None = "b3e77a91c5d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "articles", sa.Column("newsletter_attached_via", sa.String(length=120), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("articles", "newsletter_attached_via")
