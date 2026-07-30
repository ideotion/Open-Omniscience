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
        # 6 elements since 2026-07-30: the when/where/who EXTRACTION half joined
        # this same precompute (it was the serial ~200-300 ms/article that capped a
        # field import at ~2 art/s). On the error path it is None -- "not
        # precomputed", so index_article extracts inline, which is the same
        # correct-and-slower fallback the terms/sentiment error path already takes.
        aid, terms, score, label, err, www = rp._worker_compute(1, "x", "t", "en", None)
    finally:
        rp._worker_extractor = None
    assert aid == 1
    assert terms == []
    assert score is None and label is None
    assert err is not None and "simulated extraction failure" in err
    assert www is None, "a failed article must not claim a when/where/who result"


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


# --------------------------------------------------------------------------- #
#  A pool that does not FAIL but simply never answers (field hang, 2026-07-30).
#  An import sat at 3000/686896 for over an hour: fork from the threaded API
#  process left a worker deadlocked on an inherited lock, the parent blocked in
#  pool.map, and the except-Exception guard above could not fire -- a deadlock
#  is not an exception. These pin the three things that make that survivable.
# --------------------------------------------------------------------------- #
class _FakeWorker:
    def __init__(self):
        self.terminated = False

    def is_alive(self):
        return not self.terminated

    def terminate(self):
        self.terminated = True


class _WedgedPool:
    """Accepts the work, then never answers."""

    def __init__(self, *a, **k):
        self.map_kwargs = None
        self.shutdown_calls = []
        self.worker = _FakeWorker()
        self._processes = {1: self.worker}

    def map(self, *a, **k):
        self.map_kwargs = k
        raise TimeoutError("simulated: the worker never answered")

    def shutdown(self, wait=True, cancel_futures=False):
        self.shutdown_calls.append({"wait": wait, "cancel_futures": cancel_futures})

    # Deliberately a context manager: the PRE-FIX code used `with
    # ProcessPoolExecutor(...)`, so without these the old code would fail these
    # tests merely for lacking __enter__ -- an attribute-absence failure, which
    # proves nothing about behaviour. With them, the old code reaches map() and
    # exits through shutdown(wait=True), and the tests fail for the real reason.
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.shutdown(wait=True)
        return False


def _wedged(monkeypatch):
    made = []

    class _P(_WedgedPool):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            made.append(self)

    monkeypatch.setattr(rp, "ProcessPoolExecutor", _P)
    # raising=False so this helper also runs against the pre-fix module, which
    # has no _pool_context -- see __exit__ above.
    monkeypatch.setattr(rp, "_pool_context", lambda: None, raising=False)
    return made


def test_a_wedged_pool_times_out_and_still_returns_the_right_answer(monkeypatch):
    made = _wedged(monkeypatch)
    ex = BaselineExtractor()
    stats: dict = {}
    out = rp.precompute_batch(_ARTICLE_TEXTS, extractor=ex, workers=4, stats=stats)

    ref = rp._serial(_ARTICLE_TEXTS, ex)
    assert set(out) == set(ref)
    for aid in ref:
        assert _sorted_terms(out[aid].terms) == _sorted_terms(ref[aid].terms)
    assert stats["by_path"] == {"fallback": 1}, "a hang must be recorded as a degradation"
    assert made, "the pool was never constructed"


def test_pool_map_actually_receives_a_timeout(monkeypatch):
    """A timeout that is never wired through is the entire bug -- pool.map without
    one waits forever, so this asserts the argument, not just the constant."""
    made = _wedged(monkeypatch)
    rp.precompute_batch(_ARTICLE_TEXTS, extractor=BaselineExtractor(), workers=4)
    assert made[0].map_kwargs["timeout"] == rp._POOL_TIMEOUT_S


def test_a_wedged_worker_is_never_joined(monkeypatch):
    """`with ProcessPoolExecutor(...)` exits via shutdown(wait=True), which joins
    the very worker that is stuck -- the cleanup then hangs exactly as hard as the
    thing it is cleaning up after. Teardown must never wait, and must kill."""
    made = _wedged(monkeypatch)
    rp.precompute_batch(_ARTICLE_TEXTS, extractor=BaselineExtractor(), workers=4)
    pool = made[0]
    assert pool.shutdown_calls == [{"wait": False, "cancel_futures": True}]
    assert pool.worker.terminated is True


def test_pool_timeout_env_override(monkeypatch):
    monkeypatch.setenv("OO_REINDEX_POOL_TIMEOUT_S", "12.5")
    assert rp._pool_timeout_s() == 12.5
    monkeypatch.setenv("OO_REINDEX_POOL_TIMEOUT_S", "0")
    assert rp._pool_timeout_s() is None, "0 disables the backstop, per the docstring"
    monkeypatch.setenv("OO_REINDEX_POOL_TIMEOUT_S", "not-a-number")
    assert rp._pool_timeout_s() == rp._POOL_TIMEOUT_S, "garbage must not disable it"


def test_env_worker_count_outranks_an_explicit_request(monkeypatch):
    """The import's exclusive path passes all_cores_worker_count() explicitly, so
    before this the documented OO_REINDEX_WORKERS=0 had no effect on precisely the
    run most likely to need it. An escape hatch an internal default outranks is
    not an escape hatch."""
    monkeypatch.setenv("OO_REINDEX_WORKERS", "0")
    assert rp.worker_count(rp.all_cores_worker_count()) == 0
    monkeypatch.setenv("OO_REINDEX_WORKERS", "3")
    assert rp.worker_count(32) == 3
    monkeypatch.delenv("OO_REINDEX_WORKERS", raising=False)
    assert rp.worker_count(32) == 32, "without the env var, the caller still decides"


def test_the_resolved_start_method_is_never_bare_fork(monkeypatch):
    """fork copies the parent's memory but only the calling thread, so a mutex held
    by any other thread is inherited locked with no owner -- the deadlock this whole
    section exists for. Availability is not usability, so this resolves for real."""
    monkeypatch.setattr(rp, "_POOL_CTX_RESOLVED", False)
    monkeypatch.setattr(rp, "_POOL_CTX", None)
    ctx = rp._pool_context()
    if ctx is None:  # honest: neither forkserver nor spawn is usable in this env
        return
    assert ctx.get_start_method() in {"forkserver", "spawn"}
