"""
PROPOSE what this instance qualified that no shipped catalogue has -- the other half of the accumulation loop.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE ASK (maintainer, 2026-11-14): «at each diagnostics / field test, if the app has qualified a new source, we add this
source (and proper tags, after your verification) to the repo's initial list of trusted sources».

``qualification_export`` carries verdicts for sources that SHIPPED with the app and deliberately leaves out the ones this
install found for itself (a verdict for a domain no catalogue has adopts onto nothing). This module is where those go:
every source this install QUALIFIED BY ITS OWN MEASUREMENT whose domain no curated catalogue ships, with its tags and the
evidence, so a maintainer can VERIFY it and add it to a catalogue through a normal pull request.

WHAT IT REFUSES:

  * NOTHING IS ADDED BY THIS. Every row says ``"proposal": "proposed"``; ``scripts/propose_source_additions.py`` turns the
    rows from several instances into a review table, and only a reviewed PR changes a catalogue.
  * AN INHERITED VERDICT IS NOT A CANDIDATE. Only sources with a judging attempt this install made (``measured``, the same
    rule ``qualification_export`` applies) are listed; one a backup brought in is counted apart.
  * PRIVATE SOURCES STAY HOME. Newsletter and mailbox sources (their domain can name a person's subscriptions) are left
    out and counted. A feed address keeps only scheme, host, port and path: user, password, query and fragment are
    removed, so a feed's token never leaves.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import func
from sqlalchemy.orm import Session

SCHEMA = "oo-candidate-sources-1"
PROPOSED = "proposed"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


def clean_feed_address(url: str | None) -> str | None:
    """Scheme, host, port and path of a feed address; user, password, query and fragment removed. A non-web address
    keeps only its scheme; an address that does not parse is withheld."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
        if parts.scheme.lower() not in ("http", "https"):
            return f"{parts.scheme or 'address'}:[withheld]"
        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        netloc = host + (f":{parts.port}" if parts.port else "")
    except ValueError:
        return "[address withheld]"
    return urlunsplit((parts.scheme.lower(), netloc, parts.path, "", ""))


def _tags(raw: str | None) -> list[str]:
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


def build_candidate_sources(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """Every source this install qualified by its own measurement that no curated catalogue ships, proposed for review."""
    from src.catalog.provenance_scope import app_provided_filter, curated_catalogue_domains
    from src.catalog.qualification import STATUS_QUALIFIED
    from src.catalog.qualification_export import _locally_measured_ids
    from src.database.models import Article, Source, SourceQualificationAttempt
    from src.ingest.email import NEWSLETTER_SOURCE_DOMAINS

    now = now or datetime.now(UTC)
    measured = _locally_measured_ids(session)
    shipped = curated_catalogue_domains()
    private = {d.lower() for d in NEWSLETTER_SOURCE_DOMAINS}
    rows = (
        session.query(Source)
        .filter(~app_provided_filter(Source.tags), Source.status == STATUS_QUALIFIED)
        .order_by(Source.domain.asc())
        .all()
    )
    skipped = {"in_a_shipped_catalogue": 0, "inherited_not_measured": 0, "newsletter_or_mailbox": 0}
    kept: list[Any] = []
    for s in rows:
        domain = (s.domain or "").lower()
        tags = _tags(s.tags)
        if domain in private or any("newsletter" in t.lower() or "mailbox" in t.lower() for t in tags):
            skipped["newsletter_or_mailbox"] += 1
        elif domain in shipped:
            skipped["in_a_shipped_catalogue"] += 1
        elif s.id not in measured:
            skipped["inherited_not_measured"] += 1
        else:
            kept.append(s)
    # two grouped reads for all candidates, never one query per source
    attempts: dict[int, dict[str, Any]] = {}
    articles: dict[int, tuple[int, Any, Any]] = {}
    ids = [s.id for s in kept]
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        A = SourceQualificationAttempt
        for sid, verdict, n, first, last in (
            session.query(A.source_id, A.verdict, func.count(), func.min(A.attempted_at), func.max(A.attempted_at))
            .filter(A.source_id.in_(chunk)).group_by(A.source_id, A.verdict).all()
        ):
            row = attempts.setdefault(int(sid), {"attempts": {}, "first": None, "last": None})
            row["attempts"][str(verdict)] = int(n)
            row["first"] = first if row["first"] is None or (first and first < row["first"]) else row["first"]
            row["last"] = last if row["last"] is None or (last and last > row["last"]) else row["last"]
        for sid, n, first_art, last_art in (
            session.query(Article.source_id, func.count(Article.id), func.min(Article.published_at),
                          func.max(Article.published_at))
            .filter(Article.source_id.in_(chunk)).group_by(Article.source_id).all()
        ):
            articles[int(sid)] = (int(n or 0), first_art, last_art)
    out: list[dict[str, Any]] = []
    for s in kept:
        att = attempts.get(s.id, {"attempts": {}, "first": None, "last": None})
        n_art, first_art, last_art = articles.get(s.id, (0, None, None))
        out.append({
            "proposal": PROPOSED,
            "domain": (s.domain or "").lower(),
            "name": s.name,
            "feed": clean_feed_address(s.rss_url),
            "tags": _tags(s.tags),
            "language": s.language,
            "country": s.country,
            "region": s.region,
            "source_type": s.source_type,
            "qualified_at": _iso(s.qualified_at),
            "criteria_version": s.qualification_criteria_version,
            "evidence": {
                "attempts": att["attempts"],
                "first_attempt": _iso(att["first"]),
                "last_attempt": _iso(att["last"]),
                "articles_stored": n_art,
                "first_article": _iso(first_art),
                "last_article": _iso(last_art),
                "last_crawled_at": _iso(s.last_crawled_at),
            },
        })
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(timespec="seconds"),
        "note": ("Sources this install qualified by its own measurement that no shipped catalogue has. Every row is a "
                 "PROPOSAL: nothing here is added to the shipped list until a maintainer verifies it and a reviewed pull "
                 "request adds it to a catalogue."),
        "candidates": out,
        "left_out": skipped,
        "feed_addresses": "scheme, host, port and path only: user, password, query and fragment removed",
    }
