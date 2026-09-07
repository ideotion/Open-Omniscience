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
import secrets
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.paths import data_dir

_LOG = logging.getLogger(__name__)

_STATE_FILE = "import_queue.json"

# The kinds an import run can contain, in the order the scan surfaces them. The
# order matters: the corpus merge must land before the newsletter import, so the
# .eml articles are screened against the corpus the backups just contributed.
KINDS = ("corpus", "legacy", "blobs", "newsletters")

# --------------------------------------------------------------------------- #
#  The checkpoint interval K (the 2026-08-08 queue entry's item (b))
# --------------------------------------------------------------------------- #
#: The highest K this code will honour. Not a safety limit -- the mechanism is the
#: same at any K -- but a stated ceiling, because K is a DURABILITY choice and a
#: number nobody meant (a fat-fingered 500) should read as "never checkpoint", which
#: is not a thing anyone would ask for. Twenty-four is comfortably above the largest
#: queue the field has run (eighteen).
CHECKPOINT_K_MAX = 24
CHECKPOINT_K_DEFAULT = 1


def import_checkpoint_k() -> int:
    """How many corpus backups share ONE verify + snapshot + swap.

    THE TRADE, in one paragraph, because this is the whole decision. Today (K = 1)
    every backup pays its own working-copy snapshot of the entire corpus, its own
    whole-file ``quick_check`` + ``foreign_key_check``, and its own atomic swap --
    on an eighteen-item queue that is eighteen copies of a growing multi-GB file and
    eighteen structural walks of it. At K > 1 the working copy is CARRIED across up
    to K consecutive backups and paid for once. What that buys in time it spends in
    durability: nothing is durable until a swap, so a kill, a Stop or a failure part
    way through a group discards every merge in it. At K = 1 a kill at item 12 keeps
    eleven; at K = 18 it loses twelve merges' CPU.

    THE DEFAULT IS 1 -- today's behaviour exactly, byte for byte -- because the
    trade is the maintainer's to make and the ledger records it as needing a ruling
    rather than a guess (CLAUDE.md open queue, 2026-08-08, item (b)). **The
    recommendation on record is 3.** Setting it is one value:
    ``AppSettings.import_checkpoint_k``, or ``OO_IMPORT_CHECKPOINT_K`` for a run
    that should not touch stored settings.

    Resolution order is settings first, env second, so an operator's stored choice
    is authoritative and the env var stays what it is elsewhere in this module: an
    override for a single process. An unreadable or out-of-range value falls back to
    the default rather than to a guess -- the safe direction here is fewer items per
    checkpoint, never more.
    """
    raw = os.getenv("OO_IMPORT_CHECKPOINT_K", "").strip()
    if not raw:
        try:
            from src.config.app_settings import load_settings

            raw = str(load_settings().import_checkpoint_k)
        except Exception:  # noqa: BLE001 - an unreadable setting is not a licence to guess
            _LOG.debug("could not read import_checkpoint_k; using the default", exc_info=True)
            return CHECKPOINT_K_DEFAULT
    try:
        k = int(raw)
    except ValueError:
        return CHECKPOINT_K_DEFAULT
    if k < 1 or k > CHECKPOINT_K_MAX:
        return CHECKPOINT_K_DEFAULT
    return k


@dataclass
class _CheckpointGroup:
    """The working copy a K > 1 run carries across consecutive corpus items.

    It lives under ``data_dir()`` with the engine's own ``.restore-`` prefix, so the
    existing stale-staging janitor reclaims it if this process dies -- and, unlike a
    prefetched STAGING tree (the reason C3's prefetch is harder than it looks), the
    file it holds preserves the live corpus's at-rest state, so an orphan is
    encrypted whenever the corpus is and is not an at-rest hole.
    """

    dir: Path
    #: Ids of the items merged into ``working`` and not yet committed.
    item_ids: list[str] = field(default_factory=list)
    #: Their artifact digests, so a duplicate later in the SAME group is skipped
    #: rather than merged twice -- the live corpus cannot answer that question yet.
    digests: set[str] = field(default_factory=set)

    @property
    def working(self) -> Path:
        return self.dir / "working.db"


