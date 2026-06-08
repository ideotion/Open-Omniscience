"""
World-law corpus & change-tracking — a "Wikipedia for the law" (FUTURE_DEVELOPMENTS §5).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Aggregate the **law** — statutes, legislation, official gazettes, IP records — from
every jurisdiction that publishes it, and **track its changes over time**. Law is
public in many countries and changes by amendment, so the data *is the diff*: what
changed, when. This **reuses the Wikipedia vertical almost wholesale** (baseline
snapshot → per-change diff → honest large-change flag, all through the ethical,
robots-fail-closed fetcher) and the shared `src/signals/` engines (near-dup surfaces
**model legislation** copied across jurisdictions; correlation gives **law ↔ news**).

A worldwide catalog of **real official primary sources** (`configs/legal_sources.yml`)
is seeded by default, so a fresh install ships ready to ingest and track law globally.

Honesty (law is high-stakes): the aggregated copy is a **research mirror**, never the
authoritative source; every record links back to the official gazette; the tool tracks
and surfaces — it **never** gives legal advice or judges legality. "Public" ≠ "freely
redistributable": licences vary, are respected, and provenance is stored.
"""

from __future__ import annotations

from src.law.catalog import (
    load_legal_catalog,
    register_documents,
    seed_legal_sources,
)
from src.law.track import track_document, track_watched

__all__ = [
    "load_legal_catalog",
    "seed_legal_sources",
    "register_documents",
    "track_document",
    "track_watched",
]
