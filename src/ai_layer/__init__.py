"""
The AI layer: AI-derived analytics held in a SEPARATE, parallel database.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ruling 2026-06-17 (CLAUDE.md — "LLM SCOPE — STRICT PHYSICAL SEPARATION"):
the AI must NEVER write the MAIN database except to summarize/translate (those stay
in ``article_analyses``). ALL OTHER AI-derived analytics — LLM-extracted keywords,
entities, claims, cross-language dedup — live HERE, in a second encrypted SQLCipher
file under the SAME passphrase, NEVER ATTACHed or joined to the main store. The
separation is PHYSICAL (two engines, two files) so a forgotten ``WHERE`` clause can
never leak the trusted analytics; this layer is a clearly-labelled lens, rebuildable
and disposable. The trusted rule-based keyword index stays canonical in the main DB.
"""

from __future__ import annotations
