"""Parallel precomputation of keyword extraction + sentiment (src/analytics/reindex_parallel.py).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field report 2026-07-19: a large restore-merge pinned one CPU core for hours (the
post-merge per-article re-index is a serial Python loop) while disk writes trickled
to a crawl every 30+ seconds -- the interval spent entirely inside single-threaded
extraction. This module offloads the two CPU-bound, DB-free steps (keyword
extraction + sentiment scoring) to a bounded process pool. These tests pin: real
serial/parallel PARITY (the whole point -- a parallel run must be byte-identical to
the serial one), a small batch / disabled workers / unrecognised extractor NEVER
touching the pool, a worker's own per-article error isolation (never dropping the
rest of the batch), and a pool failure degrading to the exact serial computation.
"""

from __future__ import annotations

import src.analytics.reindex_parallel as rp
from src.analytics.extract import BaselineExtractor


def _sorted_terms(terms):
    return sorted((t.term, t.normalized, t.kind, t.count, t.first_offset) for t in terms)


def test_worker_count_explicit_override():
    assert rp.worker_count(0) == 0
    assert rp.worker_count(5) == 5
    assert rp.worker_count(-3) == 0  # never negative


def test_worker_count_env_override(monkeypatch):
    monkeypatch.setenv("OO_REINDEX_WORKERS", "2")
    assert rp.worker_count() == 2
    monkeypatch.setenv("OO_REINDEX_WORKERS", "0")
    assert rp.worker_count() == 0  # the documented opt-out


def test_worker_count_default_leaves_one_core_and_caps(monkeypatch):
    monkeypatch.delenv("OO_REINDEX_WORKERS", raising=False)
    monkeypatch.setattr(rp.os, "cpu_count", lambda: 6)
    assert rp.worker_count() == 5  # cpu_count - 1
    monkeypatch.setattr(rp.os, "cpu_count", lambda: 64)
    assert rp.worker_count() == rp._MAX_WORKERS_CAP  # capped, not dozens of workers
    monkeypatch.setattr(rp.os, "cpu_count", lambda: 1)
    assert rp.worker_count() == 0  # a single-core box never parallelises


def test_all_cores_worker_count_ignores_the_conservative_cap(monkeypatch):
    """'import owns the machine' (field-feedback Session A §4): unlike
    worker_count()'s default, this NEVER reserves a core for a writer
    process and NEVER clamps to _MAX_WORKERS_CAP -- an explicit override for
    when collection is genuinely paused and nothing else needs a core. It
    IS still bounded at _MAX_EXCLUSIVE_WORKERS_CAP, a HIGHER but still finite
    ceiling (a data-loss-lens skeptic finding, 2026-07-24, MEDIUM: the first
    cut had no ceiling at all -- a huge box would spawn an equally huge
    process pool, stacking with the concurrently-enlarged SQLite cache)."""
    monkeypatch.setattr(rp.os, "cpu_count", lambda: 6)
    assert rp.all_cores_worker_count() == 6  # not 5 (worker_count's cpu-1)
    monkeypatch.setattr(rp.os, "cpu_count", lambda: 20)
    assert rp.all_cores_worker_count() == 20  # well above worker_count's cap of 8
    monkeypatch.setattr(rp.os, "cpu_count", lambda: 64)
    assert rp.all_cores_worker_count() == rp._MAX_EXCLUSIVE_WORKERS_CAP  # capped, not 64
    assert rp._MAX_EXCLUSIVE_WORKERS_CAP > rp._MAX_WORKERS_CAP  # a HIGHER ceiling than the default
    monkeypatch.setattr(rp.os, "cpu_count", lambda: 1)
    assert rp.all_cores_worker_count() == 1  # never 0 -- always at least one worker
    monkeypatch.setattr(rp.os, "cpu_count", lambda: None)
    assert rp.all_cores_worker_count() == 1  # honest fallback, never a crash


_ARTICLE_TEXTS = [
    (
        i,
        f"Reuters reports the WHO announced a wonderful election policy on climate "
        f"change and the vaccine market number {i}. Great fantastic news today.",
        f"Title {i}",
        "en",
        "en",
    )
    for i in range(1, 40)
]


