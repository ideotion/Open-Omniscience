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
single DB session/writer still applies the results serially, exactly as before
-- the single-writer SQLite design is untouched; only the CPU-bound, DB-free
precomputation is parallelised.

WHEN/WHERE/WHO IS PART OF THAT PRECOMPUTE (2026-07-30). This module used to say
WWW "is more tightly DB-coupled ... and is not the dominant per-article cost",
and left it running inline. That claim was asserted, never measured, and it is
FALSE. Measured on date/place-SPARSE generic prose, so it is not an artifact of
date-dense synthetic text:

    body size   extract_dates   extract_locations   serial total   ceiling
       10 KB         57.9 ms            22.5 ms         80.5 ms   12.4 art/s
       25 KB        143.9 ms            47.6 ms        191.5 ms    5.2 art/s
       40 KB        226.1 ms            71.7 ms        297.8 ms    3.4 art/s
       50 KB        278.7 ms            94.2 ms        373.0 ms    2.7 art/s

against ~36 ms for the pooled half at the same size. At this project's own
stated ~35 KB article (the SQLCipher codec-trap lesson), the SERIAL half was
roughly TEN TIMES the parallel one -- so the pool was carefully parallelising
the cheap part while the expensive part pinned one core. A field import
measured ~2 articles/sec, which is exactly the ceiling that table predicts and
which no amount of extra workers could have moved.

The EXTRACTION half of when/where/who is as pure as the other two -- a function
of the article's own text -- so it now rides the same pool. Only the STORE half
(savepoints, live-session error handling, the delete-then-reinsert) stays in
the main process, where it belongs and where its cost is small.

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
import time
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

#: One task. The first five elements are ``(article_id, content, title, language,
#: sentiment_language)``; a SIXTH, optional element carries the when/where/who
#: context ``(country, anchor_iso_date, today_iso_date)`` and opts that article
#: into pooled WWW extraction. Deliberately optional rather than a widened
#: tuple: every existing caller and its exact-equality assertions keep working
#: unchanged, and a caller that cannot supply the context (or does not want WWW
#: precomputed) simply omits it and gets the previous behaviour exactly.
Task = tuple  # (int, str, str, str, str | None[, WwwContext | None])

#: ``(country, anchor_iso, today_iso)`` -- plain data, never an ORM object.
WwwContext = tuple


@dataclass
class ArticleDerivatives:
    """The DB-free half of one article's ``index_article`` result."""

    article_id: int
    terms: list[ExtractedTerm]
    sentiment_score: float | None
    sentiment_label: str | None
    error: str | None = None  # set only when THIS article's compute failed
    #: The when/where/who EXTRACTION result, when the task asked for it. ``None``
    #: means "not precomputed" -- which the caller must treat as "extract it
    #: inline", NOT as "this article has none". The two are different facts and
    #: conflating them would silently drop every date and place on any path that
    #: does not use the pool.
    www: dict | None = None


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


def _extract_www(content: str, language: str | None, www_ctx) -> dict | None:
    """The PURE half of when/where/who: extraction only, no database.

    Returns plain, picklable data (lists of dicts) or ``None`` when the caller
    did not ask for it. Runs in a worker process, so it must never touch an ORM
    object or a session -- it is handed only the article's own text plus the
    three scalars the extractors need (``country`` for place disambiguation,
    ``anchor`` for relative dates like "yesterday", ``today`` for the same).

    A failure here returns ``None`` rather than raising: ``None`` means "not
    precomputed", so the caller falls back to extracting inline exactly as it
    did before, and a broken WWW extraction can never cost the article its
    keywords.

    ...WHICH IS WHY THE FAILURE IS RECORDED, not just swallowed. This degrade is
    SILENT BY DESIGN -- correct results, quietly at the old speed -- so on its own
    it is a perfect hiding place for the very bug it exists to survive. (Proven
    immediately: the first cut imported ``extract_entities`` from the wrong module,
    every call returned None, every article fell back to inline extraction, and
    NOTHING failed -- the optimisation simply did not happen. A benchmark caught it;
    no test would have.) The ``__www_error__`` marker rides back with the result so
    the caller can count it and the import report can say so."""
    if not www_ctx:
        return None
    from datetime import date as _date

    country, anchor_iso, today_iso = (list(www_ctx) + [None, None, None])[:3]
    try:
        from src.timemap.dateextract import extract_dates
        from src.timemap.entextract import extract_entities
        from src.timemap.locextract import extract_locations

        return {
            "dates": extract_dates(
                content or "",
                today=_date.fromisoformat(today_iso) if today_iso else None,
                anchor=_date.fromisoformat(anchor_iso) if anchor_iso else None,
                language=language,
            ),
            "places": extract_locations(content or "", source_country=country),
            "entities": extract_entities(content or ""),
        }
    except Exception as exc:  # noqa: BLE001 - degrades to inline, never to "none found"
        _LOG.warning("pooled when/where/who extraction failed", exc_info=True)
        return {"__www_error__": str(exc)}


def _worker_compute(
    article_id: int,
    content: str,
    title: str,
    language: str,
    sentiment_lang: str | None,
    www_ctx=None,
) -> tuple[int, list[ExtractedTerm], float | None, str | None, str | None, "dict | None"]:
    """Runs in a worker process. Never raises: one article's extraction error
    is returned as a marker (5th element) so the caller can isolate just that
    article, instead of losing the whole batch's parallel work."""
    from src.analytics.sentiment import score_article

    try:
        terms = _worker_extractor.extract(
            content or "", title=title or "", language=language or "en"
        )
        score, label = score_article(content, sentiment_lang)
        return article_id, terms, score, label, None, _extract_www(content, language, www_ctx)
    except Exception as exc:  # noqa: BLE001 - isolate one bad article, never the batch
        return article_id, [], None, None, str(exc), None


