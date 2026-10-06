"""index articles for the article list's language filter and its sort by title

The article list's two slow shapes read one whole row per candidate because no index covers
them. A language filter: idx_article_language (language) finds the rows, but the date the list
orders them by sits after the article's text in the record, so every row is read to sort it
(1,447 ms cold on a 40,000-article, 2 GB synthetic store). A sort by title: the list orders
`title COLLATE NOCASE` (case-insensitive, matching the FTS path), which no existing index can
serve because an index's collation is its own (807 ms cold, same store).

  idx_article_language_published (language, published_at)   plan: SEARCH ... USING COVERING INDEX,
                                                            no sort step; 1,447 -> 3 ms cold
  idx_article_title_nocase (title COLLATE NOCASE)           plan: SCAN ... USING COVERING INDEX,
                                                            no sort step; 807 -> 3 ms cold

Measured on the same store: 1.5 MB and 1.9 MB (about 38 and 46 bytes an article, so about 57 and
70 MB per 1.5 million articles) and 4.0 s plus 0.1 s to build with a cold file; each adds one small
write per ingested article. idx_article_language stays (counts still use it).

ROLLOUT: purely additive, results unchanged, only cost. IF NOT EXISTS on both directions: the live
app builds these two at start-up in its own step (src/database/article_indexes.py, with the free
space measured first and the progress in the task manager), so a store that ran a newer app before
this migration was stamped already has them. A staged copy migrated by `alembic upgrade` builds
them here, one statement each.

Revision ID: c3a91f5e7b24
Revises: a7c9e1b3d5f7
Create Date: 2026-10-06

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "c3a91f5e7b24"
down_revision: str | None = "a7c9e1b3d5f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LANGUAGE = (
    "CREATE INDEX IF NOT EXISTS idx_article_language_published "
    "ON articles (language, published_at)"
)
_TITLE = (
    "CREATE INDEX IF NOT EXISTS idx_article_title_nocase "
    "ON articles (title COLLATE NOCASE)"
)


def upgrade() -> None:
    # IF NOT EXISTS: the start-up step (article_indexes) may have built them already on a store
    # that ran a newer app before its migration was stamped.
    op.execute(text(_LANGUAGE))
    op.execute(text(_TITLE))


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS idx_article_title_nocase"))
    op.execute(text("DROP INDEX IF EXISTS idx_article_language_published"))
