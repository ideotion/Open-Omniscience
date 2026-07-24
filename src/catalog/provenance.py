"""
Content-provenance class — a DESCRIPTIVE ingestion-channel label, never a score.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each item is classified by WHAT KIND of channel it came in through — a wiki
edition, an imported newsletter, an official-statistics producer, or a plain web
article. This is an ASSERTED FACT known by construction (the ingest path / the
source domain tells us the channel), NOT a classifier and NOT a quality/credibility
judgement: "newsletter" is a channel, not "less reliable". So it fits the no-score /
no-fabricated-metadata non-negotiables.

This module is the read-side derivation (pure, network-free, unit-tested without the
ORM). It is the same logic the eventual content-provenance ``Source.source_type``
backfill (docs/FUTURE_DEVELOPMENTS.md → "Content-provenance class") will use, so the
two never drift; once a denormalised column exists, the per-bucket counts become a
covering-index scan instead of needing this per-row derivation.
"""

from __future__ import annotations

# The filterable provenance classes the Articles toggle exposes. "web" is the
# catch-all (a plain scraped article). Order is display order; "all" (no filter)
# is handled by the caller, not a member here.
WIKIPEDIA = "wikipedia"
NEWSLETTER = "newsletter"
STATISTICS = "statistics"
# A SECONDARY source discovered because articles CITE it (an in-article link),
# auto-registered disabled by the citation channel. A descriptive channel label
# ("discovered via citation"), never a quality judgement -- a widely-cited primary
# source and a laundering hub look identical here; the user judges.
CITED = "cited"
# Law/legal channel (maintainer-asked 2026-07-17: "a proper article tag dedicated to
# laws"): tracked legal documents ingest as corpus Articles under synthetic
# ``law.<jurisdiction>.local`` sources (source_type "legal"), and the seeded official
# portals/gazettes carry source_type "legal"/"ip". A channel fact, never a judgement.
LAW = "law"
# Open geophysical-hazard alerts (USGS/GDACS), ingested as corpus Articles under
# synthetic hazard.<provider>.local sources (2026-07-24 field-feedback Session A §6,
# ruled: "hazards ingested as Articles"). A channel fact, never a judgement --
# provider-declared severity/magnitude ride a LINKED, source-asserted detail record
# (HazardEventDetail), never a score.
HAZARD = "hazard"
WEB = "web"

PROVENANCE_CLASSES: tuple[str, ...] = (WEB, WIKIPEDIA, NEWSLETTER, STATISTICS, CITED, LAW, HAZARD)

# Tags IMPLIED by a source's channel class (maintainer-asked 2026-07-17: "tags should
# also be deduced from source type, and source tags"). These are appended to a source's
# explicit tags — never replacing them — so tag-based filters (the analysis `tags`
# param, the scheduler's select_tags, the wizard's theme facets) find law/wikipedia/…
# articles even where a synthetic source was created without tags. Descriptive only.
CLASS_IMPLIED_TAGS: dict[str, tuple[str, ...]] = {
    WIKIPEDIA: ("wikipedia", "encyclopedia"),
    NEWSLETTER: ("newsletter",),
    STATISTICS: ("statistics",),
    CITED: ("cited",),
    LAW: ("law",),
    HAZARD: ("hazard",),
    WEB: (),
}


def implied_tags(domain: str | None, source_type: str | None, tags_csv: str | None) -> list[str]:
    """The source's explicit tags MERGED with its channel-implied tags (pure).

    Existing tags keep their order; missing implied tags are appended; the "ip"
    source_type additionally implies the ``ip`` tag beside ``law``. Returns a list
    (callers join with "," for the CSV column)."""
    existing = [t.strip() for t in (tags_csv or "").split(",") if t.strip()]
    seen = {t.lower() for t in existing}
    out = list(existing)
    cls = provenance_of(domain, source_type)
    implied = list(CLASS_IMPLIED_TAGS.get(cls, ()))
    if (source_type or "").strip().lower() == "ip":
        implied.append("ip")
    for tag in implied:
        if tag.lower() not in seen:
            out.append(tag)
            seen.add(tag.lower())
    return out


def ensure_channel_tags(session) -> int:
    """Idempotent boot heal: materialise the channel-implied tags onto the BOUNDED set
    of sources whose class implies tags (wiki editions, synthetic law sources, legal/ip
    portals, statistics producers, newsletter buckets, cited discoveries). Existing
    tags are never removed or reordered — implied tags are only appended. Returns the
    number of rows updated (0 on an already-healed store). Lazy ORM import so the
    pure derivation above stays unit-testable without the ORM."""
    from sqlalchemy import or_

    from src.database.models import Source

    candidates = (
        session.query(Source)
        .filter(
            or_(
                Source.domain.like("%.wikipedia.org"),
                Source.domain == "wikipedia.org",
                Source.domain.like("law.%.local"),
                Source.domain.like("hazard.%.local"),
                Source.domain.in_(sorted(NEWSLETTER_DOMAINS)),
                Source.source_type.in_(["legal", "ip", "statistics", "cited", "hazard"]),
            )
        )
        .all()
    )
    healed = 0
    for src in candidates:
        merged = implied_tags(src.domain, src.source_type, src.tags)
        csv = ",".join(merged)
        if csv != (src.tags or "") and len(csv) <= 500:
            src.tags = csv
            healed += 1
    if healed:
        session.commit()
    return healed

# Newsletter import buckets (the .eml file import + the live IMAP/POP3 pull). Kept
# in sync with src/api/ingestion.py (_NEWSLETTER_DOMAIN / _MAILBOX_DOMAIN) and
# src/ingest/email.py (NEWSLETTER_SOURCE_DOMAINS).
NEWSLETTER_DOMAINS: frozenset[str] = frozenset(
    {"newsletters.import.local", "mailbox.import.local"}
)


def provenance_of(domain: str | None, source_type: str | None = None) -> str:
    """Return the content-provenance class for a source, from its domain + type.

    Deterministic and total: every source resolves to exactly one class, defaulting
    to ``WEB``. Wikipedia and newsletters are recognised by DOMAIN (reliable today,
    independent of the inconsistent ``source_type`` column); official statistics and
    citation-discovered sources by the ``source_type`` the ingester/promoter sets
    explicitly (``"statistics"`` / ``"cited"``).
    """
    d = (domain or "").strip().lower().rstrip(".")
    if d == "wikipedia.org" or d.endswith(".wikipedia.org"):
        return WIKIPEDIA
    if d in NEWSLETTER_DOMAINS:
        return NEWSLETTER
    if d.startswith("law.") and d.endswith(".local"):
        return LAW
    if d.startswith("hazard.") and d.endswith(".local"):
        return HAZARD
    st = (source_type or "").strip().lower()
    if st == STATISTICS:
        return STATISTICS
    if st == CITED:
        return CITED
    if st in ("legal", "ip"):
        return LAW
    if st == HAZARD:
        return HAZARD
    return WEB
