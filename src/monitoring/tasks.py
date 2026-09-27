"""In-process registry of BACKGROUND TASKS for the task manager.

The task manager must show "what is actually happening" — not only scrapes and
downloads, but LLM summarize/translate runs, AI keyword extraction, and any other
long-running background work (maintainer 2026-06-18, the Windows-Task-Manager
vision: "see what is actually happening — is an LLM translating?").

This is a tiny, thread-safe, LIVE registry: an operation registers a task when it
starts and finishes it when done. No persistence, no shadow state — like
``/api/jobs``, the view aggregates the REAL running operations, so it cannot
disagree with reality. A leaked task (a missed ``finish`` on an odd exception
path) self-expires after ``_STALE_S`` so a crash never pins a ghost row forever.

Honesty by construction: a task carries only real, owner-reported facts (a label,
an optional detail, an optional done/total it chooses to publish) — never a
fabricated percentage or ETA. A label that carries a value ("Summarizing “{title}”")
may also be given as its FRAME and values (``label_i18n`` / ``label_vars``), which the
task managers write in the UI language; ``label`` stays the English sentence
(click-through B17, T11). The ``detail`` line may travel the same way
(``detail_i18n`` / ``detail_vars``: "model {model}", click-through B19, Q5). Kinds
group the rows in the UI (``llm`` / ``analytics`` / ``index`` …); the
scrape/download jobs keep their own owners
(``/api/jobs`` aggregates both).
"""

from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

_LOCK = threading.Lock()
_SEQ = itertools.count(1)
_TASKS: dict[int, dict] = {}

# A task with no update for this long is treated as stale and pruned — defensive
# against a missed finish() on an exception path that bypasses ``track``.
_STALE_S = 3600.0


def register(
    kind: str,
    label: str,
    *,
    detail: str | None = None,
    total: int | None = None,
    label_i18n: str | None = None,
    label_vars: dict | None = None,
    detail_i18n: str | None = None,
    detail_vars: dict | None = None,
) -> int:
    """Register a running background task; returns a token to update/finish it."""
    tok = next(_SEQ)
    now = time.time()
    with _LOCK:
        _TASKS[tok] = {
            "token": tok,
            "kind": kind,
            "label": label,
            "label_i18n": label_i18n,
            "label_vars": dict(label_vars) if label_vars else None,
            "detail": detail,
            "detail_i18n": detail_i18n,
            "detail_vars": dict(detail_vars) if detail_vars else None,
            "total": total,
            "done": 0,
            "started_at": now,
            "updated_at": now,
        }
    return tok


def update(
    token: int,
    *,
    detail: str | None = None,
    done: int | None = None,
    total: int | None = None,
    detail_i18n: str | None = None,
    detail_vars: dict | None = None,
) -> None:
    """Publish real progress the owner chose to report (never a fabricated %)."""
    with _LOCK:
        t = _TASKS.get(token)
        if not t:
            return
        if detail is not None:
            t["detail"] = detail
            # A new detail replaces its frame too: a frame left from the previous detail
            # would write the OLD sentence in every language but English.
            t["detail_i18n"] = detail_i18n
            t["detail_vars"] = dict(detail_vars) if detail_vars else None
        if done is not None:
            t["done"] = done
        if total is not None:
            t["total"] = total
        t["updated_at"] = time.time()


def finish(token: int) -> None:
    """Remove the task (it is no longer running)."""
    with _LOCK:
        _TASKS.pop(token, None)


@contextmanager
def track(
    kind: str,
    label: str,
    *,
    detail: str | None = None,
    total: int | None = None,
    label_i18n: str | None = None,
    label_vars: dict | None = None,
    detail_i18n: str | None = None,
    detail_vars: dict | None = None,
) -> Iterator[int]:
    """Context manager: the task is visible for the duration of the ``with`` block
    and always removed on exit (success or error)."""
    tok = register(
        kind, label, detail=detail, total=total, label_i18n=label_i18n, label_vars=label_vars,
        detail_i18n=detail_i18n, detail_vars=detail_vars,
    )
    try:
        yield tok
    finally:
        finish(tok)


def snapshot() -> list[dict]:
    """Point-in-time copy of the running background tasks, oldest first. Stale rows
    (no update within ``_STALE_S``) are pruned defensively."""
    now = time.time()
    with _LOCK:
        stale = [k for k, v in _TASKS.items() if now - v["updated_at"] > _STALE_S]
        for k in stale:
            _TASKS.pop(k, None)
        out = [dict(t) for t in _TASKS.values()]
    for d in out:
        d["elapsed_s"] = round(now - d["started_at"], 1)
    out.sort(key=lambda d: d["started_at"])
    return out
