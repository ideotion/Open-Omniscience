"""
Seed the source list from a curated YAML so a fresh install is immediately useful.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Idempotent: sources are matched by domain, so re-seeding never creates duplicates.
This only registers sources; nothing is fetched until an ingest is triggered (and
even then only through the ethical, robots-respecting fetcher).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from src.database.models import Source

DEFAULT_SOURCES_PATH = Path(__file__).resolve().parents[2] / "configs" / "default_sources.yaml"


def load_sources_from_yaml(path: Path | None = None) -> list[dict]:
    """Read and validate source definitions from a YAML file."""
    path = path or DEFAULT_SOURCES_PATH
    data = yaml.safe_load(path.read_text()) or {}
    sources = data.get("sources", [])
    valid = []
    for s in sources:
        if not isinstance(s, dict) or not s.get("name") or not s.get("domain"):
            continue  # skip malformed entries rather than crash
        valid.append(s)
    return valid


def seed_sources(session: Session, sources: list[dict]) -> dict[str, int]:
    """Create Source rows for any domain not already present. Idempotent."""
    existing = {d for (d,) in session.query(Source.domain).all()}
    created = 0
    skipped = 0
    for s in sources:
        if s["domain"] in existing:
            skipped += 1
            continue
        session.add(Source(
            name=s["name"],
            domain=s["domain"],
            rss_url=s.get("rss_url"),
            tags=s.get("tags", ""),
            rate_limit_ms=s.get("rate_limit_ms", 2000),
            enabled=True,
            priority=s.get("priority", 2),
        ))
        existing.add(s["domain"])
        created += 1
    session.commit()
    return {"created": created, "skipped": skipped, "total": len(sources)}


def seed_default_sources(session: Session, path: Path | None = None) -> dict[str, int]:
    """Convenience: load the curated YAML and seed it."""
    return seed_sources(session, load_sources_from_yaml(path))
