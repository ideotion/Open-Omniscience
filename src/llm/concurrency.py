"""
Bounded concurrent-generation helper (B3, 2026-07-24 field-feedback Session B).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

vLLM's actual advantage over Ollama is that it CAN serve many concurrent
generation requests efficiently (continuous batching on the GPU) -- Ollama,
by this project's own default posture, processes one generation at a time.
Rather than every batch consumer (bulk summarize/translate, the continuous
langdetect job, the triage/tag runs, law-change summaries) hand-rolling its
own thread pool with its own guess at a worker count, this module is the ONE
place that decision lives.

``concurrency_for(backend_name)`` returns the bounded worker count:
  * vLLM  -- a conservative, DISCLOSED default (never asserted as an exact,
    measured fact -- the same honesty posture as
    ``vllm_lifecycle.compute_server_args``), overridable via
    ``OO_VLLM_CONCURRENCY``.
  * Ollama -- 1 (strictly serial) unless the OPERATOR explicitly raises it via
    ``OO_OLLAMA_CONCURRENCY``. Ollama can itself serve concurrent requests if
    ``OLLAMA_NUM_PARALLEL`` is set on the Ollama SERVER side, but this app
    never assumes that is configured -- serial-by-default is the safe,
    honest posture; the operator opts in.

``run_concurrent(items, fn, max_workers=)`` runs ``fn(item)`` for every item:
  * ORDER-PRESERVING -- the returned list lines up 1:1 with ``items``, so a
    caller storing per-article results never has to re-sort them.
  * PER-ITEM ERROR ISOLATION -- one raising call becomes a captured exception
    in its own slot; it never aborts the batch and never propagates (the A1
    resilience discipline: a batch consumer decides for itself what an
    isolated failure vs. a genuine "the backend just went away" signal means
    by inspecting each slot's ``error``).
  * ``max_workers <= 1`` never spins up a thread pool -- a byte-identical
    plain ``for`` loop, so the Ollama default has zero behavioural or timing
    surprises versus the pre-B3 code.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")
R = TypeVar("R")

# A conservative, disclosed default -- NOT a measured fact. Mirrors the
# vllm_lifecycle context auto-tune's own "heuristic, never asserted as exact"
# posture. The operator can measure and override via OO_VLLM_CONCURRENCY.
DEFAULT_VLLM_CONCURRENCY = 4


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def concurrency_for(backend_name: str) -> int:
    """The bounded worker count for a resolved backend name ("vllm"/"ollama").

    Unknown backend names fall back to the serial (1) default -- the safe
    posture when a caller passes something this module doesn't recognise."""
    if backend_name == "vllm":
        return _int_env("OO_VLLM_CONCURRENCY", DEFAULT_VLLM_CONCURRENCY)
    return _int_env("OO_OLLAMA_CONCURRENCY", 1)


@dataclass
class ConcurrentResult:
    """One slot's outcome. Exactly one of ``value``/``error`` is set."""

    ok: bool
    value: Any = None
    error: BaseException | None = None


def run_concurrent(
    items: Sequence[T],
    fn: Callable[[T], R],
    *,
    max_workers: int = 1,
) -> list[ConcurrentResult]:
    """Run ``fn(item)`` for every item in ``items``.

    Returns a list the same length as ``items``, in the SAME order, each slot
    a :class:`ConcurrentResult`. ``max_workers <= 1`` (the Ollama default)
    never touches a thread pool at all."""
    if not items:
        return []
    if max_workers <= 1:
        out: list[ConcurrentResult] = []
        for it in items:
            try:
                out.append(ConcurrentResult(ok=True, value=fn(it)))
            except Exception as exc:  # noqa: BLE001 - isolate per item, never abort the batch
                out.append(ConcurrentResult(ok=False, error=exc))
        return out

    workers = min(max_workers, len(items))
    out = [ConcurrentResult(ok=False, error=RuntimeError("not scheduled"))] * len(items)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fn, it): i for i, it in enumerate(items)}
        for fut, i in futures.items():
            try:
                out[i] = ConcurrentResult(ok=True, value=fut.result())
            except Exception as exc:  # noqa: BLE001 - isolate per item, never abort the batch
                out[i] = ConcurrentResult(ok=False, error=exc)
    return out


def chunked(items: Sequence[T], size: int) -> list[list[T]]:
    """Split ``items`` into consecutive chunks of at most ``size`` -- the
    granularity at which callers check a cooperative-cancel flag between
    concurrent batches (a chunk in flight still runs to completion, mirroring
    the project's existing batched-commit cancellation convention)."""
    size = max(1, size)
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


__all__ = [
    "DEFAULT_VLLM_CONCURRENCY",
    "ConcurrentResult",
    "chunked",
    "concurrency_for",
    "run_concurrent",
]
