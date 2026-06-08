"""
Source integrity & anti-amplification — §6, the keystone that arranges the rest.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This package answers "*whose signal counts?*" **without becoming an arbiter of
truth**. It lives entirely in the allowed half of FUTURE_DEVELOPMENTS §6 —
**(B) authenticity / structure signals** (is this source coordinated? does it
originate or only echo? is its output within human capacity? is it transparent about
who runs it?) — and is **forbidden** the disallowed half (a single automated
veracity/quality "trust score").

Two pieces, both *user-guided* (propose → the user disposes):

  * :mod:`profile` — a per-source panel of *measured* signals, **no composite score**.
    The user weights which dimensions matter into *their* view; off by default,
    reversible, with the raw equal view always one click away.
  * :mod:`collapse` — the actor graph (from :mod:`src.signals.coordination`) plus the
    user's *applied* collapse decisions. Anti-amplification is **never** a silent
    transform: the app proposes a collapse with its evidence; only the user's explicit
    action merges a coordinated flood into one actor; every applied collapse stays
    flagged and expandable, and toggling it off reproduces the raw equal counts exactly.
"""

from __future__ import annotations

from src.integrity.actors import actor_signature, corpus_actors
from src.integrity.collapse import (
    actor_weighted_source_counts,
    apply_collapse,
    collapse_status,
    is_applied,
    revert_collapse,
)
from src.integrity.profile import source_profile

__all__ = [
    "corpus_actors",
    "actor_signature",
    "apply_collapse",
    "revert_collapse",
    "is_applied",
    "collapse_status",
    "actor_weighted_source_counts",
    "source_profile",
]
