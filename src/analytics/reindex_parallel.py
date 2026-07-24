"""
Parallel precomputation of the pure, DB-free half of ``index_article`` (keyword
extraction + sentiment scoring) for a batch of articles.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY: after a backup restore-merge, every newly-merged article is re-indexed
against the current extraction engine (P0-4). That loop calls ``index_article``
article-by-article, and its two most CPU-expensive steps -- ``extractor.extract``
(tokenize + stopword filter + entity/acronym detection over the whole article
body) and ``score_article`` (VADER) -- are PURE functions of the article's own
text: they need no database access at all. Yet the loop runs on a single Python
thread, so a large re-index pins exactly one CPU core while the rest of the
machine sits idle (field report: a 6-core restore showed one core at 100%, the
other five idle, disk writes trickling to a crawl every 30+ seconds -- the
interval between one article's commit and the next, spent entirely inside that
single-threaded extraction).

This module offloads JUST those two pure steps to a bounded process pool, so N
articles' text extraction runs across N cores concurrently while the caller's
single DB session/writer still applies the results (delete-then-reinsert +
counter deltas + when/where/who) serially, exactly as before -- the
single-writer SQLite design is untouched; only the CPU-bound, DB-free
precomputation is parallelised. When/where/who extraction stays inline in
``index_article`` (unchanged): it is more tightly DB-coupled (savepoints, error
handling tuned to a live session) and is not the dominant per-article cost.

SAFE BY CONSTRUCTION:
  * a worker process is handed only plain data (article id + text/title/
    language) and returns plain data (terms + sentiment) -- no ORM object, no
    session, ever crosses a process boundary.
  * each worker reconstructs the extractor ONCE (at pool startup) via the same
    ``get_extractor(name, gazetteer=...)`` factory every other caller uses --
    so parallel dispatch is attempted only for the two REGISTERED extractor
    kinds (``baseline``/``spacy``). An unrecognised/custom extractor (e.g. a
    test double) always takes the serial path below, where the CALLER's own
    object runs directly -- never silently reconstructed as something else.
  * a single article's extraction failure is isolated inside the worker and
    reported back as an error marker -- it never drops or corrupts the rest of
    the batch's parallel work.
  * ANY failure to build/use the pool (process spawn restricted in this
    environment, a pickling hiccup, a broken worker, ...) degrades to the
    exact serial computation over the WHOLE batch -- a parallelism problem
    must never cost a re-index its result, only its speed.
  * a small batch skips the pool entirely (process-spawn overhead would cost
    more than it saves) -- see ``_MIN_PARALLEL_BATCH``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any

from src.analytics.extract import ExtractedTerm

_LOG = logging.getLogger(__name__)

# Below this batch size, process-spawn + IPC overhead is not worth it -- just
# compute inline (the byte-identical serial path is also the fallback).
_MIN_PARALLEL_BATCH = 16
# A hard cap independent of core count: on a huge box, dozens of worker
# processes buy little beyond a handful (the DB-writing main process stays the
# other half of the pipeline) and cost more idle memory per worker.
_MAX_WORKERS_CAP = 8
# A separate, higher cap for the exclusive "own the machine" path
# (all_cores_worker_count, below): deliberately allows meaningfully MORE than
# _MAX_WORKERS_CAP on a big multi-core box (that IS the point of the exclusive
# mode), while still bounding the worst case -- a data-loss-lens skeptic
# finding (2026-07-24, MEDIUM): the first cut had NO ceiling at all, so a
# 64+-core machine would spawn a same-sized ProcessPoolExecutor, once per
# _PRECOMPUTE_WINDOW articles, stacking with the concurrently-enlarged SQLite
# merge-connection cache (import_cache_mb) -- a real resource-exhaustion
# exposure even though it occurs strictly post-swap (the already-committed
# corpus can't be corrupted by it; worst case is a temporarily un-reindexed
# batch, an already-designed-for, recoverable outcome).
_MAX_EXCLUSIVE_WORKERS_CAP = 32
# Extractor kinds the worker can safely rebuild BY NAME (mirrors get_extractor's
# own registry). Anything else takes the serial path so the caller's own
# (possibly custom/test) extractor object is used directly, never guessed at.
_RECONSTRUCTIBLE_EXTRACTORS = ("baseline", "spacy")

# One (article_id, content, title, language, sentiment_language) task.
Task = tuple[int, str, str, str, "str | None"]


@dataclass
class ArticleDerivatives:
    """The DB-free half of one article's ``index_article`` result."""

    article_id: int
    terms: list[ExtractedTerm]
    sentiment_score: float | None
    sentiment_label: str | None
    error: str | None = None  # set only when THIS article's compute failed


