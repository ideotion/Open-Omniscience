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

import contextlib
import logging
import threading
import time
from typing import Any, Callable

from src.monitoring.secret_scrub import exception_text, log_failure

_LOG = logging.getLogger("jobs.background")


class Framed(str):
    """An English progress line that also carries its keyed FRAME and values.

    Everywhere a plain ``str`` goes it IS one -- the English sentence, unchanged -- so a
    caller, a log line or a test double that reads ``detail`` sees exactly what it saw
    before. ``set_progress`` also publishes the frame (``detail_i18n`` / ``detail_vars``
    in the status), which the task managers write in the UI language by the ``label_i18n``
    conventions of src/api/jobs.py: a number is formatted there, a value that is itself
    ``{"i18n": key, "vars": {...}}`` is written in the UI language too, and any other
    value is data (click-through B19, Q5/Q12). It rides INSIDE the string on purpose:
    ``set_progress``'s signature is pinned by the test doubles of a dozen workers, and a
    new keyword there would make each of them a context that cannot exist.
    """

    i18n: str
    vars: dict

    def __new__(cls, text: str, frame: str, **values: Any) -> Framed:
        s = super().__new__(cls, text)
        s.i18n = frame
        s.vars = values
        return s


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
                # A new line replaces its frame too: a frame left from the previous line
                # would write the OLD sentence in every language but English.
                self._job._detail_frame = (
                    {"i18n": detail.i18n, "vars": dict(detail.vars)}
                    if isinstance(detail, Framed) else None
                )

    def set_metrics(self, metrics: dict | None) -> None:
        """Publish the worker's own MEASUREMENTS into the live status (2026-09-21, F3).

        ``done``/``total``/``detail`` answer *how far*; this answers *what it is
        spending the time on* -- the phase split a long writer job already computes
        internally and, until now, could only report in its final ``result``. A drain
        that runs for days is exactly the job whose measurements are worthless at the
        end and decisive while it runs.

        REPORT-ONLY, and never load-bearing: a replaced dict (not merged), copied on
        the way in so a worker that keeps mutating its own accumulator cannot publish a
        half-updated read, and ``None`` clears it. Nothing here may change the worker's
        control flow.
        """
        with self._job._lock:
            self._job._metrics = dict(metrics) if metrics else None


def _job_secrets(kwargs: dict[str, Any]) -> tuple[str, ...]:
    """The strings a job was started with that are secrets, found by the NAME they are passed under: the convention of
    ``src/safety/scrub.py`` (a key that holds ``passphrase``, ``password``, ``secret``, ``token``, ``api_key`` and the rest of
    ``SECRET_KEY_FRAGMENTS``), which is how a route hands one over (``passphrase=body.passphrase``, ``**body.model_dump()``,
    a mailbox's ``password``). The held passphrases are not among them: ``scrubbed`` and ``log_failure`` take those out
    themselves. Only the top level is read, and only a string is a secret here.

    Imported when a job fails: ``src.safety`` pulls the whole backup stack in, and a module every job imports stays light."""
    from src.safety.scrub import SECRET_KEY_FRAGMENTS

    return tuple(
        dict.fromkeys(
            value
            for key, value in kwargs.items()
            if isinstance(key, str) and isinstance(value, str) and value and any(f in key.lower() for f in SECRET_KEY_FRAGMENTS)
        )
    )


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
        self._detail_frame: dict | None = None
        self._metrics: dict | None = None
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
            self._detail_frame = None
            self._metrics = None
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
        failure: Exception | None = None
        secrets: tuple[str, ...] | None = ()
        try:
            result = self._worker(ctx, **kwargs)
            with self._lock:
                self._result = result
                # Only a COOPERATIVELY-cancellable worker can end 'cancelled' (it broke on
                # ctx.stopping). An opaque worker always runs to completion -> 'done', so a
                # late cancel() never mislabels a finished-with-full-result run.
                self._state = "cancelled" if (self.cancellable and self._stop.is_set()) else "done"
        except Exception as exc:  # noqa: BLE001 - a worker crash must not take the app down
            failure = exc
            # The error is shown in the task manager and /api/jobs, and an engine's error can quote the statement that held
            # the key: the text is scrubbed of every passphrase the process holds (``scrubbed`` takes those out itself) AND of
            # the secrets the job was started with (``_job_secrets``: a backup's passphrase, a mailbox's password), BEFORE the
            # cut, and withheld when it cannot be.
            name = type(exc).__name__
            try:
                secrets = _job_secrets(kwargs)
                # ``exception_text``: scrubbed, then cut, and the class and a fixed note when a ``UnicodeError`` is in the chain
                # or group (its text names a character and its offset, a piece of a key that no scrub knows).
                error = exception_text(exc, *secrets, limit=300)
            except Exception:  # noqa: BLE001 - the text could not be made or scrubbed: the class says what failed
                secrets = None
                error = f"{name}: its text is withheld"
            with self._lock:
                self._error = error
                self._state = "error"
        finally:
            with self._lock:
                self._ended_at = time.time()
        if failure is not None:
            # Written AFTER the handler, so that a record that cannot be written raises with no exception to chain: the thread's
            # excepthook prints what is raised and the exception it was raised while handling, as it made its message.
            self._log_failure(failure, secrets)

    def _log_failure(self, failure: Exception, secrets: tuple[str, ...] | None) -> None:
        """The failure as a WARNING with the secrets out of it, or, when they could not be read or the record could not be written,
        the exception's class and none of its words. Never raises: the job has already ended as an error."""
        try:
            if secrets is not None:
                log_failure(_LOG, f"background job {self.kind} failed", failure, *secrets, level=logging.WARNING)
                return
        except Exception:  # noqa: BLE001 - what is written instead is the class
            pass
        with contextlib.suppress(Exception):
            _LOG.warning(
                "background job %s failed (%s): its text is withheld, the scrub could not run",
                self.kind,
                type(failure).__name__,
            )

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
                # ADDITIVE (click-through B19): the detail's keyed frame when the worker
                # published a Framed line, else None -- `detail` above is unchanged.
                "detail_i18n": self._detail_frame["i18n"] if (self._detail and self._detail_frame) else None,
                "detail_vars": dict(self._detail_frame["vars"]) if (self._detail and self._detail_frame) else None,
                # ADDITIVE (2026-09-21): the worker's own live measurements, or None.
                # Every key above and below is unchanged, so an existing reader of this
                # payload sees exactly what it saw before.
                "metrics": dict(self._metrics) if self._metrics else None,
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
