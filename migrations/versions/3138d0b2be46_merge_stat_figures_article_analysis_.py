"""Merge the two alembic heads that forked from f4a5b6c7d8e9.

Two PRs branched a migration from the SAME parent (f4a5b6c7d8e9) and merged into the
0.09 cycle in parallel, leaving the tree with two heads:

  * ``f5a6b7c8d9e0`` — official-statistics figures table (Group N).
  * ``a1b2c3d4e5f6`` — article_analysis prompt-text column.

Two heads make ``alembic upgrade head`` ambiguous (it errors, "Multiple head
revisions are present"), which broke every test that stages migrations (the
DB-reliability torture suite, the sqlcipher round-trips, and test_migrations'
no-drift check). This is a pure MERGE revision — no schema change, just a single
descendant of both heads so there is one unambiguous head again. (The ledger's
standing lesson: parallel PRs can fork migrations; reconcile with a merge.)

Revision ID: 3138d0b2be46
Revises: a1b2c3d4e5f6, f5a6b7c8d9e0
Create Date: 2026-06-17
"""

from collections.abc import Sequence

revision: str = "3138d0b2be46"
down_revision: tuple[str, str] | None = ("a1b2c3d4e5f6", "f5a6b7c8d9e0")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Pure merge — no schema change.
    pass


def downgrade() -> None:
    # A merge cannot be meaningfully un-merged into two heads automatically.
    pass
