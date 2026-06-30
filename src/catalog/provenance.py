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
WEB = "web"

PROVENANCE_CLASSES: tuple[str, ...] = (WEB, WIKIPEDIA, NEWSLETTER, STATISTICS)

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
    independent of the inconsistent ``source_type`` column); official statistics by
    the ``source_type="statistics"`` the stats ingester sets explicitly.
    """
    d = (domain or "").strip().lower().rstrip(".")
    if d == "wikipedia.org" or d.endswith(".wikipedia.org"):
        return WIKIPEDIA
    if d in NEWSLETTER_DOMAINS:
        return NEWSLETTER
    if (source_type or "").strip().lower() == STATISTICS:
        return STATISTICS
    return WEB
