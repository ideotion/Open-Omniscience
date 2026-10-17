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
from typing import Any

import yaml
from sqlalchemy.orm import Session

from src.catalog.cctld import infer_country, infer_language
from src.catalog.countries import normalize_country
from src.catalog.normalize import country_from_title
from src.database.feed_key import feed_key
from src.database.models import Source
from src.database.source_identity import composite_key_active
from src.ingest.seed_plan import (
    entry_key,
    entry_tags,
    exclusive_family,
    plan_registration,
    split_tags,
)

#: What a seed run reports. Mostly counts, plus a short list of examples for the
#: entries no install can ever register -- so the annotation cannot be `dict[str, int]`.
# Widened 2026-09-09 for the nested "reconciled" counts: a seed now reports what it
# FILLED on rows it did not create, alongside what it created and skipped.
SeedResult = dict[str, Any]

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


# libyaml when the wheel carries it, the pure-Python parser when it does not. SAFE either
# way -- this is a speed choice, never a safety one. Measured 2026-09-11 on
# configs/sources.yml (5,580 entries): 3,148 ms pure-Python vs 411 ms with libyaml, and
# boot parses seven catalogues, so it is seconds off every start.
_SAFE_YAML_LOADERS = tuple(
    c for c in (getattr(yaml, "CSafeLoader", None), yaml.SafeLoader) if c is not None
)
_YAML_LOADER = _SAFE_YAML_LOADERS[0]


def _load_safe_yaml(text: str):
    """``yaml.safe_load``'s own body, with the C loader when it is available.

    NOT the generic loader entry point with a ``Loader=`` argument:
    ``test_no_dangerous_eval_or_deserialization_sinks``
    bans that token outright, and rightly -- a rule a reviewer has to read an argument to
    apply is a rule that gets misapplied. This is not a way around that rule, it is a
    stricter reading of it: PyYAML exposes no C-loader variant of ``safe_load``, so the
    loader is fixed HERE, at module level, as one of the two safe classes and nothing
    else, with no per-call-site ``Loader=`` argument for a later edit to get wrong. Pinned
    by ``test_seed_sources.py``, which asserts the class AND feeds it a
    ``!!python/object/apply`` payload to prove the refusal rather than assume it.
    """
    loader = _YAML_LOADER(text)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def load_sources_from_yaml(path: Path | None = None) -> list[dict]:
    """Read and validate source definitions from a YAML catalog."""
    path = path or DEFAULT_SOURCES_PATH
    data = _load_safe_yaml(path.read_text(encoding="utf-8")) or {}
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


def _usable(sources: list[dict]) -> list[dict]:
    """The entries that can be a source: a name AND a domain (what both loaders already require)."""
    return [x for x in sources if (x.get("domain") or "").strip() and (x.get("name") or "").strip()]


def _db_rows_by_domain(session: Session) -> dict[str, list[Source]]:
    """Every registered source, grouped by its (lower-cased) domain, oldest first."""
    out: dict[str, list[Source]] = {}
    for row in session.query(Source).order_by(Source.id):
        out.setdefault((row.domain or "").strip().lower(), []).append(row)
    return out


def _row_catalogue(row: Source) -> str | None:
    """The catalogue a row was made from: its ``via:`` provenance tag, or None for a row that carries none."""
    return next((t[4:] for t in split_tags(row.tags) if t.startswith("via:")), None)


def _same_catalogue(row: Source, entry: dict) -> bool:
    """False only when BOTH name a catalogue and they differ. A seed call sees part of the catalogue (the legal seed hands
    over only the legal entries), so every row another catalogue made is a "leftover" in it: a name match with such a row is
    two catalogues describing one outlet, never a corrected feed, and pairing them made the two seeds take one row back and
    forth on every boot (Opus read of the J3 fold, F1). No tag or no provenance behaves as before."""
    owner, prov = _row_catalogue(row), entry.get("_provenance")
    return not (owner and prov and owner != prov)


