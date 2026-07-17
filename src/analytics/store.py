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
from src.database.models import Article, Keyword, KeywordMention, KeywordTag, Source

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
    scope: str = "full",
    commit: bool = True,
) -> dict:
    """Extract + store mentions for one article (idempotent). Returns a small tally.

    ``scope`` (keyword-engine Phase 1.2): ``"full"`` (default) recomputes keywords +
    when/where/who (dates/places/entities) + sentiment; ``"keywords"`` does the keyword
    pass ONLY and leaves the dates/places/entities + sentiment untouched — ≈⅔ less work
    for a keyword-only cleanup. The language deduction stays in BOTH (it picks the
    extraction stoplist + the keyword's analytic language).

    ``commit`` (keyword-engine Phase 1.3, COLLECTOR_WRITER_BATCHING.md): ``True``
    (default) commits this article's work — byte-identical to every existing caller.
    ``False`` leaves the mentions + counter deltas (+ when/where/who) PENDING in the
    session so a caller can batch several articles into ONE commit (one fsync). Because
    the counter deltas accumulate read-your-own-writes within a single transaction, a
    batched commit equals the sum of the per-article commits exactly. A batching caller
    MUST provide the proven rollback-then-redo-per-article fallback on a commit failure
    (see :func:`reindex_all_batch`) so a collision/lock never drops a batch-mate."""
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
    # backfill all populate the (previously dead) sentiment columns. Skipped in the
    # keyword-only scope (a keyword cleanup leaves sentiment untouched).
    if scope != "keywords":
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
    # Capture BEFORE the try block: a flush failure inside it expires every ORM
    # object in the session (SQLAlchemy's default post-rollback behaviour), so
    # re-touching `article.id` from the except handler below would itself need a
    # fresh query against a transaction that may no longer be usable -- exactly
    # the "Can't operate on closed transaction" cascade from the field report
    # below. `article.id` is safe to read now: it was already resolved earlier
    # in this same call (the keyword-mention inserts above reference it).
    article_id = article.id
    try:
        if scope != "keywords":  # keyword-only cleanup skips the when/where/who passes
            from src.timemap.datestore import store_for_article as _store_dates
            from src.timemap.whostore import (
                store_entities_for_article as _store_ents,
            )
            from src.timemap.whostore import (
                store_places_for_article as _store_places,
            )

            # Isolated in its OWN savepoint (field bug 2026-07-15): a flush failure
            # here -- e.g. an unrelated pending row elsewhere in the session
            # autoflushing into a UNIQUE collision (seen with a law-tracking
            # revision racing a large corpus import) -- used to leave the
            # session's transaction marked "needs rollback" even though this
            # function's except below caught the Python exception. Every later
            # operation on the SAME session then raised a cascading
            # PendingRollbackError, burying the real cause under confusing
            # secondary tracebacks. A savepoint lets a WWW-pass failure roll back
            # on its own without touching the keyword mentions already added
            # above in this same transaction.
            with session.begin_nested():
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
        # (a bad date parse must never cost the article its keywords) -- the
        # savepoint above already rolled itself back, so the session is healthy
        # again by the time we get here.
        from src.database.write import is_locked_error

        if is_locked_error(exc):
            raise
        _LOG.warning("when/where/who persistence failed for %s", article_id, exc_info=True)
    if commit:
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
    # Re-index is delete-then-reinsert, so the disposable columnar rollup must FULL-rebuild
    # rather than incrementally merge (the D3 double-count guard). This is ALSO the
    # restore-merge path: reindex_imported_articles re-indexes the merged articles against
    # the live DB after the atomic swap, so bumping here covers restore too. Best-effort.
    if article_ids:
        from src.analytics.corpus_epoch import bump_corpus_epoch

        bump_corpus_epoch(session, reason="reindex_articles")
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
    session: Session,
    *,
    extractor,
    limit: int = 300,
    after_id: int = 0,
    scope: str = "full",
    commit_batch: int = 1,
) -> dict:
    """FORCE-re-index a batch of ALL articles (id > ``after_id``), oldest first.

    Unlike :func:`backfill_corpus` (which skips already-indexed articles), this
    recomputes EVERY article's CORE-ENGINE metadata — needed to drain stale rows an
    OLD engine produced (e.g. the pre-2026-06-20 .eml bodies that leaked bare CSS
    keywords before ``strip_markup`` landed). ``index_article`` is delete-then-reinsert
    per article, so the new engine's output overwrites the old; AI artifacts
    (summaries/translations and the AI-derived keyword rows) are untouched. PAGED:
    returns ``last_id`` so the caller loops (after_id=last_id) until ``done``. One bad
    article never aborts the batch. Counts only — no score.

    ``commit_batch`` (keyword-engine Phase 1.3, COLLECTOR_WRITER_BATCHING.md): >1 commits
    every N articles instead of once per article — fewer fsyncs through the encrypted
    writer on a big re-index. Default 1 = the per-article behaviour, byte-identical. NO
    DATA LOSS: a batch-commit failure (a transient lock) OR an error building one
    article's mentions rolls the batch back and REDOES it one article at a time (each
    committed, a bad/locked one isolated) — the proven ``ingest_emails`` fallback;
    re-index is idempotent, so the redo reproduces the full result. The single-writer
    gate is HELD across a batch, so keep ``commit_batch`` modest for a background re-index
    that must interleave with a live scrape."""
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
    commit_batch = max(1, commit_batch)

    # Bump the corpus epoch ONCE per non-empty batch: re-index is delete-then-reinsert,
    # so the disposable columnar rollup must FULL-rebuild rather than incrementally merge
    # this batch (the D3 double-count guard). Done here (before the loop, no pending
    # writes) so a partially-failing batch still forces the rebuild. Best-effort.
    if ids:
        from src.analytics.corpus_epoch import bump_corpus_epoch

        bump_corpus_epoch(session, reason="reindex_all_batch")

    def _reindex_one(aid: int, *, commit: bool) -> bool:
        """Index one article: True if re-indexed, False if it was missing (deleted
        mid-run). ``commit=False`` lets a failure PROPAGATE so the batch handler can roll
        back and redo per-article; ``commit=True`` callers catch to isolate one article."""
        art = session.get(Article, aid)
        if art is None:
            return False
        index_article(session, art, extractor=extractor, country=art.country, scope=scope, commit=commit)
        return True

    def _redo_committed(aids: list[int]) -> None:
        """Re-index each article one-at-a-time, COMMITTED — the no-loss fallback after a
        batch rollback. A bad/locked article is isolated (rollback + failed++), never
        dropping its batch-mates (idempotent re-index reproduces the full result)."""
        nonlocal reindexed, failed
        for baid in aids:
            try:
                if _reindex_one(baid, commit=True):
                    reindexed += 1
            except Exception:  # noqa: BLE001 - isolate one bad/locked article
                session.rollback()
                failed += 1
                _LOG.warning("re-index of article %s failed (redo)", baid, exc_info=True)

    if commit_batch <= 1:
        for aid in ids:
            last_id = aid
            try:
                if _reindex_one(aid, commit=True):
                    reindexed += 1
            except Exception:  # noqa: BLE001 - one bad article must not abort the batch
                session.rollback()
                failed += 1
                _LOG.warning("re-index of article %s failed", aid, exc_info=True)
    else:
        pending: list[int] = []

        def _flush() -> None:
            nonlocal reindexed
            if not pending:
                return
            try:
                session.commit()
                reindexed += len(pending)
            except Exception:  # noqa: BLE001 - a lock/collision must not drop batch-mates
                session.rollback()
                _redo_committed(list(pending))
            pending.clear()

        for aid in ids:
            last_id = aid
            try:
                if _reindex_one(aid, commit=False):
                    pending.append(aid)
            except Exception:  # noqa: BLE001 - this article corrupted the in-flight batch
                # Roll back (drops this article's partial work AND the uncommitted batch),
                # redo the accumulated batch per-article (committed), count this one failed.
                session.rollback()
                redo = list(pending)
                pending.clear()
                _redo_committed(redo)
                failed += 1
                _LOG.warning("re-index of article %s failed (batch)", aid, exc_info=True)
                continue
            if len(pending) >= commit_batch:
                _flush()
        _flush()
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


