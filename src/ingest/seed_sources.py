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

import json
import logging
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from src.catalog.cctld import infer_country, infer_language
from src.catalog.countries import normalize_country
from src.catalog.normalize import country_from_title
from src.database.models import Source

#: What a seed run reports. Mostly counts, plus a short list of examples for the
#: entries no install can ever register -- so the annotation cannot be `dict[str, int]`.
# Widened 2026-09-09 for the nested "reconciled" counts: a seed now reports what it
# FILLED on rows it did not create, alongside what it created and skipped.
SeedResult = dict[str, "int | dict[str, int] | list[dict[str, str | None]]"]

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
# The two catalogues the 2026-09-11 ruling admitted: sources that are NOT reporting and are
# deliberately kept OUT of configs/sources.yml, so a corpus statistic over the news catalogue
# keeps meaning what it says. Seeded by default -- a primary source no one collects is no use.
ACADEMIC_SOURCES_PATH = Path(__file__).resolve().parents[2] / "configs" / "academic_sources.yml"
OFFICIAL_SOURCES_PATH = Path(__file__).resolve().parents[2] / "configs" / "official_sources.yml"

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

#: How many kept operator edits a correction sync names. The COUNT beside them is exact;
#: the examples are there so the log says WHICH rows diverged, not merely how many.
_CONFLICT_EXAMPLES = 8

_LOGGER = logging.getLogger(__name__)


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


# THE FIELDS THE CATALOGUE OWNS, as opposed to the ones the OPERATOR owns. The split is the
# whole policy of :func:`sync_catalogue_corrections` and it is deliberately conservative.
#
# OWNED HERE: facts about the SOURCE that the shipped catalogue is the authority on, and that
# an operator edits rarely if ever. A fixed feed URL is the case that motivated this -- of the
# 22,045 candidates Stage A judged, 2,622 had an unparseable feed and 669 a stale one, and the
# same rot reaches rows we already ship.
#
# NOT OWNED, and left alone forever: ``enabled``, ``priority``, ``rate_limit_ms``,
# ``reliability_score`` -- the operator's own knobs, which the UI exists to set.
#
# ``tags`` IS DELIBERATELY OUT of v1, and the reason is not timidity. It is a SET with FOUR
# writers -- the catalogue, the seed's ``via:`` provenance marker, ``ensure_channel_tags``, and
# the operator -- so a replace would silently drop the other three, while a union can never
# express a REMOVAL, which is precisely what correcting a wrong tag means. A set needs its own
# merge policy and its own ruling; a half-considered one here would lose provenance quietly.
CATALOGUE_OWNED_FIELDS: tuple[str, ...] = (
    "rss_url", "name", "country", "language", "region", "source_type",
)


def _norm(value: object) -> str | None:
    """One comparison form, so ``""`` and ``None`` and ``" es "`` cannot read as three values."""
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _baseline_of(row: Source) -> dict | None:
    """What the catalogue last shipped for this row, or None if it has never been recorded."""
    raw = getattr(row, "catalog_baseline", None)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None                      # unreadable -> treat as unknown, never as "unedited"
    return parsed if isinstance(parsed, dict) else None


