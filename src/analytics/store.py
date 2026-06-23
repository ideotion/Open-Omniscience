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

    # SECONDARY/DEDUCED language (field §2.6, maintainer ruling Q3): when the
    # authoritative `language` (source/extractor) is absent, deduce it OFFLINE
    # (confidence-gated, never a guess) and store it in `detected_language` WITHOUT
    # touching `language`. `known_lang` (asserted first, then deduced) drives extraction
    # + sentiment + the keyword's analytic language, so a foreign UNTAGGED article gets
    # the RIGHT stoplist instead of leaking its function words as keywords.
    if not (article.language or "").strip() and not (
        getattr(article, "detected_language", None) or ""
    ).strip():
        from src.analytics.langdetect import detect_language

        deduced = detect_language(content)
        if deduced:
            article.detected_language = deduced
    known_lang = (
        (article.language or "").strip()
        or (getattr(article, "detected_language", None) or "").strip()
        or None
    )

    # Sentiment at ingest (language-aware, honest): VADER scores ENGLISH articles
    # and stores the result on the article; every other language stays NULL — never
    # a fabricated neutral. Runs on the one per-article hook, so ingest / re-index /
    # backfill all populate the (previously dead) sentiment columns.
    from src.analytics.sentiment import score_article

    article.sentiment_score, article.sentiment_label = score_article(content, known_lang)

    terms = extractor.extract(
        content or "",
        title=article.title or "",
        language=known_lang or "en",  # extractor needs SOME stoplist; "en" here is an
        # extraction working assumption, never stored as the keyword's language.
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
            session, t, language=known_lang, extractor=extractor.name
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
                source_id=article.source_id,  # denormalised (like observed_on/country)
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
    except Exception as exc:  # noqa: BLE001 - deductions are a bonus, never a blocker
        # A transient 'database is locked' here must NOT be swallowed: doing so
        # leaves the session in a failed-flush state, so the line-below commit
        # then raises "transaction has been rolled back ... Original exception was:
        # database is locked" and the WHOLE article's keyword+WWW indexing is lost
        # (field log 2026-06-17 scheduler rollback). Re-raise lock errors so the
        # caller's run_write_with_retry rolls back and re-runs this idempotent
        # index instead of dropping data. Genuine extraction bugs stay swallowed
        # (a bad date parse must never cost the article its keywords).
        from src.database.write import is_locked_error

        if is_locked_error(exc):
            raise
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


def reindex_all_batch(
    session: Session, *, extractor, limit: int = 300, after_id: int = 0
) -> dict:
    """FORCE-re-index a batch of ALL articles (id > ``after_id``), oldest first.

    Unlike :func:`backfill_corpus` (which skips already-indexed articles), this
    recomputes EVERY article's CORE-ENGINE metadata — needed to drain stale rows an
    OLD engine produced (e.g. the pre-2026-06-20 .eml bodies that leaked bare CSS
    keywords before ``strip_markup`` landed). ``index_article`` is delete-then-reinsert
    per article, so the new engine's output overwrites the old; AI artifacts
    (summaries/translations and the AI-derived keyword rows) are untouched. PAGED:
    returns ``last_id`` so the
    caller loops (after_id=last_id) until ``done``. One bad article never aborts the
    batch. Counts only — no score."""
    rows = (
        session.query(Article.id)
        .filter(Article.id > after_id)
        .order_by(Article.id)
        .limit(max(1, limit))
        .all()
    )
    ids = [r[0] for r in rows]
    reindexed = 0
    failed = 0
    last_id = after_id
    for aid in ids:
        art = session.get(Article, aid)
        last_id = aid
        if art is None:
            continue
        try:
            index_article(session, art, extractor=extractor, country=art.country)
            reindexed += 1
        except Exception:  # noqa: BLE001 - one bad article must not abort the batch
            session.rollback()
            failed += 1
            _LOG.warning("re-index of article %s failed", aid, exc_info=True)
    remaining = (
        session.query(Article.id).filter(Article.id > last_id).count() if ids else 0
    )
    return {
        "reindexed": reindexed,
        "failed": failed,
        "last_id": last_id,
        "remaining": remaining,
        "done": not ids or remaining == 0,
    }


def prune_orphan_keywords(session: Session, *, chunk: int = 500) -> dict:
    """Delete keywords that NO view references — pure garbage collection, never a cap.

    A keyword with ZERO ``KeywordMention`` rows contributes nothing to any analytic
    (every view reads mentions or the counters, which are 0). These accumulate when an
    article is re-indexed/deleted and a term it alone carried drops out — notably after
    the markup re-index drain, where leaked ``<div>``/``font-size`` tokens lose all
    clean mentions. This removes ONLY those inert rows; it never touches a keyword that
    still has mentions, so it is junk-removal, NOT the (rejected) arbitrary cap.

    Curation-safe: a keyword whose ``normalized_term`` is referenced by a family override
    or a super-group member is KEPT even if momentarily mention-less (the user's
    structure must survive). Takes the single-writer gate; chunked under the 999-variable
    limit. Counts only — no score."""
    from sqlalchemy import func, select

    from src.database.models import KeywordFamilyOverride, KeywordSuperGroupMember
    from src.database.writer import write_lock

    total = int(session.query(func.count(Keyword.id)).scalar() or 0)
    # Authoritative orphan test: id NOT present in the mentions table (not the counter,
    # which could be momentarily stale) — one anti-join over the indexed keyword_id.
    mentioned = select(KeywordMention.keyword_id).distinct().scalar_subquery()
    candidate_ids = [
        kid for (kid,) in session.query(Keyword.id).filter(Keyword.id.notin_(mentioned)).all()
    ]
    if not candidate_ids:
        return {"keywords": total, "orphans": 0, "pruned": 0, "kept_curated": 0}

    # Protect curated structure (overrides / super-group members reference the term).
    curated_terms = {
        t for (t,) in session.query(KeywordFamilyOverride.normalized_term).all()
    } | {
        t for (t,) in session.query(KeywordSuperGroupMember.normalized_term).all()
    }
    prunable: list[int] = []
    kept_curated = 0
    for i in range(0, len(candidate_ids), 900):
        batch = candidate_ids[i : i + 900]
        for kid, term in session.query(Keyword.id, Keyword.normalized_term).filter(
            Keyword.id.in_(batch)
        ):
            if term in curated_terms:
                kept_curated += 1
            else:
                prunable.append(kid)

    pruned = 0
    with write_lock():
        for i in range(0, len(prunable), chunk):
            batch = prunable[i : i + chunk]
            try:
                session.query(KeywordTag).filter(KeywordTag.keyword_id.in_(batch)).delete(
                    synchronize_session=False
                )
                pruned += (
                    session.query(Keyword).filter(Keyword.id.in_(batch)).delete(
                        synchronize_session=False
                    )
                    or 0
                )
                session.commit()
            except Exception:  # noqa: BLE001 - one bad chunk must not abort the GC
                session.rollback()
                _LOG.warning("orphan-keyword prune chunk failed", exc_info=True)
    return {
        "keywords": total,
        "orphans": len(candidate_ids),
        "pruned": int(pruned),
        "kept_curated": kept_curated,
    }


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


# How long a reconcile stays trusted as `exact` before the envelope downgrades the
# counters to `estimated` (a rare cascade delete could have drifted them since). The
# incremental maintenance keeps them correct between reconciles, so this is a
# conservative honesty window, not a correctness requirement. OO_COUNTER_FRESH_HOURS.
def _fresh_window_hours() -> int:
    import os

    try:
        return max(1, int(os.getenv("OO_COUNTER_FRESH_HOURS", "24")))
    except ValueError:
        return 24


def reconcile_keyword_counters(session: Session, *, now=None) -> dict:
    """Recompute the counters EXACTLY from the live mentions, detect drift, and stamp
    ``Keyword.last_reconciled_at`` (Slice 2 — the bounded background reconcile).

    This is the authoritative repair for the rare cascade-delete drift
    (``ondelete=CASCADE`` bypasses the incremental maintenance in :func:`index_article`).
    It is the one place a full ``GROUP BY`` over the mentions is paid — OFF the request
    path (the hot endpoints read the counters, never this) — so after it runs the
    counters are proven equal to the canonical store and the honesty envelope can
    disclose them as ``exact``. Counts only, no score. Returns a tally including
    ``drift_repaired`` = how many keyword counters were wrong before this pass.
    """
    from datetime import UTC, datetime

    from sqlalchemy import func

    stamp = now or datetime.now(UTC)
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
    # Detect drift: compare every keyword's CURRENT counters to the recomputed truth.
    # O(keywords) (a small-row scan of the keywords table), never a per-keyword mention
    # scan — and runs in the background, not on a read.
    drift = 0
    for kid, cur_m, cur_a in session.query(
        Keyword.id, Keyword.mention_count, Keyword.article_count
    ):
        if (int(cur_m or 0), int(cur_a or 0)) != agg.get(kid, (0, 0)):
            drift += 1
    # Repair: zero all, set the keywords that have mentions, stamp the watermark on
    # EVERY keyword (so a never-mentioned keyword is also "verified 0 as of now").
    session.query(Keyword).update(
        {Keyword.mention_count: 0, Keyword.article_count: 0, Keyword.last_reconciled_at: stamp},
        synchronize_session=False,
    )
    if agg:
        session.bulk_update_mappings(
            Keyword,
            [
                {"id": kid, "mention_count": m, "article_count": a, "last_reconciled_at": stamp}
                for kid, (m, a) in agg.items()
            ],
        )
    session.commit()
    total = session.query(func.count(Keyword.id)).scalar() or 0
    return {
        "keywords": int(total),
        "with_mentions": len(agg),
        "drift_repaired": int(drift),
        "as_of": stamp.isoformat(timespec="seconds"),
    }


def counter_envelope(session: Session, *, window_hours: int | None = None, now=None):
    """The honesty envelope (Slice 1) over the maintained keyword counters (Slice 2).

    Cheap (``O(keywords)`` — never a mention scan): the hot endpoints call this to
    disclose their counter-backed numbers as ``exact`` vs ``estimated``. The envelope's
    ``value`` is the number of keywords whose counters back the view (``n``); its
    ``basis`` is:

      * ``exact``     — every keyword-with-mentions was reconciled within the freshness
        window (the counters are verified equal to the canonical store);
      * ``estimated`` — some keyword is unreconciled (NULL watermark) or its last
        reconcile is stale, so the counters MAY have drifted (cascade delete) and are an
        honest best-effort.

    ``as_of`` is real, never fabricated: the reconcile watermark when known, else the
    serve time for an as-yet-unverified maintained snapshot.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func

    from src.analytics.envelope import Envelope, now_iso

    win = window_hours if window_hours is not None else _fresh_window_hours()
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=win)

    n = int(session.query(func.count(Keyword.id)).filter(Keyword.mention_count > 0).scalar() or 0)
    method = (
        "denormalised per-keyword counters maintained at index time; "
        "reconciled exactly against the corpus in the background"
    )
    if n == 0:
        # No counters back anything yet — an empty/fresh corpus. Honest, computed now.
        return Envelope.exact(0, as_of=now_iso(), method=method, n=0)

    # Is any keyword-with-mentions unreconciled or stale? Short-circuits (LIMIT 1).
    stale = (
        session.query(Keyword.id)
        .filter(Keyword.mention_count > 0)
        .filter(
            (Keyword.last_reconciled_at.is_(None)) | (Keyword.last_reconciled_at < cutoff)
        )
        .first()
    )
    # The reconcile watermark = the OLDEST verification among counter-backing keywords
    # (min ignores NULLs in SQL; we already detected NULLs via `stale`).
    watermark = (
        session.query(func.min(Keyword.last_reconciled_at))
        .filter(Keyword.mention_count > 0)
        .scalar()
    )
    if stale is not None:
        # Estimated: as_of = the last KNOWN-exact reconcile time if one exists ("exact
        # as of then, may have drifted since"), else the serve time (never reconciled).
        as_of = watermark.isoformat(timespec="seconds") if watermark else now_iso()
        return Envelope.estimated(n, as_of=as_of, method=method, n=n)
    return Envelope.exact(n, as_of=watermark.isoformat(timespec="seconds"), method=method, n=n)


def maybe_reconcile_counters(session: Session) -> dict:
    """Run :func:`reconcile_keyword_counters` only when the counters are NOT fresh.

    The bounded background trigger (called where ``warm_cache`` runs, after a scrape
    pass — OFF the request path). When the envelope already reports ``exact`` this is a
    cheap no-op, so it naturally throttles to roughly once per freshness window. Returns
    the reconcile tally, or ``{"skipped": "fresh"}`` when nothing needed repair.
    """
    if counter_envelope(session).is_exact():
        return {"skipped": "fresh"}
    try:
        return reconcile_keyword_counters(session)
    except Exception:  # noqa: BLE001 - a background safety net must never break the pass
        session.rollback()
        _LOG.warning("background keyword-counter reconcile failed", exc_info=True)
        return {"skipped": "error"}
