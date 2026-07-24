"""Hazard records enter THE corpus — same aggregation as any other article.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

2026-07-24 field-feedback Session A §6 (ruled: hazards are INGESTED AS ARTICLES):
"a versioned/relayed source is an Article + a linked layer" (the pattern already
used for laws/wikipedia) applies here too — a hazard record (USGS earthquake,
GDACS disaster alert) becomes ONE corpus Article per provider event id, so it
joins full-text search, the keyword aggregator, and the When×Where×Who anchoring
like any scraped article. Mirrors ``src/law/corpus.py`` deliberately: the same
one-``index_article`` hook, the same idempotent-on-content-hash upsert.

Honesty notes:
  * the Article body is the provider's OWN title, verbatim — NEVER synthesized
    prose (the parsed hazard record carries no separate "description" field, so
    inventing narrative text around a bare title would be exactly the fabrication
    the house's non-negotiables forbid). A place line is appended only when it is
    a genuinely SEPARATE real fact the title does not already contain.
  * provenance: each PROVIDER gets ONE synthetic source ("Hazard (USGS)", domain
    ``hazard.usgs.local``, ``source_type="hazard"``) — a filterable provenance
    class, following the app's ``*.local`` non-web-provenance convention (cf.
    ``law.<jur>.local``, ``mailbox.import.local``).
  * magnitude/coordinates/severity are the PROVIDER's own asserted values, stored
    in the LINKED :class:`HazardEventDetail` layer — never promoted into the
    deduced ``ArticleMentionedPlace``/``ArticleEntity`` tables, and never a score.
    A record missing a field (e.g. GDACS carries no magnitude) stores that field
    as NULL — absence, never a fabricated 0.
  * ``published_at`` is the provider's own event time when it parses; an
    unparseable/absent time is left NULL — never guessed as "now" (that would
    assert something we do not actually know).
  * zero network here: ingestion reads records ALREADY produced by the LOCAL
    snapshot / the one consented refresh action, never fetches on its own.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from src.database.models import Article, HazardEventDetail, Source
from src.database.write import is_integrity_error

_LOG = logging.getLogger(__name__)

# Below this, a record cannot be honestly dated or placed as an event and is
# skipped rather than fabricated into a placeholder Article.
_REQUIRED_FIELDS = ("source", "id")


def _hazard_domain(provider: str) -> str:
    p = (provider or "unknown").strip().lower() or "unknown"
    return f"hazard.{p}.local"


def hazard_canonical_url(provider: str, event_id: str) -> str:
    """The stable per-event dedup key — never a real web URL (so it can never
    collide with a scraped article's canonical_url)."""
    p = (provider or "unknown").strip().lower() or "unknown"
    e = (event_id or "").strip()
    return f"hazard://{p}/{e}"


def ensure_hazard_source(session: Session, provider: str) -> Source:
    """ONE catalog source per provider — hazard-derived rows stay filterable.

    Mirrors ``src.law.corpus.ensure_law_source`` exactly: a synthetic
    ``hazard.<provider>.local`` domain, ``source_type="hazard"``, the
    channel-implied ``hazard`` tag set at creation (boot heal covers older rows).
    """
    p = (provider or "unknown").strip().lower() or "unknown"
    domain = _hazard_domain(p)
    src = session.query(Source).filter_by(domain=domain).first()
    if src is None:
        src = Source(
            name=f"Hazard ({p.upper()})",
            domain=domain,
            rss_url=None,
            source_type="hazard",
            tags="hazard",  # channel-implied (provenance.CLASS_IMPLIED_TAGS)
        )
        session.add(src)
        session.flush()
    return src


def _parse_time(value) -> datetime | None:
    """The provider's own event timestamp, or None (never guessed as "now") —
    mirrors the exact parsing already used by src.api.timemap._hazard_signals
    for consistency across the two hazard-consuming surfaces."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def _hazard_body(record: dict) -> str | None:
    """The Article body: the provider's own title, verbatim, plus a place line
    only when place is a genuinely separate real fact (never invented prose)."""
    title = (record.get("title") or "").strip()
    place = (record.get("place") or "").strip()
    if not title and not place:
        return None
    lines = [title] if title else []
    if place and place.lower() not in title.lower():
        lines.append(place)
    return "\n".join(lines) if lines else None


def _valid(record: dict) -> bool:
    if not isinstance(record, dict):
        return False
    return all((record.get(f) or "").__str__().strip() for f in _REQUIRED_FIELDS)


def _hazard_title(record: dict) -> str:
    """The Article title: the provider's title, else place, else an honest
    generic label -- each candidate STRIPPED before the fallback chain checks
    truthiness, so a whitespace-only title (truthy but empty once stripped)
    correctly falls through to a real place instead of winning the `or` chain
    and stripping down to "" (a skeptic-caught defect)."""
    title = (record.get("title") or "").strip()
    place = (record.get("place") or "").strip()
    return (title or place or "Hazard alert")[:500]


def ingest_hazard_record(session: Session, record: dict, *, extractor=None) -> dict:
    """Upsert ONE hazard record as a corpus Article + its linked detail, indexed.

    Keyed on the provider+event-id canonical URL — an updated alert for the SAME
    event (a revised USGS magnitude, a GDACS status change) UPDATES the existing
    Article + HazardEventDetail, never duplicates. A malformed record (missing
    source/id, or with no usable title/place at all) is skipped, honestly — never
    fabricates an Article. Routes through the SINGLE ``index_article`` hook so
    hazards get keywords + When×Where×Who exactly like any scraped article.
    """
    if not _valid(record):
        return {"status": "skipped-malformed"}
    provider = str(record.get("source") or "").strip().lower()
    event_id = str(record.get("id") or "").strip()
    body = _hazard_body(record)
    if not body:
        return {"status": "skipped-no-text", "provider": provider, "event_id": event_id}

    url = hazard_canonical_url(provider, event_id)
    # Hashed WITH the per-event url, never the body alone -- a skeptic-caught
    # HIGH defect: two DIFFERENT events (e.g. two USGS quakes that happen to
    # share a rounded magnitude + a generic "near City" place description, or
    # two GDACS alerts with the same formulaic name) can produce byte-identical
    # _hazard_body() text. With a body-only hash, Article.hash's GLOBAL unique
    # constraint would then make the SECOND event's commit collide with the
    # FIRST event's row -- the "duplicate-content" branch below would silently
    # and PERMANENTLY attribute the second (genuinely distinct) event's own
    # magnitude/coordinates/severity to nothing at all, forever (every future
    # re-ingest of it recomputes the same hash and hits the same collision).
    # Folding `url` into the hash makes a cross-event collision require a
    # genuine SHA-256 collision rather than mere prose coincidence, while
    # leaving the "same event, unchanged body" / "same event, changed body"
    # comparisons below exactly as before (url is constant for one event).
    content_hash = hashlib.sha256(f"{url}\n{body}".encode()).hexdigest()
    event_time = _parse_time(record.get("time"))
    lat, lon = record.get("lat"), record.get("lon")
    try:
        lat = float(lat) if lat is not None else None
        lon = float(lon) if lon is not None else None
    except (TypeError, ValueError):
        lat = lon = None
    mag = record.get("magnitude")
    try:
        mag = float(mag) if mag is not None else None
    except (TypeError, ValueError):
        mag = None

    art = session.query(Article).filter(Article.canonical_url == url).first()
    created = False
    # Tracked EXPLICITLY rather than re-derived from `art.hash == content_hash`
    # after the fact — the update branch below unconditionally sets art.hash to
    # content_hash, which would make that comparison trivially true for every
    # genuine content change too (a bug caught by test_a_genuinely_new_title_
    # updates_the_article_and_reindexes: a real title/body change was silently
    # skipping its own re-index).
    content_changed = False
    if art is None:
        src = ensure_hazard_source(session, provider)
        art = Article(
            url=url,
            canonical_url=url,
            source_id=src.id,
            title=_hazard_title(record),
            content=body,
            language=None,  # never guessed — a provider record states no language
            hash=content_hash,
            published_at=event_time,
        )
        session.add(art)
        created = True
        content_changed = True
    elif art.hash == content_hash:
        # Unchanged body — still refresh the asserted metadata layer below (the
        # provider may have revised magnitude/severity without changing the
        # title), but skip the (identical) re-index.
        pass
    else:
        art.content = body
        art.hash = content_hash
        art.title = _hazard_title(record)
        if event_time:
            art.published_at = event_time
        content_changed = True
    try:
        session.commit()
    except Exception as exc:  # noqa: BLE001 - is_integrity_error is the precise discriminator
        # Same cross-driver fix as src/law/corpus.py: Article.hash is globally
        # unique, and identical hazard text (a rare coincidence) must dedup
        # honestly rather than raise or silently drop the record.
        if not is_integrity_error(exc):
            raise
        session.rollback()
        existing = session.query(Article).filter(Article.hash == content_hash).first()
        return {
            "status": "duplicate-content", "provider": provider, "event_id": event_id,
            "article_id": existing.id if existing else None,
        }

    detail = session.query(HazardEventDetail).filter_by(article_id=art.id).first()
    if detail is None:
        detail = HazardEventDetail(article_id=art.id, provider=provider, event_id=event_id)
        session.add(detail)
    detail.event_type = record.get("type")
    detail.severity = record.get("severity")
    detail.magnitude = mag
    detail.lat = lat
    detail.lon = lon
    detail.place = record.get("place")
    detail.event_time = event_time
    detail.source_url = record.get("url")
    try:
        session.commit()
    except Exception as exc:  # noqa: BLE001 - a second provider event sharing (provider,id)
        # is structurally impossible (event_id is the provider's own key), but
        # degrade honestly rather than raise into the batch caller.
        if not is_integrity_error(exc):
            raise
        session.rollback()
        return {"status": "duplicate-detail", "provider": provider, "event_id": event_id, "article_id": art.id}

    if not content_changed:
        return {"status": "updated-metadata-only", "provider": provider, "event_id": event_id, "article_id": art.id}

    if extractor is None:
        from src.analytics.extract import BaselineExtractor

        extractor = BaselineExtractor()
    from src.analytics.store import index_article

    tally = index_article(session, art, extractor=extractor)
    return {
        "status": "created" if created else "updated",
        "provider": provider,
        "event_id": event_id,
        "article_id": art.id,
        "mentions": tally.get("mentions", 0),
    }


def ingest_hazard_records(session: Session, records: list[dict], *, extractor=None) -> dict:
    """Ingest a BATCH of hazard records (e.g. a whole snapshot). One bad record
    never breaks the batch. Returns a tally, never raises."""
    out = {"total": 0, "created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    if extractor is None:
        from src.analytics.extract import BaselineExtractor

        extractor = BaselineExtractor()
    for rec in records or []:
        out["total"] += 1
        try:
            res = ingest_hazard_record(session, rec, extractor=extractor)
        except Exception:  # noqa: BLE001 - one bad record must not abort the batch
            session.rollback()
            _LOG.warning("hazard ingest failed for a record", exc_info=True)
            out["skipped"] += 1
            continue
        status = res.get("status", "")
        if status in ("created",):
            out["created"] += 1
        elif status in ("updated", "updated-metadata-only"):
            out["updated"] += 1
        elif status in ("duplicate-content", "duplicate-detail"):
            out["unchanged"] += 1
        else:
            out["skipped"] += 1
    return out
