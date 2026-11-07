"""Helpers that several modules used to carry as byte-identical private copies (audit A-036).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Stdlib only, and a top-level module on purpose: importing it must cost nothing and can never
close an import cycle (``src.utils`` imports bleach and the secret scrubber, which is too much
for a monitoring or ingest module to take on for a 14-line recursion).

Add a helper here only when two or more modules would otherwise hold the same body. Behaviour
is exactly what each copy did: the folding is a move, not a change
(``tests/test_shared_helpers_folded.py`` pins both halves).
"""

from __future__ import annotations

import json
import os
import statistics
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


def walk_no_score(obj: Any) -> None:
    """Raises explicitly (never a bare ``assert``, which ``python -O``/
    ``PYTHONOPTIMIZE`` strips silently and would let this self-test's own
    no-fabricated-score check false-pass under that flag — transversal
    audit 09, 2026-07-25, §10.4)."""
    banned = ("score", "ranking", "rating", "grade")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if any(b in str(k).lower() for b in banned):
                raise AssertionError(f"score-like key: {k}")
            walk_no_score(v)
    elif isinstance(obj, list):
        for v in obj:
            walk_no_score(v)


def median_ms(fn, repeats: int) -> tuple[float, float, int | None]:
    """Run ``fn`` ``repeats`` times; return (cold_ms, warm_median_ms, result_size)."""
    runs: list[float] = []
    size: int | None = None
    for i in range(repeats):
        t0 = time.perf_counter()
        out = fn()
        runs.append((time.perf_counter() - t0) * 1000.0)
        if i == 0:
            size = len(out) if hasattr(out, "__len__") else None
    warm = runs[1:] or runs
    return round(runs[0], 1), round(statistics.median(warm), 1), size


def coerce_bool(value, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return fallback


def snapshot_or_unavailable(snapshot: Callable[[], dict]) -> dict:
    """``snapshot()``, or the class of the failure that kept it from being read (never its words, never a zero)."""
    try:
        return snapshot()
    except Exception as exc:  # noqa: BLE001 - the pass is written without the figures, saying so
        return {"unavailable": type(exc).__name__}


def import_owns_the_machine() -> bool:
    """True while an import run holds the exclusive window. Best-effort: an
    unreadable scheduler must never park this job forever."""
    try:
        from src.scheduler.runner import exclusive_window_open

        return exclusive_window_open()
    except Exception:  # noqa: BLE001 - a courtesy check is never load-bearing
        return False


def rss_mb() -> float | None:
    try:
        import psutil

        return round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001 - RSS is best-effort
        return None


def read_jsonl_tail(path: Path, limit: int) -> list[dict]:
    """The last ``limit`` lines of a JSON-lines file that parse (a torn or foreign line is skipped); ``[]`` when the file is missing."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def tri_state(env_name: str) -> str:
    """'forced-on' for ``1``, 'forced-off' for ``0``, else 'auto': how a serve is decided from one environment variable."""
    env = os.getenv(env_name)
    if env == "1":
        return "forced-on"
    if env == "0":
        return "forced-off"
    return "auto"