def paired_rows(session: Session, sources: list[dict], *, plan=None, rows_by_domain=None):
    """Which registered row each catalogue ROW entry is, and which entries have none yet.

    Returns ``(pairs, todo, plan, rows_by_domain)``: ``pairs`` is ``[(Source, entry)]`` for the entries a row already
    holds, ``todo`` the entries that need one. An entry belongs to the row with its ``(domain, feed_key)``; failing
    that, and ONLY when the domain has exactly one entry and exactly one row, they are the same source -- the case a
    corrected feed URL is (the catalogue changed the feed, the row still carries the old one), which the
    domain-keyed seeder applied and which must not turn into a second row. The same one-to-one fallback the restore
    merge uses (``src.backup.merge._same_source``), so two paths can never disagree about whether two rows are one.
    """
    plan = plan if plan is not None else plan_registration(_usable(sources))
    rows_by_domain = rows_by_domain if rows_by_domain is not None else _db_rows_by_domain(session)
    entries_by_domain: dict[str, list[dict]] = {}
    for e in plan.rows:
        entries_by_domain.setdefault(entry_key(e)[0], []).append(e)
    pairs: list[tuple[Source, dict]] = []
    todo: list[dict] = []
    for domain, entries in entries_by_domain.items():
        rows = rows_by_domain.get(domain, [])
        if len(entries) == 1 and len(rows) == 1:
            pairs.append((rows[0], entries[0]))
            continue
        by_key = {}
        for r in rows:
            by_key.setdefault(r.feed_key or "", r)
        unmatched: list[dict] = []
        for e in entries:
            row = by_key.get(entry_key(e)[1])
            if row is not None:
                pairs.append((row, e))
            else:
                unmatched.append(e)
        # A feed URL the catalogue CORRECTED on an outlet that holds several feeds: no entry carries the row's key any
        # more, so by key the entry is new and the row keeps the dead URL. A leftover entry and a leftover row are the
        # same source when the row's recorded baseline is that entry's NAME (the name is what the catalogue kept) and
        # exactly one leftover row says so; anything less certain registers a new row, as it always did.
        paired_ids = {id(r) for r, _ in pairs}
        leftover = [r for r in rows if id(r) not in paired_ids and r.feed_key]
        for e in unmatched:
            named = [
                r for r in leftover
                if (_baseline_of(r) or {}).get("name") == e.get("name") and _same_catalogue(r, e)
            ]
            if len(named) == 1 and sum(1 for x in unmatched if x.get("name") == e.get("name")) == 1:
                pairs.append((named[0], e))
                leftover.remove(named[0])
            else:
                todo.append(e)
    return pairs, todo, plan, rows_by_domain


def _dump_baseline(shipped: dict, base: dict | None) -> str:
    """The baseline JSON for ``shipped`` fields, carrying over the tags the catalogue has already merged onto the row."""
    out = dict(shipped)
    merged = (base or {}).get("merged_tags")
    if merged:
        out["merged_tags"] = merged
    return json.dumps(out, sort_keys=True)


