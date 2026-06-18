"""
The AI layer: AI-derived analytics LOGIC (extraction / jobs / store helpers).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ruling 2026-06-18 (CLAUDE.md (3) — REVERSES the earlier separate-database
design): AI-derived analytics live in their OWN tables in the MAIN corpus DB (the
``ai_keyword`` table on the main ``Base``), for seamless UI integration + fast
corpus-wide selection (a real indexed JOIN). This package holds the AI *logic*; the
*model* now lives in ``src.database.models``. The integrity guarantee is preserved BY
CONSTRUCTION, not by physical separation: own table (never the trusted ``keywords`` /
``keyword_mentions``), NO score column, model provenance, confirm-within-the-lens, and
an invariant test that the trusted rule-based index NEVER reads ``ai_keyword`` (it reads
only ``articles.content``). The AI keywords are a clearly-labelled, disposable lens; the
only AI writes to the trusted side remain summaries/translations in ``article_analyses``.
"""

from __future__ import annotations