# --------------------------------------------------------------------------- #
# P1.12 (SCALE_ROADMAP 2026-07-09): the background maintenance passes — counter
# reconcile (measured 86–104 s/pass) and orphan prune (32 s of full counts) at
# 3.06 M keywords — carry an INTERNAL soft deadline + a RESUMABLE watermark, so a
# pass stops cleanly at its budget, persists where it got to (a ``derived_meta``
# row — in the corpus, so it survives restarts and travels with backups), and the
# next pass resumes instead of re-scanning from zero. Partial state is never
# silent: the reconcile stamps ONLY the keywords it verified (the counter
# envelope keeps disclosing ``estimated`` until a sweep completes within the
# freshness window) and both tallies report ``complete``/``resumed_from_id``.
# --------------------------------------------------------------------------- #

RECONCILE_CURSOR_KEY = "counter_reconcile_cursor"
PRUNE_CURSOR_KEY = "orphan_prune_cursor"
# Keyword ids per slice (module-level so tests can shrink them to exercise the resume).
_RECONCILE_SCAN_CHUNK = 50_000
_PRUNE_SCAN_CHUNK = 20_000


def _maint_budget_s(env: str, default: float = 30.0) -> float:
    """The soft per-pass budget in seconds (0 or negative = unbounded)."""
    import os

    try:
        return float(os.getenv(env, str(default)))
    except ValueError:
        return default


def _cursor_get(session: Session, key: str) -> int:
    """The persisted resume watermark (0 = start of the keyword table). Degrades to 0
    on any doubt — a lost cursor only costs a re-scan, never a wrong number."""
    from src.database.models import DerivedMeta

    try:
        raw = session.query(DerivedMeta.value).filter(DerivedMeta.key == key).scalar()
        return int(raw) if raw is not None else 0
    except Exception:  # noqa: BLE001 - a coordination read must never break the pass
        return 0