def merge_feedless_tags(session: Session, merges: list[tuple[dict, Source]]) -> dict:
    """Put the tags of a feed-less catalogue entry on the outlet's feed row (R145, J3).

    A merged tag NEVER overwrites a different existing value: ``lean-*`` is exclusive on a row, so a second, different
    lean is a CONFLICT -- kept, listed with both sides, counted. A tag is merged ONCE per row (recorded in the row's
    baseline), so a tag the operator removed afterwards is not put back by the next boot; a row with no readable
    baseline is skipped and counted, never guessed at. ``via:`` provenance is not merged (it states a row's origin)."""
    merged_n = rows_touched = skipped_no_baseline = 0
    conflicts: list[dict] = []
    touched: set[int] = set()
    for entry, row in merges:
        base = _baseline_of(row)
        if base is None:
            skipped_no_baseline += 1
            continue
        done = {str(t) for t in (base.get("merged_tags") or [])}
        have = split_tags(row.tags)
        added: list[str] = []
        offered_present: list[str] = []
        for tag in entry_tags(entry):
            if tag in done:
                continue
            if tag in have:
                # Already on the row: nothing to add, but the catalogue HAS offered it -- recorded, so an operator who
                # removes it later does not see the next boot put it back (223 of the 240 real merges share a tag).
                offered_present.append(tag)
                continue
            fam = exclusive_family(tag)
            clash = next((t for t in have if fam and t.startswith(fam) and t != tag), None)
            if clash is not None:
                conflicts.append({
                    "domain": row.domain, "kept": clash, "catalogue": tag,
                    "entry": entry.get("name"), "provenance": entry.get("_provenance"),
                })
                continue
            have.append(tag)
            added.append(tag)
        recorded = done | set(added) | set(offered_present)
        if recorded != done:
            base["merged_tags"] = sorted(recorded)
            row.catalog_baseline = json.dumps(base, sort_keys=True)
        if not added:
            continue
        row.tags = ",".join(have)
        merged_n += len(added)
        if id(row) not in touched:
            touched.add(id(row))
            rows_touched += 1
    return {
        "tags_merged": merged_n, "rows_touched": rows_touched, "conflict_count": len(conflicts),
        "conflicts": conflicts[:_CONFLICT_EXAMPLES], "skipped_no_baseline": skipped_no_baseline,
    }


#: How many shadowed entries a seed result carries as examples. A handful, so the
#: report names the loss without dumping it; the COUNT beside them is exact.
_SHADOW_EXAMPLES = 8

#: How many kept operator edits a correction sync names. The COUNT beside them is exact;
#: the examples are there so the log says WHICH rows diverged, not merely how many.
_CONFLICT_EXAMPLES = 8

_LOGGER = logging.getLogger(__name__)


