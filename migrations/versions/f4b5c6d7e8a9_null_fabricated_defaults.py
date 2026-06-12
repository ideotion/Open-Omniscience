"""NULL the fabricated reliability_score=5 rows (audit 06 remediation).

Source.reliability_score had a silent default of 5: every source created
without an explicit rating was asserted "medium reliability" — fabricated
data, the same defect class as the removed credibility_score=50 and the
country="US" defaults. No shipped catalog asserts a 5 (verified across
configs/ on 2026-06-12), so a stored 5 is the ambient default by
construction, not an operator's judgement — it becomes an honest NULL
("not rated"). Language columns are NOT touched: catalog seeds assert
languages explicitly, so existing values are real assertions; only the
silent DEFAULTS were removed from the models (new unknowns stay NULL), and
the keyword export's language_mismatch field surfaces historical
attribution noise as evidence.

Revision ID: f4b5c6d7e8a9
Revises: e2f3a4b5c6d7
Create Date: 2026-06-12
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "f4b5c6d7e8a9"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        text("UPDATE sources SET reliability_score = NULL WHERE reliability_score = 5")
    )


def downgrade() -> None:
    # The fabricated value is not restored: there is nothing true to restore.
    pass
