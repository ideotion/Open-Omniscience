"""
Backend re-index JOB: a pausable, task-manager-visible whole-corpus re-index
(keyword-engine optimization Phase 1.1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE PAIN (maintainer, field test): re-indexing the whole corpus was driven by a
CLIENT loop (`_reindexAllLoop` in app.js → /api/insights/reindex-all) with NO
persisted cursor — closing the browser tab stopped it, and a re-open restarted
from article 0. On a large corpus that is the "keep the tab open for hours / lose
all progress" trap.

THE FIX: move the re-index OFF the browser loop into a server-side background JOB,
mirroring the download/import managers (DumpDownloadManager / NewsletterImportManager):
a worker thread, pause via a stop-event, RESUME from a PERSISTED on-disk cursor (the
last article id processed) so it survives an app restart, progress + a rule-of-three
ETA, surfaced in /api/jobs.

It is a DB-WRITER job (kind="reindex"): it drives :func:`reindex_all_batch`, whose
per-article ``index_article`` takes the SINGLE-WRITER GATE on each flush/commit and
RELEASES it between articles — so a live scrape interleaves cooperatively (never a
silent collision, never a multi-hour gate hold). ZERO network (pure DB work).

Re-index is idempotent (``index_article`` is delete-then-reinsert with exact counter
deltas), so a resumed/restarted run never double-counts or loses keyword rows — the
correctness net beneath the persisted cursor.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

# Articles per reindex_all_batch loop. Each batch commits per-article inside
# index_article, and the cursor is persisted after each batch, so a crash loses at
# most this many articles of *progress* (never data — the re-index is idempotent).
_BATCH = 300
_STATE_FILE = "reindex_job.json"


def _default_session():
    from src.database.session import SessionLocal

    return SessionLocal()


def _default_extractor():
    from src.analytics.extract import get_extractor

    return get_extractor("baseline")


class ReindexJobManager:
    """ONE pausable server-side whole-corpus re-index at a time. Progress is a CURSOR
    (the last article id processed), persisted to ``data_dir()`` so a resume survives
    an app restart; the re-index's idempotency is the correctness net."""

    def __init__(self, *, state_path: Path | None = None) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state = "idle"  # idle|running|paused|done|error|cancelled
        self._cursor = 0  # after_id: the last article id processed (resume point)
        self._total = 0  # total articles at start (for percent + ETA)
        self._done = 0  # articles processed so far (for percent + ETA)
        self._done_at_start = 0  # _done when the current run began (honest run-rate ETA)
        self._tally: dict[str, int] = {}  # reindexed / failed / pruned / kept_curated
        self._error: str | None = None
        self._cancelled = False
        self._scope = "full"  # "full" (keywords + when/where/who + sentiment) | "keywords"
        self._prune_after = False  # chain prune_orphan_keywords at the end (the cleanup flow)
        self._started_at: float | None = None
        self._session_factory = None  # test seam
        self._extractor = None  # test seam
        self._state_path_override = state_path
        self._load_persisted()

    # -- persistence -------------------------------------------------------- #
    def _state_path(self) -> Path:
        if self._state_path_override is not None:
            return self._state_path_override
        from src.paths import data_dir

        return data_dir() / _STATE_FILE

    def _save(self) -> None:
        """Persist the resume cursor (best-effort; a write hiccup never breaks the job)."""
        try:
            p = self._state_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps(
                    {
                        "cursor": self._cursor,
                        "total": self._total,
                        "done": self._done,
                        "tally": self._tally,
                        "state": self._state,
                        "scope": self._scope,
                        "prune_after": self._prune_after,
                    }
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _clear_state(self) -> None:
        try:
            self._state_path().unlink(missing_ok=True)
        except OSError:
            pass

    def _load_persisted(self) -> None:
        """On first construction (app start), restore an INTERRUPTED re-index as PAUSED
        so the user can resume it from the task manager / Settings."""
        try:
            d = json.loads(self._state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if d.get("state") not in ("running", "paused"):
            return
        self._cursor = max(0, int(d.get("cursor") or 0))
        self._total = max(0, int(d.get("total") or 0))
        self._done = max(0, int(d.get("done") or 0))
        self._tally = {str(k): int(v) for k, v in (d.get("tally") or {}).items()}
        self._scope = "keywords" if d.get("scope") == "keywords" else "full"
        self._prune_after = bool(d.get("prune_after"))
        self._state = "paused"  # an interrupted run is resumable, never silently lost

    # -- lifecycle ---------------------------------------------------------- #
    def _alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _count_articles(self, session_factory) -> int:
        """Total articles (for percent + ETA), computed up front so the first status
        the UI sees already carries it. Best-effort: a transient failure leaves 0 and
        the worker recomputes (never blocks the job from starting)."""
        try:
            from src.database.models import Article

            sess = (session_factory or _default_session)()
            try:
                return int(sess.query(Article.id).count())
            finally:
                sess.close()
        except Exception:  # noqa: BLE001 - a count hiccup must never stop the re-index
            return 0

    def start(
        self,
        *,
        scope: str = "full",
        prune_after: bool = False,
        _session_factory=None,
        _extractor=None,
        _cursor: int = 0,
        _total: int = 0,
        _done: int = 0,
    ) -> dict:
        """Launch the worker. RuntimeError if a re-index is already running. ``scope``
        ("full" | "keywords") selects whether to recompute when/where/who + sentiment
        or keywords only; ``_cursor`` (resume) is the article id to continue AFTER;
        ``prune_after`` chains the orphan-keyword GC when the pass completes (cleanup)."""
        with self._lock:
            if self._alive():
                raise RuntimeError("A re-index is already running.")
            self._stop.clear()
            self._cancelled = False
            self._state = "running"
            self._scope = "keywords" if scope == "keywords" else "full"
            self._prune_after = prune_after
            self._cursor = max(0, _cursor)
            self._done = max(0, _done)
            self._done_at_start = self._done
            self._total = max(0, _total)
            if _cursor <= 0:
                self._tally = {}
            self._error = None
            self._started_at = time.monotonic()
            self._session_factory = _session_factory
            self._extractor = _extractor
            if not self._total:
                self._total = self._count_articles(_session_factory)
            self._save()
            self._thread = threading.Thread(target=self._run, daemon=True, name="reindex-job")
            self._thread.start()
            return self.status()

    def _run(self) -> None:
        try:
            from src.analytics.store import (
                prune_orphan_keywords,
                reconcile_article_language,
                reconcile_keyword_entity_status,
                reconcile_keyword_language,
                reindex_all_batch,
            )
            from src.database.models import Article

            session = (self._session_factory or _default_session)()
            extractor = self._extractor or _default_extractor()
            try:
                with self._lock:
                    if not self._total:
                        self._total = int(session.query(Article.id).count())
                    after = self._cursor
                    self._save()
                # Phase 1.3: batch commits to cut fsyncs through the encrypted writer.
                # Default 1 = per-article (byte-identical); the maintainer raises it +
                # measures, mindful the gate is held across a batch (interleave w/ scrape).
                try:
                    commit_batch = max(1, int(os.getenv("OO_REINDEX_COMMIT_BATCH", "1") or "1"))
                except ValueError:
                    commit_batch = 1
                while True:
                    if self._stop.is_set():
                        break
                    r = reindex_all_batch(
                        session,
                        extractor=extractor,
                        limit=_BATCH,
                        after_id=after,
                        scope=self._scope,
                        commit_batch=commit_batch,
                    )
                    after = int(r["last_id"])
                    with self._lock:
                        self._tally["reindexed"] = self._tally.get("reindexed", 0) + int(r["reindexed"])
                        self._tally["failed"] = self._tally.get("failed", 0) + int(r["failed"])
                        self._done += int(r["reindexed"]) + int(r["failed"])
                        self._cursor = after
                        self._save()
                    if r["done"]:
                        break
                # Chain the orphan-keyword GC only on a COMPLETE pass (the cleanup flow);
                # a paused/cancelled run leaves pruning for when it finishes.
                completed = not self._stop.is_set()
                if completed and self._prune_after:
                    # UNBOUNDED here (budget_s=0): the user explicitly asked for the
                    # cleanup and this worker thread is already pausable/cancellable —
                    # the P1.12 soft deadline is for the AUTOMATIC background passes.
                    pr = prune_orphan_keywords(session, budget_s=0)
                    with self._lock:
                        self._tally["pruned"] = int(pr.get("pruned", 0))
                        self._tally["kept_curated"] = int(pr.get("kept_curated", 0))
                        self._save()
                if completed:
                    # P4.2: re-language keywords to their signature-majority article
                    # language (index_article never reconciles the first-write tag), so a
                    # cleanup also makes the stored language truthful.
                    rl = reconcile_keyword_language(session)
                    with self._lock:
                        self._tally["relanguaged"] = int(rl.get("relanguaged", 0))
                        self._save()
                if completed:
                    # Audit finding 2026-07-17: _get_or_create_keyword only ever UPGRADES
                    # a keyword to an entity, never downgrades -- so a cleanup also
                    # reconciles any stale is_entity flag that can no longer be a valid
                    # acronym under the current (2026-06-16) rule.
                    re_ = reconcile_keyword_entity_status(session)
                    with self._lock:
                        self._tally["entity_downgraded"] = int(re_.get("downgraded", 0))
                        self._save()
                if completed:
                    # Unknown-language articles: deduce a language (text detector first,
                    # then the article's own keyword-language majority) into the DEDUCED
                    # channel only — never overwriting an asserted language. Bounded +
                    # resumable, so drain it in batches until done.
                    total_lang = {"set_by_text": 0, "set_by_keywords": 0}
                    after = 0
                    while not self._stop.is_set():
                        al = reconcile_article_language(session, limit=500, after_id=after)
                        total_lang["set_by_text"] += int(al.get("set_by_text", 0))
                        total_lang["set_by_keywords"] += int(al.get("set_by_keywords", 0))
                        after = int(al.get("last_id", 0))
                        if al.get("done") or not al.get("scanned"):
                            break
                    with self._lock:
                        self._tally["article_language_deduced"] = (
                            total_lang["set_by_text"] + total_lang["set_by_keywords"]
                        )
                        self._save()
                if completed:
                    # Phase 1.4: refresh the planner stats after the big keyword-table
                    # churn (+ merge any FTS segments) so post-cleanup queries are fast.
                    from src.database.fts import optimize_after_bulk

                    optimize_after_bulk(session)
                with self._lock:
                    if self._stop.is_set():
                        self._state = "cancelled" if self._cancelled else "paused"
                    else:
                        self._state = "done"
                    self._save()
                    if self._state in ("done", "cancelled"):
                        self._clear_state()
            finally:
                session.close()
        except Exception as exc:  # noqa: BLE001 - surface the failure, never crash the thread
            with self._lock:
                self._state = "error"
                self._error = str(exc)
                self._save()

    def pause(self) -> None:
        self._stop.set()  # the worker stops between batches; state -> paused (persisted)

    def resume(self) -> dict:
        with self._lock:
            if self._state not in ("paused", "error", "cancelled"):
                raise RuntimeError("Nothing paused to resume.")
            sf, ex = self._session_factory, self._extractor
            cur, tot, done, pa, sc = self._cursor, self._total, self._done, self._prune_after, self._scope
            tally = dict(self._tally)
        out = self.start(
            scope=sc, prune_after=pa, _session_factory=sf, _extractor=ex, _cursor=cur, _total=tot, _done=done
        )
        with self._lock:  # carry the prior tally forward (progress continues)
            self._tally = tally
            self._save()
        return out

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
        self._stop.set()
        if not self._alive():  # already idle/paused — clear the persisted state now
            with self._lock:
                self._state = "cancelled"
                self._clear_state()

    def status(self) -> dict:
        with self._lock:
            total = self._total
            done = self._done
            eta_s = None
            # Honest run-rate ETA: rate over THIS run only (done since it started),
            # so a resume's prior progress never inflates the estimate.
            recent = done - self._done_at_start
            if self._started_at is not None and recent > 0 and total and done < total:
                elapsed = max(0.001, time.monotonic() - self._started_at)
                rate = recent / elapsed  # articles/s (rule of three)
                if rate > 0:
                    eta_s = round((total - done) / rate)
            return {
                "state": self._state,
                "articles_total": total,
                "articles_done": done,
                "percent": round(100 * done / total, 1) if total else 0.0,
                "tally": dict(self._tally),
                "eta_seconds": eta_s,
                "scope": self._scope,
                "prune_after": self._prune_after,
                "error": self._error,
                "running": self._alive(),
            }


_MANAGER: ReindexJobManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_reindex_manager() -> ReindexJobManager:
    """Process-wide singleton so the job is visible across requests + in /api/jobs."""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = ReindexJobManager()
        return _MANAGER
