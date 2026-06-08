"""
Load and seed the worldwide law & IP catalog.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``sources:`` from ``configs/legal_sources.yml`` are seeded as ordinary ingestible /
searchable :class:`Source` rows (``source_type`` legal/ip), so worldwide legal portals
flow through the *same* ethical pipeline as news. ``documents:`` are registered as
tracked :class:`LawDocument` rows (baseline → diff → flag). Both are idempotent and seed
on first run, so the vertical is **on by default** without fabricating anything: a record
appears only for a real official URL, and text is only ever stored from a real fetch.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from src.database.models import LawDocument

LEGAL_CATALOG_PATH = Path(__file__).resolve().parents[2] / "configs" / "legal_sources.yml"


def load_legal_catalog(path: Path | None = None) -> dict:
    """Return ``{"sources": [...], "documents": [...]}`` from the catalog YAML."""
    path = path or LEGAL_CATALOG_PATH
    if not path.exists():
        return {"sources": [], "documents": []}
    data = yaml.safe_load(path.read_text()) or {}
    return {
        "sources": [s for s in data.get("sources", []) if isinstance(s, dict) and s.get("name") and s.get("domain")],
        "documents": [d for d in data.get("documents", []) if isinstance(d, dict) and d.get("url") and d.get("jurisdiction")],
    }


def seed_legal_sources(session: Session, path: Path | None = None) -> dict[str, int]:
    """Seed the legal/IP portals as Source rows (idempotent, by domain)."""
    from src.ingest.seed_sources import seed_sources

    catalog = load_legal_catalog(path)
    for s in catalog["sources"]:
        s.setdefault("_provenance", "legal")
    return seed_sources(session, catalog["sources"])


def register_documents(session: Session, path: Path | None = None) -> dict[str, int]:
    """Register the curated trackable legal documents (idempotent, by jurisdiction+url)."""
    catalog = load_legal_catalog(path)
    existing = {(j, u) for (j, u) in session.query(LawDocument.jurisdiction, LawDocument.url).all()}
    created = 0
    for d in catalog["documents"]:
        key = (d["jurisdiction"], d["url"])
        if key in existing:
            continue
        existing.add(key)
        session.add(LawDocument(
            jurisdiction=d["jurisdiction"],
            title=d.get("title", d["url"]),
            url=d["url"],
            official_url=d.get("official_url"),
            category=d.get("category", "legislation"),
            consolidated=bool(d.get("consolidated", False)),
            watched=True,
        ))
        created += 1
    if created:
        session.commit()
    return {"created": created, "total": len(catalog["documents"])}
