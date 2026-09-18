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
from src.ingest.seed_sources import SeedResult

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


#: A ``gazette_feed`` becomes a live ``rss_url`` only at this tier. See
#: ``FEED_VERIFICATION_STATUSES`` in ``scripts/validate_legal_catalog.py`` for why a feed
#: carries its own tier rather than inheriting the row's: the row status is about the
#: PORTAL, and one of the four rows carrying a feed (impo.com.uy) has a feed nobody ever
#: fetched, which its own notes describe as the site's generic WordPress news feed.
_WIREABLE_FEED_STATUS = "fetched"


def feed_rss_url(source: dict) -> str | None:
    """Pure: the ``rss_url`` this catalog row contributes, or ``None``.

    S2 of the law-vertical brief (2026-07-17), built 2026-09-07. Four generated rows
    carry a ``gazette_feed`` — an official gazette's own RSS — and none of them ever
    became an ``rss_url``, so the cheapest real coverage in the vertical sat in the
    catalog unused while the normal ingest pipeline was right there.

    A feed is promoted ONLY when its own ``gazette_feed_verification.status`` is
    ``fetched``, i.e. the producing session actually asked that URL and recorded what
    came back. A ``lead`` feed is kept in the catalog (it is a real research lead) and
    is never fetched, exactly as a ``lead`` source is. An explicit ``rss_url`` already
    on the row always wins — this only ever fills an absence.
    """
    if source.get("rss_url"):
        return None
    feed = source.get("gazette_feed")
    if not feed:
        return None
    ver = source.get("gazette_feed_verification") or {}
    if ver.get("status") != _WIREABLE_FEED_STATUS:
        return None
    return str(feed)


#: Q924 = a: "each source carries ``verified: live | fixture | unverified`` with a date;
#: the UI shows it". THREE tiers, and the middle one is the honest majority of this
#: catalogue today.
#:
#: THIS IS NOT ``verification.status``, AND CONFLATING THE TWO WOULD BE THE WHOLE DEFECT.
#: That field is about the RESEARCH: did the session that wrote this row confirm the
#: portal exists (``fetched`` / ``search-verified`` / ``lead``)? This one is about THIS
#: APP: has an adapter in this tree actually read a document from this source, and
#: against what? A portal can be ``fetched`` by a researcher's browser and ``unverified``
#: here, which is exactly the state 276 of the 277 rows are in.
VERIFIED_TIERS: tuple[str, ...] = ("live", "fixture", "unverified")

#: What each tier CLAIMS, in one sentence. The claims are deliberately narrow: "an
#: adapter read a document" is not "this source works", and a surface that renders the
#: tier without the sentence invites the stronger reading.
VERIFIED_TIER_NOTES: dict[str, str] = {
    "live": "an adapter in this tree read a document fetched from this source's own host",
    "fixture": (
        "an adapter in this tree read a stored fixture of this source's format; the "
        "live host has not answered here"
    ),
    "unverified": "no adapter has read anything from this source, live or stored",
}


def verified_tier(source: dict) -> dict:
    """Pure: this source's Q924 tier, its date and its method — never inferred.

    A row with no ``verified`` block is ``unverified`` with NO date, because "nobody
    recorded a verification" is what that state means and stamping it with today's date
    would turn an absence into a measurement. The tier is likewise never derived from
    ``verification.status``: a researcher confirming a portal exists says nothing about
    whether this app can read it.

    An unknown tier degrades to ``unverified`` and says so in ``note``, rather than
    raising: this is read on a rendering path, and a catalogue typo should show as an
    unverified row rather than as a 500 on the coverage surface.
    """
    block = source.get("verified")
    if not isinstance(block, dict):
        return {"tier": "unverified", "as_of": None, "method": None,
                "note": VERIFIED_TIER_NOTES["unverified"]}
    tier = str(block.get("tier") or "").strip().lower()
    if tier not in VERIFIED_TIERS:
        return {
            "tier": "unverified",
            "as_of": None,
            "method": None,
            "note": VERIFIED_TIER_NOTES["unverified"],
            "unreadable_tier": block.get("tier"),
        }
    return {
        "tier": tier,
        "as_of": block.get("as_of"),
        "method": block.get("method"),
        "note": VERIFIED_TIER_NOTES[tier],
    }


def counts_documents(official_count: dict | None) -> bool:
    """Pure: may a coverage figure DIVIDE by this count? (Q921 = a)

    ``True`` only when the row says so IN SO MANY WORDS. The catalogue's counts are in
    codes, acts, volumes, gazette issues, treaties and cases; a volume or an issue
    contains many acts, so dividing a tracked-document count by one of those produces a
    percentage of nothing. Ruling 47's rail says to "declare it explicitly on each
    catalog entry rather than inferring it from the unit string", and this is that
    declaration — absent means REFUSE, which is what ``src/law/coverage.py`` has always
    done and now does for a stated reason rather than for all of them at once.
    """
    return bool(isinstance(official_count, dict) and official_count.get("counts_documents") is True)


#: Q919 = a: "each law authority is a ``Source`` row with ``source_type=\"law\"``, so the
#: Sources tab, coverage and qualification see it like any other source."
LAW_SOURCE_TYPE = "law"

