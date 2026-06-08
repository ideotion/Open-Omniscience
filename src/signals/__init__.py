"""
Pure, DB-free signal primitives — the shared measurement substrate of 0.06.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The thesis of the 0.06 "intelligence layer" is *one measurement engine, many
domains*. The primitives in this package are the engine. They are deliberately:

  * **pure** — they take plain inputs (sequences, counts, vectors) and return a
    result object. No primitive touches the database, the API, or the UI, so each
    is trivially unit-testable and reused by every domain (never duplicated).
  * **honest** — every result carries the ``method`` used, a ``caveat`` naming its
    limits, and the sample size ``n``. A primitive surfaces a *measurement*; it
    never renders a verdict (no "biased", no "trust score", no "true/fake").

See ``docs/FUTURE_DEVELOPMENTS.md`` (the *what & why*) and ``docs/ACTION_PLAN.md``
(the *how*). The first shipped primitive is :mod:`concentration`; ``near_dup`` /
``coordination`` and ``novelty`` are intentionally deferred (the riskiest math —
do it properly or not at all).
"""

from __future__ import annotations

from src.signals.concentration import (
    ConcentrationResult,
    concentration,
    gini,
    top_share,
)

__all__ = [
    "ConcentrationResult",
    "concentration",
    "gini",
    "top_share",
]