def _new_group_dir() -> Path:
    d = data_dir() / f".restore-group-{secrets.token_hex(8)}"
    d.mkdir(parents=True, exist_ok=True)
    return d


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
        # Whether that pass has RUN, which is a different question from what it achieved:
        # it is the last STAGE of the run, so progress is not complete until it is over,
        # whether it succeeded or not (`_tuned` reports which). Skipped after a Stop, so a
        # stopped run correctly never reaches its own end.
        self._tuning_done = False
        # Live progress of the sub-job currently in flight (mirrored, never authored).
        self._live: dict[str, Any] | None = None
        # THE CHECKPOINT GROUP (K > 1). None whenever no working copy is being
        # carried, which at the default K = 1 is always -- so every attribute below
        # is inert on the shipped default and the run is byte-identical to before.
        self._group: _CheckpointGroup | None = None
        self._group_guard: Any = None
        #: The K this RUN resolved, captured once at its start rather than read per
        #: item -- an operator changing the setting mid-run must not split a group.
        self._checkpoint_k: int = CHECKPOINT_K_DEFAULT
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
        # A STAGED item is one whose merge landed in a working copy that was never
        # swapped in. That copy does not survive this process, so on the next boot
        # the item did not import -- and leaving it "staged" would show it as work
        # in flight forever, while calling it "done" would claim an import that
        # never reached the corpus. It is discarded, by name.
        for it in self._items:
            if it.get("state") == "staged":
                it["state"] = "discarded"
                it["discarded_reason"] = (
                    "merged into this run's working copy, which the app did not "
                    "survive to commit — import it again"
                )

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
            self._tuning_done = False
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

        # THE ONLY THING THAT STARTS THE DRAIN FOR A QUEUED RUN. Each item's own
        # hand-off correctly declines while the window is open -- a parallel re-index
        # after item 1 would compete with items 2..n for the machine the window exists
        # to reserve. Something therefore has to start it once the window is gone, or
        # a multi-backup import would end with the whole backlog sitting untouched
        # until somebody noticed the caveat and clicked, which is "deferred but lost"
        # wearing a different hat. Best-effort: it must never turn a completed import
        # into a reported failure.
        try:
            from src.backup.volume_job import start_reindex_drain

            started, detail = start_reindex_drain()
            _LOG.info(
                "post-import re-index drain %s",
                "started" if started else f"not started ({detail})",
            )
        except Exception:  # noqa: BLE001
            _LOG.warning("could not start the post-import re-index drain", exc_info=True)

    def _drive(self) -> None:
        """Walk the queue. Separated from :meth:`_run` so the exclusive window is a
        plain ``with`` block -- the courtesy pause must never be able to skip the
        import it was only meant to make faster."""
        with self._lock:
            self._checkpoint_k = import_checkpoint_k()
        try:
            for idx, item in enumerate(self._items):
                if self._stop.is_set():
                    break
                hold = self._decide_hold(idx, item)
                with self._lock:
                    self._cursor = idx
                    item["state"] = "running"
                    item["started_at"] = time.time()
                    self._save()
                try:
                    summary = self._run_item(item, hold=hold)
                    state = "stopped" if self._stop.is_set() else "done"
                    if summary.get("held"):
                        # NOT "done": the merge landed in a working copy nothing has
                        # swapped in yet, so calling it imported would claim a corpus
                        # change that has not happened.
                        state = "staged"
                    with self._lock:
                        item["state"] = state
                        item["summary"] = summary
                    self._after_item(item, summary)
                except Exception as exc:  # noqa: BLE001 - one bad item must not lose the rest
                    _LOG.exception("import item %s failed", item.get("id"))
                    with self._lock:
                        item["state"] = "error"
                        item["error"] = str(exc)
                    # A failure ANYWHERE in an item that had an open group taints the
                    # group: windowed merge steps commit mid-merge, so the working
                    # copy may carry a half-merged artifact, and a half-merged copy
                    # must never become the live corpus. Discarding is the only safe
                    # answer, and it costs the group's other merges -- which is the
                    # durability half of the K trade, stated where it is paid.
                    self._discard_group(
                        f"the import of {item.get('label') or item.get('id')} failed, "
                        "so the shared working copy could not be trusted"
                    )
                finally:
                    with self._lock:
                        item["ended_at"] = time.time()
                        self._save()
        finally:
            # A group still open here never reached a checkpoint (a Stop, or a queue
            # whose remaining corpus items all turned out to be already merged). It
            # is discarded rather than committed: committing would mean running the
            # whole-file verification and the swap from a path that has no artifact
            # to check the merge against, and a silent nothing-happened would be
            # worse than either.
            self._discard_group(
                "the run ended before this group of backups reached a checkpoint"
            )
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
                # Reached only if the stage actually ran (the Stop check returns above
                # it), so a stopped run leaves this False and never reads as complete.
                self._tuning_done = True

    # -- the checkpoint group ------------------------------------------------ #
    def _decide_hold(self, idx: int, item: dict) -> bool:
        """Should THIS item stop short of the swap and leave its merge in the
        carried working copy?

        Four conditions, all of them necessary:

        * K > 1 -- at the shipped default this returns False for every item and
          nothing below ever runs.
        * the item is a CORPUS backup. The other kinds (legacy archives, large-data
          folders, newsletters) do not go through ``run_restore``'s working copy at
          all, and the newsletter import in particular reads the live corpus to
          screen against it, so a group must be committed before one runs.
        * the group would not be FULL -- K counts the backups that share one
          checkpoint, so the K-th item of a group is the one that commits it.
        * something after this item will actually MERGE. Not merely "another corpus
          item exists": an artifact this corpus has already merged is answered from
          one small JSON read and never opens a working copy, so if every remaining
          corpus item is a repeat, this item is the last one that can commit the
          group and holding it would strand the whole group.
        """
        # MEASURED, not assumed: at K = 1 the group-full check below ALSO returns
        # False for every item (`open_items + 1 >= 1` holds for any non-negative
        # count), so a mutation that deletes this line alone changes nothing. It
        # stays as a belt on the shipped default rather than as the mechanism: an
        # off-by-one in that comparison (`>` for `>=`) would otherwise let K = 1 hold
        # an item, which is the one behaviour the default exists to make unreachable.
        # The mutation matrix reverts BOTH together, because reverting one proves
        # nothing about a property two clauses hold (the recorded 2026-08-02 lesson).
        if self._checkpoint_k <= 1 or item.get("kind") != "corpus":
            return False
        with self._lock:
            open_items = len(self._group.item_ids) if self._group is not None else 0
        if open_items + 1 >= self._checkpoint_k:
            return False
        return self._another_item_will_merge(idx)

    def _another_item_will_merge(self, idx: int) -> bool:
        """True when some corpus item AFTER ``idx`` would open a working copy.

        Uses the SAME two questions the item itself will ask (the artifact's digest,
        and whether this corpus already carries it), rather than a second rule that
        could disagree with the one that decides. A digest that cannot be read is
        treated as "will merge", because an unknown digest never matches the
        already-merged skip either -- the two answers stay consistent.
        """
        from src.backup.merge import artifact_source_digest, find_completed_import

        with self._lock:
            in_group = set(self._group.digests) if self._group is not None else set()
        for later in self._items[idx + 1 :]:
            if later.get("kind") != "corpus":
                # A non-corpus item ENDS the group, so nothing beyond it can commit
                # this one -- see _decide_hold.
                return False
            if later.get("force"):
                return True
            try:
                digest = artifact_source_digest(later.get("path") or "")
            except Exception:  # noqa: BLE001 - unreadable reads as "will merge"
                return True
            if not digest:
                return True
            if digest in in_group:
                continue
            try:
                if find_completed_import(digest) is None:
                    return True
            except Exception:  # noqa: BLE001 - same direction: assume it will merge
                return True
        return False

    def _open_group(self) -> _CheckpointGroup:
        """Create the run's carried working-copy directory and register it as a LIVE
        staging path, so the stale-staging janitor's age guard can never reclaim it
        mid-run (the same protection the pre-restore snapshot takes)."""
        from contextlib import ExitStack

        from src.backup.stream_backup import active_staging

        group = _CheckpointGroup(dir=_new_group_dir())
        guard = ExitStack()
        guard.enter_context(active_staging(group.dir))
        with self._lock:
            self._group = group
            self._group_guard = guard
        return group

    def _release_group(self) -> _CheckpointGroup | None:
        with self._lock:
            group, guard = self._group, self._group_guard
            self._group, self._group_guard = None, None
        if guard is not None:
            try:
                guard.close()
            except Exception:  # noqa: BLE001 - a registry release must never fail a run
                _LOG.warning("releasing the checkpoint group's staging guard failed", exc_info=True)
        return group

    def _discard_group(self, reason: str) -> None:
        """Throw the carried working copy away and SAY which items went with it."""
        group = self._release_group()
        if group is None:
            return
        shutil.rmtree(group.dir, ignore_errors=True)
        if not group.item_ids:
            return
        _LOG.warning(
            "discarding %d staged import(s) with the checkpoint group: %s",
            len(group.item_ids), reason,
        )
        with self._lock:
            for it in self._items:
                if it.get("id") in group.item_ids and it.get("state") == "staged":
                    it["state"] = "discarded"
                    it["discarded_reason"] = reason
            self._save()

    def _commit_group(self) -> None:
        """The checkpoint landed: the swap MOVED the working copy onto the live
        corpus, so every item that had been staged into it is now imported."""
        group = self._release_group()
        if group is None:
            return
        shutil.rmtree(group.dir, ignore_errors=True)
        if not group.item_ids:
            return
        with self._lock:
            for it in self._items:
                if it.get("id") in group.item_ids and it.get("state") == "staged":
                    it["state"] = "done"
            self._save()

    def _after_item(self, item: dict, summary: dict) -> None:
        """Fold one finished item into the group's bookkeeping."""
        if summary.get("held"):
            group = self._group
            if group is not None:
                with self._lock:
                    group.item_ids.append(str(item.get("id")))
                    if summary.get("source_digest"):
                        group.digests.add(str(summary["source_digest"]))
            return
        if item.get("kind") != "corpus":
            return
        report = summary.get("report") or {}
        if report.get("committed"):
            self._commit_group()
        elif report.get("refused"):
            # The merge landed and the verification refused it, so the copy carries
            # rows nothing has vouched for. Same answer as a raised failure.
            self._discard_group(
                "post-merge verification refused "
                f"{item.get('label') or item.get('id')}, so the shared working copy "
                "could not be trusted"
            )

    def _run_item(self, item: dict, *, hold: bool = False) -> dict:
        kind = item["kind"]
        if kind == "corpus":
            return self._run_corpus(item, hold=hold)
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

    def _run_corpus(self, item: dict, *, hold: bool = False) -> dict:
        from src.backup.volume_job import get_volume_manager

        mgr = get_volume_manager()
        # THE GROUP is opened lazily, by the first item that is going to use it --
        # so a K > 1 run that happens to contain a single corpus backup never
        # creates a directory it does not need, and a K = 1 run never reaches here
        # at all (``_decide_hold`` returns False before any of this).
        group = self._group
        if group is None and hold:
            group = self._open_group()
        working_copy = group.working if group is not None else None
        already = frozenset(group.digests) if group is not None else frozenset()
        mgr.start_restore(
            item["path"], self._passphrase, force=bool(item.get("force")),
            working_copy=working_copy, hold_after_merge=hold,
            already_merged_digests=already,
        )
        st = self._await(mgr.status, mgr.cancel)
        summary = st.get("summary") or {}
        rep = summary.get("report") or {}
        out = {
            "report": rep,
            "state": st.get("state"),
            "held": bool(summary.get("held")),
            "source_digest": summary.get("source_digest"),
        }
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
        # queued=True: this item runs INSIDE the exclusive window this run already opened,
        # so it must not stand aside for it. Drop this and the item parks on its own run's
        # window while _await() below waits on the item -- the queue hangs.
        mgr.start(item["path"], queued=True)
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
            tuning_done = self._tuning_done
            k = self._checkpoint_k
            open_group = len(self._group.item_ids) if self._group is not None else 0
        now = time.time()
        for it in items:
            s, e = it.get("started_at"), it.get("ended_at")
            it["elapsed_s"] = round((e or now) - s, 1) if s else None
        # An item whose own work is FINISHED, which at K > 1 includes one that has
        # merged into the carried working copy: the queue really has walked past it,
        # and a bar that stalled while three backups merged would be as wrong as one
        # that claimed a corpus change. What has actually reached the corpus is the
        # separate `items_committed` below, so the two facts stay two facts.
        done = sum(1 for it in items if it["state"] in ("done", "skipped", "staged"))
        committed = sum(1 for it in items if it["state"] in ("done", "skipped"))
        staged = sum(1 for it in items if it["state"] == "staged")
        return {
            "state": state,
            "items": items,
            "cursor": cursor,
            "current": items[cursor] if 0 <= cursor < len(items) else None,
            "live": dict(live) if isinstance(live, dict) else None,
            "items_done": done,
            "items_total": len(items),
            # COMMITTED vs STAGED, at any moment (the 2026-08-08 checkpoint entry).
            # At the default K = 1 `staged` is always 0 and `items_committed` equals
            # `items_done`, so this says nothing new until an operator chooses to
            # trade durability for time -- and then it says exactly what that trade
            # is costing them right now.
            "items_committed": committed,
            "items_staged": staged,
            "checkpoint": {
                "k": k,
                "open_group_items": open_group,
                # Stated rather than left for the reader to derive from K: at K = 1
                # there is nothing to explain, and above it the sentence IS the
                # disclosure of what a Stop or a crash would cost.
                "note": (
                    "Every backup is written to your corpus as soon as it finishes."
                    if k <= 1
                    else (
                        f"Backups are written to your corpus once every {k}. Until "
                        "that happens their merges live in a working copy that a "
                        "Stop, a failure or a crash discards — they would need "
                        "importing again."
                    )
                ),
            },
            # STAGES, for anything that draws a BAR. Items alone reach "all done" while
            # the run is still working -- the search-index merge is a real final stage
            # inside the same exclusive window, and on a large corpus it is minutes of
            # it. A bar at 100% beside a run that is still holding the machine is the
            # kind of number this project does not publish, so the denominator counts
            # the stage that is actually left. The item COUNT above is untouched: it was
            # never wrong, it just is not the whole run.
            "stages_done": done + (1 if tuning_done else 0),
            "stages_total": len(items) + 1,
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
