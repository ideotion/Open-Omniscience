"""store the newsletter List-Id, so the publisher preview can reach its own best answer

`publisher_key` resolves a platform-hosted newsletter (Substack, beehiiv,
Mailchimp, ...) by the publication label on the sending host, and falls back to
the RFC 2919 List-Id when the host carries no usable label -- the
`platform-list-id` basis. `parse_email` has read that header since the
2026-06-15 ruling kept it (recipient-safe by construction: List-Id names the
LIST, never a subscriber), and `_email_article` then dropped it on the floor.

So the ONE non-test caller of the resolver, `resolution_preview`, had nothing to
pass. It reconstructs a sender as `f"x@{dom}"` from the stored From header, with
no List-Id, and for every platform sender whose host carries no publication
label that forces the refusal branch:

    sent through substack.com with no publication label on the host and no
    List-Id naming one -- attaching to the platform itself would merge every
    publisher on it into one source

...even for a message that DID carry a List-Id naming the publication. The
endpoint exists "so the decision can be reviewed against evidence rather than
described", and it was systematically under-reporting the resolver for the
commonest newsletter shape there is. The preview's own caveat already said so;
this closes it rather than restating it.

WHY A COLUMN AND NOT A DERIVATION. The docket asked for "the provenance columns
(an additive migration) ... send-domain + attached source id". Measured against
the tree, that is one column, not three:
  * the SEND DOMAIN is already recoverable -- `_email_article` stores the raw
    From header as `Article.author`, and `sender_domain(author)` is exactly what
    the preview already calls. Storing it again would be denormalisation, not
    provenance.
  * the ATTACHED SOURCE ID cannot be recorded before the attach exists. The
    attach is the NEXT slice (it is gated on the announcing import UI + undo);
    inventing its record shape now is the half-built schema this project parks
    on purpose.
  * the LIST-ID is the only fact genuinely lost at ingest, and it is
    unrecoverable afterwards: it lives in a header of a file the app
    deliberately does not keep.

NULLABLE, NO BACKFILL, and the NULL is honest rather than absent-minded: it
means "no List-Id header, or imported before this column existed", which is why
the preview's caveat keeps naming the pre-existing corpus instead of claiming
the gap is closed for messages already stored. Nothing can reconstruct it --
re-importing the same .eml is the only path, and that is the user's own file.

ROLLOUT: additive nullable ADD COLUMN, no row rewrite, no index. Mirrored into
the boot self-heal (src/database/maintenance.py) on the source_revision
precedent, because create_all never ALTERs an existing table and not every
install runs alembic.

Revision ID: a7c31d9e5b02
Revises: 1f504b87844f
Create Date: 2026-09-10

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c31d9e5b02"
down_revision: str | None = "1f504b87844f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "articles", sa.Column("newsletter_list_id", sa.String(length=255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("articles", "newsletter_list_id")
