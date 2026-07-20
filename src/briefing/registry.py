"""
The card-producer registry — adding a capability = registering one producer.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Every feature in the 0.06 intelligence layer is a *card producer*: a callable
``(session) -> list[Card]``. Registering one makes it light up in the *same* Home
feed — there are no orphan endpoints. A producer must **degrade loudly, never
fabricate**: if its inputs or optional dependencies are absent it returns ``[]``
(and logs why), it never invents a card.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from src.briefing.card import Card

_LOG = logging.getLogger(__name__)

# A producer: given a DB session, return the cards it can honestly produce now.
Producer = Callable[[object], list[Card]]

_REGISTRY: list[tuple[str, Producer]] = []


def register(name: str, producer: Producer) -> None:
    """Register a card producer under a stable ``name`` (idempotent by name)."""
    global _REGISTRY
    _REGISTRY = [(n, p) for (n, p) in _REGISTRY if n != name]
    _REGISTRY.append((name, producer))


def producers() -> list[tuple[str, Producer]]:
    """The registered producers, in registration order."""
    return list(_REGISTRY)


def run_all(session, on_progress: Callable[[int, int, str], None] | None = None) -> list[Card]:
    """Run every registered producer, isolating failures.

    One misbehaving producer must never blank the whole briefing, so each is run in
    its own ``try`` and its error is logged, not raised (no silent ``pass``: the
    warning is visible).

    ``on_progress(done, total, name)`` (optional) is called after each producer so a
    background recompute can publish a determinate progress bar; it is cosmetic and is
    never allowed to break the feed.
    """
    cards: list[Card] = []
    total = len(_REGISTRY)
    for i, (name, producer) in enumerate(_REGISTRY):
        try:
            produced = producer(session) or []
        except Exception:  # noqa: BLE001 - one bad producer must not abort the feed
            _LOG.warning("briefing producer %r failed", name, exc_info=True)
            produced = []
        for card in produced:
            if isinstance(card, Card):
                cards.append(card)
        if on_progress is not None:
            try:
                on_progress(i + 1, total, name)
            except Exception:  # noqa: BLE001 - progress is cosmetic, never fatal
                pass

    # S5.1 (Leads-calibration, cross-card dedup belt): each producer already keys its
    # own cards for de-duplication (e.g. laundering's registrable-origin domain,
    # convergence/weather's country+window span, ripple's commodity) — this is the
    # belt UNDERNEATH those per-producer keys: an exact (type, key) collision across
    # the WHOLE feed is dropped, loudly logged (never silent), keeping the first
    # (registration-order) occurrence.
    seen: set[tuple[str, str]] = set()
    deduped: list[Card] = []
    dup_count = 0
    for card in cards:
        ident = (card.type, card.key)
        if ident in seen:
            dup_count += 1
            continue
        seen.add(ident)
        deduped.append(card)
    if dup_count:
        _LOG.info("run_all: dropped %d duplicate (type, key) card(s) across producers", dup_count)
    return deduped
