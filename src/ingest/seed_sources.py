"""
Seed the source list from the curated catalog so a fresh install is preconfigured.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The catalog (``configs/sources.yml``, ~1900 public-interest outlets with rich
metadata) is loaded into the database at install time, alongside the worldwide
markets catalog, a curated political-spectrum catalog (``sources_spectrum.yml``),
and -- once a maintainer generates it -- the Wikidata world catalog
(``world_news_sources.yml``, the path to tens of thousands of sources). Seeding is
idempotent (matched by domain), and only *registers* sources -- nothing is fetched
until an ingest runs, and even then only through the ethical, robots-respecting
fetcher.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from src.catalog.cctld import infer_country, infer_language
from src.catalog.countries import normalize_country
from src.database.models import Source

# The full curated catalog shipped with the project.
DEFAULT_SOURCES_PATH = Path(__file__).resolve().parents[2] / "configs" / "sources.yml"

# Curated worldwide markets catalog (stock/commodity exchanges, price/data sources,
# financial publishers). Seeded alongside the news catalog so the app ships ready to
# ingest market coverage. Dedup-by-domain means an outlet already in the news
# catalog is not duplicated.
MARKETS_SOURCES_PATH = Path(__file__).resolve().parents[2] / "configs" / "markets_sources.yml"

# Optional, generator-produced worldwide catalog (news organisations + official
# institutions by country, from Wikidata). Absent until a maintainer runs
# scripts/build_world_news_catalog.py; seeded automatically once present.
WORLD_SOURCES_PATH = Path(__file__).resolve().parents[2] / "configs" / "world_news_sources.yml"

# Curated political-spectrum catalog: real, well-known outlets hand-tagged by
# leaning (lean-left … lean-right) and ownership (public-broadcaster, state-media,
# wire-agency) with topic keywords -- the editorial dimension Wikidata can't give.
SPECTRUM_SOURCES_PATH = Path(__file__).resolve().parents[2] / "configs" / "sources_spectrum.yml"

# Curated worldwide LAW & IP catalog: official legislation portals, gazettes and IP
# offices across every region (source_type legal/ip). The trackable consolidated-law
# *documents* in the same file are registered separately (src/law/catalog.py).
LEGAL_SOURCES_PATH = Path(__file__).resolve().parents[2] / "configs" / "legal_sources.yml"

# YAML keys that map 1:1 to Source columns (everything except name/domain/tags,
# which are handled explicitly).
_PASSTHROUGH_FIELDS = (
    "rss_url",
    "rate_limit_ms",
    "enabled",
    "priority",
    "reliability_score",
    "language",
    "region",
    "country",
    "source_type",
    "update_frequency",
    "cacheability",
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
    """Map a catalog entry to Source constructor kwargs (tags list -> CSV).

    Also (a) records *provenance* as a ``via:<origin>`` tag when known, and
    (b) backfills missing ``country``/``language`` from the domain's ccTLD so the
    catalogue's geographic/linguistic skew is measurable (conservative — see
    ``src/catalog/cctld.py``; never overrides an explicit value).
    """
    kwargs = {"name": s["name"], "domain": s["domain"]}
    tags = s.get("tags")
    tag_list = [str(t) for t in tags] if isinstance(tags, list) else ([str(tags)] if tags else [])
    prov = s.get("_provenance")
    if prov:
        tag_list.append(f"via:{prov}")
    if tag_list:
        kwargs["tags"] = ",".join(tag_list)
    for field in _PASSTHROUGH_FIELDS:
        if s.get(field) is not None:
            kwargs[field] = s[field]
    # Canonicalise to lowercase ISO-2 (one conversion layer, 0.09): full names,
    # slugs and any-case codes all normalise; an unrecognisable value is dropped
    # (never stored as junk) so the ccTLD fallback gets its chance instead.
    if kwargs.get("country"):
        kwargs["country"] = normalize_country(str(kwargs["country"]))
        if kwargs["country"] is None:
            del kwargs["country"]
    if not kwargs.get("country"):
        c = infer_country(s["domain"])
        if c:
            kwargs["country"] = c
    if not kwargs.get("language"):
        lang = infer_language(s["domain"])
        if lang:
            kwargs["language"] = lang
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
    """Convenience: load the curated catalog(s) and seed them.

    With the default catalog (``path is None``) the worldwide markets catalog and,
    when present, the generated world news+institutions catalog are appended too,
    so a fresh install ships ready to ingest market and global political coverage.
    An explicit ``path`` seeds only that file (used by tests). Dedup-by-domain
    handles any overlap across the catalogs.
    """
    sources = load_sources_from_yaml(path)
    if path is None:
        for s in sources:
            s.setdefault("_provenance", "curated")
        for extra, prov in (
            (MARKETS_SOURCES_PATH, "markets"),
            (SPECTRUM_SOURCES_PATH, "spectrum"),
            (WORLD_SOURCES_PATH, "wikidata"),
        ):
            if extra.exists():
                extra_sources = load_sources_from_yaml(extra)
                for s in extra_sources:
                    s["_provenance"] = prov
                sources = sources + extra_sources
        # Worldwide law & IP official portals (the §5 vertical), seeded by default so a
        # fresh install can ingest and search legal primary sources globally.
        if LEGAL_SOURCES_PATH.exists():
            legal = load_sources_from_yaml(LEGAL_SOURCES_PATH)
            for s in legal:
                s["_provenance"] = "legal"
            sources = sources + legal
    return seed_sources(session, sources)
