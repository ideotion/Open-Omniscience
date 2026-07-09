"""A generic run-to-completion, cancellable, task-manager-visible background job (Item 8 P1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE FASTAPI-FREEZE LESSON (field test 2026-07-08, Item 8 P1): several heavy button actions
ran their whole multi-minute body SYNCHRONOUSLY in the request handler — governments
load-standard (2.9 min), enrich-source-types (8.5 min), keyword-tags backfill (1 min).
Even a plain ``def`` handler holds a threadpool token for the whole run AND (for a DB
writer) can hold the single-writer gate across the whole operation, so the button "freezes
the app" and blocks collection.

This is the lightweight background-job manager they should use. It differs from the
persisted, resumable managers (``ReindexJobManager`` / ``NewsletterImportManager``) on
purpose: these are BOUNDED one-shot operations, so there is no persisted cursor — a crash
just means re-run, never a lost corpus. What it provides:

  * a worker on a daemon thread, so the request returns immediately;
  * cooperative CANCEL (a stop Event the worker checks between units);
  * live PROGRESS (done/total/detail the worker reports, surfaced in /api/jobs);
  * honest terminal states (done / cancelled / error), the error message captured;
  * a registry so /api/jobs can enumerate every background job with no shadow state.

DB-writer workers open their OWN ``session_scope`` and commit per unit, so the writer gate
is taken+released per unit (never held across a network fetch or the whole run) — they join
the writer-arbitration set in /api/jobs. Network workers are still airplane-gated by their
endpoint up front. No score, local only.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

_LOG = logging.getLogger("jobs.background")


class JobContext:
    """Handed to the worker: cooperative stop + progress reporting (thread-safe)."""

    def __init__(self, job: BackgroundJob) -> None:
        self._job = job

    @property
    def stopping(self) -> bool:
        """True once cancel() was called — the worker should stop at the next safe point."""
        return self._job._stop.is_set()

    def set_progress(
        self, *, done: int | None = None, total: int | None = None, detail: str | None = None
    ) -> None:
        with self._job._lock:
            if done is not None:
                self._job._done = int(done)
            if total is not None:
                self._job._total = int(total)
            if detail is not None:
                self._job._detail = str(detail)


class BackgroundJob:
    """One named background job kind (a process-lifetime singleton per kind)."""

    def __init__(
        self,
        kind: str,
        label: str,
        worker: Callable[..., Any],
        *,
        is_writer: bool = False,
        cancellable: bool = False,
    ) -> None:
        self.kind = kind
        self.label = label
        self._worker = worker
        self.is_writer = is_writer
        # HONESTY (no theater): only advertise a Cancel affordance when the worker actually
        # checks ctx.stopping and stops early. A worker that wraps an OPAQUE library call
        # (apply_source_types / backfill_baseline_tags loop internally, take no ctx) cannot
        # be interrupted mid-pass — for those cancellable=False, so /api/jobs offers no
        # cancel button and a completed run is NEVER mislabelled 'cancelled'.
        self.cancellable = cancellable
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = "idle"  # idle | running | done | cancelled | error
        self._error: str | None = None
        self._result: Any = None
        self._done = 0
        self._total = 0
        self._detail = ""
        self._started_at: float | None = None
        self._ended_at: float | None = None

    def _alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, **kwargs: Any) -> dict:
        """Spawn the worker on a daemon thread and return the initial status immediately.

        Raises RuntimeError if a run is already in flight (the caller maps it to 409 or
        returns the current status — a single job of a kind runs at a time)."""
        with self._lock:
            if self._alive():
                raise RuntimeError(f"a {self.kind} job is already running")
            self._stop.clear()
            self._state = "running"
            self._error = None
            self._result = None
            self._done = 0
            self._total = 0
            self._detail = ""
            self._started_at = time.time()
            self._ended_at = None
            ctx = JobContext(self)
            t = threading.Thread(
                target=self._run, args=(ctx, kwargs), name=f"bgjob-{self.kind}", daemon=True
            )
            self._thread = t
            t.start()
        return self.status()

    def _run(self, ctx: JobContext, kwargs: dict) -> None:
        try:
            result = self._worker(ctx, **kwargs)
            with self._lock:
                self._result = result
                # Only a COOPERATIVELY-cancellable worker can end 'cancelled' (it broke on
                # ctx.stopping). An opaque worker always runs to completion -> 'done', so a
                # late cancel() never mislabels a finished-with-full-result run.
                self._state = "cancelled" if (self.cancellable and self._stop.is_set()) else "done"
        except Exception as exc:  # noqa: BLE001 - a worker crash must not take the app down
            with self._lock:
                self._error = f"{type(exc).__name__}: {exc}"[:300]
                self._state = "error"
            _LOG.warning("background job %s failed", self.kind, exc_info=True)
        finally:
            with self._lock:
                self._ended_at = time.time()

    def cancel(self) -> None:
        """Ask the worker to stop at its next safe point (cooperative; never kills a thread)."""
        self._stop.set()

    def status(self) -> dict:
        with self._lock:
            total = self._total
            done = self._done
            state = self._state
            prog = (
                {
                    "done": done,
                    "total": total,
                    "unit": "items",
                    "percent": round(100.0 * done / total, 1) if total else 0.0,
                }
                if total
                else None
            )
            return {
                "kind": self.kind,
                "label": self.label,
                "state": state,
                "running": state == "running",
                "cancellable": self.cancellable,
                "done": done,
                "total": total,
                "detail": self._detail or None,
                "progress": prog,
                "error": self._error,
                "result": self._result,
                "is_writer": self.is_writer,
                "started_at": self._started_at,
                "ended_at": self._ended_at,
            }


# ---- registry (so /api/jobs enumerates every background job, no shadow state) ---------- #

_REGISTRY: dict[str, BackgroundJob] = {}
_REG_LOCK = threading.Lock()


def register_job(job: BackgroundJob) -> BackgroundJob:
    """Register (or replace) a job kind and return it (call at module import)."""
    with _REG_LOCK:
        _REGISTRY[job.kind] = job
    return job


def get_job(kind: str) -> BackgroundJob | None:
    with _REG_LOCK:
        return _REGISTRY.get(kind)


def all_job_statuses() -> list[dict]:
    """Every registered background job's live status (for /api/jobs)."""
    with _REG_LOCK:
        jobs = list(_REGISTRY.values())
    return [j.status() for j in jobs]


def _reset_registry_for_tests() -> None:
    with _REG_LOCK:
        _REGISTRY.clear()