def _cursor_set(session: Session, key: str, value: int) -> None:
    """Persist the watermark (0 clears it back to 'sweep from the start'). Joins the
    caller's transaction; the caller commits. Best-effort by design."""
    from datetime import UTC, datetime

    from src.database.models import DerivedMeta

    try:
        row = session.get(DerivedMeta, key)
        if row is None:
            session.add(DerivedMeta(key=key, value=str(int(value)), updated_at=datetime.now(UTC)))
        else:
            row.value = str(int(value))
            row.updated_at = datetime.now(UTC)
    except Exception:  # noqa: BLE001 - a coordination write must never break the pass
        _LOG.warning("maintenance cursor write failed (%s)", key, exc_info=True)


def prune_orphan_keywords(session: Session, *, chunk: int = 500, budget_s: float | None = None) -> dict:
    """Delete keywords that NO view references — pure garbage collection, never a cap.

    A keyword with ZERO ``KeywordMention`` rows contributes nothing to any analytic
    (every view reads mentions or the counters, which are 0). These accumulate when an
    article is re-indexed/deleted and a term it alone carried drops out — notably after
    the markup re-index drain, where leaked ``<div>``/``font-size`` tokens lose all
    clean mentions. This removes ONLY those inert rows; it never touches a keyword that
    still has mentions, so it is junk-removal, NOT the (rejected) arbitrary cap.

    Curation-safe: a keyword whose ``normalized_term`` is referenced by a family override
    or a super-group member is KEPT even if momentarily mention-less (the user's
    structure must survive). Takes the single-writer gate per slice; chunked under the
    999-variable limit. Counts only — no score.

    P1.12: the scan walks the keyword table in id-ordered SLICES (each slice's orphan
    test is one covering-index range scan of the mentions table — never the old
    whole-table anti-join + full count, the measured 32 s at 3.06 M keywords) under a
    soft DEADLINE (``budget_s``, default ``OO_PRUNE_BUDGET_S`` = 30 s; <= 0 unbounded).
    A pass that hits its budget stops cleanly, persists its watermark (``derived_meta``
    ``orphan_prune_cursor``) and reports ``complete: false``; the next pass RESUMES
    there. Correctness does not depend on the cursor: a keyword skipped this pass is
    simply pruned by a later sweep."""
    import time as _time

    from src.database.models import KeywordFamilyOverride, KeywordSuperGroupMember
    from src.database.writer import write_lock

    budget = budget_s if budget_s is not None else _maint_budget_s("OO_PRUNE_BUDGET_S")
    scan_chunk = _PRUNE_SCAN_CHUNK  # ids per slice (one mention index range scan each)
    t0 = _time.monotonic()

    after_id = _cursor_get(session, PRUNE_CURSOR_KEY)
    resumed_from = after_id
    # Protect curated structure (overrides / super-group members reference the term).
    curated_terms = {
        t for (t,) in session.query(KeywordFamilyOverride.normalized_term).all()
    } | {
        t for (t,) in session.query(KeywordSuperGroupMember.normalized_term).all()
    }

    scanned = 0
    orphans = 0
    pruned = 0
    kept_curated = 0
    epoch_bumped = False
    complete = False
    while True:
        ids = [
            kid
            for (kid,) in session.query(Keyword.id)
            .filter(Keyword.id > after_id)
            .order_by(Keyword.id)
            .limit(scan_chunk)
        ]
        if not ids:
            complete = True
            break
        lo, hi = after_id, ids[-1]
        # Authoritative orphan test for the slice: which of these ids appear in the
        # mentions table (covering (keyword_id, article_id) index range scan — not the
        # counter, which could be momentarily stale).
        mentioned = {
            kid
            for (kid,) in session.query(KeywordMention.keyword_id)
            .filter(KeywordMention.keyword_id > lo, KeywordMention.keyword_id <= hi)
            .distinct()
        }
        candidates = [kid for kid in ids if kid not in mentioned]
        orphans += len(candidates)
        prunable: list[int] = []
        if candidates:
            for i in range(0, len(candidates), 900):
                batch = candidates[i : i + 900]
                for kid, term in session.query(Keyword.id, Keyword.normalized_term).filter(
                    Keyword.id.in_(batch)
                ):
                    if term in curated_terms:
                        kept_curated += 1
                    else:
                        prunable.append(kid)
        # Pruning DELETES mention-less keyword rows, so the disposable columnar rollup
        # must FULL-rebuild rather than incrementally merge (the D3 double-count guard).
        # Bump once per pass, before the first delete, only when something is pruned.
        if prunable and not epoch_bumped:
            from src.analytics.corpus_epoch import bump_corpus_epoch

            bump_corpus_epoch(session, reason="prune_orphan_keywords")
            epoch_bumped = True
        if prunable:
            with write_lock():
                for i in range(0, len(prunable), chunk):
                    batch = prunable[i : i + chunk]
                    try:
                        session.query(KeywordTag).filter(
                            KeywordTag.keyword_id.in_(batch)
                        ).delete(synchronize_session=False)
                        pruned += (
                            session.query(Keyword)
                            .filter(Keyword.id.in_(batch))
                            .delete(synchronize_session=False)
                            or 0
                        )
                        session.commit()
                    except Exception:  # noqa: BLE001 - one bad chunk must not abort the GC
                        session.rollback()
                        _LOG.warning("orphan-keyword prune chunk failed", exc_info=True)
        scanned += len(ids)
        after_id = hi
        # Persist the watermark WITH the slice (the resume point survives a restart).
        _cursor_set(session, PRUNE_CURSOR_KEY, after_id)
        session.commit()
        if budget > 0 and _time.monotonic() - t0 > budget:
            break  # soft deadline: stop cleanly; the cursor resumes the sweep next pass
    if complete:
        _cursor_set(session, PRUNE_CURSOR_KEY, 0)
        session.commit()
    return {
        "keywords": scanned,  # scanned THIS pass (never the old 32 s whole-table count)
        "orphans": orphans,
        "pruned": int(pruned),
        "kept_curated": kept_curated,
        "complete": complete,
        "resumed_from_id": resumed_from,
        "cursor_id": 0 if complete else after_id,
        "budget_s": budget,
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


def reconcile_keyword_counters(
    session: Session, *, now=None, budget_s: float | None = None
) -> dict:
    """Recompute the counters EXACTLY from the live mentions, detect drift, and stamp
    ``Keyword.last_reconciled_at`` (Slice 2 — the bounded background reconcile).

    This is the authoritative repair for the rare cascade-delete drift
    (``ondelete=CASCADE`` bypasses the incremental maintenance in :func:`index_article`).
    It is the one place a ``GROUP BY`` over the mentions is paid — OFF the request path
    (the hot endpoints read the counters, never this) — so after a sweep completes the
    counters are proven equal to the canonical store and the honesty envelope can
    disclose them as ``exact``. Counts only, no score. Returns a tally including
    ``drift_repaired`` = how many keyword counters were wrong in the swept range.

    P1.12 (measured 86–104 s/pass at 3.06 M keywords): the sweep walks the keyword table
    in id-ordered SLICES — each slice one covering-index range GROUP BY over the mentions,
    never the whole-table scan — under a soft DEADLINE (``budget_s``, default
    ``OO_RECONCILE_BUDGET_S`` = 30 s; <= 0 unbounded). A pass that hits its budget stops
    cleanly, persists its watermark (``derived_meta`` ``counter_reconcile_cursor``) and
    reports ``complete: false``; the next pass RESUMES there. PARTIAL STATE IS NEVER
    SILENT: only the keywords a pass actually verified get stamped, so
    :func:`counter_envelope` keeps disclosing ``estimated`` until a whole sweep lands
    within the freshness window — half-reconciled counters can never masquerade as
    ``exact`` (the envelope/basis discipline)."""
    import time as _time
    from datetime import UTC, datetime

    from sqlalchemy import func

    stamp = now or datetime.now(UTC)
    budget = budget_s if budget_s is not None else _maint_budget_s("OO_RECONCILE_BUDGET_S")
    scan_chunk = _RECONCILE_SCAN_CHUNK
    t0 = _time.monotonic()

    after_id = _cursor_get(session, RECONCILE_CURSOR_KEY)
    resumed_from = after_id
    scanned = 0
    with_mentions = 0
    drift = 0
    complete = False
    while True:
        ids = [
            kid
            for (kid,) in session.query(Keyword.id)
            .filter(Keyword.id > after_id)
            .order_by(Keyword.id)
            .limit(scan_chunk)
        ]
        if not ids:
            complete = True
            break
        lo, hi = after_id, ids[-1]
        # The slice's truth: one covering-index range GROUP BY over the mentions. Every
        # keyword id in (lo, hi] is in `ids` (consecutive ordered ids), so the range
        # filter is exactly this slice.
        agg = {
            kid: (int(m or 0), int(a or 0))
            for kid, m, a in (
                session.query(
                    KeywordMention.keyword_id,
                    func.sum(KeywordMention.count),
                    func.count(func.distinct(KeywordMention.article_id)),
                )
                .filter(KeywordMention.keyword_id > lo, KeywordMention.keyword_id <= hi)
                .group_by(KeywordMention.keyword_id)
            )
        }
        # Detect drift within the slice (small-row keyword scan, background only).
        for kid, cur_m, cur_a in session.query(
            Keyword.id, Keyword.mention_count, Keyword.article_count
        ).filter(Keyword.id > lo, Keyword.id <= hi):
            if (int(cur_m or 0), int(cur_a or 0)) != agg.get(kid, (0, 0)):
                drift += 1
        # Repair the slice: zero + stamp everything in range (a never-mentioned keyword
        # is also "verified 0 as of now"), then set the keywords that have mentions.
        session.query(Keyword).filter(Keyword.id > lo, Keyword.id <= hi).update(
            {
                Keyword.mention_count: 0,
                Keyword.article_count: 0,
                Keyword.last_reconciled_at: stamp,
            },
            synchronize_session=False,
        )
        if agg:
            session.bulk_update_mappings(
                Keyword,
                [
                    {
                        "id": kid,
                        "mention_count": m,
                        "article_count": a,
                        "last_reconciled_at": stamp,
                    }
                    for kid, (m, a) in agg.items()
                ],
            )
        scanned += len(ids)
        with_mentions += len(agg)
        after_id = hi
        # Persist the watermark WITH the slice's repair (one commit; the resume point
        # survives an app restart and travels with the corpus).
        _cursor_set(session, RECONCILE_CURSOR_KEY, after_id)
        session.commit()
        if budget > 0 and _time.monotonic() - t0 > budget:
            break  # soft deadline: stop cleanly; the stamps above disclose the partial
    if complete:
        _cursor_set(session, RECONCILE_CURSOR_KEY, 0)
        session.commit()
    return {
        "keywords": scanned,  # scanned THIS pass (a sweep may span several passes)
        "with_mentions": with_mentions,
        "drift_repaired": int(drift),
        "as_of": stamp.isoformat(timespec="seconds"),
        "complete": complete,
        "resumed_from_id": resumed_from,
        "cursor_id": 0 if complete else after_id,
        "budget_s": budget,
    }


def reconcile_source_counters(session: Session, *, now=None) -> dict:
    """Recompute ``Source.article_count`` EXACTLY from articles (one ``GROUP BY source_id``)
    and stamp ``counter_reconciled_at`` (S6). The authoritative repair + initial population
    for the maintained per-source counter that ``source_io/sources`` + the reader read instead
    of a live per-source ``COUNT(*)``.

    CHEAP by design: sources are few (hundreds–thousands, not the 3 M keywords), so this is one
    grouped scan + a bulk update — no cursor/budget needed. NEVER a ``keyword_mentions ->
    articles`` join (the codec column-order trap): it counts on the indexed
    ``Article.source_id`` only. Counts only, no score. Returns ``{sources, drift_repaired}``.
    """
    from datetime import UTC, datetime

    from sqlalchemy import func

    stamp = now or datetime.now(UTC)
    live: dict[int, int] = {
        sid: cnt
        for sid, cnt in session.query(Article.source_id, func.count(Article.id))
        .group_by(Article.source_id)
        .all()
    }
    drift = 0
    sources = session.query(Source).all()
    for src in sources:
        want = int(live.get(src.id, 0))
        if src.article_count != want:  # includes NULL -> a first population counts as drift
            drift += 1
        src.article_count = want
        src.counter_reconciled_at = stamp
    session.commit()
    return {
        "sources": len(sources),
        "drift_repaired": drift,
        "reconciled_at": stamp.isoformat(),
    }


def source_counter_envelope(session: Session, source, *, fresh_within_hours: float = 24.0) -> dict:
    """The honesty envelope ``{value, basis, as_of, n, method}`` for ONE source's article count.

    Reads the maintained counter; a NULL counter (never reconciled) FALLS BACK to a live
    ``COUNT(*)`` on the indexed ``Article.source_id`` (``basis: "live"`` — never wrong, just
    computed now). A populated counter is ``exact`` within the freshness window, else
    ``estimated`` (stale but disclosed with its ``as_of``). No score.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func

    if source.article_count is None:
        n = int(
            session.query(func.count(Article.id))
            .filter(Article.source_id == source.id)
            .scalar()
            or 0
        )
        return {"value": n, "basis": "live", "as_of": None, "n": n,
                "method": "live COUNT(*) on Article.source_id (counter not yet reconciled)"}
    ra = source.counter_reconciled_at
    fresh = False
    as_of = None
    if ra is not None:
        aware = ra if ra.tzinfo is not None else ra.replace(tzinfo=UTC)
        as_of = aware.isoformat()
        fresh = (datetime.now(UTC) - aware) < timedelta(hours=fresh_within_hours)
    val = int(source.article_count)
    return {"value": val, "basis": "exact" if fresh else "estimated", "as_of": as_of, "n": val,
            "method": "maintained per-source article counter (reconciled from Article.source_id)"}


def reconcile_keyword_language(
    session: Session, *, min_articles: int = 2
) -> dict:
    """Set ``Keyword.language`` to the SIGNATURE-MAJORITY article language — the fix for
    the first-write-wins language that ``index_article`` never reconciles (keyword-engine
    P4.2; the 16% / 40%-of-head mismatch). A background pass, mirroring
    :func:`reconcile_keyword_counters`: off the request path, counts only, no score.

    Effective language of a keyword = the language of the ARTICLES that mention it,
    by distinct-article majority — the same signal :func:`queries._ring_lang_of` uses for
    ring membership, but written back so the stored tag becomes truthful (and gates
    correct grouping + the later lemmatization, P4.3). A correction only happens with a
    CLEAR majority (``> half`` of the keyword's located mentions) backed by
    ``>= min_articles`` distinct articles, so a single stray article never flips a tag.

    PERF (the SQLCipher codec column-order trap, ledger): NEVER the per-row
    ``keyword_mentions -> articles`` join to read ``Article.language`` (that drags whole
    ~35 KB article rows through the codec). Instead a covering article-language map (via
    ``idx_article_language``) + a covering ``(keyword_id, article_id)`` mention scan, joined
    in Python. There is exactly one mention per ``(keyword, article)`` (the unique index),
    so a per-(keyword, language) row COUNT already equals COUNT(DISTINCT article_id).

    Keywords whose mentions are ALL in untagged ("?") articles are LEFT as-is — the
    query-time ``global_stopwords`` already routes every keyword (incl. unknown-language)
    through the English + all-language stoplist, so "?" boilerplate is filtered there; an
    aggressive email/web boilerplate denylist stays the evidence-driven stoplist process
    (never a guess, per the no-over-stoplist discipline). Returns a small tally."""
    # 1) article id -> language for LOCATED articles only (covering idx_article_language;
    # no content read). Empty corpus / all-untagged -> nothing to reconcile.
    art_lang: dict[int, str] = {}
    for aid, lang in session.query(Article.id, Article.language).filter(
        Article.language.isnot(None), Article.language != ""
    ):
        art_lang[int(aid)] = lang
    if not art_lang:
        return {"keywords_with_signature": 0, "relanguaged": 0, "null_to_lang": 0, "lang_to_lang": 0}

    # 2) per-keyword language distribution (count == distinct articles, one mention per
    # (keyword, article)). Covering (keyword_id, article_id) scan, streamed to bound RAM.
    dist: dict[int, dict[str, int]] = {}
    q = session.query(KeywordMention.keyword_id, KeywordMention.article_id)
    for kid, aid in q.yield_per(20000):
        lang = art_lang.get(int(aid))
        if lang is None:
            continue
        d = dist.setdefault(int(kid), {})
        d[lang] = d.get(lang, 0) + 1

    # 3) decide the signature per keyword + collect the changes vs the stored language.
    relanguaged = null_to_lang = lang_to_lang = 0
    updates: list[dict] = []
    for kid, stored in session.query(Keyword.id, Keyword.language):
        langs = dist.get(int(kid))
        if not langs:
            continue
        total = sum(langs.values())
        sig_lang, sig_n = max(langs.items(), key=lambda kv: kv[1])
        # A clear majority (> half), backed by enough distinct articles.
        if sig_n < min_articles or sig_n * 2 <= total:
            continue
        if (stored or None) == sig_lang:
            continue
        updates.append({"id": int(kid), "language": sig_lang})
        relanguaged += 1
        if stored:
            lang_to_lang += 1
        else:
            null_to_lang += 1
    if updates:
        session.bulk_update_mappings(Keyword, updates)
        session.commit()
    return {
        "keywords_with_signature": len(dist),
        "relanguaged": relanguaged,
        "null_to_lang": null_to_lang,
        "lang_to_lang": lang_to_lang,
    }


def reconcile_keyword_entity_status(session: Session) -> dict:
    """Downgrade a keyword's stale ``is_entity`` flag when it can no longer be a
    valid acronym under the CURRENT extraction rule (audit finding 2026-07-17).

    ``_get_or_create_keyword`` only ever UPGRADES a keyword (term -> entity, when a
    later mention is recognised as one); there was no corresponding downgrade, so a
    ``Keyword`` row created under the PRE-2026-06-16 rule (any Title-Case word) --
    or one whose ``normalized_term`` simply no longer matches the acronym shape --
    stays flagged an entity FOREVER, even across a full re-index (the same
    ``_get_or_create_keyword`` chokepoint every re-index path calls). This mirrors
    :func:`reconcile_keyword_language`: a background pass, off the request path,
    counts only, no score.

    SCOPE (deliberately conservative): only ``entity_type == "entity"`` rows -- the
    GENERIC acronym bucket ``_entities()`` assigns when a term is NOT a gazetteer
    match (see extract.py's ``kind=self.gazetteer.get(norm.casefold(), "entity")``).
    A gazetteer-matched named entity (``entity_type`` "person"/"org"/"location") is
    a DIFFERENT, still-valid signal (gazetteer membership, never governed by the
    Title-Case/acronym rule this fix targets) and is intentionally left untouched.

    HONEST LIMITATION: the acronym rule's "not adjacent to another all-caps word"
    check is CONTEXT-dependent (it needs the surrounding article text, which would
    mean re-decrypting content through the SQLCipher codec for every candidate --
    the exact perf trap this codebase avoids elsewhere). This pass only re-checks
    the SHAPE-only, context-free part of the rule (an all-caps token of length >= 2,
    not a known non-acronym/CTA/accented-Latin/multi-transition-code false
    positive) against the keyword's own stored ``normalized_term`` -- a keyword that
    fails even that shape check can NEVER be a valid acronym under ANY context, so
    downgrading it is always correct. It does NOT attempt to re-derive the
    headline-adjacency exclusion (which could, in principle, also downgrade a
    genuinely valid acronym that only failed because of its original sentence
    position) -- that half of the rule is left to a full re-index, which already
    re-runs the whole extractor over the real text.
    """
    from src.analytics.extract import (
        _ACCENTED_LATIN_RE,
        _ACRONYM_STOP,
        _CTA_STOP,
        _is_caps_run_word,
        _is_code_token,
    )

    def _fails_the_shape_check(term: str) -> bool:
        if not _is_caps_run_word(term):
            return True
        cf = term.casefold()
        if cf in _ACRONYM_STOP or cf in _CTA_STOP:
            return True
        if _ACCENTED_LATIN_RE.search(term) or _is_code_token(term):
            return True
        return False

    checked = downgraded = 0
    updates: list[dict] = []
    for kid, term in session.query(Keyword.id, Keyword.normalized_term).filter(
        Keyword.is_entity.is_(True), Keyword.entity_type == "entity"
    ):
        checked += 1
        if _fails_the_shape_check(term):
            updates.append({"id": int(kid), "is_entity": False, "entity_type": None})
            downgraded += 1
    if updates:
        session.bulk_update_mappings(Keyword, updates)
        session.commit()
    return {"checked": checked, "downgraded": downgraded}


def _keyword_majority_language(
    langs: dict[str, int] | None, *, min_keywords: int
) -> str | None:
    """Pick an article's DEDUCED language from the languages of its indexed keywords.

    ``langs`` maps ``language -> number of the article's language-tagged keywords in it``.
    Returns a language only on a CLEAR majority — ``> half`` of the tagged keywords agree
    AND the winning language is backed by ``>= min_keywords`` keywords — so it is
    evidence, never a guess; a tie or too-few keywords returns ``None`` (honest unknown)."""
    if not langs:
        return None
    total = sum(langs.values())
    sig_lang, sig_n = max(langs.items(), key=lambda kv: kv[1])
    if sig_n < min_keywords or sig_n * 2 <= total:
        return None
    return sig_lang


def reconcile_article_language(
    session: Session,
    *,
    limit: int = 300,
    after_id: int = 0,
    min_keywords: int = 3,
) -> dict:
    """Backfill the DEDUCED language of UNKNOWN articles (maintainer ask 2026-07-02).

    An "unknown" article has NEITHER an asserted ``language`` (source/extractor) NOR a
    ``detected_language`` (the offline detector). ``index_article`` deduces a language at
    ingest, but it is forward-only and confidence-gated, so (a) articles ingested before
    that existed and (b) articles the text detector could not resolve (too short / low
    confidence) stay unknown. This pass assigns a language to those, storing it ONLY in
    ``detected_language`` (the DEDUCED channel) — the asserted ``language`` is NEVER
    written, preserving the two-class asserted-vs-deduced model.

    TWO-TIER deduction, most-reliable first:
      1. TEXT — :func:`~src.analytics.langdetect.detect_language` over the article content
         (the confidence-gated offline detector). This is the same signal ingest uses.
      2. KEYWORDS (the maintainer's suggested fallback, only when text fails) — the
         DOMINANT language among the article's own indexed keywords' languages, gated on a
         real majority (``> half`` agree AND ``>= min_keywords`` keywords) so it is a
         measured signal, not a guess. A keyword's language is itself a deduced signal
         (reconciled by :func:`reconcile_keyword_language`), so this stays in the deduced
         channel by construction. Truly undeterminable articles are LEFT unknown (honest).

    PERF (the SQLCipher codec column-order trap, ledger): NEVER a
    ``keyword_mentions -> articles`` join to read a keyword's language (that drags whole
    ~35 KB article rows through the codec). Instead a small covering ``Keyword.id ->
    language`` map + a covering ``(article_id, keyword_id)`` mention scan restricted to the
    candidate batch, joined in Python. The per-article CONTENT read for the text detector
    is unavoidable, so the pass is BOUNDED + RESUMABLE (``after_id`` cursor, ``done`` flag),
    exactly like :func:`reindex_all_batch` — call repeatedly with ``after_id=last_id``.

    Idempotent: the candidate filter excludes any article that already has a language of
    either class, so a re-run never re-touches a resolved article. Counts only, no score.
    """
    from sqlalchemy import or_

    from src.analytics.langdetect import SUPPORTED, detect_language

    _empty_lang = or_(Article.language.is_(None), Article.language == "")
    _empty_det = or_(Article.detected_language.is_(None), Article.detected_language == "")

    # 1) candidate UNKNOWN article ids (id > cursor), oldest first, bounded. Selects only
    # the id — no content decrypt in this scan.
    ids = [
        int(r[0])
        for r in (
            session.query(Article.id)
            .filter(Article.id > after_id, _empty_lang, _empty_det)
            .order_by(Article.id)
            .limit(max(1, limit))
            .all()
        )
    ]
    if not ids:
        return {
            "scanned": 0,
            "set_by_text": 0,
            "set_by_keywords": 0,
            "still_unknown": 0,
            "last_id": after_id,
            "done": True,
        }

    # 2) per-article keyword-language distribution for THIS batch only (the tier-2 signal).
    # Covering Keyword.id -> language map (small keywords-table scan, no content) + a
    # covering (article_id, keyword_id) mention scan chunked under the SQLite variable cap
    # — NEVER the codec-trap join through the articles table.
    kw_lang: dict[int, str] = {
        int(kid): lang
        for kid, lang in session.query(Keyword.id, Keyword.language).filter(
            Keyword.language.isnot(None), Keyword.language != ""
        )
    }
    dist: dict[int, dict[str, int]] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i : i + 500]
        for aid, kid in session.query(
            KeywordMention.article_id, KeywordMention.keyword_id
        ).filter(KeywordMention.article_id.in_(chunk)):
            lang = kw_lang.get(int(kid))
            if lang is None or lang not in SUPPORTED:
                continue
            d = dist.setdefault(int(aid), {})
            d[lang] = d.get(lang, 0) + 1

    # 3) deduce per article: text first, keyword-majority fallback, else leave unknown.
    set_by_text = set_by_keywords = still_unknown = 0
    updates: list[dict] = []
    last_id = after_id
    for aid in ids:
        last_id = aid
        art = session.get(Article, aid)
        if art is None:  # deleted mid-run
            continue
        content = art.get_content() if hasattr(art, "get_content") else (art.content or "")
        deduced = detect_language(content)  # tier 1 (reliable text detector)
        if not deduced:  # tier 2 (keyword majority — the maintainer's fallback)
            deduced = _keyword_majority_language(dist.get(aid), min_keywords=min_keywords)
            if deduced:
                set_by_keywords += 1
        else:
            set_by_text += 1
        if deduced:
            updates.append({"id": aid, "detected_language": deduced})
        else:
            still_unknown += 1

    if updates:
        session.bulk_update_mappings(Article, updates)
        session.commit()

    remaining = (
        session.query(Article.id)
        .filter(Article.id > last_id, _empty_lang, _empty_det)
        .count()
    )
    return {
        "scanned": len(ids),
        "set_by_text": set_by_text,
        "set_by_keywords": set_by_keywords,
        "still_unknown": still_unknown,
        "last_id": last_id,
        "done": remaining == 0,
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


def _cleanup_marker_path():
    from src.paths import data_dir

    return data_dir() / "keyword_cleanup.json"


def keyword_cleanup_state() -> dict:
    """The last automatic keyword-cleanup run (for the diagnostics logs). Never raises."""
    import json

    try:
        p = _cleanup_marker_path()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a diagnostic read must never crash
        pass
    return {"last_run": None}


def _cleanup_hours() -> float:
    """Minimum hours between automatic keyword-cleanup passes (OO_KEYWORD_CLEANUP_HOURS)."""
    import os

    try:
        return float(os.environ.get("OO_KEYWORD_CLEANUP_HOURS", "12"))
    except ValueError:
        return 12.0


def maybe_cleanup_keywords(session: Session, *, now=None) -> dict:
    """AUTOMATIC keyword cleanup (maintainer 2026-07-02: "I should not have to click
    Clean up keywords — make it automatic").

    Runs the CHEAP maintenance the button's heavy re-index doesn't require: prune the
    orphan keywords a re-index/prune leaves behind (the 69k-orphan field finding) and
    reconcile the first-write-wins keyword language. A FULL re-index (recompute every
    article's keywords/dates/sentiment) stays a MANUAL / post-upgrade action — it is far
    too heavy to run unprompted on a large corpus.

    Freshness-gated to at most once per OO_KEYWORD_CLEANUP_HOURS (default 12h) via a
    small data-dir marker, so it is a no-op on most scrape passes. Off the request path
    (called from warm_cache after a pass), best-effort, never raises. The marker records
    the last run + tally so the corpus-integrity diagnostic can show it ("automatic and
    part of the logs").

    P1.12: the prune runs under its soft deadline and may report ``complete: false``.
    While the LAST prune sweep is incomplete, the freshness gate lets the NEXT call
    RESUME the prune (only the prune — the language reconcile already ran this cycle and
    is not re-paid per resume), so a budget-bounded sweep converges pass by pass instead
    of stalling 12 h at its cursor."""
    import json
    from datetime import datetime, timedelta

    now = now or datetime.now()
    state = keyword_cleanup_state()
    last = state.get("last_run")
    fresh = False
    if last:
        try:
            fresh = datetime.fromisoformat(last) > now - timedelta(hours=_cleanup_hours())
        except (ValueError, TypeError):
            fresh = False  # unparseable marker → treat as due
    prev_prune = (state.get("last_tally") or {}).get("prune") or {}
    if fresh and prev_prune.get("complete") is not False:
        return {"skipped": "fresh", "last_run": last}

    tally: dict = {"at": now.isoformat(timespec="seconds")}
    if fresh:
        # Resume ONLY the incomplete prune sweep (bounded by its own budget); anchor the
        # 12 h cadence to the ORIGINAL run so resumes never slide the clock.
        marker_run = last
        tally["resumed_prune"] = True
        try:
            tally["prune"] = prune_orphan_keywords(session)
        except Exception:  # noqa: BLE001 - a background safety net must never break the pass
            session.rollback()
            _LOG.warning("automatic orphan-keyword prune resume failed", exc_info=True)
            tally["prune"] = {"skipped": "error"}
        tally["language"] = {"skipped": "ran this cycle"}
        tally["entity_status"] = {"skipped": "ran this cycle"}
    else:
        marker_run = tally["at"]
        try:
            tally["prune"] = prune_orphan_keywords(session)
        except Exception:  # noqa: BLE001 - a background safety net must never break the pass
            session.rollback()
            _LOG.warning("automatic orphan-keyword prune failed", exc_info=True)
            tally["prune"] = {"skipped": "error"}
        try:
            tally["language"] = reconcile_keyword_language(session)
        except Exception:  # noqa: BLE001
            session.rollback()
            _LOG.warning("automatic keyword-language reconcile failed", exc_info=True)
            tally["language"] = {"skipped": "error"}
        try:
            tally["entity_status"] = reconcile_keyword_entity_status(session)
        except Exception:  # noqa: BLE001 - a background safety net must never break the pass
            session.rollback()
            _LOG.warning("automatic keyword-entity-status reconcile failed", exc_info=True)
            tally["entity_status"] = {"skipped": "error"}

    # Record the marker (freshness + the diagnostics log). Best-effort.
    try:
        p = _cleanup_marker_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({"last_run": marker_run, "last_tally": tally}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001 - the marker is an optimisation, not correctness
        pass
    _LOG.info("automatic keyword cleanup: %s", tally)
    return tally
