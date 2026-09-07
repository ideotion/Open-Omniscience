"""
Seed the source list from the curated catalog so a fresh install is preconfigured.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The catalog (``configs/sources.yml``, ~3,200 public-interest outlets with rich
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
from src.catalog.normalize import country_from_title
from src.database.models import Source

#: What a seed run reports. Mostly counts, plus a short list of examples for the
#: entries no install can ever register -- so the annotation cannot be `dict[str, int]`.
SeedResult = dict[str, "int | list[dict[str, str | None]]"]

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
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = data.get("sources", [])
    valid = []
    for s in sources:
        if isinstance(s, dict) and s.get("name") and s.get("domain"):
            valid.append(s)
    return valid


def _to_source_kwargs(s: dict) -> dict:
    """Map a catalog entry to Source constructor kwargs (tags list -> CSV).

    Also (a) records *provenance* as a ``via:<origin>`` tag when known, and
    (b) backfills a missing ``country`` from the catalog's explicit
    ``Name (Country)`` title convention, then from the domain's ccTLD, and a
    missing ``language`` from the ccTLD — so the catalogue's geographic/linguistic
    skew is measurable (conservative — see ``src/catalog/normalize.py`` and
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
    # Honour the explicit "Name (Country)" title convention before the ccTLD:
    # a human-authored origin marker outranks a guess from the domain suffix.
    if not kwargs.get("country"):
        from_title = country_from_title(s.get("name"))
        if from_title:
            kwargs["country"] = from_title
    if not kwargs.get("country"):
        c = infer_country(s["domain"])
        if c:
            kwargs["country"] = c
    if not kwargs.get("language"):
        lang = infer_language(s["domain"])
        if lang:
            kwargs["language"] = lang
    return kwargs


#: How many shadowed entries a seed result carries as examples. A handful, so the
#: report names the loss without dumping it; the COUNT beside them is exact.
_SHADOW_EXAMPLES = 8


def catalog_domain_collisions(sources: list[dict]) -> dict[str, list[dict]]:
    """Catalog entries a domain-keyed seeder can never register: ``{domain: [shadowed]}``.

    ``Source.domain`` is UNIQUE, so one domain holds one feed -- and the catalogue
    describes several distinct feeds per registrable domain. Measured 2026-09-07 on
    ``configs/sources.yml``: 54 domains carry more than one entry and 227 of 3,429 are
    shadowed by an earlier sibling. Measured on what ``seed_default_sources`` really
    builds -- five catalogues concatenated -- 299 domains and **475 of 3,870**, which
    is the figure an install reports and the only one that counts a CROSS-catalogue
    collision.

    They are NOT redundant rows, and the losses come in two shapes:

    * **Language services.** ``bbc.com`` carries 31 entries and the 30 that lose are
      BBC Arabic, Hausa, Swahili, Persian and the rest; ``dw.com`` and ``rfi.fr`` the
      same. Across the curated file, 75 shadowed entries declare a language and
      declare a DIFFERENT one than the sibling that survives.
    * **Editorial metadata.** 220 of the cross-catalogue losses are
      ``sources_spectrum.yml`` losing to ``sources.yml``, and 192 shadowed entries
      carry a ``lean-*`` tag the survivor lacks -- ``cnn.com`` loses
      ``lean-center-left``, ``dailymail.co.uk`` loses ``lean-right``. The
      political-lean vocabulary reaches ``Source.tags`` for barely any outlet that
      has it.

    That makes the obvious repair the wrong one: DELETING the shadowed entries would
    delete exactly the multilingual breadth the language-equilibrium lever exists to
    balance, and the editorial dimension the spectrum catalogue exists for. Recovering
    them needs a decision about source identity (today a domain; the alternative is the
    feed) which reaches the alias-aware dedup, the restore-merge's domain joins, the
    qualification overlay and the citations tally -- a maintainer ruling, recorded
    rather than taken here. Note what does NOT work: the language services do not live
    on distinct hosts (all 31 BBC entries share ``feeds.bbci.co.uk``, differing only in
    the feed PATH), so splitting them into separate domain rows is not available.

    NOT EVERY COLLISION IS A DEFECT. ``seed_legal_sources`` routes through the same
    seeder, and the legal catalogue deliberately carries one host as two rows when it
    publishes both a codes portal and a gazette (ruled 2026-07-17: "registration must
    collapse them"). Those 14 are a designed collapse counted by the same field as an
    accidental one -- the count is exact either way, the INTERPRETATION differs by
    catalogue.

    This function exists so the loss is COUNTED and inspectable instead of silent.

    Pure: takes the loaded catalogue, touches no database. The winner is the FIRST entry
    for a domain, which is the order ``seed_sources`` itself inserts in.
    """
    seen: set[str] = set()
    shadowed: dict[str, list[dict]] = {}
    for s in sources:
        domain = str(s.get("domain") or "")
        if not domain:
            continue
        if domain in seen:
            shadowed.setdefault(domain, []).append(s)
        else:
            seen.add(domain)
    return shadowed


def seed_sources(session: Session, sources: list[dict]) -> SeedResult:
    """Create Source rows for any domain not already present. Idempotent.

    Deduplicates both against the existing DB and within the input list, then bulk
    inserts in a single commit (efficient for the full ~3,200-entry catalog).

    THE SKIP REASONS ARE REPORTED APART (2026-09-07). ``skipped`` used to be one
    counter over two facts that mean opposite things: a domain already in the database
    is an idempotent re-run working correctly, while a domain claimed by an EARLIER
    entry of this same input is a catalogue entry that will never be registered on any
    install. Conflated, the second was invisible -- 475 entries on a real boot, 227 of
    them inside ``configs/sources.yml`` alone (see :func:`catalog_domain_collisions`
    for what they are and why deleting them is the wrong repair). ``skipped`` keeps its
    old value (now the sum of all three reasons) so every existing caller reads
    unchanged.
    """
    existing = {d for (d,) in session.query(Source.domain).all()}
    claimed: set[str] = set()
    to_add = []
    skipped_existing = 0
    skipped_malformed = 0
    shadowed: list[dict] = []
    for s in sources:
        domain = s.get("domain") or ""
        if not domain:
            # The same rule `catalog_domain_collisions` uses, for the same reason: one
            # rule, two implementations, and they must not answer differently. Reading
            # `s["domain"]` raised on an absent key and, worse, an entry with an empty
            # domain was counted as SHADOWED and then built into a `Source(domain=None)`
            # against a NOT NULL column -- an IntegrityError at commit that would take
            # the whole batch with it. Unreachable through either shipped loader (both
            # filter on a truthy name and domain), which is exactly why it needed
            # pinning rather than leaving to chance.
            skipped_malformed += 1
            continue
        # Shadowing is a property of the CATALOGUE, not of this run: an entry an
        # earlier sibling of the same input already claims can never be registered
        # on any install, whether or not the database happens to hold that domain
        # yet. Checked first, and by the same first-wins rule
        # `catalog_domain_collisions` uses, so a re-seed reports the same loss a
        # first seed did rather than quietly reclassifying it as idempotent.
        if domain in claimed:
            shadowed.append(s)
            continue
        claimed.add(domain)
        if domain in existing:
            skipped_existing += 1
            continue
        existing.add(domain)
        to_add.append(Source(**_to_source_kwargs(s)))
    if to_add:
        session.add_all(to_add)
        session.commit()
    return {
        "created": len(to_add),
        "skipped": skipped_existing + len(shadowed) + skipped_malformed,
        "total": len(sources),
        "skipped_existing": skipped_existing,
        "skipped_malformed": skipped_malformed,
        "shadowed": len(shadowed),
        "shadowed_examples": [
            {"name": s.get("name"), "domain": s.get("domain")}
            for s in shadowed[:_SHADOW_EXAMPLES]
        ],
    }


def seed_default_sources(session: Session, path: Path | None = None) -> SeedResult:
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
