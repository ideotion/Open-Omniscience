"""
The AI layer's schema lives in the MAIN database now (maintainer ruling 2026-06-18).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

REVERSES the earlier separate-database design: AI-derived analytics are their OWN
tables in the main corpus DB (for seamless UI integration + fast corpus-wide
selection via an indexed JOIN), with the integrity guarantee preserved by
construction — own table, no score, model provenance, and an invariant test that the
trusted rule-based index never reads it. The canonical model now lives in
``src.database.models``; this module re-exports it so the ``src.ai_layer`` package
stays the home of the AI *logic* (extract / jobs / store).
"""

from __future__ import annotations

from src.database.models import AiKeyword

__all__ = ["AiKeyword"]
