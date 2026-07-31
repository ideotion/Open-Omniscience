"""Server-side import QUEUE: one exclusive window, per-item identity, immediate stop.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field remarks 2026-07-29, remark 2: importing a folder of six backups showed ONE
shared progress bar with no per-item identity, no true rate, no pause and no stop.
The cause was structural -- the sequencing lived in the BROWSER (``_uxImRun`` looped
over the discovered items, POSTing each in turn), so:

  * every item wrote into the same bar behind a constant "Corpus" prefix;
  * a page reload killed the sequencing (the item already on the server finished,
    the rest never started, and nothing anywhere recorded that);
  * Stop could not exist, because there was no server-side owner of "the run";
  * collection was paused and RESUMED around EACH item, re-opening between every
    backup the exact race the pause exists to close (ruling item 10: a multi-backup
    run is ONE import).

This module is that owner. It is deliberately a SEQUENCER, not a second engine: each
item still runs in the manager that already owns that kind of work (volume restore,
folder/large-data restore, newsletter import) or, for legacy archives, the same
staging+merge helpers the endpoint uses. So every proven code path, progress dict and
cancel wiring is reused verbatim; what is new is the run that spans them.

WHAT IS PERSISTED (``data_dir()/import_queue.json``): the item list, each item's
state, the cursor, and the timings. The PASSPHRASE is held in memory only and never
written -- a queue file is an ordinary file on the same disk as the encrypted corpus,
and writing the key beside the lock would defeat the at-rest encryption entirely.
That is why a run cannot survive a SERVER restart: on the next boot the file is read
back and reported honestly as interrupted, with its per-item outcomes intact, rather
than silently resumed with a passphrase we would have had to store to have.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from src.paths import data_dir

_LOG = logging.getLogger(__name__)

_STATE_FILE = "import_queue.json"

# The kinds an import run can contain, in the order the scan surfaces them. The
# order matters: the corpus merge must land before the newsletter import, so the
# .eml articles are screened against the corpus the backups just contributed.
KINDS = ("corpus", "legacy", "blobs", "newsletters")


def _state_path() -> Path:
    return data_dir() / _STATE_FILE


class ImportQueueManager:
    """ONE import run at a time. Items are executed in order; the run owns a single
    exclusive collection window spanning all of them (ruling item 10)."""

    def __init__(self, state_path: Path | None = None) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state_path = state_path
        self._state = "idle"  # idle|running|done|error|stopped|interrupted
        self._items: list[dict[str, Any]] = []
        self._cursor = -1  # index of the item currently running
        self._started_at: float | None = None
        self._ended_at: float | None = None
        self._passphrase: str = ""  # memory only, never persisted
        self._collection_paused = False
        # What the post-run tuning pass actually did ({"fts", "planner"} bools), or None
        # while a run is still going -- reported, never assumed to have succeeded.
        self._tuned: dict[str, bool] | None = None
        # Live progress of the sub-job currently in flight (mirrored, never authored).
        self._live: dict[str, Any] | None = None
        self._load_persisted()

    # -- persistence -------------------------------------------------------- #
    def _path(self) -> Path:
        return self._state_path or _state_path()

    def _save(self) -> None:
        """Best-effort. A queue file that cannot be written must never break the
        import it is only describing (the standing crash-journal lesson: a sidecar
        added for resilience must not become a second point of failure)."""
        try:
            payload = {
                "state": self._state,
                "items": self._items,
                "cursor": self._cursor,
                "started_at": self._started_at,
                "ended_at": self._ended_at,
            }
            p = self._path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, p)
        except Exception:  # noqa: BLE001 - never break an import over its own log
            _LOG.warning("could not persist the import queue state", exc_info=True)

    def _load_persisted(self) -> None:
        try:
            raw = json.loads(self._path().read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - absent/corrupt is simply "no previous run"
            return
        if not isinstance(raw, dict):
            return
        items = raw.get("items")
        if not isinstance(items, list):
            return
        self._items = items
        self._cursor = int(raw.get("cursor", -1) or -1)
        self._started_at = raw.get("started_at")
        self._ended_at = raw.get("ended_at")
        state = str(raw.get("state") or "idle")
        if state == "running":
            # The process died mid-run (or was restarted). Say so: the passphrase
            # was never stored, so this cannot be resumed -- reporting it as still
            # "running" would be a bar that never moves again.
            self._state = "interrupted"
            for it in self._items:
                if it.get("state") == "running":
                    it["state"] = "interrupted"
        else:
            self._state = state

    # -- lifecycle ---------------------------------------------------------- #
    def start(self, items: list[dict], *, passphrase: str = "") -> dict:
        """Queue ``items`` and begin. Each item is ``{kind, path, label?}`` plus any
        kind-specific keys (``categories`` for blobs). Raises RuntimeError if a run
        is already in flight, ValueError if the list is empty or malformed."""
        with self._lock:
            if self._state == "running" and self._thread is not None and self._thread.is_alive():
                raise RuntimeError("An import is already running.")
            if self._thread is not None:
                self._thread.join(timeout=5)
                self._thread = None
            queued: list[dict[str, Any]] = []
            for i, raw in enumerate(items or []):
                kind = str(raw.get("kind") or "")
                if kind not in KINDS:
                    raise ValueError(f"unknown import kind {kind!r}")
                path = str(raw.get("path") or "")
                if not path:
                    raise ValueError(f"item {i} has no path")
                queued.append({
                    "id": f"{i}-{kind}",
                    "kind": kind,
                    "path": path,
                    "label": str(raw.get("label") or Path(path).name or kind),
                    "categories": list(raw.get("categories") or []),
                    "state": "queued",
                    "started_at": None,
                    "ended_at": None,
                    "error": None,
                    "summary": None,
                })
            if not queued:
                raise ValueError("nothing to import")
            self._stop.clear()
            self._items = queued
            self._cursor = -1
            self._passphrase = passphrase or ""
            self._started_at = time.time()
            self._ended_at = None
            self._state = "running"
            self._save()
            self._thread = threading.Thread(target=self._run, daemon=True, name="import-queue")
            self._thread.start()
            return self.status()

    def stop(self) -> None:
        """Stop the run IMMEDIATELY (ruling item 15). The item in flight is cancelled
        through its own manager -- which, for a restore, aborts free and complete
        before the atomic swap and stops the resumable re-index after it -- and every
        item still queued is marked cancelled rather than silently skipped."""
        self._stop.set()
        for cancel in (self._cancel_volume, self._cancel_folder, self._cancel_newsletters):
            try:
                cancel()
            except Exception:  # noqa: BLE001 - one manager's refusal must not block the others
                _LOG.warning("cancelling a sub-job during import stop failed", exc_info=True)

    # -- sub-manager seams (overridable in tests) ---------------------------- #
    def _cancel_volume(self) -> None:
        from src.backup.volume_job import get_volume_manager

        get_volume_manager().cancel()

    def _cancel_folder(self) -> None:
        from src.backup.folder_backup import get_folder_manager

        get_folder_manager().cancel()

    def _cancel_newsletters(self) -> None:
        from src.ingest.import_job import get_import_manager

        get_import_manager().cancel()

    # -- the run ------------------------------------------------------------ #
    def _run(self) -> None:
        # ONE exclusive window for the WHOLE queue (ruling item 10): collection goes
        # down once here and comes back up once at the end, instead of flapping
        # between every backup. The per-item restore's own pause nests inside this
        # and becomes a no-op -- including, crucially, its resume.
        from src.scheduler.runner import exclusive_window

        # ``drove`` is set BEFORE the call, not after: the fallback below exists for
        # the case where the WINDOW could not be established, and must never re-run an
        # import that already started. (A first cut called _drive() from the except
        # block, which would have run the whole import TWICE if _drive itself raised.)
        drove = False
        try:
            with exclusive_window():
                with self._lock:
                    self._collection_paused = True
                drove = True
                self._drive()
        except Exception:  # noqa: BLE001 - the pause is a courtesy, never load-bearing
            _LOG.warning("the exclusive window for the import failed", exc_info=True)
        finally:
            with self._lock:
                self._collection_paused = False
        if not drove:
            # The pause is a throughput courtesy; the import is the point. A scheduler
            # that refused to stop must not cost the user their import.
            self._drive()

    def _drive(self) -> None:
        """Walk the queue. Separated from :meth:`_run` so the exclusive window is a
        plain ``with`` block -- the courtesy pause must never be able to skip the
        import it was only meant to make faster."""
        for idx, item in enumerate(self._items):
            if self._stop.is_set():
                break
            with self._lock:
                self._cursor = idx
                item["state"] = "running"
                item["started_at"] = time.time()
                self._save()
            try:
                summary = self._run_item(item)
                state = "stopped" if self._stop.is_set() else "done"
                with self._lock:
                    item["state"] = state
                    item["summary"] = summary
            except Exception as exc:  # noqa: BLE001 - one bad item must not lose the rest
                _LOG.exception("import item %s failed", item.get("id"))
                with self._lock:
                    item["state"] = "error"
                    item["error"] = str(exc)
            finally:
                with self._lock:
                    item["ended_at"] = time.time()
                    self._save()
        self._tune_after_run()
        with self._lock:
            stopped = self._stop.is_set()
            for it in self._items:
                if it["state"] == "queued":
                    # Explicitly cancelled, never left looking "still to come" --
                    # a queued item after a stop would read as work still pending.
                    it["state"] = "cancelled" if stopped else "skipped"
            any_error = any(it["state"] == "error" for it in self._items)
            self._state = "stopped" if stopped else ("error" if any_error else "done")
            self._cursor = -1
            self._ended_at = time.time()
            self._passphrase = ""  # drop the key the moment the run ends
            self._save()

    def _tune_after_run(self) -> None:
        """ONE post-bulk tuning pass for the whole run (import-speed fix 2026-07-30).

        ``verify_copy`` used to run a full FTS5 ``'rebuild'`` on every item, which
        incidentally left the search index as one merged segment. That rebuild is gone
        (it re-read every article's text through the codec to redo work the sync
        triggers had already done), so the segment churn a bulk import causes now needs
        the operation that actually addresses it: ``optimize_after_bulk`` -- an FTS5
        ``'optimize'`` (merge the segments, no article content re-read) plus a
        ``PRAGMA optimize`` refresh of the planner statistics after the big
        ``keyword_mentions`` churn, which the restore path never did at all.

        HERE rather than inside the restore, and once rather than per item: this is the
        one place that knows a run has ENDED, and running it per item would put back a
        per-item index-scaled cost in the middle of the very queue this fix is for.

        SKIPPED after a Stop: ruling item 15 makes Stop IMMEDIATE, and an FTS segment
        merge over a large index is minutes of work the user just asked to end. The
        committed items keep their (unmerged, entirely correct) index entries; the next
        run's pass -- or the standalone re-index job's -- merges them.

        Best-effort and never fatal, exactly like the tuning pass's other two callers:
        a failed optimisation must not turn a completed set of committed, additive
        imports into a failed run."""
        if self._stop.is_set():
            return
        # SAID, not silent. An FTS5 segment merge over a large index is minutes of
        # single-threaded work, and it happens after the LAST item finishes -- so
        # without this the run would sit at "running" with no item in flight and the
        # last item's numbers frozen on screen, which reads as a hang (the exact class
        # of defect the post-merge re-index used to be before it got its own phase).
        # No percentage and no ETA: SQLite reports neither for 'optimize', and inventing
        # one would be the fabricated-progress this project refuses.
        with self._lock:
            self._cursor = -1
            self._live = {
                "phase": "tuning",
                "own_the_machine": True,
                "detail": "merging the search index after the import",
            }
        try:
            from src.database.fts import optimize_after_bulk
            from src.database.session import session_scope

            with session_scope() as session:
                self._tuned = optimize_after_bulk(session)
        except Exception:  # noqa: BLE001 - tuning is never load-bearing
            _LOG.warning("post-import tuning pass failed", exc_info=True)
        finally:
            with self._lock:
                self._live = None

    def _run_item(self, item: dict) -> dict:
        kind = item["kind"]
        if kind == "corpus":
            return self._run_corpus(item)
        if kind == "legacy":
            return self._run_legacy(item)
        if kind == "blobs":
            return self._run_blobs(item)
        if kind == "newsletters":
            return self._run_newsletters(item)
        raise ValueError(f"unknown import kind {kind!r}")

    def _await(self, status_fn, cancel_fn, *, poll: float = 0.4) -> dict:
        """Drive one sub-manager to a terminal state, mirroring its live progress.

        The queue's own Stop reaches the sub-job through ``cancel_fn`` (once), then
        keeps waiting for it to actually finish: abandoning the wait would leave a
        thread still writing while the next item started."""
        cancelled = False
        while True:
            st = status_fn() or {}
            state = str(st.get("state") or "")
            with self._lock:
                self._live = st
            if state in ("done", "error", "cancelled", "stopped", "paused", "idle"):
                if state == "error":
                    raise RuntimeError(str(st.get("error") or "the job failed"))
                return st
            if self._stop.is_set() and not cancelled:
                cancelled = True
                try:
                    cancel_fn()
                except Exception:  # noqa: BLE001
                    _LOG.warning("cancelling a sub-job failed", exc_info=True)
            time.sleep(poll)

    def _run_corpus(self, item: dict) -> dict:
        from src.backup.volume_job import get_volume_manager

        mgr = get_volume_manager()
        mgr.start_restore(item["path"], self._passphrase, force=bool(item.get("force")))
        st = self._await(mgr.status, mgr.cancel)
        summary = st.get("summary") or {}
        rep = summary.get("report") or {}
        out = {"report": rep, "state": st.get("state")}
        # An artifact already merged completes in milliseconds with no report. Say so
        # explicitly: a fast, empty success is otherwise indistinguishable from a
        # failure that produced nothing, and the queue's own log is where the
        # operator looks to find out which of the two happened.
        if summary.get("skipped") == "already-merged":
            out["skipped"] = "already-merged"
            out["merged_as_batch"] = summary.get("merged_as_batch")
            out["merged_at"] = summary.get("merged_at")
        return out

    def _run_legacy(self, item: dict) -> dict:
        # The endpoint's own extracted helper -- ONE legacy-restore code path, so the
        # queue can never drift from the single-archive route.
        from src.api.backup_v2 import restore_legacy_path

        return restore_legacy_path(
            item["path"], self._passphrase, should_stop=self._stop.is_set
        )

    def _run_blobs(self, item: dict) -> dict:
        from src.backup.folder_backup import get_folder_manager

        mgr = get_folder_manager()
        mgr.start(item["path"], item.get("categories") or [], mode="restore")
        st = self._await(mgr.status, mgr.cancel)
        p = st.get("progress") or {}
        return {"restored": p.get("restored", 0), "skipped": p.get("skipped", 0)}

    def _run_newsletters(self, item: dict) -> dict:
        from src.ingest.import_job import get_import_manager

        mgr = get_import_manager()
        mgr.start(item["path"])
        st = self._await(mgr.status, mgr.cancel)
        return {"tally": st.get("tally") or {}}

    # -- reporting ---------------------------------------------------------- #
    def status(self) -> dict:
        """The whole run: every item with its own identity and outcome, plus the
        live sub-job progress for the one in flight.

        The per-item ELAPSED times are real measurements. No ETA for the run as a
        whole is emitted: the items are different kinds of work over different
        units, so extrapolating one from the other would be a fabricated number --
        the caller shows the current item's own phase progress instead."""
        with self._lock:
            items = [dict(it) for it in self._items]
            cursor = self._cursor
            live = self._live
            state = self._state
            started, ended = self._started_at, self._ended_at
            paused = self._collection_paused
            tuned = self._tuned
        now = time.time()
        for it in items:
            s, e = it.get("started_at"), it.get("ended_at")
            it["elapsed_s"] = round((e or now) - s, 1) if s else None
        done = sum(1 for it in items if it["state"] in ("done", "skipped"))
        return {
            "state": state,
            "items": items,
            "cursor": cursor,
            "current": items[cursor] if 0 <= cursor < len(items) else None,
            "live": dict(live) if isinstance(live, dict) else None,
            "items_done": done,
            "items_total": len(items),
            "started_at": started,
            "ended_at": ended,
            "elapsed_s": round((ended or now) - started, 1) if started else None,
            "collection_paused": paused,
            # What the one post-run tuning pass actually managed (FTS segment merge +
            # planner statistics). None while the run is still going; a False half is
            # reported as such rather than quietly presented as done.
            "tuned": dict(tuned) if isinstance(tuned, dict) else None,
            # Stated so the UI can say it rather than the user having to infer it
            # (ruling item 12).
            "collection_note": (
                "Background collection is paused for this whole import and resumes "
                "when it finishes."
            ),
        }

    def clear(self) -> dict:
        """Forget a FINISHED run (so the dialog can start clean). Refuses while one
        is in flight -- clearing a live run would orphan its worker."""
        with self._lock:
            if self._state == "running":
                raise RuntimeError("An import is still running.")
            self._items = []
            self._cursor = -1
            self._state = "idle"
            self._started_at = self._ended_at = None
            self._save()
            return self.status()


_MANAGER: ImportQueueManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_import_queue() -> ImportQueueManager:
    """Process-wide singleton so the run is visible across requests + /api/jobs."""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = ImportQueueManager()
        return _MANAGER
