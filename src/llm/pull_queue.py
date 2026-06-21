"""
Model-download QUEUE: pulls run ONE AT A TIME, the rest wait (brief §2.C1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pulling several models at once overlapped + started them all at once (field test
2026-06-20). This makes model pulls a QUEUED, task-manager-visible job: one active
pull, the rest queue, each cancellable. Ollama's ``/api/pull`` is NOT resumable, so
the action is CANCEL (abort) — never a fake "pause/resume" of a download we can't
resume (invariant #20: real bytes only, no fabricated progress).

TRANSPORT (maintainer Q9): a pull egresses through the Ollama PROCESS over CLEARNET,
not the app's Tor proxy — airplane (the kill switch) still refuses it (OllamaClient
checks it), and the UI discloses the clearnet egress at consent.
"""

from __future__ import annotations

import re
import threading
import time

_VALID_MODEL = re.compile(r"^[a-zA-Z0-9._:/-]{1,128}$")


class ModelPullManager:
    """One active pull at a time; the rest queue. A single pump thread drains the
    queue. Cancel removes a queued model or aborts the active pull. State is in-memory
    (a process-wide singleton), surfaced read-only in /api/jobs."""

    def __init__(self, client_factory=None) -> None:
        self._lock = threading.RLock()
        self._queue: list[str] = []
        self._active: str | None = None
        self._progress: dict = {}
        self._history: list[dict] = []  # recent finished pulls (done/error/cancelled)
        self._cancel: set[str] = set()
        self._thread: threading.Thread | None = None
        self._client_factory = client_factory  # test seam

    def _client(self):
        if self._client_factory is not None:
            return self._client_factory()
        from src.llm.ollama import OllamaClient

        return OllamaClient()

    def enqueue(self, model: str) -> dict:
        """Add a model to the pull queue (idempotent — a model already active/queued is
        not added twice). Starts the pump if idle. Raises ValueError on a bad name."""
        model = (model or "").strip()
        # `/` is legit (registry/ns/model), but `..` (traversal) is never a real tag.
        if not _VALID_MODEL.match(model) or ".." in model:
            raise ValueError("invalid model name")
        with self._lock:
            if model == self._active or model in self._queue:
                return self.status()
            self._cancel.discard(model)
            self._queue.append(model)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._pump, daemon=True, name="model-pull")
                self._thread.start()
            return self.status()

    def cancel(self, model: str) -> dict:
        """Cancel a queued model (removed) or the active pull (aborted — Ollama's pull
        is not resumable, so cancel is the only stop)."""
        with self._lock:
            if model in self._queue:
                self._queue.remove(model)
                self._history.append({"model": model, "status": "cancelled"})
            elif model == self._active:
                self._cancel.add(model)  # the pump notices + aborts the stream
            return self.status()

    def _pump(self) -> None:
        while True:
            with self._lock:
                nxt = None
                while self._queue:
                    cand = self._queue.pop(0)
                    if cand in self._cancel:
                        self._cancel.discard(cand)
                        continue
                    nxt = cand
                    break
                if nxt is None:
                    self._active = None
                    self._progress = {}
                    return
                self._active = nxt
                self._progress = {"model": nxt, "status": "starting", "percent": 0.0}
            status, err = "done", None
            try:
                for prog in self._client().pull(nxt):
                    with self._lock:
                        if nxt in self._cancel:
                            status = "cancelled"
                            break
                        self._progress = _progress_of(nxt, prog)
            except Exception as exc:  # noqa: BLE001 - surface, never crash the pump
                status, err = "error", str(exc)
            with self._lock:
                self._cancel.discard(nxt)
                self._active = None
                self._progress = {}
                entry = {"model": nxt, "status": status, "at": time.time()}
                if err:
                    entry["error"] = err
                self._history.append(entry)
                self._history = self._history[-20:]

    def status(self) -> dict:
        with self._lock:
            active = None
            if self._active is not None:
                active = {"model": self._active, **{k: v for k, v in self._progress.items() if k != "model"}}
            return {
                "active": active,
                "queue": list(self._queue),
                "history": list(self._history[-10:]),
            }


def _progress_of(model: str, prog: dict) -> dict:
    """Map an Ollama progress object to our honest shape (real bytes only)."""
    total = prog.get("total")
    completed = prog.get("completed")
    pct = 0.0
    if total:
        try:
            pct = round(100.0 * float(completed or 0) / float(total), 1)
        except (TypeError, ValueError, ZeroDivisionError):
            pct = 0.0
    return {
        "model": model,
        "status": prog.get("status") or "pulling",
        "total": total,
        "completed": completed,
        "percent": pct,
    }


_MANAGER: ModelPullManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_pull_manager() -> ModelPullManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = ModelPullManager()
        return _MANAGER