# --------------------------------------------------------------------------- #
#  serial computation: the reference implementation AND the universal fallback
# --------------------------------------------------------------------------- #
def _compute_one(
    extractor,
    article_id: int,
    content: str,
    title: str,
    language: str,
    sentiment_lang: str | None,
    www_ctx=None,
) -> ArticleDerivatives:
    from src.analytics.sentiment import score_article

    try:
        terms = extractor.extract(content or "", title=title or "", language=language or "en")
        score, label = score_article(content, sentiment_lang)
        # DELIBERATELY NOT precomputed on the serial path. Serial means "one core",
        # which is the situation pooled WWW exists to escape; doing it here would
        # move the same work from one place to another at identical cost, and the
        # caller's inline path already handles www=None correctly. Keeping it out
        # also keeps this function the byte-identical reference the fallback needs.
        return ArticleDerivatives(article_id, terms, score, label)
    except Exception as exc:  # noqa: BLE001 - one bad article's precompute must not abort the batch
        _LOG.warning("precompute failed for article %s", article_id, exc_info=True)
        return ArticleDerivatives(article_id, [], None, None, error=str(exc))


def _serial(tasks: Sequence[Task], extractor) -> dict[int, ArticleDerivatives]:
    return {
        t[0]: _compute_one(extractor, t[0], t[1], t[2], t[3], t[4])
        for t in tasks
    }


def precompute_batch(
    tasks: Sequence[Task],
    *,
    extractor,
    workers: int | None = None,
    stats: dict | None = None,
) -> dict[int, ArticleDerivatives]:
    """Compute ``{article_id: ArticleDerivatives}`` for a batch of
    ``(article_id, content, title, language, sentiment_language)`` tuples.

    Runs in a bounded process pool when the batch is large enough and the
    extractor is a known, by-name-reconstructible kind; otherwise (or on ANY
    pool failure) computes serially in-process with the CALLER's own
    ``extractor`` object -- byte-identical to calling ``extractor.extract`` +
    ``score_article`` directly per article, just batched.

    ``stats`` (optional, an out-parameter the caller owns): accumulates WHICH
    PATH actually ran -- ``pool`` / ``serial`` (the deliberate small-batch or
    unknown-extractor short-circuit) / ``fallback`` (a pool that broke and
    degraded). Without this a wall-clock measurement of this function cannot
    distinguish genuine parallel CPU work from a SILENT degradation to one
    core, which is exactly the question a "why is my import slow?" report has
    to answer. An out-parameter rather than a changed return type, so every
    existing caller and its exact-equality assertions are untouched.
    """
    if not tasks:
        return {}

    def _note(path: str, seconds: float) -> None:
        if stats is None:
            return
        stats["windows"] = stats.get("windows", 0) + 1
        stats["articles"] = stats.get("articles", 0) + len(tasks)
        stats["seconds"] = round(stats.get("seconds", 0.0) + seconds, 3)
        by = stats.setdefault("by_path", {})
        by[path] = by.get(path, 0) + 1

    n_workers = worker_count(workers)
    extractor_name = getattr(extractor, "name", None)
    if (
        n_workers <= 1
        or len(tasks) < _MIN_PARALLEL_BATCH
        or extractor_name not in _RECONSTRUCTIBLE_EXTRACTORS
    ):
        _t0 = time.monotonic()
        out_serial = _serial(tasks, extractor)
        _note("serial", time.monotonic() - _t0)
        return out_serial

    gazetteer = getattr(extractor, "gazetteer", None)
    n_workers = min(n_workers, len(tasks))
    chunksize = max(1, len(tasks) // (n_workers * 4))
    _t0 = time.monotonic()
    try:
        out: dict[int, ArticleDerivatives] = {}
        with ProcessPoolExecutor(
            max_workers=n_workers,
            initializer=_worker_init,
            initargs=(extractor_name, gazetteer),
        ) as pool:
            # Tolerate BOTH task shapes (5-tuple, or 6-tuple with the WWW context)
            # in the same batch: zip(*tasks) would raise on a ragged mix, and a
            # caller that supplies context for some articles and not others is a
            # legitimate case (an article with no usable anchor, say).
            ids = [t[0] for t in tasks]
            contents = [t[1] for t in tasks]
            titles = [t[2] for t in tasks]
            languages = [t[3] for t in tasks]
            slangs = [t[4] for t in tasks]
            ctxs = [t[5] if len(t) > 5 else None for t in tasks]
            for aid, terms, score, label, err, www in pool.map(
                _worker_compute, ids, contents, titles, languages, slangs, ctxs,
                chunksize=chunksize,
            ):
                out[aid] = ArticleDerivatives(aid, terms, score, label, error=err, www=www)
                if stats is not None and isinstance(www, dict) and "__www_error__" in www:
                    stats["www_errors"] = stats.get("www_errors", 0) + 1
                elif stats is not None and www:
                    stats["www_precomputed"] = stats.get("www_precomputed", 0) + 1
        _note("pool", time.monotonic() - _t0)
        return out
    except Exception:  # noqa: BLE001 - a multiprocessing hiccup must NEVER cost a re-index its result
        _LOG.warning("parallel precompute failed; falling back to serial", exc_info=True)
        out_fb = _serial(tasks, extractor)
        # Charge the WHOLE window (the wasted pool attempt AND the serial redo) to the
        # fallback -- measured from _t0, before the pool was attempted. That total is
        # what the operator actually waited for; timing only the redo would understate
        # exactly the degradation this stat exists to expose.
        _note("fallback", time.monotonic() - _t0)
        return out_fb
