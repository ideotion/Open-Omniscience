"""index article_links (article_id, normalized_url) -- convergence._shared_origin's covering index

``convergence._shared_origin`` (src/analytics/convergence.py) counts the outbound URLs that more than one
article of a set cites: ``GROUP BY normalized_url HAVING count(DISTINCT article_id) > 1`` over the links of a
few hundred article ids. With only ``idx_article_link_article_id`` the planner seeks each id and then reads
the whole link row for ``normalized_url`` (two String(1000) columns, a page decrypt each under SQLCipher).
The 2026-11-07 field bundle measured 32-55 s per statement (finding F2/F8; R455, R611).

EXPLAIN QUERY PLAN on a synthetic 4,160,000-link store, 400-id set, page cache dropped before each run,
median of three, SQLite 3.45.1 and 3.53.1 alike:

  before  SEARCH article_links USING INDEX idx_article_link_article_id (article_id=?)
          USE TEMP B-TREE FOR GROUP BY / FOR count(DISTINCT)
  after   SEARCH article_links USING COVERING INDEX idx_article_link_article_url (article_id=?)
          USE TEMP B-TREE FOR GROUP BY

  SQLCipher, each article's links scattered (a restore merge's shape): 1,392 -> 171 ms
  SQLCipher, links contiguous: 213 -> 180 ms; SQLite 3.53.1: 75 -> 35 ms; 3.45.1: 67 -> 41 ms

The one-time build: 3.3 s (SQLite) and 13.2 s (SQLCipher) for the 4.16 M links, +67 bytes an index entry on
disk at urls of 54 characters, +104 bytes of RAM per link for the sort (temp_store=MEMORY). It is also a
DEFERRED entry of the boot self-heal (src/database/maintenance.py HOT_INDEXES), built by the visible
``article-indexes`` start-up step with its free-space and memory gates, so a store that ran a newer app
before this migration was stamped may already have it: IF NOT EXISTS both ways.

Purely additive: no query result changes, only the cost.

Revision ID: a7c3e5f19b20
Revises: b3d8f1a6c4e2
Create Date: 2026-11-08

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "a7c3e5f19b20"
down_revision: str | None = "b3d8f1a6c4e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_article_link_article_url"
            " ON article_links (article_id, normalized_url)"
        )
    )


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS idx_article_link_article_url"))
