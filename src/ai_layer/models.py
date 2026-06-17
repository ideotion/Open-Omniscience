"""
The AI layer's schema — AI-derived analytics, stored apart from the trusted corpus.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

These tables live in their OWN database (src.ai_layer.db), never the main corpus.
``AiBase`` is a declarative-metadata namespace DISJOINT from the main
``src.database.models.Base`` (enforced by tests/test_ai_layer.py), so the two
databases can never be confused or merged.

Honesty by construction (the standing project invariants apply here too):
  * NO composite score column — ever. AI output is a labelled assertion, not a rank.
  * ``article_id`` is a PLAIN integer SOFT reference — there is NO ForeignKey to the
    main ``articles`` table, because the two databases are never joined. The
    reference is resolved in application code.
  * Every row carries its model provenance (which local LLM produced it, under which
    prompt version) so AI-derived text is never shown without its origin.
  * ``confirmed`` curates the lens IN PLACE (confirm-within-the-lens). A confirmed AI
    item does NOT migrate into the trusted main tables — that would "touch main",
    forbidden by the ruling. It simply becomes "confirmed within the AI lens".
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class AiBase(DeclarativeBase):
    """Declarative base for the AI layer — a metadata namespace deliberately kept
    DISJOINT from the main corpus's ``Base`` so the two stores share no table."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AiKeyword(AiBase):
    """An AI-extracted keyword / entity / claim — the "second keyword database".

    The trusted, rule-based keyword index stays canonical in the MAIN database; this
    is the parallel AI lens beside it. A soft ``article_id`` (no ForeignKey) ties a
    row back to its source article in app code, never by SQL join.
    """

    __tablename__ = "ai_keyword"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Soft reference to articles.id in the MAIN database — resolved in app code,
    # NEVER an SQL join (the two databases are physically separate).
    article_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    term: Mapped[str] = mapped_column(String(300), nullable=False)
    # The kind of AI analytic: keyword | entity | claim | dedup (extensible).
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="keyword")
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Provenance: which local model produced this, under which prompt version.
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Confirm-within-the-lens: default unconfirmed. A user may curate the AI lens; a
    # confirmed row STAYS here — it never crosses into the trusted main index.
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Optional free-text evidence (e.g. the snippet the model drew the term from).
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        Index("ix_ai_keyword_article_kind", "article_id", "kind"),
        Index("ix_ai_keyword_term", "term"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<AiKeyword {self.kind} {self.term!r} a={self.article_id}>"
