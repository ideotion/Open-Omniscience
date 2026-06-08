"""
The Home briefing — surfaced intelligence as triage "cards" (the 0.06 GUI spine).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The briefing is the single surface where the app's background analysis is surfaced
for the human to judge. Each :class:`~src.briefing.card.Card` is one measurable
signal + evidence links + a caveat, sorted into an editorial bucket; producers
(``corpus → [Card]``) compose the existing real analytics, so every later capability
appears in the *same* feed. Cards are precomputed and cached (instant Home), pinned
into a :mod:`~src.briefing.draft` accumulator, and exported as evidence-carrying
Markdown — the idea→draft loop. No card renders a verdict; no composite trust score
exists (enforced in code by :func:`~src.briefing.card.assert_no_score_fields`).
"""

from __future__ import annotations

from src.briefing.card import BUCKETS, Card, assert_no_score_fields
from src.briefing.service import get_briefing, refresh_briefing

__all__ = [
    "BUCKETS",
    "Card",
    "assert_no_score_fields",
    "get_briefing",
    "refresh_briefing",
]
