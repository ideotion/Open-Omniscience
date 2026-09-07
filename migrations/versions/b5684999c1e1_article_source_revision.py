"""articles.source_revision — the version anchor for a versioned source.

One additive NULLABLE column, on the detected_language / quarantined /
keyword_indexed_at pattern: no backfill, so an existing article reads NULL,
which means "came from no versioned source, or predates this column" and is
deliberately NOT "revision unknown" — a UI must never render it as a version.

WHY. A VERSIONED SOURCE is an Article whose text is amendable — Wikipedia
today, laws next — and the standing ruling is that its audit trail is only
meaningful if an analytic result can name the version it was computed against.
``src.wiki.corpus.upsert_wiki_corpus_article`` has always RECEIVED the revid
(from the tracker's latest text, or from the dump the page was read out of) and
had nowhere to put it, so it returned the number to its caller and dropped it.
The revision that produced an article's stored text was therefore recoverable
only for WATCHED pages, by deriving the wiki+title from the canonical URL and
reading ``WikiPage.latest_text_revid`` — which is the tracker's CURRENT state,
not the one the stored text came from, and does not exist at all for a page
ingested from a dump.

WHY NOT ON keyword_mentions, which is where the ledger's shorthand put it: all
of an article's mentions are produced by one indexing pass over one text, so a
per-mention column would store a per-article constant once per mention — on a
field-scale corpus, millions of copies of a value with one distinct reading per
article, on the largest table in the store, carrying no fact this column does
not. The mentions inherit the anchor through their article.

A STRING, not an int: a wiki revid is an integer, but a law revision, a
statistics vintage and a gazette issue are not, and this is the one seam every
versioned source will write into.

Revision ID: b5684999c1e1
Revises: 7280ec4d08b1
Create Date: 2026-09-07

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "b5684999c1e1"
down_revision: str | None = "7280ec4d08b1"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("source_revision", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("articles", "source_revision")
