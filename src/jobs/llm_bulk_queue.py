"""The bulk summarize / translate QUEUE, on the server (R600's second PR, OPEN_QUEUE item 40).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY. #1830 made one bulk run outlive its tab (src/api/detached_stream.py), but the QUEUE of runs stayed in the page: the runs
waiting behind it lived in a JavaScript array and were started by the tab when the one before ended. Closing the browser on an
instance left running (the terminal panel exists for exactly that, R600 / R658) kept the run in flight and lost every run behind
it, and a stream that broke mid-run let the page start the next run while the old one still ran on the server.

WHAT THIS IS. The queue lives here, one run at a time, on a registered :class:`~src.jobs.background.BackgroundJob`
(``llm-bulk-queue``) that drains it and ends when it is empty. Each run is the SAME generator the streamed endpoint uses
(:func:`src.api.llm.prepare_bulk_run`), so a queued run stores exactly what a streamed one stores, one commit per article, and
shows in the task manager as the same ``llm`` row with its own Stop. The page only adds, cancels and reads.

WHAT KEEPS IT HONEST.
  * Persisted in the encrypted store (``app_state`` through :mod:`src.config.kv_store`), never a side file: a queued run's
    selection is a search the operator typed, and it does not belong in cleartext beside a SQLCipher corpus. The store is read
    lazily and only once it can be read (a locked app reads nothing and writes nothing), so a queue is never overwritten by an
    empty one read from a store that was not open yet.
  * After a restart nothing starts by itself: a run that was going is restored PAUSED with whatever waited behind it, and the
    task manager's Resume (or the page's) carries on. The articles a run is about are frozen when it first starts (a search
    that matches more later does not grow it), and a resumed run skips every article that already got this run's result
    (``resume_since``), including the one committed just before the stop could be recorded, so nothing is stored twice.
  * Stops: the task manager's Stop on the running row (or the page's Cancel) ends THAT run after the articles in flight and the
    queue goes on; stopping the job itself (the shutdown's stop of registered jobs, R670) leaves the run paused, never lost. A
    process that dies without that stop relies on the last save instead: a run stored as running comes back paused, and one
    whose Cancel was stored comes back cancelled. A queued run's Cancel removes it before it starts.
  * A swapped corpus file (a panic wipe, a restore, a merge) takes the queue with it: what was read from the old file, typed
    searches included, is forgotten, the run in flight stops, and nothing of it is written into the file that is live.
  * It stands aside, holding no transaction, while a restore owns the machine (the scheduler's exclusive hold) or the storage
    guard is engaged, and says so on the run's row.
  * Counts only: done / total / stored / skipped / failed are what the run reported, never an estimate. No network: the model is
    the local backend (loopback Ollama or vLLM), which airplane mode lets through by construction.
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any

from src.jobs.background import BackgroundJob, Framed, JobContext, register_job, stop_all_count
from src.monitoring.secret_scrub import log_failure

_LOG = logging.getLogger("jobs.llm_bulk_queue")

KIND = "llm-bulk-queue"
#: The queue's row in the encrypted ``app_state`` store.
KV_KEY = "jobs.llm_bulk_queue"
#: One frozen article list per started run, kept apart so a progress save never rewrites thousands of ids.
IDS_KEY_PREFIX = "jobs.llm_bulk_queue.ids."
#: Runs that may wait at once: a bound on the stored queue, far above what anyone queues by hand.
MAX_PENDING = 50
#: Finished runs kept for the page to show after it is reopened (the newest).
KEEP_FINISHED = 20
#: How often a running run's counts are written back (a state change is written at once).
SAVE_EVERY_S = 10.0
#: How often a run standing aside re-reads the hold that parked it.
STAND_ASIDE_POLL_S = 5.0

#: The run's row while a restore holds the machine (a locale key, x12).
_FRAME_RESTORE_WAIT = "Waiting: a restore is using the machine; the run carries on after it"

_OPS = ("summarize", "translate")
_SELECTION = ("article_ids", "query", "source", "language", "start_date", "end_date")
_BODY_KEYS = _SELECTION + ("op", "target_language", "output_language", "ui_lang", "model", "skip_existing")
_PENDING = ("queued", "running", "paused")
#: What a run that ended forgets: the selection, and the languages typed for it (free text too).
_FORGOTTEN = _SELECTION + ("target_language", "output_language")


def _forget_selection(entry: dict) -> None:
    """A run that ended (done, failed or cancelled) keeps no trace of WHAT it was run on (R669 (b)): the typed search, the
    filters and the article ids leave the stored entry, and only the operation and its counts stay for the page's list."""
    body = entry.get("body")
    if isinstance(body, dict):
        entry["body"] = {k: v for k, v in body.items() if k not in _FORGOTTEN}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _clean_body(body: dict) -> dict:
    """The request fields a run needs, and nothing else (``limit`` is not offered: a queued run is the whole selection)."""
    out = {k: body[k] for k in _BODY_KEYS if k in body and body[k] not in (None, "", [])}
    if "article_ids" in out:
        ids: list[int] = []
        seen: set[int] = set()
        for v in out["article_ids"]:
            if isinstance(v, int) and not isinstance(v, bool) and v > 0 and v not in seen:
                seen.add(v)
                ids.append(v)
        if ids:
            out["article_ids"] = ids
        else:
            out.pop("article_ids")
    out["skip_existing"] = bool(body.get("skip_existing", True))
    return out