def test_serial_and_parallel_are_byte_identical():
    """The whole point of this module: offloading to workers must never change a
    single extracted term, count, offset, or sentiment value."""
    ex = BaselineExtractor()
    assert len(_ARTICLE_TEXTS) >= rp._MIN_PARALLEL_BATCH  # a real parallel dispatch, not the small-batch gate
    serial = rp.precompute_batch(_ARTICLE_TEXTS, extractor=ex, workers=0)
    parallel = rp.precompute_batch(_ARTICLE_TEXTS, extractor=ex, workers=4)
    assert set(serial) == set(parallel) == {t[0] for t in _ARTICLE_TEXTS}
    for aid, d in serial.items():
        p = parallel[aid]
        assert _sorted_terms(d.terms) == _sorted_terms(p.terms)
        assert d.sentiment_score == p.sentiment_score
        assert d.sentiment_label == p.sentiment_label
        assert d.error is None and p.error is None


def test_small_batch_and_disabled_workers_never_touch_the_pool(monkeypatch):
    """A batch under the parallel threshold, ``workers=0``/``1``, or an
    unrecognised (custom/test-double) extractor must ALWAYS take the serial path --
    proven by making the pool explode if it is ever constructed."""

    def _boom(*a, **k):
        raise AssertionError("the pool must not be constructed for this case")

    monkeypatch.setattr(rp, "ProcessPoolExecutor", _boom)
    ex = BaselineExtractor()

    # too small for the parallel threshold
    small = _ARTICLE_TEXTS[:3]
    out = rp.precompute_batch(small, extractor=ex, workers=8)
    assert len(out) == 3

    # workers explicitly disabled
    out = rp.precompute_batch(_ARTICLE_TEXTS, extractor=ex, workers=0)
    assert len(out) == len(_ARTICLE_TEXTS)

    # an unrecognised extractor kind (mirrors a test double / custom extractor):
    # reconstructing it BY NAME in a worker would silently swap in a real
    # BaselineExtractor instead of the caller's own object -- must never happen.
    class CustomExtractor:
        name = "custom-test-double"

        def extract(self, content, *, title="", language="en"):
            return ex.extract(content, title=title, language=language)

    out = rp.precompute_batch(_ARTICLE_TEXTS, extractor=CustomExtractor(), workers=8)
    assert len(out) == len(_ARTICLE_TEXTS)


def test_worker_compute_isolates_one_articles_error():
    """``_worker_compute`` runs INSIDE a worker process, so it must never raise --
    one article's extraction bug is reported as a marker, never propagated (which
    would otherwise force the WHOLE batch back to serial, losing every other
    article's already-done parallel work)."""

    class Boom:
        name = "baseline"

        def extract(self, content, *, title="", language="en"):
            raise RuntimeError("simulated extraction failure")

    rp._worker_extractor = Boom()
    try:
        aid, terms, score, label, err = rp._worker_compute(1, "x", "t", "en", None)
    finally:
        rp._worker_extractor = None
    assert aid == 1
    assert terms == []
    assert score is None and label is None
    assert err is not None and "simulated extraction failure" in err


def test_pool_failure_degrades_to_serial(monkeypatch):
    """ANY trouble building/using the pool (spawn restricted, a broken worker, a
    pickling hiccup, ...) must fall back to the exact serial computation over the
    WHOLE batch -- a parallelism problem must never cost a re-index its result."""

    class _BrokenPool:
        def __init__(self, *a, **k):
            raise OSError("simulated: process spawn restricted in this environment")

    monkeypatch.setattr(rp, "ProcessPoolExecutor", _BrokenPool)
    ex = BaselineExtractor()
    out = rp.precompute_batch(_ARTICLE_TEXTS, extractor=ex, workers=4)
    ref = rp._serial(_ARTICLE_TEXTS, ex)
    assert set(out) == set(ref)
    for aid in ref:
        assert _sorted_terms(out[aid].terms) == _sorted_terms(ref[aid].terms)
        assert out[aid].error is None


def test_empty_batch_returns_empty():
    assert rp.precompute_batch([], extractor=BaselineExtractor(), workers=4) == {}
