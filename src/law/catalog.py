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
# The parallel-internet-session enrichment file (maintainer-ruled 2026-07-17; contract +
# session prompt in docs/design/LAW_SOURCES_ACQUISITION_2026-07-17.md). Vetted before commit
# (scripts/validate_legal_catalog.py + PR review); merged CURATED-WINS below, so a generated
# row can extend the catalog but never override a hand-curated entry.
GENERATED_CATALOG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "legal_sources_generated.yml"
)


def _read_catalog_yaml(path: Path) -> dict:
    if not path.exists():
        return {"sources": [], "documents": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        "sources": [
            s
            for s in data.get("sources", [])
            if isinstance(s, dict) and s.get("name") and s.get("domain")
        ],
        "documents": [
            d
            for d in data.get("documents", [])
            if isinstance(d, dict) and d.get("url") and d.get("jurisdiction")
        ],
    }


def load_legal_catalog(path: Path | None = None, generated_path: Path | None = None) -> dict:
    """Return ``{"sources": [...], "documents": [...]}`` — the curated catalog merged with
    the (optional) generated enrichment file, CURATED WINS on a source ``domain`` or a
    document ``(jurisdiction, url)`` collision. No generated file → byte-identical to the
    curated-only behavior. Extra metadata fields on generated entries (languages,
    enumeration_url, official_count, structured, verification…) ride along untouched for
    downstream consumers (adapters, the coverage diagnostic).

    A generated row is marked ``_generated: True`` so registration-time consumers can
    apply the review-before-enable posture (seed DISABLED, skip unverified leads) without
    a second file read; planning consumers can ignore the marker."""
    merged = _read_catalog_yaml(path or LEGAL_CATALOG_PATH)
    gen = _read_catalog_yaml(generated_path or GENERATED_CATALOG_PATH)
    if gen["sources"]:
        seen = {s["domain"] for s in merged["sources"]}
        for s in gen["sources"]:
            if s["domain"] not in seen:
                s["_generated"] = True
                merged["sources"].append(s)
    if gen["documents"]:
        seen_docs = {(d["jurisdiction"], d["url"]) for d in merged["documents"]}
        for d in gen["documents"]:
            if (d["jurisdiction"], d["url"]) not in seen_docs:
                d["_generated"] = True
                merged["documents"].append(d)
    return merged


def registration_source_rows(catalog: dict) -> list[dict]:
    """Pure: the Source rows a catalog registers, with the enable posture applied.

    Curated entries keep their catalog-stated posture. GENERATED entries (the
    parallel-research harvest) always seed ``enabled=False`` with their own
    ``via:legal-generated`` provenance — the review-before-enable ruling: a
    research-harvested source never auto-enables (several are robots-blocked;
    enabling is a maintainer action or the future promotion frontier)."""
    rows = []
    for s in catalog["sources"]:
        s = dict(s)
        if s.pop("_generated", False):
            s["enabled"] = False
            s.setdefault("_provenance", "legal-generated")
        else:
            s.setdefault("_provenance", "legal")
        rows.append(s)
    return rows


def registrable_documents(catalog: dict) -> list[dict]:
    """Pure: the documents a catalog may register as watched.

    A generated document qualifies only when its producing session actually
    verified it (verification.status fetched/search-verified) — an unverified
    ``lead`` is a maintainer decision, never silently watched."""
    out = []
    for d in catalog["documents"]:
        d = dict(d)
        if d.pop("_generated", False):
            status = (d.get("verification") or {}).get("status")
            if status not in ("fetched", "search-verified"):
                continue
        out.append(d)
    return out


def seed_legal_sources(session: Session, path: Path | None = None) -> dict[str, int]:
    """Seed the legal/IP portals as Source rows (idempotent, by domain)."""
    from src.ingest.seed_sources import seed_sources

    return seed_sources(session, registration_source_rows(load_legal_catalog(path)))


def register_documents(session: Session, path: Path | None = None) -> dict[str, int]:
    """Register the curated trackable legal documents (idempotent, by jurisdiction+url).

    A generated document registers only when its producing session actually verified
    it (verification.status fetched/search-verified) — an unverified ``lead`` is a
    maintainer decision, never silently watched (see ``registrable_documents``)."""
    docs = registrable_documents(load_legal_catalog(path))
    existing = {(j, u) for (j, u) in session.query(LawDocument.jurisdiction, LawDocument.url).all()}
    created = 0
    for d in docs:
        key = (d["jurisdiction"], d["url"])
        if key in existing:
            continue
        existing.add(key)
        session.add(
            LawDocument(
                jurisdiction=d["jurisdiction"],
                title=d.get("title", d["url"]),
                url=d["url"],
                official_url=d.get("official_url"),
                category=d.get("category", "legislation"),
                consolidated=bool(d.get("consolidated", False)),
                watched=True,
            )
        )
        created += 1
    if created:
        session.commit()
    return {"created": created, "total": len(docs)}