_SEARCH_REFUSED = "The search could not be read; check its wording and queue it again."
_NOTHING_MATCHED = "No matching articles with content."


def _start_refusal(status: int, detail: str) -> str:
    """What a run that could not start keeps as its error: never the selection's own words."""
    if status >= 500:
        return detail
    return _NOTHING_MATCHED if detail == _NOTHING_MATCHED else _SEARCH_REFUSED


def _store_epoch() -> int:
    """The kv store's swap epoch: ``kv_invalidate()`` moves it on every file swap (panic wipe, restore, merge, migration), and a
    single setting's invalidation does not."""
    from src.config.kv_store import kv_swap_epoch

    return kv_swap_epoch()


class QueueUnavailable(RuntimeError):
    """The encrypted store cannot be read yet (a locked app): nothing is queued, so nothing can be lost."""


class LlmBulkQueue:
    """ONE server-side queue of bulk summarize/translate runs, drained by the ``llm-bulk-queue`` job."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._loaded = False
        self._entries: list[dict] = []
        self._paused = False
        self._seq = 0
        self._last_save = 0.0
        # True from a kick until the drain finds no queued run (set and cleared under ``_lock``), so a run added while the drain is
        # ending is never left waiting: either the drain still sees it, or the kick starts a new drain once the old one is gone.
        self._draining = False
        # The store this queue was read from (the kv store's swap epoch: a panic wipe, a restore or a merge swaps the file and bumps
        # it), and a generation that moves each time the queue forgets a store, so a run started against the old file never writes
        # into the new one.
        self._epoch = -1
        self._gen = 0
        # Saves are numbered under ``_lock`` and written under ``_write_lock`` in order: an older snapshot never lands after a
        # newer one (a cancelled run's search must not come back from a periodic save that was taken just before the cancel).
        self._write_lock = threading.Lock()
        self._save_seq = 0
        self._written_seq = 0

    # -- the store this queue belongs to ------------------------------------ #
    def _forget_store(self) -> None:
        """The corpus file was swapped (a panic wipe, a restore, a merge): drop everything read from the old one, typed searches
        included, and stop the run in flight. Called under ``_lock``; the next read loads the queue of the file that is live."""
        from src.monitoring.tasks import request_cancel

        for entry in self._entries:
            if entry.get("state") == "running" and entry.get("task") is not None:
                with contextlib.suppress(Exception):
                    request_cancel(int(entry["task"]))
        self._entries = []
        self._paused = False
        self._seq = 0
        self._loaded = False
        self._gen += 1

    def _stale(self, gen: int | None = None) -> bool:
        """True when the store was swapped since this queue read it (and forget it), or since generation ``gen``."""
        with self._lock:
            if self._loaded and self._epoch != _store_epoch():
                self._forget_store()
            return gen is not None and gen != self._gen

    # -- persistence -------------------------------------------------------- #
    def _load(self) -> bool:
        """Read the stored queue once the store can be read. A run that was going when the app stopped comes back paused, and
        so does the queue behind it: nothing starts by itself after a restart."""
        with self._lock:
            self._stale()
            if self._loaded:
                return True
            epoch = _store_epoch()
            try:
                from src.config.kv_store import kv_get_json_checked

                data = kv_get_json_checked(KV_KEY) or {}
            except Exception as exc:  # noqa: BLE001 - a locked or unreadable store: try again on the next read
                _LOG.debug("bulk queue: the store is not readable yet (%s)", type(exc).__name__)
                return False
            entries = [entry for entry in (data.get("entries") or []) if isinstance(entry, dict) and entry.get("op") in _OPS]
            stale_ids: list[int] = []
            for entry in entries:
                if entry.get("state") not in _PENDING:
                    _forget_selection(entry)
                if entry.get("state") == "running" and entry.get("stopping"):
                    # Cancel was pressed and stored, and the process died before the run said it had stopped: it stays cancelled.
                    entry["state"] = "cancelled"
                    entry["ended_at"] = entry.get("ended_at") or _now_iso()
                    entry["stopping"] = False
                    entry.pop("task", None)
                    _forget_selection(entry)
                    stale_ids.append(int(entry.get("id") or 0))
                    continue
                if entry.get("state") in ("running", "paused"):
                    entry["state"] = "paused"
                    entry["stopping"] = False
                    entry.pop("task", None)
            self._entries = entries
            self._seq = max([int(data.get("seq") or 0)] + [int(entry.get("id") or 0) for entry in entries])
            self._paused = bool(data.get("paused")) or any(entry.get("state") in _PENDING for entry in entries)
            self._loaded = True
            self._epoch = epoch
        for entry_id in stale_ids:
            self._drop_ids(entry_id)
        if stale_ids:
            self._save()  # the stored row still holds the cancelled run's search
        return True

    def _save(self) -> None:
        """Write the queue back (best effort: a write the store refuses is logged, and the queue in memory goes on)."""
        if self._stale():
            return
        with self._lock:
            if not self._loaded:
                return
            finished = [entry for entry in self._entries if entry.get("state") not in _PENDING][-KEEP_FINISHED:]
            keep = [entry for entry in self._entries if entry.get("state") in _PENDING or entry in finished]
            self._entries = keep
            data = {"seq": self._seq, "paused": self._paused, "entries": [dict(entry) for entry in keep]}
            self._last_save = time.monotonic()
            self._save_seq += 1
            seq, epoch = self._save_seq, self._epoch
        with self._write_lock:
            if seq < self._written_seq or epoch != _store_epoch():
                return  # a newer snapshot is already stored, or the file it was read from is gone
            self._written_seq = seq
            try:
                from src.config.kv_store import kv_set_json

                kv_set_json(KV_KEY, data, expect_swap=epoch)
            except Exception as exc:  # noqa: BLE001 - the run goes on; the next save tries again
                _LOG.warning("bulk queue: the queue could not be stored (%s)", type(exc).__name__)

    def _save_ids(self, entry_id: int, ids: list[int]) -> None:
        try:
            from src.config.kv_store import kv_set_json

            kv_set_json(f"{IDS_KEY_PREFIX}{entry_id}", {"ids": list(ids)}, expect_swap=self._epoch)
        except Exception as exc:  # noqa: BLE001 - a resume then re-reads the selection instead
            _LOG.warning("bulk queue: a run's article list could not be stored (%s)", type(exc).__name__)

    @staticmethod
    def _read_ids(entry_id: int) -> list[int] | None:
        try:
            from src.config.kv_store import kv_get_json

            d = kv_get_json(f"{IDS_KEY_PREFIX}{entry_id}") or {}
        except Exception:  # noqa: BLE001
            return None
        ids = d.get("ids")
        return [int(i) for i in ids if isinstance(i, int)] if isinstance(ids, list) and ids else None

    def _drop_ids(self, entry_id: int) -> None:
        try:
            from src.config.kv_store import kv_delete

            kv_delete(f"{IDS_KEY_PREFIX}{entry_id}", expect_swap=self._epoch)  # never another file's run of the same number
        except Exception:  # noqa: BLE001 - an orphaned list is a few kilobytes, never a wrong result
            pass

    # -- the operator's actions -------------------------------------------- #
    def enqueue(self, body: dict) -> dict:
        """Add a run at the end of the queue and start the drain unless the queue is paused. Raises ``ValueError`` for a run
        that cannot be made and :class:`QueueUnavailable` while the store cannot be read."""
        clean = _clean_body(body)
        op = str(clean.get("op") or "").strip().lower()
        if op not in _OPS:
            raise ValueError("op must be 'summarize' or 'translate'.")
        clean["op"] = op
        if not any(k in clean for k in _SELECTION):
            raise ValueError("Provide article_ids or a query/filter.")
        if not self._load():
            raise QueueUnavailable("the queue is stored in the corpus, which is not open yet")
        with self._lock:
            pending = sum(1 for entry in self._entries if entry.get("state") in _PENDING)
            if pending >= MAX_PENDING:
                raise ValueError(f"The queue already holds {pending} runs; wait for some to finish.")
            self._seq += 1
            entry = {
                "id": self._seq, "op": op, "body": clean, "state": "queued", "created_at": _now_iso(),
                "since": None, "total": 0, "done": 0, "stored": 0, "skipped": 0, "failed": 0, "error": None,
                "stopping": False,
            }
            self._entries.append(entry)
            ahead = pending
        self._save()
        self.kick()
        return {"entry": dict(entry), "ahead": ahead, "paused": self._paused}

    def cancel(self, entry_id: int) -> bool:
        """A queued or paused run is dropped before it starts again; the running one stops after the articles in flight (its
        finished articles stay stored) and the queue goes on. False when there is no such run still pending."""
        if not self._load():
            return False
        tok = None
        with self._lock:
            entry = next((x for x in self._entries if x.get("id") == entry_id), None)
            if entry is None or entry.get("state") not in _PENDING:
                return False
            dropped = entry["state"] != "running"
            if not dropped:
                entry["stopping"] = True
                tok = entry.get("task")
            else:
                entry["state"] = "cancelled"
                entry["ended_at"] = _now_iso()
                _forget_selection(entry)
                if not any(x.get("state") in _PENDING for x in self._entries):
                    self._paused = False  # nothing is left waiting: a run added later starts, and no row says "paused"
        if dropped:
            self._drop_ids(entry_id)
        if tok is not None:
            from src.monitoring.tasks import request_cancel

            request_cancel(int(tok))
        self._save()
        return True

    def cancel_pending(self) -> int:
        """Drop every run that is not running (the paused queue's Cancel in the task manager). Returns how many."""
        if not self._load():
            return 0
        gone: list[int] = []
        with self._lock:
            for entry in self._entries:
                if entry.get("state") in ("queued", "paused"):
                    entry["state"] = "cancelled"
                    entry["ended_at"] = _now_iso()
                    _forget_selection(entry)
                    gone.append(int(entry["id"]))
            self._paused = False
        for entry_id in gone:
            self._drop_ids(entry_id)
        self._save()
        return len(gone)

    def resume(self) -> bool:
        """Carry on a queue a restart paused: the paused run first, then the ones that waited behind it. False when nothing
        was paused."""
        if not self._load():
            return False
        with self._lock:
            had = self._paused or any(entry.get("state") == "paused" for entry in self._entries)
            for entry in self._entries:
                if entry.get("state") == "paused":
                    entry["state"] = "queued"
            self._paused = False
        self._save()
        self.kick()
        return had

    def clear_finished(self) -> int:
        if not self._load():
            return 0
        with self._lock:
            before = len(self._entries)
            self._entries = [entry for entry in self._entries if entry.get("state") in _PENDING]
            n = before - len(self._entries)
        self._save()
        return n

    def kick(self) -> None:
        """Start the drain when there is work and the queue is not paused (a drain already running picks the new run up)."""
        with self._lock:
            if self._paused or self._draining or not any(entry.get("state") == "queued" for entry in self._entries):
                return
            self._draining = True
        try:
            _JOB.start()
            return
        except RuntimeError:
            pass
        # The previous drain found the queue empty and is returning. Wait for its thread OFF the request (Lane F row 13: three
        # joins of 5 s held an add or a Resume for up to 15 s), then start again.
        threading.Thread(target=self._start_after_previous, args=(stop_all_count(),), name="oo-llmbulk-kick", daemon=True).start()

    def _start_after_previous(self, stops_seen: int) -> None:
        for _ in range(3):
            _JOB.join(5)
            if stop_all_count() != stops_seen:
                # The app is shutting down: do not start a writer the shutdown's stop has not seen.
                with self._lock:
                    self._draining = False
                return
            try:
                _JOB.start()
            except RuntimeError:
                continue
            except Exception as exc:  # noqa: BLE001 - a failed start must not leave the queue marked draining for good
                log_failure(_LOG, "bulk queue: the drain could not be started", exc, level=logging.WARNING)
                break
            if stop_all_count() != stops_seen:
                # The shutdown began between the check and the start (stop_all_jobs counts before it looks at the jobs): stop
                # the drain it may not have seen. A start racing it closer still is refused at its first statement by
                # src/database/after_shutdown.py (R689 (2)).
                _JOB.cancel()
            return
        with self._lock:
            self._draining = False
        _LOG.warning("bulk queue: the drain could not be started; the next add or Resume tries again")

    def snapshot(self) -> dict:
        """What the page and the task manager read. ``readable`` False while the store cannot be read (a locked app)."""
        readable = self._load()
        with self._lock:
            return {
                "readable": readable,
                "paused": self._paused,
                "draining": _JOB.status().get("running", False),
                "entries": [dict(entry) for entry in self._entries],
            }

    # -- the drain ----------------------------------------------------------- #
    def _next(self) -> dict | None:
        with self._lock:
            if self._paused:
                self._draining = False
                return None
            entry = next((x for x in self._entries if x.get("state") == "queued"), None)
            if entry is None:
                self._draining = False
                return None
            entry["state"] = "running"
            entry["stopping"] = False
            entry["error"] = None
            entry["started_at"] = entry.get("started_at") or _now_iso()
            fresh = entry.get("since") is None
            if fresh:
                # Naive UTC, the shape ``ArticleAnalysis.created_at`` is compared in, taken BEFORE the first article is stored.
                entry["since"] = datetime.now(UTC).replace(tzinfo=None).isoformat()
            entry["resumed"] = not fresh
        self._save()
        return entry

    def _finish(self, entry: dict, state: str, reason: str | None = None, *, gen: int | None = None) -> None:
        if self._stale(gen):
            return  # the store this run belonged to is gone: nothing of it is written into the one that is live
        with self._lock:
            entry["state"] = state
            entry["stopping"] = False
            entry.pop("task", None)
            if reason:
                entry["error"] = reason[:300]
            if state != "paused":
                entry["ended_at"] = _now_iso()
                _forget_selection(entry)
        if state != "paused":
            self._drop_ids(int(entry["id"]))
        self._save()

    def _stand_aside(self, ctx: JobContext, entry: dict) -> bool:
        """Wait, between two articles, while a restore owns the machine or the storage guard is engaged. ``False`` when the job
        was stopped during the wait. Never raises: a hold that cannot be read is not a reason to stop the run."""
        from src.monitoring import tasks as _tasks

        tok = entry.get("task")
        before: dict = {}

        def _halt() -> bool:
            # ``stopping``: a Cancel pressed before the run's first start, when it has no task row to cancel yet.
            return ctx.stopping or bool(entry.get("stopping")) or (tok is not None and _tasks.cancel_requested(int(tok)))

        def _say(detail: str) -> None:
            # A Framed line keeps its keyed frame, so the task manager writes it in the UI language. The run's own line is kept
            # the first time, so it comes back once the wait is over.
            if tok is None:
                return
            if not before:
                row = next((t for t in _tasks.snapshot() if t.get("token") == int(tok)), None) or {}
                before.update(detail=row.get("detail") or "", detail_i18n=row.get("detail_i18n"), detail_vars=row.get("detail_vars"))
            _tasks.update(
                int(tok), detail=str(detail), detail_i18n=getattr(detail, "i18n", None), detail_vars=getattr(detail, "vars", None)
            )

        try:
            from src.scheduler.runner import get_scheduler

            sched = get_scheduler()
            said = False
            while not _halt() and sched.holds_exclusive():
                if not said:
                    _say(Framed(_FRAME_RESTORE_WAIT, _FRAME_RESTORE_WAIT))
                    said = True
                deadline = time.monotonic() + STAND_ASIDE_POLL_S
                while not _halt() and time.monotonic() < deadline:
                    time.sleep(0.25)
        except Exception:  # noqa: BLE001
            pass
        try:
            from src.scheduler.storage_guard import stand_aside_detail, storage_guard

            storage_guard.wait_if_engaged(should_stop=_halt, on_wait=lambda kind: _say(stand_aside_detail(kind)))
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("bulk queue: the storage guard could not be consulted (%s)", type(exc).__name__)
        if before and tok is not None:
            _tasks.update(int(tok), **before)
        return not ctx.stopping

    def _run(self, ctx: JobContext, entry: dict) -> None:
        """Run one queued entry to its end, a Stop, or the job's own stop (which leaves it paused)."""
        from fastapi import HTTPException

        from src.api.llm import BulkLLMRequest, get_llm_client_with_name, prepare_bulk_run
        from src.database.session import SessionLocal
        from src.monitoring import tasks as _tasks
        from src.monitoring.secret_scrub import http_detail

        gen0 = self._gen
        if not self._stand_aside(ctx, entry):
            self._finish(entry, "paused", gen=gen0)  # stopped while a restore held the machine: nothing was resolved yet
            return
        if entry.get("stopping"):
            self._finish(entry, "cancelled", gen=gen0)
            return
        body = dict(entry["body"])
        frozen = self._read_ids(int(entry["id"])) if entry.get("resumed") else None
        if frozen:
            for k in _SELECTION:
                body.pop(k, None)
            body["article_ids"] = frozen
        since = datetime.fromisoformat(entry["since"]) if entry.get("resumed") and entry.get("since") else None
        try:
            req = BulkLLMRequest(**body)
            with SessionLocal() as db:
                # R689 (1): the stop is looked at while a generation runs, so a shutdown's stop lands within its deadline.
                tok, gen, ids = prepare_bulk_run(
                    req, db, get_llm_client_with_name(), resume_since=since, should_stop=lambda: ctx.stopping,
                )
        except HTTPException as exc:
            # A refusal of the selection can quote it (an unreadable search's words, an unknown source's name): the finished run
            # keeps a fixed phrase instead, so nothing of what it was run on outlives it (R669(b)). The model's own refusals
            # (5xx: not installed, not running) say nothing of the selection and are kept, scrubbed.
            refusal = _start_refusal(exc.status_code, http_detail(exc, limit=200))
            self._finish(entry, "error", refusal, gen=gen0)
            return
        except Exception as exc:  # noqa: BLE001 - a run that cannot start ends as an error; a database error can quote the search
            self._finish(entry, "error", f"The run could not start ({type(exc).__name__}).", gen=gen0)
            return
        if self._stale(gen0):
            with contextlib.suppress(Exception):
                gen.close()
            return
        if not frozen:
            self._save_ids(int(entry["id"]), ids)
        with self._lock:
            entry["task"] = tok
            # A resumed run counts from zero: the articles it stored before the restart come back as "done before the restart"
            # (``resume_since`` makes that set exact) and are counted as stored, so the tally is the run's whole one.
            entry.update(total=len(ids), done=0, stored=0, skipped=0, failed=0)
            stop_now = bool(entry.get("stopping"))
        if stop_now:
            _tasks.request_cancel(tok)  # Cancel pressed while the run was being prepared
        ctx.set_progress(done=0, total=len(ids))
        outcome: tuple[str, str | None] | None = None
        try:
            for line in gen:
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                ev = o.get("event")
                with self._lock:
                    if ev == "item":
                        entry["done"] = int(o.get("i") or entry["done"])
                        status = o.get("status")
                        if status == "skipped" and o.get("reason") == "done before the restart":
                            entry["stored"] = int(entry.get("stored") or 0) + 1
                        elif status in ("stored", "skipped", "failed"):
                            entry[status] = int(entry.get(status) or 0) + 1
                    elif ev == "stopped":
                        # The generation in flight was abandoned and nothing of it stored: a task-manager Stop cancels the run,
                        # anything else (the job's stop: a shutdown, a model release) leaves it paused for the resume.
                        outcome = ("cancelled", None) if _tasks.cancel_requested(tok) else ("paused", None)
                    elif ev == "done":
                        if o.get("aborted"):
                            # The only abort is the model backend being unreachable (stopped, model gone, airplane mode):
                            # the run waits PAUSED with its frozen list, never an error that forgets it (R669). The queue
                            # pauses behind it, so a Resume before the backend is back pauses it again and loses nothing.
                            outcome = ("paused", str(o.get("reason") or "the model backend is not reachable"))
                        else:
                            outcome = ("done", None)
                    done_now = entry["done"]
                ctx.set_progress(done=done_now)
                if ev in ("done", "stopped"):
                    break
                if ctx.stopping:
                    outcome = ("paused", None)
                    break
                if self._stale(gen0):
                    outcome = ("cancelled", None)
                    break
                if _tasks.cancel_requested(tok):
                    outcome = ("cancelled", None)
                    break
                if not self._stand_aside(ctx, entry):
                    outcome = ("paused", None)
                    break
                if self._stale(gen0):  # the restore it waited for swapped the file: not one more article from the old list
                    outcome = ("cancelled", None)
                    break
                if _tasks.cancel_requested(tok):
                    outcome = ("cancelled", None)
                    break
                if time.monotonic() - self._last_save >= SAVE_EVERY_S:
                    self._save()
            if outcome is None:
                # The stream ended with no done line of its own (read before the close below forgets the Stop).
                outcome = ("cancelled", None) if _tasks.cancel_requested(tok) else ("done", None)
        except Exception as exc:  # noqa: BLE001 - a run that failed mid-way: what it stored stays stored
            outcome = ("error", f"The run stopped on an error ({type(exc).__name__}).")
        finally:
            with contextlib.suppress(Exception):
                gen.close()  # the runner's own finally: the task row's finish and the model hold's release
        if outcome and outcome[0] == "paused" and not self._stale(gen0):
            with self._lock:
                self._paused = True  # _next stops the drain here; the runs behind wait for the same Resume
        self._finish(entry, outcome[0] if outcome else "error", outcome[1] if outcome else "the run ended unexpectedly", gen=gen0)


def _drain(ctx: JobContext) -> dict:
    """The ``llm-bulk-queue`` job: run queued entries one after another until none is left, the queue is paused, or the job is
    stopped (the app shutting down), which leaves the run in flight paused."""
    q = get_queue()
    ran = 0
    try:
        while not ctx.stopping:
            entry = q._next()
            if entry is None:
                break
            gen = q._gen
            try:
                q._run(ctx, entry)
            except Exception as exc:  # noqa: BLE001 - that run ends in error and the runs behind it go on
                _LOG.warning("bulk queue: a run failed (%s)", type(exc).__name__)
                q._finish(entry, "error", f"The run stopped on an error ({type(exc).__name__}).", gen=gen)
            ran += 1
    except BaseException:
        with q._lock:
            q._draining = False
        raise
    if ctx.stopping:
        # A stop that landed between two runs: what is still queued waits for a Resume, as after a restart.
        with q._lock:
            q._draining = False
            if any(x.get("state") in _PENDING for x in q._entries):
                q._paused = True
        q._save()
    return {"runs": ran}


# A writer: every run commits one ArticleAnalysis per article (tests/test_job_writer_flags.py).
_JOB = register_job(BackgroundJob(KIND, "Summary & translation queue", _drain, is_writer=True, cancellable=True))
_QUEUE = LlmBulkQueue()


def get_queue() -> LlmBulkQueue:
    return _QUEUE


def pause_for_backend() -> bool:
    """Before the model backend is released or stopped: the run in flight pauses at once (the article in flight is dropped and redone on resume), and the queue
    behind it waits paused for a Resume (R669: paused, never lost, nothing stored twice). True when a run was going."""
    if not _JOB.status().get("running"):
        return False
    _JOB.cancel()  # the job's own stop: ``_run`` ends the run "paused" and the queue pauses behind it
    return True


def wait_paused(timeout: float) -> bool:
    """Wait for the drain :func:`pause_for_backend` stopped to end. True when it has."""
    return _JOB.join(timeout)


def queue_rows() -> list[dict[str, Any]]:
    """The task manager's rows for what the queue holds besides the running run (which shows as its own ``llm`` row with a Stop):
    the paused queue after a restart (Resume / Cancel), or each run waiting its turn (Cancel)."""
    try:
        snap = get_queue().snapshot()
    except Exception:  # noqa: BLE001 - the task manager never fails for a row
        return []
    entries = snap["entries"]
    waiting = [entry for entry in entries if entry.get("state") in ("queued", "paused")]
    if not waiting:
        return []
    if snap["paused"]:
        n = len(waiting)
        return [{
            "id": KIND,
            "kind": KIND,
            "label": f"Summary & translation queue paused ({n} run(s) waiting)",
            "label_i18n": "Summary & translation queue paused ({n} run(s) waiting)",
            "label_vars": {"n": n},
            "state": "paused",
            "progress": None,
            "actions": ["resume", "cancel"],
        }]
    rows: list[dict[str, Any]] = []
    for entry in waiting:
        verb = "Summary" if entry["op"] == "summarize" else "Translation"
        rows.append({
            "id": f"llm-bulk:{entry['id']}",
            "kind": KIND,
            "label": f"{verb} run waiting its turn",
            "label_i18n": f"{verb} run waiting its turn",
            "label_vars": {},
            "state": "queued",
            "progress": None,
            "actions": ["cancel"],
        })
    return rows
