"""the tentative keyword-translation table (Q404), so the LLM tier survives a restart

The 2026-06-19 ruling paired VERIFIED Wikidata rings with an LLM FALLBACK for the
terms no ring covers. The ring half is durable (two YAML files); the fallback half
has lived since then in `src/ai_layer/translate.py`'s process-global dict -- 5,000
entries, dropped on every restart, carried by no backup, and therefore re-paid in
local model time after every restore. Q404 (2026-09-15) gives it a table.

WHY A VINTAGE KEY RATHER THAN "ONE TRANSLATION PER TERM PAIR".
`uq_keyword_translation` is the full tuple (term, source_lang, target_lang, model,
prompt_version), which is the `uq_stat_figure_vintage` shape. A different model or a
changed prompt is a different measurement, so collapsing them would pick a winner
between two answers nobody compared -- and, in a MERGE, would let an incoming row
overwrite a local one. With the full tuple the merge handler is a pure
`WHERE NOT EXISTS` dedupe: it can add, it can never replace. A reader needing exactly
one answer takes the newest `created_at`, a rule that lives at the read where it is
visible.

NOTHING WRITES IT YET, AND THAT IS THE SEQUENCING, NOT AN OVERSIGHT. Brief `S04-06`
owns the writers (the three-tier ladder). This slice is the ONE backup-format bump
(gate row K), so the table has to exist and restore BEFORE the writers land, or the
first backup taken after them would carry rows an older build cannot place.

ROLLOUT: an additive CREATE TABLE. `Base.metadata.create_all` materialises a missing
TABLE on every existing database at boot (the `FeedFetchState` precedent), so unlike
an ADD COLUMN this needs no separate boot self-heal entry and an install that never
runs alembic still gets the table.

Revision ID: 5adfcc0ed33e
Revises: c4f18b62d0a7
Create Date: 2026-09-16

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5adfcc0ed33e"
down_revision: str | None = "c4f18b62d0a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    return table in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    # `Base.metadata.create_all` at boot (src/database/session.py) materialises a missing
    # TABLE before the stamp ever advances, so this migration routinely arrives at a
    # database that already has it -- exactly the case `d0e1f2a3b4c5_ai_keyword_table`
    # and `cdf441950256_hazard_event_details` guard, with the latter saying so in as many
    # words. MEASURED without this guard: `alembic upgrade head` over a pre-created table
    # died with "table keyword_translations already exists", leaving the stamp behind
    # head. The boot path self-heals that (align_stamp_to_head), but the RESTORE path
    # does not: `upgrade_database_file` runs alembic straight at a staged artifact copy
    # and never calls create_all, so an artifact from a machine in that state would have
    # failed to restore at all.
    if _has_table("keyword_translations"):
        return
    op.create_table(
        "keyword_translations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("term", sa.String(length=200), nullable=False),
        sa.Column("source_lang", sa.String(length=16), nullable=False),
        sa.Column("target_lang", sa.String(length=16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("prompt_version", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "term", "source_lang", "target_lang", "model", "prompt_version",
            name="uq_keyword_translation",
        ),
    )
    # The NULL-safe twin of `uq_keyword_translation`. SQLite's UNIQUE treats NULL as
    # distinct from NULL, so the constraint alone stops nothing when `model` and
    # `prompt_version` are unset -- and the merge handler COALESCEs exactly these five.
    # Measured: two identical NULL-keyed `INSERT OR IGNORE`s produced two rows.
    op.create_index(
        "uq_keyword_translation_nullsafe",
        "keyword_translations",
        [
            sa.text("term"), sa.text("source_lang"), sa.text("target_lang"),
            sa.text("COALESCE(model,'')"), sa.text("COALESCE(prompt_version,'')"),
        ],
        unique=True,
    )
    op.create_index(
        "ix_keyword_translations_lookup",
        "keyword_translations",
        ["term", "source_lang", "target_lang"],
    )


def downgrade() -> None:
    # THIS DROPS THE ROWS, and that is the intended cost. Every row here is a local
    # model's ~translation, never the trusted index (Q404), so losing them costs
    # re-translation time rather than information -- the same trade every sibling
    # table-creating migration in this tree makes. Said out loud because the migration
    # is silent about it otherwise, and a downgrade that quietly destroys a table an
    # operator has been filling for weeks should not be a surprise discovered afterwards.
    op.drop_index("ix_keyword_translations_lookup", table_name="keyword_translations")
    op.drop_index("uq_keyword_translation_nullsafe", table_name="keyword_translations")
    op.drop_table("keyword_translations")