def worker_count(requested: int | None = None) -> int:
    """How many worker processes to use. <= 1 means "don't parallelise" (the
    caller then always takes the serial path).

    ``OO_REINDEX_WORKERS`` overrides the default when set (``0`` disables
    parallel precompute entirely -- useful in a constrained/sandboxed
    environment or for debugging); otherwise the default leaves ONE core for
    the writer process, which is doing DB work concurrently with the pool.
    """
    if requested is not None:
        return max(0, requested)
    raw = os.getenv("OO_REINDEX_WORKERS", "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    cpu = os.cpu_count() or 1
    return max(0, min(_MAX_WORKERS_CAP, cpu - 1))


def all_cores_worker_count() -> int:
    """Most of the machine's CPU cores -- an explicit override of
    :func:`worker_count`'s conservative default (field-feedback Session A §4,
    "import owns the machine": re-index workers scale with core count). Used
    ONLY when a restore is genuinely running exclusively (background
    collection confirmed paused for its duration, i.e. the caller only reaches
    this when its own ``was_paused`` is True), so there is no writer process
    competing for the other cores. Every per-worker task is CPU-bound
    pure-Python extraction with no DB/ORM access (see the module docstring),
    so handing it many cores is safe from a CORRECTNESS standpoint -- but
    still bounded at :data:`_MAX_EXCLUSIVE_WORKERS_CAP` (never literally
    unbounded) so a huge box can't spawn an equally huge process pool, once
    per precompute window, stacked on top of the concurrently-enlarged SQLite
    cache -- a resource-EXHAUSTION concern, not a correctness one."""
    return max(1, min(_MAX_EXCLUSIVE_WORKERS_CAP, os.cpu_count() or 1))


# --------------------------------------------------------------------------- #
#  worker process: the extractor is reconstructed ONCE at pool startup and
#  reused for every task handed to that worker.
# --------------------------------------------------------------------------- #
_worker_extractor: Any = None  # process-local global, set by _worker_init


def _worker_init(extractor_name: str, gazetteer: dict[str, str] | None) -> None:
    global _worker_extractor
    from src.analytics.extract import get_extractor

    _worker_extractor = get_extractor(extractor_name, gazetteer=gazetteer)


def _worker_compute(
    article_id: int, content: str, title: str, language: str, sentiment_lang: str | None
) -> tuple[int, list[ExtractedTerm], float | None, str | None, str | None]:
    """Runs in a worker process. Never raises: one article's extraction error
    is returned as a marker (5th element) so the caller can isolate just that
    article, instead of losing the whole batch's parallel work."""
    from src.analytics.sentiment import score_article

    try:
        terms = _worker_extractor.extract(
            content or "", title=title or "", language=language or "en"
        )
        score, label = score_article(content, sentiment_lang)
        return article_id, terms, score, label, None
    except Exception as exc:  # noqa: BLE001 - isolate one bad article, never the batch
        return article_id, [], None, None, str(exc)


# --------------------------------------------------------------------------- #
#  serial computation: the reference implementation AND the universal fallback
# --------------------------------------------------------------------------- #
def _compute_one(
    extractor, article_id: int, content: str, title: str, language: str, sentiment_lang: str | None
) -> ArticleDerivatives:
    from src.analytics.sentiment import score_article

    try:
        terms = extractor.extract(content or "", title=title or "", language=language or "en")
        score, label = score_article(content, sentiment_lang)
        return ArticleDerivatives(article_id, terms, score, label)
    except Exception as exc:  # noqa: BLE001 - one bad article's precompute must not abort the batch
        _LOG.warning("precompute failed for article %s", article_id, exc_info=True)
        return ArticleDerivatives(article_id, [], None, None, error=str(exc))


def _serial(tasks: Sequence[Task], extractor) -> dict[int, ArticleDerivatives]:
    return {
        aid: _compute_one(extractor, aid, content, title, language, slang)
        for aid, content, title, language, slang in tasks
    }


def precompute_batch(
    tasks: Sequence[Task],
    *,
    extractor,
    workers: int | None = None,
) -> dict[int, ArticleDerivatives]:
    """Compute ``{article_id: ArticleDerivatives}`` for a batch of
    ``(article_id, content, title, language, sentiment_language)`` tuples.

    Runs in a bounded process pool when the batch is large enough and the
    extractor is a known, by-name-reconstructible kind; otherwise (or on ANY
    pool failure) computes serially in-process with the CALLER's own
    ``extractor`` object -- byte-identical to calling ``extractor.extract`` +
    ``score_article`` directly per article, just batched.
    """
    if not tasks:
        return {}
    n_workers = worker_count(workers)
    extractor_name = getattr(extractor, "name", None)
    if (
        n_workers <= 1
        or len(tasks) < _MIN_PARALLEL_BATCH
        or extractor_name not in _RECONSTRUCTIBLE_EXTRACTORS
    ):
        return _serial(tasks, extractor)

    gazetteer = getattr(extractor, "gazetteer", None)
    n_workers = min(n_workers, len(tasks))
    chunksize = max(1, len(tasks) // (n_workers * 4))
    try:
        out: dict[int, ArticleDerivatives] = {}
        with ProcessPoolExecutor(
            max_workers=n_workers,
            initializer=_worker_init,
            initargs=(extractor_name, gazetteer),
        ) as pool:
            ids, contents, titles, languages, slangs = zip(*tasks, strict=True)
            for aid, terms, score, label, err in pool.map(
                _worker_compute, ids, contents, titles, languages, slangs, chunksize=chunksize
            ):
                out[aid] = ArticleDerivatives(aid, terms, score, label, error=err)
        return out
    except Exception:  # noqa: BLE001 - a multiprocessing hiccup must NEVER cost a re-index its result
        _LOG.warning("parallel precompute failed; falling back to serial", exc_info=True)
        return _serial(tasks, extractor)
