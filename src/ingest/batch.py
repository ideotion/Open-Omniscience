"""
Collector-path write batching (P1.8): N articles per gate window, zero loss.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why this exists (field event 2026-07-09): across one 21.6-hour, 50-worker
collect pass the single-writer gate accrued 847,351 s of cumulative write-wait
(~22% of all worker time; 234,551 contentions, max single wait 438 s). The
per-article store paid THREE gate windows + fsyncs per stored article (article
commit, keyword-index commit, link commit). This module batches the collector's
stores so several articles share ONE write transaction — the long-deferred
strategy-P1.3 item, now with its live justification.

The two invariants that shape the design:

  * THE GATE IS NEVER HELD ACROSS A FETCH. Workers fetch + extract first (pure
    network/CPU, no DB writes), stage the extracted result — the raw HTML is
    dropped at stage time (links are pre-extracted), so a batch holds only
    extracted text — and the buffered batch is written in one short gate window
    at flush. A batch is bounded by count AND by staged-text bytes (this is the
    OOM session: buffering must never become its own accumulation).

  * ZERO LOSS. In-batch dedup keys on the ACTUAL unique column
    (``articles.hash`` — the email-import lesson), a flush re-checks the DB
    (another worker may have stored the same content since staging), and a
    batch commit that still collides/locks is ROLLED BACK AND REDONE ONE
    ARTICLE AT A TIME (the proven ``ingest_emails`` fallback), so a single
    collision never drops its batch-mates. The redo path reuses the existing
    per-article store semantics (retry on transient locks; a duplicate is
    counted, never raised).

``OO_COLLECT_COMMIT_BATCH`` sizes the batch (default 8, deliberately
conservative); ``0`` disables batching entirely — the byte-identical legacy
per-article path.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.database.models import Source

_LOG = logging.getLogger("ingest.batch")

# A batch is bounded by staged-text BYTES as well as count: this is the OOM
# session — the batching fix must never become its own memory accumulation.
_BATCH_MAX_TEXT_BYTES = 4 * 1024 * 1024


def collect_batch_size() -> int:
    """The collector commit-batch size (0 = batching disabled, legacy path)."""
    try:
        return max(0, int(os.getenv("OO_COLLECT_COMMIT_BATCH", "8")))
    except (TypeError, ValueError):
        return 8


@dataclass
class _StagedArticle:
    """One extracted article buffered for the next batched flush.

    Holds ONLY what the store needs — never the raw HTML (links are extracted
    at stage time, so the multi-MB page is released the moment we stage).
    """

    requested_url: str
    canonical_url: str
    content_hash: str
    title: str | None
    text: str
    published_at: datetime | None
    language: str | None
    author: str | None
    server_ip: str | None
    server_ip_reason: str | None
    fetched_at: datetime | None
    staged_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    links: list[dict] = field(default_factory=list)


class ArticleBatch:
    """Per-source staging buffer: fetch/extract outside the gate, write in one.

    One instance per source ingest/crawl (per worker session). ``stage()`` is
    pure buffering (no DB writes, no gate); ``flush()`` writes every staged
    article + its keyword index + its links in ONE transaction, with the
    rollback-then-redo-per-article fallback so a collision never drops a
    batch-mate. The final tallies live in ``self.tally`` and are merged by the
    caller AFTER flush (a staged article's disposition is only known then).
    """

    def __init__(self, session: Session, source: Source, *, size: int | None = None) -> None:
        self._session = session
        self._source = source
        self._size = collect_batch_size() if size is None else max(1, size)
        self._pending: list[_StagedArticle] = []
        self._pending_text_bytes = 0
        self._pending_hashes: set[str] = set()
        self._pending_canonicals: set[str] = set()
        self.tally: dict[str, int] = {"stored": 0, "duplicate": 0, "errors": 0}
        self._city = self._source_city(source)

    @staticmethod
    def _source_city(source) -> str | None:
        try:
            meta = source.source_metadata
            return meta.city if meta else None
        except Exception:  # noqa: BLE001 - metadata is optional
            return None

    def has_hash(self, content_hash: str) -> bool:
        return content_hash in self._pending_hashes

    def has_canonical(self, canonical: str) -> bool:
        return canonical in self._pending_canonicals

    def stage(self, fetched, doc, canonical: str, content_hash: str) -> None:
        """Buffer one extracted article (links pre-extracted, HTML dropped)."""
        entry = _StagedArticle(
            requested_url=fetched.requested_url,
            canonical_url=canonical,
            content_hash=content_hash,
            title=doc.title,
            text=doc.text,
            published_at=doc.published_at,
            language=doc.language or self._source.language,
            author=doc.author,
            server_ip=getattr(fetched, "server_ip", None),
            server_ip_reason=getattr(fetched, "server_ip_reason", None),
            fetched_at=fetched.fetched_at,
            links=self._extract_links(fetched.content, fetched.final_url),
        )
        self._pending.append(entry)
        self._pending_hashes.add(content_hash)
        self._pending_canonicals.add(canonical)
        self._pending_text_bytes += len(doc.text)
        if len(self._pending) >= self._size or self._pending_text_bytes >= _BATCH_MAX_TEXT_BYTES:
            self.flush()

    @staticmethod
    def _extract_links(html: str | None, base_url: str) -> list[dict]:
        """Outbound-link extraction at STAGE time (pure CPU, no DB) so the raw
        HTML is released immediately. Mirrors pipeline._maybe_index_links's
        filter (external only, deduped, capped)."""
        if os.getenv("OO_NO_INDEX") == "1" or not html:
            return []
        try:
            from src.services.link_analyzer import LinkExtractor

            links = LinkExtractor().extract_links(html, base_url=base_url, article_id=0)
            seen: set[str] = set()
            out: list[dict] = []
            for ln in links:
                if ln.get("link_type") != "external":
                    continue
                nu = ln.get("normalized_url") or ln.get("url")
                if not nu or nu in seen:
                    continue
                seen.add(nu)
                out.append(ln)
                if len(out) >= 300:  # guard against pathological link-farm pages
                    break
            return out
        except Exception:  # noqa: BLE001 - link analysis is auxiliary
            _LOG.warning("link extraction at stage time failed", exc_info=True)
            return []

    # -- flush ------------------------------------------------------------- #

    def flush(self) -> None:
        """Write every staged article in ONE gate window; zero loss on failure.

        A failed batched commit rolls back and REDOES the batch one article at
        a time (the proven ``ingest_emails`` fallback) — a single conflict
        never drops its batch-mates. The catch is deliberately BROAD
        (skeptic-hardened): even a non-DB failure mid-flush (a MemoryError
        building rows — this IS the OOM session) must roll back (so
        flushed-uncommitted rows can never leak into a later bookkeeping
        commit unindexed and untallied) and hand every entry to the redo path.
        Never raises; every entry's disposition lands in the tally.
        """
        if not self._pending:
            return
        entries = self._pending
        self._pending = []
        self._pending_hashes = set()
        self._pending_canonicals = set()
        self._pending_text_bytes = 0
        try:
            self._flush_batched(entries)
        except Exception:  # noqa: BLE001 - zero loss outranks tidiness
            self._session.rollback()
            _LOG.warning(
                "batched collect commit failed; redoing %d article(s) one at a time",
                len(entries),
                exc_info=True,
            )
            for e in entries:
                # Per-entry guard (skeptic finding): an unexpected error on ONE
                # redo (e.g. a pool-checkout timeout) must not abort the
                # remaining batch-mates. A skipped article is counted honestly
                # and re-fetched next pass (content-hash dedup keeps it single).
                try:
                    self._store_one(e)
                except Exception:  # noqa: BLE001 - zero loss outranks tidiness
                    self.tally["errors"] += 1
                    _LOG.warning(
                        "collect redo: unexpected error storing %s; recounted "
                        "as an error, re-fetched next pass",
                        e.requested_url,
                        exc_info=True,
                    )

    def _flush_batched(self, entries: list[_StagedArticle]) -> None:
        from src.database.models import Article
        from src.ingest.dedup_front import mark_stored
        from src.ingest.pipeline import _exists, _maybe_record_custody

        to_store: list[tuple[_StagedArticle, Article]] = []
        dups = 0
        for e in entries:
            # Re-check the DB at flush time: another worker may have stored the
            # same content since this entry was staged (reads never gate).
            if _exists(self._session, hash=e.content_hash):
                dups += 1
                continue
            to_store.append((e, self._article_row(e)))
        if to_store:
            for _, a in to_store:
                self._session.add(a)
            # The ONE gate window for the whole batch opens at this flush (ids
            # are assigned here) and closes at the commit below.
            self._session.flush()
            if os.getenv("OO_NO_INDEX") != "1":
                from src.analytics.extract import get_extractor

                extractor = get_extractor("baseline")
                for e, a in to_store:
                    self._index_one(a, extractor)
                    self._links_one(a.id, e.links)
            self._session.commit()
        # Tally ONLY after the commit succeeded (skeptic finding D1): a failed
        # batch redoes EVERY entry, and a duplicate counted here would then be
        # recounted by the redo — 3 dispositions for 2 staged articles.
        self.tally["duplicate"] += dups
        self.tally["stored"] += len(to_store)
        for e, a in to_store:
            _maybe_record_custody(a)
            # C12: the store is now CONFIRMED committed -- populate the dedup
            # front so a near-future re-check of the same content (the
            # field-measured re-served-feed-item case) skips the DB entirely.
            mark_stored(canonical_url=e.canonical_url, content_hash=e.content_hash)

    def _article_row(self, e: _StagedArticle):
        from src.database.models import Article

        return Article(
            url=e.requested_url,
            canonical_url=e.canonical_url,
            source_id=self._source.id,
            title=e.title,
            content=e.text,
            published_at=e.published_at,
            language=e.language,
            hash=e.content_hash,
            author=e.author,
            word_count=len(e.text.split()),
            created_at=e.staged_at,
            updated_at=e.staged_at,
            server_ip=e.server_ip,
            server_ip_reason=e.server_ip_reason,
            ip_observed_at=e.fetched_at,
        )

    def _index_one(self, article, extractor) -> None:
        """Keyword/WWW indexing inside the batch transaction, isolated by a
        SAVEPOINT: an extractor bug costs THAT article its indexing (as the
        legacy best-effort path does), never the batch. A transient lock is
        re-raised so the whole batch takes the rollback-and-redo path (where
        the retry lives)."""
        from src.analytics.store import index_article
        from src.database.write import is_locked_error

        try:
            with self._session.begin_nested():
                index_article(
                    self._session,
                    article,
                    extractor=extractor,
                    country=self._source.country,
                    city=self._city,
                    commit=False,
                )
        except Exception as exc:  # noqa: BLE001 - indexing is auxiliary per article
            if is_locked_error(exc):
                raise
            _LOG.warning(
                "keyword indexing failed for article %s (kept unindexed)",
                article.id,
                exc_info=True,
            )

    def _links_one(self, article_id: int, links: list[dict]) -> None:
        from src.database.write import is_locked_error

        if not links:
            return
        try:
            with self._session.begin_nested():
                self._session.add_all(_link_rows(article_id, links))
        except Exception as exc:  # noqa: BLE001 - link analysis is auxiliary
            if is_locked_error(exc):
                raise
            _LOG.warning("link indexing failed for article %s", article_id, exc_info=True)

    # -- the per-article redo path (zero loss) ------------------------------ #

    def _store_one(self, e: _StagedArticle) -> None:
        """The safe per-article path used on a batch failure: exactly the
        legacy store semantics (retry transient locks; a duplicate is counted;
        an exhausted lock is logged + counted, never raised — no batch-mate is
        ever dropped because a sibling collided)."""
        from src.database.write import run_write_with_retry
        from src.ingest.dedup_front import mark_stored
        from src.ingest.pipeline import (
            _exists,
            _maybe_index_keywords,
            _maybe_record_custody,
        )

        if _exists(self._session, hash=e.content_hash):
            self.tally["duplicate"] += 1
            return
        holder: dict = {}

        def _work() -> None:
            # Rebuilt each attempt: a rollback expunges pending objects.
            a = self._article_row(e)
            self._session.add(a)
            self._session.commit()
            holder["article"] = a

        try:
            run_write_with_retry(_work, session=self._session, label="collect batch redo")
        except IntegrityError:
            self._session.rollback()
            self.tally["duplicate"] += 1
            return
        except OperationalError:
            self._session.rollback()
            self.tally["errors"] += 1
            _LOG.warning(
                "collect redo: an article could not be stored (transient db "
                "error); skipped this pass, re-fetched next pass"
            )
            return
        article = holder["article"]
        self.tally["stored"] += 1
        _maybe_record_custody(article)
        # C12: populate the dedup front now the redo commit is CONFIRMED.
        mark_stored(canonical_url=e.canonical_url, content_hash=e.content_hash)
        _maybe_index_keywords(self._session, article, self._source)
        self._store_links_committed(article.id, e.links)

    def _store_links_committed(self, article_id: int, links: list[dict]) -> None:
        """Links on the redo path: own small committed write, best-effort."""
        from src.database.write import run_write_with_retry

        if not links or os.getenv("OO_NO_INDEX") == "1":
            return
        try:

            def _work() -> None:
                rows = _link_rows(article_id, links)
                if rows:
                    self._session.add_all(rows)
                self._session.commit()

            run_write_with_retry(_work, session=self._session, label=f"index_links[{article_id}]")
        except Exception:  # noqa: BLE001 - link analysis is auxiliary
            self._session.rollback()
            _LOG.warning("link indexing on redo failed", exc_info=True)


def _link_rows(article_id: int, links: list[dict]) -> list:
    """ArticleLink rows from pre-extracted link dicts (already filtered to
    external + deduped + capped at stage time)."""
    from src.database.models import ArticleLink

    out = []
    for ln in links:
        nu = ln.get("normalized_url") or ln.get("url")
        if not nu:
            continue
        ltext = ln.get("link_text") or None
        out.append(
            ArticleLink(
                article_id=article_id,
                url=(ln.get("url") or nu)[:1000],
                normalized_url=nu[:1000],
                link_text=ltext[:500] if ltext else None,
                position=ln.get("position"),
                link_type="external",
            )
        )
    return out