def sync_catalogue_corrections(session: Session, sources: list[dict]) -> dict:
    """Push CORRECTIONS from the shipped catalogue onto rows that already exist -- a THREE-WAY
    merge, so a fix reaches an untouched row and can never overwrite the operator's own edit.

    THE GAP THIS CLOSES, and why the existing mechanism could not.
    :func:`reconcile_source_metadata` fills a field that is EMPTY and refuses to touch anything
    else, which is the right rule for a gap and the wrong one for a correction: when the
    catalogue fixes a dead feed URL, a wrong country or a name that fabricates an origin, every
    install that already holds that row keeps the broken value forever, and the only remedy is
    an export/import. Measured before this shipped: a row whose ``rss_url`` the catalogue had
    corrected still served the stale URL after a re-seed.

    WHY NOT SIMPLY OVERWRITE. Because the operator can edit a source in the UI, and a re-seed
    silently reverting that is "a data-loss bug wearing a maintenance task's clothes" -- the
    words reconcile_source_metadata already uses about itself. So this needs to distinguish
    "the value we shipped, untouched" from "the value the operator chose", and a two-way
    comparison cannot: both are simply "not equal to the new catalogue value".

    THE THIRD SIDE is ``Source.catalog_baseline``: a small JSON record of what the catalogue
    last shipped for this row. For each owned field there are then three values -- what the
    catalogue ships NOW, what it shipped THEN (the baseline), and what the row holds LIVE:

      * ships now == shipped then  -> upstream changed nothing. Skipped, so a steady state
        costs one comparison and no write.
      * live == shipped then       -> the operator never touched it, so the correction is
        theirs to receive. APPLIED.
      * otherwise                  -> the operator's value differs from what we gave them.
        KEPT, and REPORTED by domain and field. Never overwritten, never silently dropped.

    A LIVE VALUE THAT IS EMPTY IS A GAP, NOT AN EDIT, and is skipped here so the two mechanisms
    cannot fight over one field: filling empties belongs to reconcile_source_metadata, and
    without this rule a freshly-filled field would read as an operator edit on the same boot.

    THE BASELINE ADVANCES EVEN WHEN THE EDIT IS KEPT. A conflict is therefore reported ONCE,
    at the boot where it arises, rather than nagging on every start for the life of the
    install -- and the operator's value stands, which is the outcome that matters.

    A ROW WITH NO BASELINE ADOPTS THE CURRENT CATALOGUE AND CHANGES NOTHING. Every row that
    predates this column is in that position, and we cannot tell an operator's edit from a
    shipped value without a baseline to compare against. So the first boot after the upgrade
    RECORDS where things stand and moves on: corrections made from then on flow, and nothing
    an operator set is touched on the strength of a guess. The cost is stated plainly -- a
    correction the catalogue made BEFORE this shipped will not reach an existing row.
    """
    from src.database.models import Source

    by_domain: dict[str, dict] = {}
    for s in sources:
        domain = (s.get("domain") or "").strip().lower()
        if not domain or not (s.get("name") or "").strip():
            continue
        by_domain.setdefault(domain, s)   # first-entry-wins, as seed_sources and reconcile do
    empty = {"checked": 0, "applied": 0, "kept": 0, "adopted": 0, "conflicts": []}
    if not by_domain:
        return empty

    rows = session.query(Source).filter(Source.domain.in_(list(by_domain))).all()
    applied = adopted = 0
    conflicts: list[dict] = []
    dirty = False
    for row in rows:
        entry = by_domain.get((row.domain or "").strip().lower())
        if entry is None:
            continue
        computed = _to_source_kwargs(entry)
        shipped = {f: _norm(computed.get(f)) for f in CATALOGUE_OWNED_FIELDS}
        base = _baseline_of(row)
        if base is None:
            row.catalog_baseline = json.dumps(shipped, sort_keys=True)
            adopted += 1
            dirty = True
            continue
        touched = False
        for field in CATALOGUE_OWNED_FIELDS:
            now, then = shipped[field], _norm(base.get(field))
            if now == then:
                continue                            # upstream unchanged
            live = _norm(getattr(row, field, None))
            if live is None:
                continue                            # a gap -- reconcile_source_metadata owns it
            touched = True
            if live == then:
                setattr(row, field, computed.get(field))
                applied += 1
            else:
                conflicts.append(
                    {"domain": row.domain, "field": field, "kept": live, "catalogue": now}
                )
        if touched:
            row.catalog_baseline = json.dumps(shipped, sort_keys=True)
            dirty = True
    if dirty:
        session.commit()
    if applied or conflicts:
        _LOGGER.info(
            "catalogue corrections: %d applied, %d kept as operator edits", applied, len(conflicts)
        )
    return {
        "checked": len(rows), "applied": applied, "kept": len(conflicts),
        "adopted": adopted, "conflicts": conflicts[:_CONFLICT_EXAMPLES],
    }