#: The catalogue's OWN types that describe a law authority, and therefore become ``law``
#: on the Source row. ``ip`` (10 rows) does NOT: an intellectual-property office is a
#: registry, not a law authority, and Q919 names the latter. ``case_law`` (2 rows) does
#: not either, for a stronger reason — Q902's (e) was NOT CHOSEN, so admitting those two
#: rows under the law type would quietly enter a document class this cycle declined.
LAW_AUTHORITY_TYPES: frozenset[str] = frozenset({"legal", "gazette"})

#: The token those rows carried BEFORE Q919. Readers accept both, because a store
#: mid-migration and a corpus restored from an older backup both legitimately hold the
#: old one, and a classifier that recognised only the new token would silently drop 190
#: law portals out of the law provenance class on exactly those stores.
LEGACY_LAW_SOURCE_TYPES: frozenset[str] = frozenset({"legal"})


def source_type_for(source: dict) -> str:
    """Pure: the ``source_type`` this catalogue row's Source row carries (Q919).

    A row whose catalogue type is not a law-authority type keeps its own: this is a
    rename of one class, not a flattening of four into one.
    """
    declared = str(source.get("source_type") or "").strip().lower()
    return LAW_SOURCE_TYPE if declared in LAW_AUTHORITY_TYPES else (declared or "legal")


def is_law_source_type(source_type: str | None) -> bool:
    """Does this token name a law authority — under either vocabulary?

    The ONE place the pair is written. Two call sites each spelling
    ``in ("law", "legal")`` is how one of them comes to be updated and the other not.
    """
    token = (source_type or "").strip().lower()
    return token == LAW_SOURCE_TYPE or token in LEGACY_LAW_SOURCE_TYPES


def source_for_url(url: str | None, catalog: dict | None = None) -> dict | None:
    """The catalogue row whose domain serves ``url``, or ``None``. Pure.

    Matched on the HOST, with a suffix match so ``www.legislation.gov.uk`` finds the
    ``legislation.gov.uk`` row. The match is on a DOT boundary — ``endswith("." + domain)``
    rather than ``endswith(domain)`` — because the loose form would make
    ``notlegislation.gov.uk`` resolve to the UK row and inherit its licence, which is
    precisely the claim this lookup exists to carry.
    """
    from urllib.parse import urlparse

    host = (urlparse(str(url or "")).hostname or "").strip().lower()
    if not host:
        return None
    cat = catalog if catalog is not None else load_legal_catalog()
    for source in cat["sources"]:
        domain = str(source.get("domain") or "").strip().lower()
        if domain and (host == domain or host.endswith("." + domain)):
            return source
    return None


def licence_for_url(url: str | None, catalog: dict | None = None) -> str:
    """The licence token a document served from ``url`` INHERITS (Q927).

    ``unknown`` when the source states none, which is almost all of them. The inheritance
    is a DEFAULT, not a finding: a document may carry its own licence and override this,
    and the reader says "licence not recorded" for the default rather than implying that
    anybody looked at that particular document's terms.
    """
    source = source_for_url(url, catalog)
    return str((source or {}).get("licence") or "unknown")


def registration_source_rows(catalog: dict) -> list[dict]:
    """Pure: the Source rows a catalog registers, with provenance applied.

    GENERATED entries (the parallel-research harvest) carry their own
    ``via:legal-generated`` provenance and — maintainer ruling 2026-07-17 —
    ENABLE BY DEFAULT like curated entries: the maintainer's review of the
    committed catalog file IS the vetting gate, and the end user never has to
    hand-enable sources ("everything background and automated"). Robots stays
    fail-closed and the bounded preflight verifies each domain automatically (a
    dead/robots-blocked lead gets an honest verdict, not a fetch).
    Runtime-DISCOVERED candidates (the discovery funnel) are a DIFFERENT channel
    and still register disabled.

    AMENDED 2026-09-07 (S2): this used to say "legal portals carry no rss_url so
    collect passes never fetch them" and that is no longer true of every row — the
    three rows whose OWN ``gazette_feed_verification`` records a fetched feed now
    contribute an ``rss_url`` (see :func:`feed_rss_url`), so a collect pass polls
    those three gazettes like any other feed. That is the point of the change; the
    claim is corrected here rather than left standing, because a stale safety
    sentence is read as a guarantee. Everything the sentence was protecting is
    unchanged and still applies to these three: the network consent gate, the
    kill switch, fail-closed robots and per-host politeness all sit on the one
    fetch path, and 222 of the 225 generated rows still carry no feed at all."""
    rows = []
    for s in catalog["sources"]:
        s = dict(s)
        if s.pop("_generated", False):
            s.setdefault("_provenance", "legal-generated")
        else:
            s.setdefault("_provenance", "legal")
        rss = feed_rss_url(s)
        if rss:
            s["rss_url"] = rss
        # Q919 (2026-09-18): a law authority's Source row carries `law`. The catalogue
        # keeps its own finer vocabulary -- `legal` vs `gazette` says something real
        # about the row -- so the mapping happens HERE, on the way to the Source, and
        # the file is not rewritten.
        s["source_type"] = source_type_for(s)
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


def seed_legal_sources(session: Session, path: Path | None = None) -> SeedResult:
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
