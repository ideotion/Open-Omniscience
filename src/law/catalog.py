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
    """Pure: the Source rows a catalog registers, with provenance applied.

    GENERATED entries (the parallel-research harvest) carry their own
    ``via:legal-generated`` provenance and — maintainer ruling 2026-07-17 —
    ENABLE BY DEFAULT like curated entries: the maintainer's review of the
    committed catalog file IS the vetting gate, and the end user never has to
    hand-enable sources ("everything background and automated"). This is
    network-safe by construction: legal portals carry no rss_url so collect
    passes never fetch them, robots stays fail-closed, and the bounded
    preflight verifies each domain automatically (a dead/robots-blocked lead
    gets an honest verdict, not a fetch). Runtime-DISCOVERED candidates (the
    discovery funnel) are a DIFFERENT channel and still register disabled."""
    rows = []
    for s in catalog["sources"]:
        s = dict(s)
        if s.pop("_generated", False):
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


def _doc_language(d: dict) -> str | None:
    """The document's stated language, defensively: the curated schema uses a
    singular ``language:`` string; a generated/harvested entry may instead carry
    a ``languages:`` list (several official-language versions) — take the first
    as the primary/default. Never fabricated: absent in both -> None."""
    lang = d.get("language")
    if lang:
        return lang
    langs = d.get("languages")
    if isinstance(langs, list) and langs:
        return langs[0]
    return None


def register_documents(
    session: Session, path: Path | None = None, generated_path: Path | None = None
) -> dict[str, int]:
    """Register the curated trackable legal documents (idempotent, by jurisdiction+url).

    A generated document registers only when its producing session actually verified
    it (verification.status fetched/search-verified) — an unverified ``lead`` is a
    maintainer decision, never silently watched (see ``registrable_documents``).

    S4b (the Cambodia fix): a document already registered BEFORE ``language``/
    ``country`` existed gets them healed here too — filled in ONLY while still
    NULL on the row, so this never clobbers a value set some other way. The
    ALREADY-INGESTED corpus Article (``src/law/corpus.py``) is healed in the
    SAME pass (track_document's own steady-state "unchanged" poll skips corpus
    re-sync entirely once a document has ``latest_text``, so waiting for "the
    next track pass" would never actually reach it).

    ``generated_path`` defaults to the real committed harvest file (byte-identical
    to the pre-S4b behaviour); tests pass an isolated/nonexistent path so a crafted
    fixture catalog is never silently merged with the real ~225-source harvest."""
    docs = registrable_documents(load_legal_catalog(path, generated_path))
    existing_rows = {(row.jurisdiction, row.url): row for row in session.query(LawDocument).all()}
    created = 0
    healed = 0
    for d in docs:
        key = (d["jurisdiction"], d["url"])
        row = existing_rows.get(key)
        if row is not None:
            changed = False
            lang = _doc_language(d)
            if row.language is None and lang:
                row.language = lang
                changed = True
            if row.country is None and d.get("country"):
                row.country = d["country"]
                changed = True
            if changed:
                healed += 1
                # Self-review 2026-07-17: track_document's OWN steady-state
                # "unchanged" fast path skips corpus re-sync entirely once a
                # document already has latest_text (a deliberate perf
                # optimisation, src/law/track.py), so waiting for "the next
                # track pass" to heal the linked Article's language would in
                # practice never fire for an already-baselined, unchanged
                # document. Heal the Article directly, here, the moment the
                # document itself is healed.
                if row.language:
                    from src.database.models import Article
                    from src.law.corpus import law_canonical_url

                    art = (
                        session.query(Article)
                        .filter(Article.canonical_url == law_canonical_url(row))
                        .first()
                    )
                    if art is not None and art.language != row.language:
                        art.language = row.language
            continue
        row = LawDocument(
            jurisdiction=d["jurisdiction"],
            title=d.get("title", d["url"]),
            url=d["url"],
            official_url=d.get("official_url"),
            category=d.get("category", "legislation"),
            consolidated=bool(d.get("consolidated", False)),
            watched=True,
            # The catalog's OWN asserted language/country (never guessed) — e.g. a
            # French-language Cambodian code, so its corpus Article gets the right
            # stoplist/keyword treatment. Absent in the catalog -> None, honestly (a
            # jurisdiction alone is never used to infer a language).
            language=_doc_language(d),
            country=d.get("country"),
        )
        session.add(row)
        existing_rows[key] = row
        created += 1
    if created or healed:
        session.commit()
    return {"created": created, "total": len(docs), "healed_language": healed}
