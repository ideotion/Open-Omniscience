"""Personality API: a random attributed quote or verifiable fun fact.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pure local, bundled content (no network, no DB). Powers quiet UI flourishes and the
easter egg. Every quote is attributed (disputed attributions flagged); every fun fact
carries a source.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/personality", tags=["personality"])


@router.get("/random")
def random_personality(kind: str = Query("quote", pattern="^(quote|fact)$")) -> dict:
    """A random ``quote`` (attributed) or ``fact`` (sourced). ``{item: null}`` if empty."""
    from src.personality.catalog import random_item

    return {"kind": kind, "item": random_item(kind)}


@router.get("/all")
def all_personality() -> dict:
    """The whole bundled catalog (for an 'about'/credits view)."""
    from src.personality.catalog import load_catalog

    cat = load_catalog()
    return {
        "quotes": cat["quotes"],
        "fun_facts": cat["fun_facts"],
        "counts": {"quotes": len(cat["quotes"]), "fun_facts": len(cat["fun_facts"])},
    }
