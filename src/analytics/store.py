"""
Persist extracted keywords/entities as mentions, and backfill the corpus.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``index_article`` runs an extractor over one article and writes one
``KeywordMention`` per (article, keyword), upserting the ``Keyword`` row. It is
idempotent: re-indexing an article replaces its mentions. ``backfill_corpus``
indexes articles that have no mentions yet (used by the GUI's "index corpus"
action), in bounded batches so it never blocks.

Denormalised facets (``observed_on`` from the article date, ``country`` / ``city``
from its source) are written onto each mention so trend, map and per-region
queries stay single-scan.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from src.analytics.baseline import baseline_tags
from src.analytics.extract import ExtractedTerm
from src.database.models import Article, Keyword, KeywordMention, KeywordTag

_LOG = logging.getLogger(__name__)


# Leading articles stripped when matching a source's own name (multi-language,
# matching the catalog's languages — "The Moscow Times" also matches as
# "moscow times").
_LEADING_ARTICLES = {"the", "le", "la", "les", "el", "los", "las", "die", "der", "das", "il", "al"}


def _self_name_forms(source) -> set[str]:
    """Normalized forms of the article's OWN source identity.

    A keyword equal to one of these is the source naming ITSELF (header,
    footer, byline boilerplate — the field-report #4 finding: "The Moscow
    Times" ×213 as a keyword), not article content. The match is per-article:
    the same term mentioned by OTHER sources remains a real keyword, so
    coverage ABOUT an outlet is never suppressed. Exact full-form matches
    only — single shared words ("moscow", "times") are untouched.
    """
    forms: set[str] = set()
    if source is None:
        return forms
    name = " ".join((source.name or "").split()).casefold()
    if name:
        forms.add(name)
        toks = name.split()
        if len(toks) > 1 and toks[0] in _LEADING_ARTICLES:
            forms.add(" ".join(toks[1:]))
    domain = (source.domain or "").casefold().strip()
    if domain:
        label = domain.removeprefix("www.").split(":", 1)[0]
        forms.add(label)
        parts = label.split(".")
        if len(parts) >= 2 and parts[-2]:
            forms.add(parts[-2])  # the registrable label: "themoscowtimes"
    return {f for f in forms if len(f) >= 3}


def _get_or_create_keyword(
    session: Session, t: ExtractedTerm, *, language: str | None, extractor: str
) -> Keyword:
    kw = session.query(Keyword).filter_by(normalized_term=t.normalized).first()
    is_entity = t.kind != "term"
    if kw is None:
        kw = Keyword(
            term=t.term,
            normalized_term=t.normalized,
            language=language or None,  # unknown stays NULL, never silently "en" (audit 06)
            frequency=0,
            is_entity=is_entity,
            entity_type=(t.kind if is_entity else None),
            is_ngram=(" " in t.normalized),
            ngram_size=len(t.normalized.split()),
            extractor=extractor,
        )
        session.add(kw)
        session.flush()  # assign id for the mention FK
        # Item AC: a curated baseline pre-tags a known keyword at creation time
        # (forward-only — existing keywords are not retroactively tagged here).
        # Each tag is a labelled assertion carrying its source provenance.
        for axis, tag in baseline_tags(language, t.normalized):
            session.add(KeywordTag(keyword_id=kw.id, axis=axis, tag=tag, source="baseline"))
    elif is_entity and not kw.is_entity:
        # A term first seen lowercase, later recognised as an entity -> upgrade.
        kw.is_entity = True
        kw.entity_type = t.kind
        kw.extractor = extractor
    return kw


def tags_for_keyword(session: Session, normalized: str) -> dict[str, list[str]]:
    """All tags on a keyword, grouped by axis: ``{"type": [...], "topic": [...]}``.

    Read-only; labels only, never a score. Empty when the keyword is absent or
    untagged. (Item AC; the source provenance per tag is on the KeywordTag rows.)
    """
    kw = session.query(Keyword).filter_by(normalized_term=normalized).first()
    if kw is None:
        return {}
    out: dict[str, list[str]] = {}
    rows = (
        session.query(KeywordTag)
        .filter_by(keyword_id=kw.id)
        .order_by(KeywordTag.axis, KeywordTag.tag)
    )
    for row in rows:
        out.setdefault(row.axis, []).append(row.tag)
    return out


def backfill_baseline_tags(session: Session, *, limit: int | None = None) -> dict:
    """Apply curated baseline tags to EXISTING keywords (the retroactive pass).

    Forward-only tagging (at creation) only covers keywords created since the baseline
    shipped; this one-pass backfill tags the keywords already in the store, so the
    feature is not empty on a pre-existing corpus. Idempotent: a baseline tag already
    present (same keyword/axis/tag) is skipped. The existing-rows query runs ONLY for
    keywords that actually match the baseline (most do not), so it is cheap. Reads the
    same bundled baseline — never invents a tag; counts only, no score."""
    q = session.query(Keyword)
    if limit:
        q = q.limit(limit)
    scanned = tagged_keywords = tags_added = 0
    for kw in q:
        scanned += 1
        pairs = baseline_tags(kw.language, kw.normalized_term)
        if not pairs:
            continue
        existing = {
            (r.axis, r.tag)
            for r in session.query(KeywordTag).filter_by(keyword_id=kw.id, source="baseline")
        }
        added = 0
        for axis, tag in pairs:
            if (axis, tag) not in existing:
                session.add(KeywordTag(keyword_id=kw.id, axis=axis, tag=tag, source="baseline"))
                added += 1
        if added:
            tagged_keywords += 1
            tags_added += added
    if tags_added:
        session.commit()
    return {"scanned": scanned, "tagged_keywords": tagged_keywords, "tags_added": tags_added}


def _apply_keyword_counter_deltas(
    session: Session, old_contrib: dict[int, int], new_contrib: dict[int, int]
) -> None:
    """Adjust ``Keyword.mention_count`` / ``article_count`` by ONE article's net change.

    ``old_contrib`` / ``new_contrib`` map ``keyword_id -> summed occurrence count``
    for, respectively, this article's mentions BEFORE and AFTER a re-index. Because
    there is exactly one ``KeywordMention`` row per (keyword, article) — the unique
    ``(keyword_id, article_id)`` index — a keyword's ``article_count`` changes by at
    most ±1 (present-after minus present-before) and its ``mention_count`` by
    (new occurrence count − old). This keeps the denormalised counters EXACT across
    ingest and re-index in O(keywords-in-this-article), never a corpus-wide recompute.

    The ``max(0, …)`` is a defensive floor — a counter must never display negative;
    correct maintenance never reaches it, and :func:`backfill_keyword_counters` is the
    authoritative repair (the drift tests assert counter == the live GROUP BY).
    """
    affected = set(old_contrib) | set(new_contrib)
    if not affected:
        return
    for kw in session.query(Keyword).filter(Keyword.id.in_(affected)).all():
        d_men = new_contrib.get(kw.id, 0) - old_contrib.get(kw.id, 0)
        d_art = (1 if kw.id in new_contrib else 0) - (1 if kw.id in old_contrib else 0)
        kw.mention_count = max(0, (kw.mention_count or 0) + d_men)
        kw.article_count = max(0, (kw.article_count or 0) + d_art)


def index_article(
    session: Session,
    article: Article,
    *,
    extractor,
    country: str | None = None,
    city: str | None = None,
) -> dict:
    """Extract + store mentions for one article (idempotent). Returns a small tally."""
    content = article.get_content() if hasattr(article, "get_content") else (article.content or "")

    # Sentiment at ingest (language-aware, honest): VADER scores ENGLISH articles
    # and stores the result on the article; every other language stays NULL — never
    # a fabricated neutral. Runs on the one per-article hook, so ingest / re-index /
    # backfill all populate the (previously dead) sentiment columns.
    from src.analytics.sentiment import score_article

    article.sentiment_score, article.sentiment_label = score_article(content, article.language)

    terms = extractor.extract(
        content or "",
        title=article.title or "",
        language=article.language or "en",  # extractor needs SOME stoplist; "en" here
        # is an extraction working assumption, never stored as the keyword's language.
    )

    observed = article.published_at or article.created_at
    observed_on = observed.date() if observed else None
    # Canonical lowercase ISO-2 via the one conversion layer (0.09). The old
    # `cc[:2].lower()` truncation corrupted legacy full-name values into wrong
    # codes ("china" -> "ch" = Switzerland); unrecognisable input is now None.
    from src.catalog.countries import normalize_country

    cc = normalize_country(country or article.country)

    # Capture this article's PRIOR contribution to the denormalised keyword
    # counters BEFORE replacing its mentions, so mention_count / article_count stay
    # EXACT across a re-index (idempotent). One indexed scan over this article's
    # rows (ix_mention_article) — bounded by the article's keyword count.
    old_contrib: dict[int, int] = {}
    for kid, cnt in (
        session.query(KeywordMention.keyword_id, KeywordMention.count)
        .filter_by(article_id=article.id)
        .all()
    ):
        old_contrib[kid] = old_contrib.get(kid, 0) + int(cnt or 0)

    # Idempotent re-index: drop this article's existing mentions first.
    session.query(KeywordMention).filter_by(article_id=article.id).delete()

    # Source self-names are boilerplate, not content (maintainer-ruled rule,
    # NOT a stoplist — see _self_name_forms; re-indexing applies it
    # retroactively because index_article replaces an article's mentions).
    self_forms = _self_name_forms(getattr(article, "source", None))

    written = 0
    self_suppressed = 0
    new_contrib: dict[int, int] = {}
    for t in terms:
        # Case-insensitive: _self_name_forms is casefolded, but the entity
        # detector keeps acronyms UPPERCASE (2026-06-16 ruling), so a source
        # whose name shows up all-caps in its own chrome ("Correctiv" ->
        # CORRECTIV) would otherwise dodge suppression and leak (keyword log
        # 2026-06-17). Full-form match only, so single shared words are untouched.
        if t.normalized.casefold() in self_forms:
            self_suppressed += 1
            continue
        kw = _get_or_create_keyword(
            session, t, language=article.language, extractor=extractor.name
        )
        session.add(
            KeywordMention(
                keyword_id=kw.id,
                article_id=article.id,
                count=t.count,
                first_offset=t.first_offset,
                observed_on=observed_on,
                country=cc,
                city=city,
                extractor=extractor.name,
            )
        )
        # One mention row per (keyword, article): accumulate the new occurrence
        # count so article_count moves by exactly +/-1 per keyword (see
        # _apply_keyword_counter_deltas).
        new_contrib[kw.id] = new_contrib.get(kw.id, 0) + int(t.count)
        written += 1

    # Keep the denormalised counters exact for THIS article's net change.
    _apply_keyword_counter_deltas(session, old_contrib, new_contrib)

    # When x Where x Who at ingest (T12, CONFIRMED GO): persist the deduced
    # dates/places/entities WITH the keyword pass — one hook, so every path
    # that indexes (live ingest, re-index, backfill) anchors them. Lexical
    # and bounded; failures must never abort the keyword indexing.
    www = {"dates": 0, "places": 0, "entities_stored": 0}
    try:
        from src.timemap.datestore import store_for_article as _store_dates
        from src.timemap.whostore import (
            store_entities_for_article as _store_ents,
        )
        from src.timemap.whostore import (
            store_places_for_article as _store_places,
        )

        www["dates"] = _store_dates(session, article)
        www["places"] = _store_places(session, article)
        www["entities_stored"] = _store_ents(session, article)
    except Exception:  # noqa: BLE001 - deductions are a bonus, never a blocker
        _LOG.warning("when/where/who persistence failed for %s", article.id, exc_info=True)
    session.commit()
    return {
        "article_id": article.id,
        "mentions": written,
        "entities": sum(1 for t in terms if t.kind != "term"),
        "self_name_suppressed": self_suppressed,
        **www,
    }


def _unindexed_query(session: Session):
    indexed = session.query(KeywordMention.article_id).distinct()
    return session.query(Article).filter(~Article.id.in_(indexed))


def backfill_corpus(session: Session, *, extractor, limit: int | None = 200) -> dict:
    """Index articles that have no mentions yet, up to ``limit``. Returns progress."""
    q = _unindexed_query(session).order_by(Article.id)
    if limit:
        q = q.limit(limit)
    articles = q.all()

    indexed = 0
    for art in articles:
        try:
            index_article(session, art, extractor=extractor, country=art.country)
            indexed += 1
        except Exception:  # noqa: BLE001 - one bad article must not abort the batch
            session.rollback()
            _LOG.warning("indexing article %s failed", art.id, exc_info=True)
    remaining = _unindexed_query(session).count()
    return {"indexed": indexed, "remaining": remaining}


def reindex_articles(session: Session, *, extractor, article_ids: list[int]) -> dict:
    """Recompute CORE-ENGINE derived metadata for an EXPLICIT set of articles.

    Used after a backup MERGE (maintainer ruling 2026-06-19 P0-4): an imported
    backup may have been produced by an OLDER extraction engine, so its merged-in
    keyword/date/place/entity rows can be misaligned with the CURRENT engine.
    ``index_article`` is delete-then-reinsert per article, so it OVERWRITES those
    rows with current-engine output (keywords, mentions, sentiment, when/where/who).
    AI artifacts (``article_analyses`` summaries/translations + the AI-derived keyword
    rows) are NOT touched by ``index_article``, so they stay verbatim. Idempotent; one
    bad article never aborts the batch (the restore is already committed + additive)."""
    reindexed = 0
    failed = 0
    for aid in article_ids:
        art = session.get(Article, aid)
        if art is None:
            continue
        try:
            index_article(session, art, extractor=extractor, country=art.country)
            reindexed += 1
        except Exception:  # noqa: BLE001 - one bad article must not abort the batch
            session.rollback()
            failed += 1
            _LOG.warning("re-index of imported article %s failed", aid, exc_info=True)
    return {"reindexed": reindexed, "failed": failed}


def backfill_keyword_counters(session: Session) -> dict:
    """Recompute ``Keyword.mention_count`` + ``article_count`` from the live mentions.

    The one-pass authoritative (re)population for an existing corpus — used to seed
    the columns when they are first added, and the repair if the incremental
    maintenance in :func:`index_article` ever drifts. Idempotent: it sets every
    keyword's counters to the live ``SUM(count)`` / ``COUNT(DISTINCT article_id)``
    and ZEROES keywords with no mentions, so a stale counter never lingers. Counts
    only — no score. Returns a small tally."""
    from sqlalchemy import func

    agg = {
        kid: (int(m or 0), int(a or 0))
        for kid, m, a in (
            session.query(
                KeywordMention.keyword_id,
                func.sum(KeywordMention.count),
                func.count(func.distinct(KeywordMention.article_id)),
            ).group_by(KeywordMention.keyword_id)
        )
    }
    # Zero everything first (one bulk UPDATE), then set the keywords that have
    # mentions (one fast bulk-update by primary key).
    session.query(Keyword).update(
        {Keyword.mention_count: 0, Keyword.article_count: 0}, synchronize_session=False
    )
    if agg:
        session.bulk_update_mappings(
            Keyword,
            [
                {"id": kid, "mention_count": m, "article_count": a}
                for kid, (m, a) in agg.items()
            ],
        )
    session.commit()
    total = session.query(func.count(Keyword.id)).scalar() or 0
    return {"keywords": int(total), "with_mentions": len(agg)}
