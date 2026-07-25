"""
Ingestion pipeline: ethical fetch -> extract -> dedup -> store with provenance.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

This is the spine of the product: it turns a source (an RSS feed or a single URL)
into deduplicated, provenance-tagged Article rows in the unified store. Every step
either succeeds explicitly or reports a typed failure -- there is no double-fetch,
no raw-requests bypass, and no silently-stored junk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

import feedparser
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.database.models import Article, FeedFetchState, Source
from src.ingest.dedup_front import mark_stored, seen_canonical_url, seen_content_hash

# --------------------------------------------------------------------------- #
# Per-feed de-churn backoff (field log finding F, 2026-06-13)
# --------------------------------------------------------------------------- #
# Some servers IGNORE conditional-GET headers (ETag / If-Modified-Since) and
# return a full 200 every pass even when nothing changed (~93% duplicate rate at
# 1-minute intervals). When a 200 fetch yields ZERO new articles we delay this
# ONE feed's next re-check by a CAPPED, TEMPORARY, SELF-RESETTING amount.
#
# This is a transport DE-CHURN, never an exclusion (maintainer: "no source
# starved, no selection made; ordering != exclusion"). The cap guarantees the
# feed is ALWAYS re-checked within ``BACKOFF_CAP_S`` (~6 h); ANY new article, a
# 304 (the server says unchanged honestly), or a fetch error resets the counter
# and clears the skip deadline immediately. The state is stored (never hidden)
# so the task manager / diagnostics can show "backed off until T".
#
# delay = min(BACKOFF_BASE_S * 2 ** consecutive_unchanged, BACKOFF_CAP_S)
# so the 1st no-new-content 200 waits BASE, then 2*BASE, 4*BASE, ... up to CAP.
#
# Both bounds are overridable by env so an operator can widen, narrow, or disable
# the backoff. Default ON. Set OO_FEED_BACKOFF=0 to disable (no skip deadline is
# ever written; the counter still records for diagnostics).
def _env_float(name: str, default: float) -> float:
    try:
        v = float(os.getenv(name, ""))
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


# Base delay after the FIRST all-duplicate 200 (5 min): well above the 1-minute
# hammering the field log saw, small enough that a feed that just went quiet is
# rechecked soon.
BACKOFF_BASE_S: float = _env_float("OO_FEED_BACKOFF_BASE_S", 300.0)
# Hard ceiling (~6 h): a feed is NEVER skipped longer than this, so it can never
# be starved. The exponential growth is clamped here.
BACKOFF_CAP_S: float = _env_float("OO_FEED_BACKOFF_CAP_S", 6 * 3600.0)
# Cap the exponent so 2 ** consecutive_unchanged can't overflow before the min().
_BACKOFF_MAX_EXP = 20


def _backoff_enabled() -> bool:
    return os.getenv("OO_FEED_BACKOFF", "1") != "0"
from src.ingest import (
    EthicalFetcher,
    FetchError,
    RobotsDisallowed,
    RobotsUnavailable,
)
from src.ingest.extract import extract_article
from src.ingest.fetch_verdict import classify_fetch_failure, fetch_reason_key
from src.ingest.non_article import classify_non_article, skip_non_articles_enabled
from src.utils.url_utils import canonicalize_url, generate_content_hash


class IngestResult(str, Enum):
    STORED = "stored"
    DUPLICATE = "duplicate"
    BLOCKED_ROBOTS = "blocked_robots"
    ROBOTS_UNAVAILABLE = "robots_unavailable"
    FETCH_FAILED = "fetch_failed"
    EXTRACT_FAILED = "extract_failed"
    # Skipped by the non-article filter (nav/index/tag/tool/wall page) — a distinct, counted
    # outcome (never a silent drop), reversible via OO_SKIP_NON_ARTICLES. See ingest/non_article.py.
    NON_ARTICLE = "non_article"
    # P1.8 collector write batching: buffered for the next batched commit —
    # a TRANSIENT state, never a final tally line (the batch's flush resolves
    # it to stored/duplicate/errors, which the caller merges).
    STAGED = "staged"


@dataclass
class IngestOutcome:
    url: str
    result: IngestResult
    article_id: int | None = None
    detail: str | None = None


def ingest_url(
    session: Session,
    source: Source,
    url: str,
    *,
    fetcher: EthicalFetcher,
    batch=None,
) -> IngestOutcome:
    """Fetch, extract, dedup and store a single article URL.

    Deduplication is by canonical URL (cheap, pre-fetch) and by content hash
    (post-extract, catches the same article served at different URLs).
    ``batch`` (an :class:`~src.ingest.batch.ArticleBatch`, P1.8) buffers the
    store for a batched commit instead of committing per article.
    """
    canonical = canonicalize_url(url)

    if _exists(session, canonical_url=canonical) or (
        batch is not None and batch.has_canonical(canonical)
    ):
        return IngestOutcome(url, IngestResult.DUPLICATE, detail="canonical url already stored")

    try:
        fetched = fetcher.fetch(url, require_html=True)
    except RobotsDisallowed as exc:
        return IngestOutcome(url, IngestResult.BLOCKED_ROBOTS, detail=str(exc))
    except RobotsUnavailable as exc:
        return IngestOutcome(url, IngestResult.ROBOTS_UNAVAILABLE, detail=str(exc))
    except FetchError as exc:
        return IngestOutcome(url, IngestResult.FETCH_FAILED, detail=str(exc))

    return store_fetched(session, source, fetched, batch=batch)


def store_fetched(session: Session, source: Source, fetched, *, batch=None) -> IngestOutcome:
    """Extract, dedup and store an already-fetched page.

    Split out of :func:`ingest_url` so callers that have *already* fetched a page
    (notably the recursive crawler, which harvests links from the same bytes) can
    store it without a second network round-trip -- preserving the "one fetch per
    URL" invariant. ``fetched`` is an :class:`~src.ingest.FetchResult`.

    ``batch`` (P1.8 collector write batching): when given, the extracted
    article is STAGED for the batch's next batched commit instead of paying
    three gate windows here — the outcome is :attr:`IngestResult.STAGED` and
    the final disposition (stored/duplicate) lands in ``batch.tally`` at
    flush. ``None`` (every non-collector caller) keeps the legacy per-article
    path byte-identical.
    """
    doc = extract_article(fetched.content, url=fetched.final_url)
    if doc is None:
        return IngestOutcome(
            fetched.requested_url, IngestResult.EXTRACT_FAILED, detail="no article body extracted"
        )

    # Stop non-articles (nav / index / tag / tool / consent-wall pages) at the door — the
    # source-quality recall-gap fix. High-precision + reversible (OO_SKIP_NON_ARTICLES=0 disables);
    # a skip is a distinct COUNTED outcome + a log line, never a silent drop. Runs before dedup/
    # stage so it applies to both the batch and the direct path.
    if skip_non_articles_enabled():
        verdict = classify_non_article(
            fetched.final_url, title=doc.title, text=doc.text, word_count=len(doc.text.split()),
            language=doc.language or source.language,
        )
        if verdict is not None:
            import logging

            logging.getLogger(__name__).info(
                "skipping non-article (%s) from %s: %s",
                verdict.signal, source.domain, fetched.final_url,
            )
            return IngestOutcome(
                fetched.requested_url, IngestResult.NON_ARTICLE, detail=verdict.reason
            )

    content_hash = generate_content_hash(doc.text)
    # In-batch dedup FIRST, on the actual unique column (the email-import
    # lesson: two pages serving the same body in ONE uncommitted batch would
    # collide at flush on UNIQUE articles.hash).
    if batch is not None and batch.has_hash(content_hash):
        return IngestOutcome(
            fetched.requested_url, IngestResult.DUPLICATE, detail="content hash already staged"
        )
    if _exists(session, hash=content_hash):
        return IngestOutcome(
            fetched.requested_url, IngestResult.DUPLICATE, detail="content hash already stored"
        )

    # Prefer the page's declared canonical link; fall back to the final fetched URL.
    canonical_final = canonicalize_url(doc.canonical_url or fetched.final_url)
    if batch is not None:
        batch.stage(fetched, doc, canonical_final, content_hash)
        return IngestOutcome(
            fetched.requested_url, IngestResult.STAGED, detail="buffered for a batched commit"
        )
    now = datetime.now(UTC)
    article = Article(
        url=fetched.requested_url,
        canonical_url=canonical_final,
        source_id=source.id,
        title=doc.title,
        content=doc.text,
        published_at=doc.published_at,
        language=doc.language or source.language,
        hash=content_hash,
        author=doc.author,
        word_count=len(doc.text.split()),
        created_at=now,
        updated_at=now,
        # Source IP provenance (Slice 6a): the server we connected to (clearnet) or an
        # honest "unavailable (proxy/Tor)" reason. Our vantage point, not the origin.
        server_ip=getattr(fetched, "server_ip", None),
        server_ip_reason=getattr(fetched, "server_ip_reason", None),
        ip_observed_at=fetched.fetched_at,
    )
    session.add(article)
    try:
        session.commit()
    except IntegrityError:
        # Another entry in the same loop (or a concurrent writer) inserted the same
        # content hash between the _exists check and here. Roll back so the loop
        # continues, and report the duplicate rather than aborting the batch.
        session.rollback()
        return IngestOutcome(
            fetched.requested_url,
            IngestResult.DUPLICATE,
            detail="content hash already stored (race)",
        )
    # C12: populate the dedup front now that the store is CONFIRMED -- a
    # near-future re-check of the same URL/hash (the field-measured
    # re-served-feed-item case) becomes an instant front hit.
    mark_stored(canonical_url=canonical_final, content_hash=content_hash)
    _maybe_record_custody(article)
    _maybe_index_keywords(session, article, source)
    _maybe_index_links(session, article, fetched.content, fetched.final_url)
    return IngestOutcome(fetched.requested_url, IngestResult.STORED, article_id=article.id)


def _maybe_index_keywords(session: Session, article: Article, source: Source) -> None:
    """Best-effort keyword/entity indexing on ingest (fast baseline extractor).

    Fail-open and isolated: indexing must never break ingestion, so any error is
    swallowed (and logged) and the already-committed article is untouched. Disable
    with OO_NO_INDEX=1. City is taken from the source's metadata when known
    (the reliable "source-based" location signal).
    """
    import os

    if os.getenv("OO_NO_INDEX") == "1":
        return
    try:
        from src.analytics.extract import get_extractor
        from src.analytics.store import index_article
        from src.database.write import run_write_with_retry

        city = None
        try:
            meta = source.source_metadata
            city = meta.city if meta else None
        except Exception:  # noqa: BLE001 - metadata is optional
            city = None
        # The single-writer gate (keystone #1) serialises writers so a lock should
        # never occur; this retry is belt-and-braces for a transient lock (gate
        # disabled, a restore's FTS rebuild racing the live engine, etc.) so the
        # already-fetched article never loses its keyword/when/where/who indexing
        # to a dropped transaction (field log 2026-06-17: 62 such losses, pre-gate).
        # index_article is idempotent (delete-then-reinsert), so a rollback + re-run
        # reproduces the full result.
        extractor = get_extractor("baseline")
        run_write_with_retry(
            lambda: index_article(
                session, article, extractor=extractor, country=source.country, city=city
            ),
            session=session,
            label=f"index_article[{article.id}]",
        )
    except Exception:  # noqa: BLE001 - analytics is auxiliary; never fail ingestion
        session.rollback()
        import logging

        logging.getLogger(__name__).warning("keyword indexing on ingest failed", exc_info=True)


def _maybe_index_links(session: Session, article: Article, html: str | None, base_url: str) -> None:
    """Best-effort extraction of outbound EXTERNAL links into ``article_links``.

    Powers co-citation analysis ("which articles cite the same source", "most-cited
    links") — see docs/DESIGN.md. Fail-open and isolated like
    keyword indexing: never breaks ingestion. Only genuine *external* links are kept
    — internal navigation, images, ads, social and trackers are excluded, in line
    with docs/ROADMAP.md. De-duplicated per article and capped. Disable with
    OO_NO_INDEX=1.
    """
    import os

    if os.getenv("OO_NO_INDEX") == "1" or not html:
        return
    try:
        from src.database.models import ArticleLink
        from src.database.write import run_write_with_retry
        from src.services.link_analyzer import LinkExtractor

        links = LinkExtractor().extract_links(html, base_url=base_url, article_id=article.id)

        def _build_rows() -> list[ArticleLink]:
            # Rebuilt inside the retry's work callable: a rollback on a transient
            # lock expunges pending objects, so the rows must be fresh each attempt.
            seen: set[str] = set()
            out: list[ArticleLink] = []
            for ln in links:
                if ln.get("link_type") != "external":
                    continue
                nu = ln.get("normalized_url") or ln.get("url")
                if not nu or nu in seen:
                    continue
                seen.add(nu)
                ltext = ln.get("link_text") or None
                out.append(
                    ArticleLink(
                        article_id=article.id,
                        url=(ln.get("url") or nu)[:1000],
                        normalized_url=nu[:1000],
                        link_text=ltext[:500] if ltext else None,
                        position=ln.get("position"),
                        link_type="external",
                    )
                )
                if len(out) >= 300:  # guard against pathological link-farm pages
                    break
            return out

        def _work() -> None:
            rows = _build_rows()
            if rows:
                session.add_all(rows)
                session.commit()

        # Belt-and-braces retry (the single-writer gate makes a lock unlikely, but
        # a dropped transaction here lost link indexing 87× in the 2026-06-17 field
        # log). A lock fails the commit atomically (nothing persisted), so a
        # rollback + rebuild is collision-free.
        run_write_with_retry(_work, session=session, label=f"index_links[{article.id}]")
    except Exception:  # noqa: BLE001 - link analysis is auxiliary; never fail ingestion
        session.rollback()
        import logging

        logging.getLogger(__name__).warning("link indexing on ingest failed", exc_info=True)


def _maybe_record_custody(article: Article) -> None:
    """Opt-in: append a signed custody entry for a freshly stored article.

    Best-effort and fail-open: custody logging must never break ingestion, so any
    error here is swallowed (and logged). Controlled by the GUI-editable custody
    setting ``auto_log_on_ingest`` (which defaults to the legacy
    OO_CUSTODY_ON_INGEST flag until a preference is saved). The item_hash is the
    article's content hash, so the custody entry binds to exactly the bytes that
    were stored.
    """
    try:
        from src.custody.settings import load_settings

        prefs = load_settings()
        if not prefs.auto_log_on_ingest:
            return
        from src.custody.log import CustodyAction, CustodyLog

        with CustodyLog() as log:
            log.record(
                f"article:{article.id}",
                article.hash,
                CustodyAction.INGEST,
                actor=prefs.default_actor or "ingest-pipeline",
                metadata={
                    "url": article.url,
                    "canonical_url": article.canonical_url,
                    "source_id": article.source_id,
                },
            )
    except Exception:  # noqa: BLE001 - custody is auxiliary; never fail ingestion
        import logging

        logging.getLogger(__name__).warning("custody logging on ingest failed", exc_info=True)


def ingest_source(
    session: Session,
    source: Source,
    *,
    fetcher: EthicalFetcher,
    max_items: int = 50,
) -> dict[str, int]:
    """Ingest a source's RSS/Atom feed (the feed is fetched through the ethical path).

    Returns a tally keyed by IngestResult value, plus the feed entry count.
    """
    # STAGED is transient by contract (resolved at flush) — it must never
    # appear as a permanent zero line in a user-facing tally.
    tally = {r.value: 0 for r in IngestResult if r is not IngestResult.STAGED}
    tally["entries"] = 0
    tally["not_modified"] = 0  # feeds answered 304 Not Modified (skipped cheaply)

    if not source.rss_url:
        return tally

    # Conditional GET: reuse the stored ETag / Last-Modified so an UNCHANGED feed
    # comes back as a cheap 304 instead of a full re-download + re-parse (field
    # log 2026-06-13: ~93% duplicate rate at 1-minute intervals). Best-effort:
    # any bookkeeping hiccup degrades to a normal fetch, never blocks collection.
    extra_headers = _feed_conditional_headers(session, source.id)

    try:
        feed_resp = fetcher.fetch(
            source.rss_url, require_html=False, extra_headers=extra_headers or None
        )
    except FetchError:
        # Feed itself blocked/unavailable: nothing to ingest, but not an article
        # failure. A transient error is NOT a "feed is quiet" signal — reset any
        # backoff so a recovered feed is re-checked at the normal cadence.
        _update_feed_backoff(session, source.id, reset=True)
        _commit_feed_bookkeeping(session)
        return tally

    if feed_resp.status_code == 304:
        # Unchanged since last pass — nothing new to parse or ingest. The server
        # answered honestly, so this is NOT penalised: clear any backoff. No
        # article fetches follow, so writing the bookkeeping here is safe.
        _record_feed_state(session, source.id, feed_resp)
        tally["not_modified"] = 1
        _update_feed_backoff(session, source.id, reset=True)
        _commit_feed_bookkeeping(session)
        return tally

    parsed = feedparser.parse(feed_resp.content)
    links = [e.link for e in parsed.entries if getattr(e, "link", None)][:max_items]
    tally["entries"] = len(links)

    # P1.8 collector write batching: buffer stores across this feed's items so
    # several articles share ONE gate window/fsync (the field pass measured
    # 847 K s of cumulative write-wait at per-article commits). Fetches still
    # happen OUTSIDE any gate; OO_COLLECT_COMMIT_BATCH=0 restores the legacy
    # per-article path exactly.
    from src.ingest.batch import ArticleBatch, collect_batch_size

    batch = ArticleBatch(session, source) if collect_batch_size() > 0 else None
    try:
        for link in links:
            outcome = ingest_url(session, source, link, fetcher=fetcher, batch=batch)
            if outcome.result is IngestResult.STAGED:
                continue  # resolved at flush; merged from batch.tally below
            tally[outcome.result.value] += 1
            # Break the raw fetch_failed count down by WHY (Tor-403 vs DNS vs connect
            # vs …) so a report isn't a mystery number. Flat int keys ("ff:<reason>")
            # so the scheduler's scalar tally-aggregation sums them for free; the
            # per-reason counts always sum to fetch_failed (unknown -> "other").
            if outcome.result is IngestResult.FETCH_FAILED:
                rk = fetch_reason_key(classify_fetch_failure(outcome.detail))
                tally[rk] = tally.get(rk, 0) + 1
    finally:
        # ZERO LOSS: staged entries always get their write attempt, even if a
        # mid-feed error aborts the loop — and the backoff decision below then
        # sees the true stored count.
        if batch is not None:
            batch.flush()
            for k, v in batch.tally.items():
                if v:
                    tally[k] = tally.get(k, 0) + v

    # Feed bookkeeping runs AFTER the article loop, DELIBERATELY (P1.8 skeptic
    # finding, reproduced empirically): validators/backoff written BEFORE the
    # loop leave the session DIRTY, and the loop's first dedup SELECT then
    # AUTOFLUSHES them — acquiring the single-writer gate and holding it ACROSS
    # the article fetch (a slow fetch + politeness while holding the gate = the
    # field log's 438 s max single write-wait; the batched path would have held
    # it across the WHOLE feed). Down here the loop runs on a CLEAN session —
    # no autoflush, no gate — and the de-churn backoff (a 200 that stored ZERO
    # new articles delays this feed's next re-check, capped, self-resetting)
    # reads the true post-flush stored count.
    _record_feed_state(session, source.id, feed_resp)
    if tally[IngestResult.STORED.value] > 0 or tally.get("errors", 0) > 0:
        # New content stored — or OUR store errored (skeptic finding D2): a
        # store failure is NOT a "feed is quiet" signal, and a prompt re-fetch
        # is exactly the loss-recovery path. Same rule as the fetch-error case.
        _update_feed_backoff(session, source.id, reset=True)
    else:
        _update_feed_backoff(session, source.id, reset=False)
    _commit_feed_bookkeeping(session)

    return tally


def _commit_feed_bookkeeping(session: Session) -> None:
    """Commit the per-feed validators/backoff rows so ``ingest_source`` always
    RETURNS WITH A CLEAN SESSION.

    Best-effort: the bookkeeping is an optimisation (conditional GET /
    de-churn), so a failed commit rolls back and is logged, never raised — but
    it must never stay PENDING: a dirty session hands the single-writer gate
    to the NEXT source's dedup query via autoflush, and the gate is then held
    across that source's network fetches (the P1.8 skeptic finding — the
    sequential pass shares one session across every source).
    """
    try:
        session.commit()
    except Exception:  # noqa: BLE001 - bookkeeping is auxiliary, never fatal
        session.rollback()
        import logging

        logging.getLogger(__name__).debug("feed bookkeeping commit failed", exc_info=True)


def _feed_conditional_headers(session: Session, source_id: int) -> dict[str, str]:
    """Build If-None-Match / If-Modified-Since from the stored feed validators.

    Best-effort: returns ``{}`` on any error (a fresh DB, a missing row) so a
    bookkeeping problem can never stop a feed from being fetched normally.
    """
    headers: dict[str, str] = {}
    try:
        state = session.get(FeedFetchState, source_id)
        if state is not None:
            if state.etag:
                headers["If-None-Match"] = state.etag
            if state.last_modified:
                headers["If-Modified-Since"] = state.last_modified
    except Exception:  # noqa: BLE001 - conditional GET is an optimisation, never required
        import logging

        logging.getLogger(__name__).debug("feed conditional-GET lookup failed", exc_info=True)
    return headers


def _record_feed_state(session: Session, source_id: int, resp) -> None:
    """Persist the feed's latest HTTP validators + status for the next pass.

    On a 304 the server may omit the ETag; the existing validator is then kept
    (only non-None values overwrite). Best-effort and isolated from ingestion.
    """
    try:
        state = session.get(FeedFetchState, source_id)
        if state is None:
            state = FeedFetchState(source_id=source_id)
            session.add(state)
            # Flush so a same-call _update_feed_backoff() sees THIS row via
            # session.get and reuses it (a second add() would duplicate the PK).
            session.flush()
        if resp.etag is not None:
            state.etag = resp.etag
        if resp.last_modified is not None:
            state.last_modified = resp.last_modified
        state.last_status = resp.status_code
        state.last_checked_at = datetime.now(UTC)
    except Exception:  # noqa: BLE001 - never let feed bookkeeping break ingestion
        import logging

        logging.getLogger(__name__).debug("recording feed fetch state failed", exc_info=True)


def _update_feed_backoff(session: Session, source_id: int, *, reset: bool) -> None:
    """Advance or clear the per-feed de-churn backoff (field log finding F).

    ``reset=True`` (new article stored, a 304, or a fetch error): zero the
    counter and clear the skip deadline — the feed is behaving / changing.

    ``reset=False`` (a 200 that yielded zero new articles): increment the
    consecutive-unchanged counter and push the skip deadline out exponentially,
    CLAMPED to :data:`BACKOFF_CAP_S` so the feed is always re-checked soon
    enough — never starved. When the backoff is disabled (``OO_FEED_BACKOFF=0``)
    the counter still advances for diagnostics but no skip deadline is written.

    Best-effort and isolated: any error degrades to "no backoff", never blocks
    ingestion. The row is created on demand so a feed fetched before any state
    existed still gets bookkeeping.
    """
    try:
        state = session.get(FeedFetchState, source_id)
        if state is None:
            if reset:
                # Nothing to clear and no penalty to record — avoid a useless row.
                return
            state = FeedFetchState(source_id=source_id)
            session.add(state)
        if reset:
            state.consecutive_unchanged = 0
            state.skip_until = None
            return
        count = (state.consecutive_unchanged or 0) + 1
        state.consecutive_unchanged = count
        if _backoff_enabled():
            exp = min(count, _BACKOFF_MAX_EXP)
            delay_s = min(BACKOFF_BASE_S * (2 ** (exp - 1)), BACKOFF_CAP_S)
            state.skip_until = datetime.now(UTC) + timedelta(seconds=delay_s)
        else:
            state.skip_until = None
    except Exception:  # noqa: BLE001 - backoff is an optimisation, never required
        import logging

        logging.getLogger(__name__).debug("feed backoff update failed", exc_info=True)


def feed_is_due(state: FeedFetchState | None, *, now: datetime | None = None) -> bool:
    """Return whether a feed should be re-checked THIS pass.

    A feed is due unless it carries a ``skip_until`` deadline in the FUTURE (it
    was backed off after an all-duplicate 200). The cap on ``skip_until`` (see
    :data:`BACKOFF_CAP_S`) guarantees the feed becomes due again soon — this is a
    de-churn, never an exclusion. ``None`` state (never fetched) is always due.

    Pure and side-effect free so the collect loop can pre-filter cheaply; ``now``
    is injectable for deterministic tests.
    """
    if state is None or state.skip_until is None:
        return True
    deadline = state.skip_until
    if deadline.tzinfo is None:
        # Stored naive (SQLite DateTime) — interpret as UTC, the only thing we write.
        deadline = deadline.replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) >= deadline


def _exists(session: Session, **filters) -> bool:
    """Existence check for a dedup filter (``canonical_url=`` or ``hash=``).

    C12 (2026-07-24 throughput brief, A2): consults the in-memory dedup front
    FIRST when the filter is EXACTLY one of the two known dedup keyspaces. A
    front HIT is unconditionally trustworthy (an exact set -- see
    ``src.ingest.dedup_front``'s module docstring) and skips the
    codec-decrypting DB read entirely -- the field-measured ~90% duplicate
    case. A MISS is NEVER trusted alone (bounded LRU eviction is this
    structure's only imprecision, and it is false-negative-ONLY) -- it always
    falls through to the real query below, and a genuine hit there re-warms
    the front for next time. Any other filter shape (an unrecognised kwarg, or
    more than one) bypasses the front entirely and runs the authoritative
    query unchanged.
    """
    if len(filters) == 1:
        canonical_url = filters.get("canonical_url")
        if canonical_url and canonical_url in seen_canonical_url():
            return True
        content_hash = filters.get("hash")
        if content_hash and content_hash in seen_content_hash():
            return True
    found = session.query(Article.id).filter_by(**filters).first() is not None
    if found and len(filters) == 1:
        mark_stored(canonical_url=filters.get("canonical_url"), content_hash=filters.get("hash"))
    return found
