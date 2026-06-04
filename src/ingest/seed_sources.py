"""
Seed the source list from the curated catalog so a fresh install is preconfigured.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The catalog (``configs/sources.yml``, ~1900 public-interest outlets with rich
metadata) is loaded into the database at install time. Seeding is idempotent
(matched by domain), and only *registers* sources -- nothing is fetched until an
ingest runs, and even then only through the ethical, robots-respecting fetcher.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from src.database.models import Source

# The full curated catalog shipped with the project.
DEFAULT_SOURCES_PATH = Path(__file__).resolve().parents[2] / "configs" / "sources.yml"

# YAML keys that map 1:1 to Source columns (everything except name/domain/tags,
# which are handled explicitly).
_PASSTHROUGH_FIELDS = (
    "rss_url", "rate_limit_ms", "enabled", "priority", "reliability_score",
    "language", "region", "country", "source_type", "update_frequency", "cacheability",
)


def load_sources_from_yaml(path: Path | None = None) -> list[dict]:
    """Read and validate source definitions from a YAML catalog."""
    path = path or DEFAULT_SOURCES_PATH
    data = yaml.safe_load(path.read_text()) or {}
    sources = data.get("sources", [])
    valid = []
    for s in sources:
        if isinstance(s, dict) and s.get("name") and s.get("domain"):
            valid.append(s)
    return valid


def _to_source_kwargs(s: dict) -> dict:
    """Map a catalog entry to Source constructor kwargs (tags list -> CSV)."""
    kwargs = {"name": s["name"], "domain": s["domain"]}
    tags = s.get("tags")
    if isinstance(tags, list):
        kwargs["tags"] = ",".join(str(t) for t in tags)
    elif tags:
        kwargs["tags"] = str(tags)
    for field in _PASSTHROUGH_FIELDS:
        if s.get(field) is not None:
            kwargs[field] = s[field]
    return kwargs


def seed_sources(session: Session, sources: list[dict]) -> dict[str, int]:
    """Create Source rows for any domain not already present. Idempotent.

    Deduplicates both against the existing DB and within the input list, then bulk
    inserts in a single commit (efficient for the full ~1900-entry catalog).
    """
    existing = {d for (d,) in session.query(Source.domain).all()}
    to_add = []
    skipped = 0
    for s in sources:
        domain = s["domain"]
        if domain in existing:
            skipped += 1
            continue
        existing.add(domain)
        to_add.append(Source(**_to_source_kwargs(s)))
    if to_add:
        session.add_all(to_add)
        session.commit()
    return {"created": len(to_add), "skipped": skipped, "total": len(sources)}


def seed_default_sources(session: Session, path: Path | None = None) -> dict[str, int]:
    """Convenience: load the curated catalog and seed it."""
    return seed_sources(session, load_sources_from_yaml(path))
