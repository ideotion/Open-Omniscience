"""article observed-date expression index (field-test 2026-07-08 Item 8 P0)

The single biggest field-measured cost: the corpus date-range probe
``SELECT min(coalesce(published_at, created_at)), max(coalesce(published_at,
created_at)) FROM articles`` measured 4,775 ms x 154 calls = 735 s total,
because ``coalesce(published_at, created_at)`` had no index -- so every call
was a full ``SCAN articles`` that dragged all ~59,566 rows (each carrying the
large ``content`` column) through the SQLCipher codec. The SAME expression is
also a ``>= cutoff`` range filter (equally full-scan) in
src/integrity/{collapse,actors,profile}.py, src/api/link_analysis.py and
src/analytics/{copypasta,headline_body,recycled_claim}.py.

This expression index makes both shapes index-only: EXPLAIN QUERY PLAN goes
from a bare ``SCAN articles`` to ``SCAN articles USING COVERING INDEX
ix_article_observed`` (the min/max probe) and ``SEARCH articles USING COVERING
INDEX ix_article_observed (<expr>>?)`` (the cutoff filters) -- no per-row heap
page read, so no SQLCipher decrypt per row. SQLite matches an expression index
only when the query expression is written identically; every call site already
uses ``func.coalesce(Article.published_at, Article.created_at)`` (verified), and
SQLite normalises the qualified query form ``coalesce(articles.published_at,
articles.created_at)`` against this unqualified index expression.

``IF NOT EXISTS`` (both directions): init_db()'s boot self-heal
(maintenance.ensure_hot_indexes, HOT_INDEXES["ix_article_observed"]) may have
created it already on installs that boot before they migrate -- the same
parallel the mention indexes keep (migration e2f3a4b5c6d7).

Not declared on the ORM model (SQLAlchemy cannot reflect expression indexes, so
alembic autogenerate/`alembic check` never sees it -- no model drift); the
migration and the boot self-heal are the two canonical creators.

Revision ID: 5ea842778603
Revises: c1d2e3f4a5b6
Create Date: 2026-07-08 19:43:23.322760
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5ea842778603"
down_revision: str | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The single canonical DDL, byte-identical to
# maintenance.HOT_INDEXES["ix_article_observed"]. SQLite expression-index
# matching is by normalised parse tree, so the exact text of THIS expression
# must equal what the queries compile to (func.coalesce(published_at,
# created_at)); keep the two creators in lock-step.
_CREATE = (
    "CREATE INDEX IF NOT EXISTS ix_article_observed "
    "ON articles (coalesce(published_at, created_at))"
)
_DROP = "DROP INDEX IF EXISTS ix_article_observed"


def upgrade() -> None:
    op.execute(_CREATE)


def downgrade() -> None:
    op.execute(_DROP)
