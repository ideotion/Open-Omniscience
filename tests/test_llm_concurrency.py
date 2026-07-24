"""Tests for the B3 bounded concurrent-generation helper (src/llm/concurrency.py)."""

from __future__ import annotations

import threading
import time

from src.llm import concurrency as C


def test_concurrency_for_defaults_ollama_serial_vllm_conservative(monkeypatch):
    monkeypatch.delenv("OO_OLLAMA_CONCURRENCY", raising=False)
    monkeypatch.delenv("OO_VLLM_CONCURRENCY", raising=False)
    assert C.concurrency_for("ollama") == 1
    assert C.concurrency_for("vllm") == C.DEFAULT_VLLM_CONCURRENCY
    assert C.concurrency_for("something-unknown") == 1


def test_concurrency_for_honors_operator_overrides(monkeypatch):
    monkeypatch.setenv("OO_OLLAMA_CONCURRENCY", "3")
    monkeypatch.setenv("OO_VLLM_CONCURRENCY", "16")
    assert C.concurrency_for("ollama") == 3
    assert C.concurrency_for("vllm") == 16


def test_concurrency_for_ignores_bad_or_non_positive_overrides(monkeypatch):
    monkeypatch.setenv("OO_VLLM_CONCURRENCY", "not-a-number")
    assert C.concurrency_for("vllm") == C.DEFAULT_VLLM_CONCURRENCY
    monkeypatch.setenv("OO_VLLM_CONCURRENCY", "0")
    assert C.concurrency_for("vllm") == C.DEFAULT_VLLM_CONCURRENCY
    monkeypatch.setenv("OO_VLLM_CONCURRENCY", "-5")
    assert C.concurrency_for("vllm") == C.DEFAULT_VLLM_CONCURRENCY


def test_run_concurrent_empty_input_returns_empty():
    assert C.run_concurrent([], lambda x: x, max_workers=4) == []


def test_run_concurrent_serial_path_never_uses_a_thread(monkeypatch):
    """max_workers<=1 must be a byte-identical plain for-loop -- no ThreadPoolExecutor
    touched at all (the Ollama-default posture)."""
    calling_thread = threading.current_thread()
    seen_threads = []

    def fn(x):
        seen_threads.append(threading.current_thread())
        return x * 2

    results = C.run_concurrent([1, 2, 3], fn, max_workers=1)
    assert [r.value for r in results] == [2, 4, 6]
    assert all(r.ok for r in results)
    assert all(t is calling_thread for t in seen_threads)


def test_run_concurrent_default_max_workers_is_serial():
    results = C.run_concurrent([1, 2, 3], lambda x: x + 1)  # max_workers defaults to 1
    assert [r.value for r in results] == [2, 3, 4]


def test_run_concurrent_preserves_order_under_real_concurrency():
    """Items dispatched with varying artificial delays must still come back in
    INPUT order, not completion order."""
    delays = {1: 0.05, 2: 0.01, 3: 0.03}

    def fn(x):
        time.sleep(delays[x])
        return x

    results = C.run_concurrent([1, 2, 3], fn, max_workers=3)
    assert [r.value for r in results] == [1, 2, 3]
    assert all(r.ok for r in results)


def test_run_concurrent_actually_overlaps_when_max_workers_over_one():
    """Prove real concurrency, not a disguised serial loop: N items each sleeping
    ``d`` seconds must complete in materially less than N*d wall time."""
    n, d = 6, 0.05
    start = time.monotonic()
    results = C.run_concurrent(list(range(n)), lambda x: (time.sleep(d), x)[1], max_workers=6)
    elapsed = time.monotonic() - start
    assert [r.value for r in results] == list(range(n))
    assert elapsed < (n * d) * 0.6  # generous margin, still proves real overlap


def test_run_concurrent_isolates_a_failure_without_aborting_the_batch():
    def fn(x):
        if x == 2:
            raise ValueError("boom")
        return x

    results = C.run_concurrent([1, 2, 3], fn, max_workers=3)
    assert results[0].ok and results[0].value == 1
    assert not results[1].ok and isinstance(results[1].error, ValueError)
    assert results[2].ok and results[2].value == 3


def test_run_concurrent_isolates_a_failure_in_serial_mode_too():
    def fn(x):
        if x == 2:
            raise RuntimeError("boom")
        return x

    results = C.run_concurrent([1, 2, 3], fn, max_workers=1)
    assert results[0].ok and results[2].ok
    assert not results[1].ok and isinstance(results[1].error, RuntimeError)


def test_run_concurrent_caps_worker_count_to_item_count():
    """max_workers larger than the item count must not error or hang."""
    results = C.run_concurrent([1], lambda x: x, max_workers=50)
    assert [r.value for r in results] == [1]


def test_chunked_splits_into_bounded_groups():
    assert C.chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert C.chunked([1, 2, 3], 10) == [[1, 2, 3]]
    assert C.chunked([], 3) == []
    assert C.chunked([1, 2, 3], 0) == [[1], [2], [3]]  # size floored to 1, never a div-by-zero