def catalog_domain_collisions(sources: list[dict]) -> dict[str, list[dict]]:
    """Catalog entries that share a domain with an earlier entry: ``{domain: [later entries]}``.

    **AFTER ROW J (S05-10) THIS IS THE CATALOGUE'S MULTIPLICITY PER DOMAIN, NOT THE LOSS.** A source is keyed on
    ``(domain, feed)``, so a later entry of a domain is a second feed (a row), a feed-less description (its tags merge
    onto the outlet's row) or, in 24 cases on a real boot, truly unregistered -- :func:`~src.ingest.seed_plan.plan_registration`
    names which, and the seeder's ``shadowed`` counts only the last. The text below is the measurement as it stood
    when a domain held one feed; it is the argument that deleting those entries was never the repair.

    Entries a domain-keyed seeder could never register (the pre-row-J meaning):

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


def sync_catalogue_corrections(session: Session, sources: list[dict], *, pairs: list | None = None) -> dict:
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
    pairs = pairs if pairs is not None else paired_rows(session, sources)[0]
    empty = {"checked": 0, "applied": 0, "kept": 0, "adopted": 0, "foreign_catalogue": 0, "conflicts": []}
    if not pairs:
        return empty

    applied = adopted = foreign = 0
    conflicts: list[dict] = []
    dirty = False
    for row, entry in pairs:
        # A row is corrected by the catalogue it was MADE from. Another catalogue's entry for the same domain describes the
        # outlet differently (the legal catalogue's feed-less "African Union" against the news row "African Union News"):
        # taking its values as corrections, and the baseline from it, made the default seed and the legal seed undo each
        # other on every boot and erased the feed of seven news rows for good. A row with no ``via:`` marker, and an entry
        # with no provenance (the explicit-path form), behave as before.
        if not _same_catalogue(row, entry):
            foreign += 1
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
            row.catalog_baseline = _dump_baseline(shipped, base)
            dirty = True
    if dirty:
        session.commit()
    if applied or conflicts:
        _LOGGER.info(
            "catalogue corrections: %d applied, %d kept as operator edits", applied, len(conflicts)
        )
    return {
        "checked": len(pairs), "applied": applied, "kept": len(conflicts),
        "adopted": adopted, "foreign_catalogue": foreign, "conflicts": conflicts[:_CONFLICT_EXAMPLES],
    }


def reconcile_source_metadata(session: Session, sources: list[dict], *, pairs: list | None = None) -> dict:
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
    pairs = pairs if pairs is not None else paired_rows(session, sources)[0]
    if not pairs:
        return {"checked": 0, "country_filled": 0, "language_filled": 0, "tags_filled": 0}

    filled = {"country": 0, "language": 0, "tags": 0}
    for row, entry in pairs:
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
        "checked": len(pairs),
        "country_filled": filled["country"],
        "language_filled": filled["language"],
        "tags_filled": filled["tags"],
    }


#: How many rows a feed repair names in each of its lists. The COUNTS beside them are exact; this bounds what the seed
#: result (logged and returned on every boot) can grow to if a catalogue change ever makes many rows unprovable.
_REPAIR_LIST_MAX = 50


def repair_erased_feeds(session: Session, sources: list[dict]) -> dict:
    """Give back the feed and region the seed flip-flop erased (R152) -- a targeted, provable repair, not a null-fill.

    THE DAMAGE. Until the legal catalogue was built one way by both seeds, the legal seed's feed-less entry for a host
    the news catalogue also lists (au.int, oas.org, gov.uk ...) was taken as a CORRECTION of the news row: its empty
    ``rss_url`` and ``region`` were written over the row's, and the row's baseline was rewritten to match. An empty live
    value is then read as a gap (``sync_catalogue_corrections``) and ``reconcile_source_metadata`` fills neither field,
    so the seven feeds never came back and those sources stopped being collected.

    WHEN A ROW IS GIVEN BACK ITS VALUE -- all of these, field by field (``rss_url``, ``region``):
      * the row's own ``via:`` catalogue carries a value for it (exactly one entry of that catalogue for the domain);
      * the live value is EMPTY;
      * the row's baseline holds no value either AND is what a feed-less entry of ANOTHER catalogue ships for this
        domain (its name, or all of name/country/language/region when both catalogues use the same name). That is the
        fingerprint of the erasure: nothing an operator does writes a baseline.
    A feed an operator cleared on purpose is never refilled: the baseline still names the feed, which the operator's edit
    cannot change. A row that fails a condition is counted (``operator_cleared``) or listed as not restored with its
    reason, so nothing is guessed. A restored value also moves the baseline, so the next three-way sync reads it as
    unedited rather than as an operator's change; the name, country and language the flip-flop swapped then return
    through that same sync, which only ever moves a value the operator has not touched.

    Idempotent: a restored row is no longer a candidate. Needs the full catalogue list, so the legal seed (which hands
    over only its own entries) repairs nothing and the default seed, which runs first at boot, does the work.
    """
    by_domain: dict[str, list[dict]] = {}
    for e in _usable(sources):
        if e.get("_provenance"):
            by_domain.setdefault(entry_key(e)[0], []).append(e)
    empty_value = (Source.rss_url.is_(None)) | (Source.rss_url == "") | (Source.region.is_(None)) | (Source.region == "")
    candidates = [
        r for r in session.query(Source).filter(Source.catalog_baseline.isnot(None)).filter(empty_value).order_by(Source.id)
        if (r.domain or "").strip().lower() in by_domain
    ]
    restored: list[dict] = []
    not_restored: list[dict] = []
    operator_cleared = 0
    for row in candidates:
        domain = (row.domain or "").strip().lower()
        base = _baseline_of(row)
        owner = _row_catalogue(row)
        if base is None or not owner:
            continue
        entries = by_domain[domain]
        mine = [e for e in entries if e.get("_provenance") == owner]
        want = {}
        if len(mine) == 1:
            computed = _to_source_kwargs(mine[0])
            for field in ("rss_url", "region"):
                value = _norm(computed.get(field))
                if value is not None and _norm(getattr(row, field, None)) is None:
                    want[field] = (value, computed.get(field))
        elif len(mine) > 1 and any(_norm(e.get("rss_url")) for e in mine):
            if any(_norm(getattr(row, f, None)) is None for f in ("rss_url", "region")):
                not_restored.append({
                    "domain": row.domain, "reason": f"the {owner} catalogue holds {len(mine)} entries for this domain",
                })
            continue
        if not want:
            continue
        if any(_norm(base.get(f)) is not None for f in want):
            operator_cleared += 1                # the baseline still names the value: cleared since, by the operator
            continue
        own_name = _norm(mine[0].get("name"))
        explained_by = None
        for e in entries:
            if e.get("_provenance") == owner or _norm(e.get("rss_url")):
                continue
            theirs = {f: _norm(v) for f, v in _to_source_kwargs(e).items() if f in ("name", "country", "language", "region")}
            if _norm(base.get("name")) != theirs.get("name"):
                continue
            if theirs.get("name") == own_name and any(
                _norm(base.get(f)) != theirs.get(f) for f in ("country", "language", "region")
            ):
                continue                          # the same name in both catalogues proves nothing alone
            explained_by = e
            break
        if explained_by is None:
            not_restored.append({
                "domain": row.domain, "reason": "no feed-less entry of another catalogue explains the empty value",
            })
            continue
        mates = session.query(Source).filter(Source.domain == row.domain).all()
        new_key = feed_key(want["rss_url"][1]) if "rss_url" in want else None
        if new_key and any(r is not row and r.feed_key == new_key for r in mates):
            not_restored.append({"domain": row.domain, "reason": "another row of this domain already carries that feed"})
            continue
        for field, (norm_value, raw) in want.items():
            setattr(row, field, raw)
            base[field] = norm_value
        row.catalog_baseline = json.dumps(base, sort_keys=True)
        restored.append({
            "domain": row.domain, "fields": sorted(want), "catalogue": owner,
            "explained_by": f"{explained_by.get('_provenance')}: {explained_by.get('name')}",
        })
    if restored:
        session.commit()
        _LOGGER.warning(
            "feed repair: %d source(s) had their erased feed or region restored from their own catalogue: %s",
            len(restored), ", ".join(r["domain"] for r in restored[:_REPAIR_LIST_MAX]),
        )
    return {
        "restored": len(restored), "restored_rows": restored[:_REPAIR_LIST_MAX],
        "not_restored": len(not_restored), "not_restored_rows": not_restored[:_REPAIR_LIST_MAX],
        "operator_cleared": operator_cleared,
    }


def seed_sources(session: Session, sources: list[dict]) -> SeedResult:
    """Create Source rows for any ``(domain, feed)`` not already present. Idempotent.

    A source is its domain AND its feed (row J, S05-10): BBC's thirty language services are thirty rows of one outlet,
    not thirty losers of the first. :func:`~src.ingest.seed_plan.plan_registration` decides every entry's fate purely --
    a row, a merge of a feed-less entry's tags onto the outlet's feed row, or unregistered with a reason -- and this
    function carries it out against the database in a single commit.

    THE REPORT NAMES WHAT STAYED OUT (2026-09-07, kept): ``skipped_existing`` is an idempotent re-run working,
    ``shadowed`` is the entries NO install can register (the same feed claimed twice, a feed-less duplicate, a second
    legal entry for a host) with ``unregistered_by_reason`` and examples carrying the reason, and ``merged`` is the
    feed-less entries whose tags went onto the outlet's row (``tag_merge`` says what was added and what conflicted).
    ``skipped`` keeps its old meaning (every reason an entry did not become a row).
    """
    skipped_malformed = sum(1 for s in sources if not (s.get("domain") or ""))
    # First: a row the seed flip-flop emptied must carry its feed again before entries are matched to rows by feed key.
    feed_repair = repair_erased_feeds(session, sources)
    pairs, todo, plan, rows_by_domain = paired_rows(session, sources)
    extra_merges: list[tuple[dict, Source]] = []
    to_create: list[dict] = []
    for e in todo:
        domain, fk = entry_key(e)
        feed_rows = [r for r in rows_by_domain.get(domain, []) if r.feed_key]
        if not fk and feed_rows:
            extra_merges.append((e, feed_rows[0]))   # the outlet already has a feed row: this describes it
        else:
            to_create.append(e)
    # A store whose boot rebuild was refused still keys a source on the domain alone: a second feed of a held domain
    # would break UNIQUE (domain) and fail the whole seed, so it is held back, counted and named, never attempted.
    held_back: list[dict] = []
    if to_create and not composite_key_active(session.connection()):
        have = {d for d, held in rows_by_domain.items() if held}
        kept: list[dict] = []
        for e in to_create:
            domain, _fk = entry_key(e)
            if domain in have:
                held_back.append(e)
                continue
            have.add(domain)
            kept.append(e)
        to_create = kept
    new_rows = [Source(**_to_source_kwargs(e)) for e in to_create]
    if new_rows:
        session.add_all(new_rows)
        session.commit()
    created_for: dict[int, Source] = {id(e): r for e, r in zip(to_create, new_rows, strict=True)}
    row_of: dict[int, Source] = {id(e): r for r, e in pairs} | created_for
    # An already-registered source used to end the story: skipped, never re-read. The catalogue keeps LEARNING (new
    # explicit countries, new tags, and the title/ccTLD fallbacks that did not exist when older rows were made), and
    # none of it reached a row that already existed. NULL-only, so a re-seed can add what is missing and can never
    # revert what an operator set.
    all_pairs = pairs + [(r, e) for e, r in zip(to_create, new_rows, strict=True)]
    reconciled = reconcile_source_metadata(session, sources, pairs=pairs)
    # ...and then the other half: a field that is NOT empty but that the catalogue has since CORRECTED. Runs AFTER, so a
    # field reconcile just filled reads as a gap rather than as an edit (sync skips empties).
    corrections = sync_catalogue_corrections(session, sources, pairs=all_pairs)
    # Feed-less entries describe an outlet that already has a feed row: their tags go there, after the baseline exists.
    merges = [(e, row_of[id(t)]) for e, t in plan.merges if id(t) in row_of] + extra_merges
    tag_merge = merge_feedless_tags(session, merges)
    if merges:
        session.commit()                 # also the baselines a merge only RECORDED: get_db callers never commit for us
    from src.catalog.sibling_verdicts import inherit_sibling_verdicts

    inherited = inherit_sibling_verdicts(session, new_rows)
    unregistered = plan.unregistered
    by_reason: dict[str, int] = {}
    for _e, reason in unregistered:
        by_reason[reason] = by_reason.get(reason, 0) + 1
    return {
        "created": len(new_rows),
        "feed_repair": feed_repair,
        "reconciled": reconciled,
        "corrections": corrections,
        "tag_merge": tag_merge,
        "sibling_verdicts": inherited,
        "skipped": len(pairs) + len(unregistered) + len(plan.merges) + skipped_malformed + len(held_back),
        "held_back_legacy_key": len(held_back),
        "total": len(sources),
        "skipped_existing": len(pairs),
        "skipped_malformed": skipped_malformed,
        "merged": len(plan.merges),
        "shadowed": len(unregistered),
        "unregistered_by_reason": dict(sorted(by_reason.items())),
        "shadowed_examples": [
            {"name": e.get("name"), "domain": e.get("domain"), "reason": reason}
            for e, reason in unregistered[:_SHADOW_EXAMPLES]
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
            # The rows ``seed_legal_sources`` registers, built by the SAME function: a second spelling of one entry
            # (raw ``source_type``, no gazette feed) made the two seeds correct each other on every boot.
            from src.law.catalog import load_legal_catalog, registration_source_rows

            sources = sources + registration_source_rows(load_legal_catalog(LEGAL_SOURCES_PATH))
        # Scholarly journals and official/primary-source bodies (2026-09-11 ruling), each in its
        # own catalogue with its own provenance so every surface can lens them apart from news.
        for extra, prov in ((ACADEMIC_SOURCES_PATH, "academic"), (OFFICIAL_SOURCES_PATH, "official")):
            if extra.exists():
                rows = load_sources_from_yaml(extra)
                for s in rows:
                    s["_provenance"] = prov
                sources = sources + rows
    return seed_sources(session, sources)