def reconcile_source_metadata(session: Session, sources: list[dict]) -> dict:
    """Fill EMPTY catalogue metadata on sources that already exist. Never overwrite.

    THE GAP THIS CLOSES. ``seed_sources`` skips a domain it already holds and never
    looks at the row again, so a source registered before the catalogue knew its
    country -- or before the ccTLD/title fallbacks existed -- keeps an empty field
    forever, however many times the catalogue is re-seeded. The metadata is only used
    for description and filtering (never a score), and an absent country is the reason
    a source falls into "unlocated" on the coverage map.

    THE RULE IS NULL-ONLY, and it is the whole safety argument: a field is written only
    when the LOCAL value is empty AND the catalogue computes a value. A non-empty local
    value is left alone whatever put it there -- the operator may have set it by hand,
    and a re-seed silently reverting that would be a data-loss bug wearing a maintenance
    task's clothes. That also makes this idempotent: a second run fills nothing.

    TAGS DROP THEIR PROVENANCE MARKER, deliberately. ``_to_source_kwargs`` appends a
    ``via:<origin>`` tag recording where a row CAME FROM. Reconciling an existing row
    did not create it, so copying that marker across would assert an origin this row
    may not have -- a hand-registered source would come out claiming it arrived via a
    catalogue. The descriptive tags are facts about the source and are filled; the
    provenance tag is a fact about the row and is not.

    Derivation is `_to_source_kwargs`, the same function the create path uses, so the
    explicit-field -> title-suffix -> ccTLD ladder can never become a second, divergent
    implementation.
    """
    from src.database.models import Source

    by_domain: dict[str, dict] = {}
    for s in sources:
        domain = (s.get("domain") or "").strip().lower()
        name = (s.get("name") or "").strip()
        if not domain or not name:
            continue
        # First-entry-wins, the SAME rule seed_sources uses for shadowing, so the two
        # can never disagree about which sibling a domain's metadata comes from.
        by_domain.setdefault(domain, s)
    if not by_domain:
        return {"checked": 0, "country_filled": 0, "language_filled": 0, "tags_filled": 0}

    rows = session.query(Source).filter(Source.domain.in_(list(by_domain))).all()
    filled = {"country": 0, "language": 0, "tags": 0}
    for row in rows:
        entry = by_domain.get((row.domain or "").strip().lower())
        if entry is None:
            continue
        computed = _to_source_kwargs(entry)
        for field in ("country", "language", "tags"):
            if getattr(row, field, None):
                continue                       # already carries a value -- never touched
            value = computed.get(field)
            if field == "tags" and value:
                value = ",".join(t for t in str(value).split(",") if not t.startswith("via:"))
            if not value:
                continue
            setattr(row, field, value)
            filled[field] += 1
    if any(filled.values()):
        session.commit()
    return {
        "checked": len(rows),
        "country_filled": filled["country"],
        "language_filled": filled["language"],
        "tags_filled": filled["tags"],
    }


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
    # An already-registered domain used to end the story: skipped, never re-read. The
    # catalogue keeps LEARNING (new explicit countries, new tags, and the title/ccTLD
    # fallbacks that did not exist when older rows were made), and none of it reached a
    # row that already existed. NULL-only, so a re-seed can add what is missing and can
    # never revert what an operator set.
    reconciled = reconcile_source_metadata(session, sources)
    # ...and then the other half: a field that is NOT empty but that the catalogue has since
    # CORRECTED. reconcile fills gaps and refuses to touch anything else; this pushes the fix
    # onto rows the operator never edited, and reports the ones they did. Runs AFTER, so a
    # field reconcile just filled reads as a gap rather than as an edit (sync skips empties).
    corrections = sync_catalogue_corrections(session, sources)
    return {
        "created": len(to_add),
        "reconciled": reconciled,
        "corrections": corrections,
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
        # Scholarly journals and official/primary-source bodies (2026-09-11 ruling), each in its
        # own catalogue with its own provenance so every surface can lens them apart from news.
        for extra, prov in ((ACADEMIC_SOURCES_PATH, "academic"), (OFFICIAL_SOURCES_PATH, "official")):
            if extra.exists():
                rows = load_sources_from_yaml(extra)
                for s in rows:
                    s["_provenance"] = prov
                sources = sources + rows
    return seed_sources(session, sources)
