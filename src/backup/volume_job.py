"""Pausable task-manager job for the large volume+parity backup/restore (slice 1c).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The streaming volumes + Reed-Solomon parity (1a/2) + the artifact create/restore (1b)
are the engine. This wraps them in ONE background job (mirrors FolderBackupManager) so a
6 GB build/restore runs off the request thread, reports progress, and is cancellable.
State is IN-MEMORY; a module-level singleton makes it visible across requests + /api/jobs.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Module-level, not lazy: _on_prog fires once per merged article (~700k times on
# a large import), and even a sys.modules lookup does not belong on that path.
# runlog imports nothing but stdlib at module scope, so this cannot cycle.
from src.backup import runlog

_LOG = logging.getLogger(__name__)

# "Progress everywhere" (field-feedback Session A §4 item 2): run_restore's
# internal stage names (src/backup/merge.py) mapped onto the phase-string
# vocabulary _uxVolPhase already understands on the frontend. "merge"/
# "reindex" alias to the EXISTING "merging"/"reindexing" phases (whose own
# granular progress_cb/reindex_progress_cb immediately overwrite this coarse
# ping with real N-of-M data) rather than introducing near-duplicate names;
# every other stage gets its own honest, distinct phase name.
_STAGE_TO_PHASE = {"merge": "merging", "reindex": "reindexing"}

# The manager's OWN phases, emitted before run_restore is ever entered. They come
# first in the user-visible phase count, so run_restore's stage positions are
# offset by exactly this many (field ruling 2026-07-29 item 17: the remaining
# phase count must be visible, and it must be REAL -- a restore's true phase total
# is these plus run_restore's own plan, which itself varies with commit /
# reindex_imported).

_RESTORE_MANAGER_PHASES: tuple[str, ...] = ("verifying", "reassembling")

# THE IMPORT DOES NOT BLOCK ON THE RE-INDEX (2026-08-03, implementing the standing
# 2026-07-29 ruling 1/2: "defer the re-index off the blocking import path -- YES",
# "the re-index is AUTONOMOUS + VISIBLE").
#
# THE FIELD RUN THAT FORCED IT. A 650 MB import: all eighteen stages -- verify,
# reassemble, merge, SWAP -- finished in 118.6 s and the corpus was committed and
# safe. The post-swap re-index then ran 3.02 HOURS, reached 41%, and the operator
# killed it. So the import a user waited three and a half hours for had actually
# been complete, on disk, after two minutes. It was wearing the re-index's clock.
#
# Nothing here makes the re-index faster. It stops being the IMPORT's problem: the
# restore ends at the swap, and the already-existing, already-resumable
# ``reindex-resume`` background job drains the backlog with its own progress, its
# own Stop, and its own durable per-article watermark.
#
# SAFE BY CONSTRUCTION, not by luck -- run_restore already anticipated this flag:
#   * the corpus-epoch bump has an explicit branch for reindex_imported=False;
#   * keyword_counter_reconcile is deliberately UNCONDITIONAL, "outside the
#     reindex_imported branch", because the drift comes from the MERGE;
#   * quarantine_scan works off the batch's merged_rows ids, not off keywords.
# And under the option-(a) ruling a not-yet-re-indexed article simply has no
# mentions, which every analytics path already honours structurally -- so deferring
# shows an incomplete corpus, never a WRONG one.
#
# The honesty cost is that "import finished" no longer means "fully indexed", so the
# report says so and carries the pending count. OO_IMPORT_DEFER_REINDEX=0 restores
# the old blocking behaviour.
def defer_reindex() -> bool:
    return (os.getenv("OO_IMPORT_DEFER_REINDEX", "1").strip() or "1") != "0"


def hand_off_reindex(report: dict) -> None:
    """State the deferral in the report, and start the drain.

    TWO THINGS, and the first is the one that must never be dropped. "Import
    finished" no longer means "fully indexed", so the report SAYS so and carries the
    real pending count -- otherwise deferring would trade a visible three-hour wait
    for an invisible incomplete corpus, which is strictly worse. ``reindex_backlog``
    keeps "could not read" distinct from "nothing pending", so an unreadable backlog
    is reported as unreadable rather than as zero.

    Then it starts the existing ``reindex-resume`` job. That job already owns the
    durable watermark, the batching, the parallel precompute, the progress and the
    Stop -- this is only the caller. Best-effort by design: if it cannot start (one
    is already running, which is the common case in an import QUEUE), the backlog is
    still recorded and the job remains startable from the UI, so the work is deferred
    but never lost.
    """
    try:
        from src.backup.merge import reindex_backlog

        bk = reindex_backlog()
    except Exception:  # noqa: BLE001 - a committed import must never fail on its own epilogue
        _LOG.warning("could not read the re-index backlog after import", exc_info=True)
        bk = {"available": False, "reason": "see server log"}

    report["reindex_deferred"] = {
        "deferred": True,
        "why": (
            "The import is complete and committed. Re-indexing the imported articles "
            "runs in the background so it never blocks the import; until it finishes "
            "those articles carry no keywords and are absent from analytics."
        ),
        "articles_pending": bk.get("articles_pending") if bk.get("available") else None,
        "pending_unreadable_reason": None if bk.get("available") else bk.get("reason"),
        "job": "reindex-resume",
    }

    pending = report["reindex_deferred"]["articles_pending"]
    if not pending:
        # Nothing to drain, or nothing we could READ. Starting a job in either case is
        # pointless work whose only visible effect is a failure in the log -- and on the
        # unreadable branch it would also imply we knew there was work, which we do not.
        report["reindex_deferred"]["started"] = False
        report["reindex_deferred"]["start_detail"] = (
            "nothing pending" if pending == 0 else "the backlog could not be read"
        )
        return

    # NOT INSIDE AN IMPORT RUN'S EXCLUSIVE WINDOW. The queue takes ONE window across
    # every item precisely so the machine belongs to the import; starting a
    # CPU-heavy parallel drain after item 1 would put competing work back on it for
    # the remaining items -- the same mistake, in the opposite direction, as the
    # 2026-07-24 finding that a pause must gate every entry point starting equivalent
    # work. So this follows the shape ``resume_after_exclusive_operation`` already
    # uses: nested calls record and return, and the window itself drains once at the
    # end (:meth:`ImportQueueManager._run`).
    try:
        from src.scheduler.runner import exclusive_window_open

        nested = exclusive_window_open()
    except Exception:  # noqa: BLE001 - never let a courtesy check fail a committed import
        nested = False
    if nested:
        report["reindex_deferred"]["started"] = False
        report["reindex_deferred"]["start_detail"] = (
            "this import is one item of a run; the drain starts once the whole run ends"
        )
        return

    started, detail = start_reindex_drain()
    report["reindex_deferred"]["started"] = started
    if detail:
        report["reindex_deferred"]["start_detail"] = detail


def start_reindex_drain() -> tuple[bool, str | None]:
    """Start the background re-index drain. ``(started, detail)``; never raises.

    Its own function because there are now two callers: the per-import hand-off
    above, and the import QUEUE at the end of its exclusive window -- where it is the
    ONLY thing that starts the drain for a multi-item run, since every item's own
    hand-off correctly declined to.
    """
    try:
        from src.api.backup_v2 import _REINDEX_RESUME_JOB

        _REINDEX_RESUME_JOB.start()
        return True, None
    except Exception as exc:  # noqa: BLE001 - already-running is normal in a queue
        _LOG.info("re-index drain not started now (%s); the backlog stays visible", exc)
        return False, str(exc)


def _stage_phase_name(stage_name: str) -> str:
    return _STAGE_TO_PHASE.get(stage_name, stage_name)


class VolumeBackupManager:
    """ONE volume backup OR restore at a time — you don't run two giant crypto+IO jobs
    concurrently. The destination directory is the durable artifact; a cancelled backup's
    partial volume set is removed so it can never be mistaken for a good backup."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state = "idle"  # idle|running|paused|cancelled|done|error
        self._mode = "backup"  # backup|restore|verify
        self._dest: str | None = None
        self._progress: dict[str, Any] = {}
        self._error: str | None = None
        self._summary: dict[str, Any] | None = None
        self._pause_requested = False
        #: Re-merge even an artifact already recorded as merged (set per start_restore).
        self._force = False

    def _alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _reap_or_reject(self) -> None:
        """Reject only a GENUINELY-running job; otherwise reap a finished worker so the
        next one can start. Call under ``self._lock``.

        Fixes the back-to-back race (field report 2026-07-02: "A volume backup/restore
        is already running" when importing several archives one after another): the
        worker sets its terminal state ("done") and returns, but ``_alive()`` stays True
        for the brief thread-teardown window — so a start fired the instant the poller
        saw "done" wrongly 409'd. Gate on the logical state instead, and join the
        lingering thread so exactly one worker ever runs. Sequential imports now hand
        off cleanly (parallel volume restores stay disallowed by design — one writer)."""
        if self._state == "running" and self._alive():
            raise RuntimeError("A volume backup/restore is already running.")
        if self._thread is not None:
            self._thread.join(timeout=5)  # instant once the work is done; a safety cap
            self._thread = None

    def _on_prog(self, p: dict) -> None:
        with self._lock:
            self._progress = p
        # The run journal's view of progress. Deliberately AFTER the lock and
        # outside it: this fires once per merged article (~700k times on a large
        # import), and it is two attribute stores with no I/O -- see
        # runlog.RunLog.progress.
        runlog.progress(p)

    # -- backup ------------------------------------------------------------- #
    def start_backup(
        self,
        dest: str,
        passphrase: str,
        *,
        include_newsletters: bool = True,
        parity_fraction: float = 0.1,
        _backup_fn: Callable[..., dict] | None = None,
    ) -> dict:
        with self._lock:
            self._reap_or_reject()
            if not passphrase:
                raise ValueError("the volume backup is always encrypted: a passphrase is required")
            destp = Path(dest)
            try:
                destp.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ValueError(f"Cannot use destination {destp}: {exc}") from exc
            if not destp.is_dir():
                raise ValueError(f"{destp} is not a folder.")
            self._stop.clear()
            self._pause_requested = False
            self._state, self._mode, self._dest = "running", "backup", str(destp)
            self._error, self._summary = None, None
            self._progress = {"phase": "starting"}
            self._thread = threading.Thread(
                target=self._run_backup,
                args=(destp, passphrase, include_newsletters, parity_fraction, _backup_fn),
                daemon=True,
                name="volume-backup",
            )
            self._thread.start()
            return self.status()

    def _run_backup(self, destp, passphrase, include_newsletters, parity_fraction, backup_fn):
        from src.backup.volumes import VolumeStopped

        # The export "seems to work fine" (maintainer, 2026-07-31) -- which is
        # exactly why it is worth journalling: the numbers it has never left the
        # process, so nobody knows what "fine" costs, or where.
        runlog.begin(
            "export", label=destp.name, dest=str(destp),
            include_newsletters=include_newsletters, parity_fraction=parity_fraction,
        )
        try:
            fn = backup_fn
            if fn is None:
                from src.backup.artifact import write_volume_backup

                fn = write_volume_backup
            summary = fn(
                destp,
                passphrase,
                include_newsletters=include_newsletters,
                parity_fraction=parity_fraction,
                should_stop=self._stop.is_set,
                progress_cb=self._on_prog,
            )
            with self._lock:
                self._state = "done"
                self._summary = {k: v for k, v in summary.items() if k != "envelope"}
                self._progress = {**self._progress, "phase": "done"}
            runlog.end(
                "ok",
                volumes=summary.get("volumes"),
                bytes=summary.get("total_bytes") or summary.get("bytes"),
                # The ENGINE's own wall_s, kept beside (never instead of) the
                # journal's: they measure slightly different spans and both are real.
                engine_wall_s=summary.get("wall_s"),
                gate_held_s=summary.get("gate_held_s"),
            )
        except VolumeStopped:
            with self._lock:
                paused = self._pause_requested
            if paused:
                # PAUSE keeps the finished volumes + the resume log: starting the
                # backup again continues from them (the engine re-verifies every
                # slice, so a resumed set is still one consistent snapshot). The
                # partial set has NO final manifest, so it can never be mistaken
                # for a good backup meanwhile.
                with self._lock:
                    self._state = "paused"
                runlog.end("paused")
            else:
                # END AFTER the cleanup, not before: deleting the partial set is
                # part of this run, it touches the destination drive, and it is
                # exactly the step an operator would want timed if a cancel ever
                # appears to hang.
                runlog.milestone("stage_begin", name="cleanup_partial")
                self._cleanup_partial(destp)
                runlog.milestone("stage_end", name="cleanup_partial")
                with self._lock:
                    self._state = "cancelled"
                runlog.end("cancelled")
        except Exception as exc:  # noqa: BLE001 - surface the failure, never crash the thread
            _LOG.exception("volume backup failed")
            import traceback

            runlog.milestone(
                "error",
                cls=type(exc).__name__,
                msg=str(exc)[:2000],
                traceback="".join(traceback.format_exception(exc))[-8000:],
            )
            runlog.end("error", cls=type(exc).__name__)
            with self._lock:
                self._state, self._error = "error", str(exc)
        finally:
            # The same net as the restore path: a no-op whenever an outcome was
            # recorded, and honest about its own ignorance when one was not.
            runlog.end("ended-without-a-recorded-outcome")

    # -- restore ------------------------------------------------------------ #
    def start_restore(
        self,
        src: str,
        passphrase: str,
        *,
        allow_unverified: bool = False,
        corpus_passphrase: str | None = None,
        force: bool = False,
        _restore_fn: Callable[..., dict] | None = None,
    ) -> dict:
        with self._lock:
            self._reap_or_reject()
            srcp = Path(src)
            if not srcp.is_dir():
                raise ValueError(f"{srcp} is not a folder to restore from.")
            # Re-merge an artifact this corpus has already merged. Additive and
            # off by default: the skip exists because the redundant work is
            # expensive, not because re-merging is unsafe -- the merge is
            # idempotent, so forcing costs time and nothing else.
            self._force = bool(force)
            self._stop.clear()
            self._pause_requested = False
            self._state, self._mode, self._dest = "running", "restore", str(srcp)
            self._error, self._summary = None, None
            # phase 1 of the restore's user-visible sequence (the total is filled in
            # by _run_restore, which knows run_restore's own plan for these flags).
            self._progress = {
                "phase": "verifying",
                "phase_index": _RESTORE_MANAGER_PHASES.index("verifying") + 1,
            }
            self._thread = threading.Thread(
                target=self._run_restore,
                args=(srcp, passphrase, allow_unverified, corpus_passphrase, _restore_fn),
                daemon=True,
                name="volume-restore",
            )
            self._thread.start()
            return self.status()

    def _run_restore(self, srcp, passphrase, allow_unverified, corpus_passphrase, restore_fn):
        from src.backup.merge import RestoreAborted

        # ONE run journal per queue item, opened before anything expensive. Eight
        # sequential imports at ~10 h each sharing one run_id would wrap the beat
        # ring and lose the early hours of every item but the last.
        runlog.begin("import", label=srcp.name, dest=str(srcp), force=self._force)
        try:
            if restore_fn is not None:
                summary = restore_fn(srcp, passphrase)
                with self._lock:
                    self._state, self._summary = "done", summary
                    self._progress = {"phase": "done"}
                runlog.end("ok", injected_restore_fn=True)
                return
            from src.backup.artifact import cleanup_staging, read_volume_backup
            from src.backup.merge import (
                artifact_source_digest,
                find_completed_import,
                import_cache_mb,
                import_reindex_commit_batch,
                restore_stage_plan,
                run_restore,
            )

            # ALREADY MERGED? Answered from one small JSON read, BEFORE verify,
            # parity-recovery, reassembly and staging -- which is the only place
            # the question is worth asking. Field logs 2026-07-31: 8 of 18 imports
            # added ZERO articles, the largest spending 2.96 h to merge 700,503
            # duplicates and leave the corpus byte-identical.
            #
            # Deliberately NOT silent (an import that quietly does nothing is
            # indistinguishable from one that failed): the skip names the batch and
            # date it matched, and `force` re-imports regardless.
            _digest = artifact_source_digest(srcp)
            _already = None if self._force else find_completed_import(_digest)
            if _already is not None:
                summary = {
                    "skipped": "already-merged",
                    "source_digest": _digest,
                    "merged_as_batch": _already["batch_id"],
                    "merged_at": _already["imported_at"],
                    "note": (
                        "this exact artifact was already merged; nothing to do. "
                        "Re-import with force to merge it again."
                    ),
                }
                _LOG.info(
                    "skipping %s: already merged as batch %s on %s",
                    srcp, _already["batch_id"], _already["imported_at"],
                )
                with self._lock:
                    self._state, self._summary = "done", summary
                    self._progress = {"phase": "skipped-already-merged"}
                runlog.end(
                    "skipped-already-merged",
                    merged_as_batch=_already["batch_id"], merged_at=_already["imported_at"],
                )
                return

            # "Import owns the machine" (field-feedback Session A §4, ruled):
            # a large volume restore competes for the single-writer gate and
            # CPU with any in-flight background collection pass, so
            # collection is paused for the restore's WHOLE duration
            # (reassemble + merge + re-index) and resumed afterward. A
            # THROUGHPUT courtesy, never a correctness requirement -- a
            # pause/resume hiccup must never abort or corrupt an otherwise-
            # good restore, so both sides are best-effort.
            from src.scheduler.runner import (
                owns_the_machine,
                pause_for_exclusive_operation,
                resume_after_exclusive_operation,
            )

            was_paused = False
            try:
                was_paused = pause_for_exclusive_operation()
            except Exception:  # noqa: BLE001 - the pause is a courtesy, never load-bearing
                _LOG.warning("pausing background collection for the restore failed", exc_info=True)

            # The user-visible phase TOTAL for this restore: our own manager phases
            # plus run_restore's own plan for these exact flags. Computed, never a
            # constant -- run_restore's plan legitimately differs by commit /
            # reindex_imported (field ruling 2026-07-29 item 17).
            _restore_plan = restore_stage_plan(
                commit=True, reindex_imported=not defer_reindex()
            )
            _phase_total = len(_RESTORE_MANAGER_PHASES) + len(_restore_plan)

            def _phase_of(stage_name: str) -> int:
                """Visible phase index of one run_restore stage. 0 means "not in this
                restore's plan" -- an honest unknown, never a guessed position."""
                if stage_name not in _restore_plan:
                    return 0
                return len(_RESTORE_MANAGER_PHASES) + _restore_plan.index(stage_name) + 1

            try:
                self._on_prog({
                    "phase": "reassembling", "own_the_machine": True,
                    "phase_index": _RESTORE_MANAGER_PHASES.index("reassembling") + 1,
                    "phase_total": _phase_total,
                })
                staged = read_volume_backup(
                    srcp, passphrase, corpus_passphrase=corpus_passphrase,
                    should_stop=self._stop.is_set,
                )  # verify + parity-recover + reassemble
                try:
                    self._on_prog({
                        "phase": "merging", "own_the_machine": True,
                        "phase_total": _phase_total,
                    })

                    def _merge_prog(done: int, total: int, name: str) -> None:
                        # Report the merge step so the UI shows a determinate bar + a
                        # rule-of-three ETA over the "Merging (additive)…" phase.
                        self._on_prog(
                            {
                                "phase": "merging",
                                "merge_step": done,
                                "merge_steps": total,
                                "merge_label": name,
                                "own_the_machine": True,
                                # Carry the position through the fine-grained pings
                                # too: without it the "phase N of M" counter would
                                # blank out for the whole of the two LONGEST phases,
                                # which are exactly the ones a user is waiting on.
                                "phase_index": _phase_of("merge"),
                                "phase_total": _phase_total,
                            }
                        )
                        # durable=False: this fires from inside merge_corpus's
                        # single BEGIN IMMEDIATE, which holds the process-wide
                        # write gate. Fourteen fsyncs there are bounded and
                        # negligible against hours of work -- but on the failing
                        # or full disk this journal exists to diagnose, an fsync
                        # can block for seconds while the gate is held, and every
                        # other writer would feel it. The next milestone's fsync
                        # flushes these to the platter anyway.
                        runlog.milestone(
                            "merge_step", durable=False, step=done, steps=total, label=name
                        )

                    def _reindex_prog(done: int, total: int) -> None:
                        # A DISTINCT "reindexing" phase (2026-07-19 field report): the
                        # post-merge per-article re-index used to run silently after the
                        # 14-step merge finished, leaving the UI frozen on "14/14" for
                        # however long the (previously single-core, unbatched) CPU-bound
                        # extraction took -- sometimes hours on a large restore, reading
                        # as a hang. Now reported as its own phase with real done/total.
                        self._on_prog({
                            "phase": "reindexing", "reindex_done": done,
                            "reindex_total": total, "own_the_machine": True,
                            "phase_index": _phase_of("reindex"),
                            "phase_total": _phase_total,
                        })

                    from src.analytics.reindex_parallel import all_cores_worker_count

                    def _stage_prog(name: str) -> None:
                        # A coarse "now doing: X" ping for stages B/D/E/G, which have
                        # no callback of their own (§4 item 2), carrying its POSITION
                        # so the UI can say "phase 11 of 19" instead of leaving the
                        # user with no sense of how much remains (field ruling
                        # 2026-07-29 item 17). The position is derived HERE from
                        # run_restore's own published plan rather than being pushed
                        # through stage_progress_cb: widening that callback's contract
                        # would silently starve any caller still passing a 1-argument
                        # sink, because StageTimings swallows the resulting TypeError.
                        self._on_prog({
                            "phase": _stage_phase_name(name),
                            "own_the_machine": True,
                            "phase_index": _phase_of(name),
                            "phase_total": _phase_total,
                        })

                    # Own-the-machine only when the pause ACTUALLY confirmed a
                    # running pass was there and got signalled to stop (§4 item 3) --
                    # a concurrency-skeptic MEDIUM finding (2026-07-24): these were
                    # applied unconditionally regardless of was_paused, so if
                    # pause_for_exclusive_operation() had raised (was_paused stays
                    # False, the scheduler's real state then unknown), the restore
                    # would STILL grab all cores + an enlarged cache while a pass
                    # might genuinely still be running -- contradicting the code's
                    # own stated precondition. was_paused == False also covers the
                    # harmless case (nothing was running to begin with); falling
                    # back to None (each parameter's own pre-existing, conservative
                    # default: worker_count()'s auto-detect / no PRAGMA at all)
                    # there costs a little throughput, never correctness -- the
                    # safe direction to err.
                    # ``reindex_commit_batch`` (field report 2026-07-29) was the one
                    # own-the-machine knob this call site never passed, so the restore's
                    # re-index silently fell back to OO_REINDEX_COMMIT_BATCH's default of
                    # 1 -- one commit, hence one fsync through the SQLCipher codec, PER
                    # ARTICLE, for every merged article. Gated on was_paused exactly like
                    # its two siblings above: a wide batch holds the single-writer gate
                    # across the batch, which is free when collection is confirmed paused
                    # and rude when it is not.
                    # OWNERSHIP, not liveness (field report 2026-07-30). These were
                    # gated on `was_paused`, which answers "did I stop a running
                    # collection loop" -- False on a fresh install (nothing was
                    # running to stop) and False for every item of an import queue
                    # (the queue's own window already paused it). In BOTH cases the
                    # machine is owned MORE completely, and all three knobs silently
                    # reverted to their conservative defaults -- most damagingly
                    # OO_REINDEX_COMMIT_BATCH's 1, one commit per article. See
                    # runner.owns_the_machine for the full reasoning.
                    _owned = owns_the_machine()
                    _reindex_workers = all_cores_worker_count() if _owned else None
                    _merge_cache_mb = import_cache_mb() if _owned else None
                    _reindex_batch = import_reindex_commit_batch() if _owned else None

                    # The knobs this run ACTUALLY resolved, recorded before the
                    # work rather than in the final report -- a killed run's
                    # settings are half the diagnosis, and the final report is
                    # precisely what a killed run never writes.
                    runlog.milestone(
                        "knobs",
                        owns_the_machine=_owned,
                        was_paused=was_paused,
                        reindex_workers=_reindex_workers,
                        merge_cache_mb=_merge_cache_mb,
                        reindex_commit_batch=_reindex_batch,
                        exclusive=_owned,
                        phase_total=_phase_total,
                    )

                    report = run_restore(
                        staged,
                        commit=True,
                        allow_unverified=allow_unverified,
                        # Recorded WITH the merge, in its transaction, so the next
                        # import of these same bytes is answered in milliseconds
                        # instead of hours. None when unreadable -- an unknown
                        # never matches, so it costs a redundant import at worst.
                        source_digest=_digest,
                        progress_cb=_merge_prog,
                        reindex_progress_cb=_reindex_prog,
                        stage_progress_cb=_stage_prog,
                        reindex_imported=not defer_reindex(),
                        reindex_workers=_reindex_workers,
                        reindex_commit_batch=_reindex_batch,
                        merge_cache_mb=_merge_cache_mb,
                        # Ruling 2026-07-29 item 15: Stop is IMMEDIATE. Before the
                        # atomic swap this aborts with the live corpus untouched;
                        # after it, it stops the (resumable) re-index tail. This job
                        # used to ignore self._stop entirely on the restore path, so
                        # a Stop button during an import was inert.
                        should_stop=self._stop.is_set,
                        # Import-speed fix 2026-07-30: lets the two whole-corpus
                        # snapshots copy the corpus's bytes instead of re-encrypting it
                        # row by row through the codec. Gated on the SAME confirmed
                        # exclusivity as the three own-the-machine knobs above (or on
                        # the queue's window, when this restore is one item of a run):
                        # the fast path holds the write gate for the copy, which is free
                        # when collection is confirmed paused and rude when it is not.
                        exclusive=_owned,
                    )
                    with self._lock:
                        self._state, self._summary = "done", {"report": report}
                        self._progress = {"phase": "done"}
                    if defer_reindex():
                        hand_off_reindex(report)
                    runlog.end("ok", **{
                        k: report.get(k) for k in ("batch_id", "reindexed", "articles_merged")
                        if report.get(k) is not None
                    })
                finally:
                    cleanup_staging(staged)
            finally:
                try:
                    resume_after_exclusive_operation(was_paused)
                except Exception:  # noqa: BLE001 - the resume is a courtesy, never load-bearing
                    _LOG.warning(
                        "resuming background collection after the restore failed", exc_info=True
                    )
        except RestoreAborted as exc:
            # The operator's own Stop, honoured before the swap -- a normal outcome,
            # never an error. The live corpus is byte-identical; the staging dir is
            # cleaned by the finally above.
            _LOG.info("volume restore stopped by the operator: %s", exc)
            runlog.end("stopped-by-operator", detail=str(exc)[:500])
            with self._lock:
                self._state = "cancelled"
                self._error = None
                self._progress = {"phase": "cancelled", "detail": str(exc)}
        except Exception as exc:  # noqa: BLE001
            _LOG.exception("volume restore failed")
            from src.backup.merge import MergeError, classify_restore_error

            # A MergeError is an intentional, well-formed refusal (the live DB stays
            # untouched) -- its own message is already the honest detail. Anything
            # else (e.g. a genuine UNIQUE-constraint data conflict) gets the same
            # classification the single-shot /api/backup/v2/restore endpoint applies
            # (P0-2, _restore_error) -- this job used to store the bare str(exc)
            # instead, so a data-merge conflict read as an unqualified, unhelpful
            # "UNIQUE constraint failed:" in the UI (field bug 2026-07-15).
            detail = str(exc) if isinstance(exc, MergeError) else classify_restore_error("restore", exc)
            # The traceback, bounded and scrubbed. `cls` + `msg` alone lose the
            # single most useful artefact a failed run leaves behind.
            import traceback

            runlog.milestone(
                "error",
                cls=type(exc).__name__,
                msg=str(exc)[:2000],
                traceback="".join(traceback.format_exception(exc))[-8000:],
            )
            runlog.end("error", cls=type(exc).__name__)
            with self._lock:
                self._state, self._error = "error", detail
        finally:
            # A net for an exit path not enumerated above. A no-op whenever an
            # outcome WAS recorded (the ambient run is already cleared), so it can
            # never overwrite a real one -- and it names its own ignorance rather
            # than guessing "ok".
            runlog.end("ended-without-a-recorded-outcome")

    # -- verify -------------------------------------------------------------- #
    def start_verify(
        self,
        src: str,
        passphrase: str | None = None,
        *,
        _verify_fn: Callable[..., dict] | None = None,
    ) -> dict:
        """Run the end-to-end volume-set verification as a background job (a 100 GB
        set is a full read — never on the request thread). Without a passphrase:
        signature + every checksum; with it: every volume is also stream-decrypted
        into a hash sink. The report lands in ``summary``."""
        with self._lock:
            self._reap_or_reject()
            srcp = Path(src)
            if not srcp.is_dir():
                raise ValueError(f"{srcp} is not a folder to verify.")
            self._stop.clear()
            self._pause_requested = False
            self._state, self._mode, self._dest = "running", "verify", str(srcp)
            self._error, self._summary = None, None
            self._progress = {"phase": "verifying"}
            self._thread = threading.Thread(
                target=self._run_verify,
                args=(srcp, passphrase, _verify_fn),
                daemon=True,
                name="volume-verify",
            )
            self._thread.start()
            return self.status()

    def _run_verify(self, srcp, passphrase, verify_fn):
        try:
            fn = verify_fn
            if fn is None:
                from src.backup.stream_backup import verify_stream_backup

                fn = verify_stream_backup
            report = fn(srcp, passphrase)
            with self._lock:
                self._state = "done"
                self._summary = {"report": report}
                self._progress = {"phase": "done"}
        except Exception as exc:  # noqa: BLE001 - surface the failure, never crash the thread
            _LOG.exception("volume verify failed")
            with self._lock:
                self._state, self._error = "error", str(exc)

    # -- controls ----------------------------------------------------------- #
    def cancel(self) -> None:
        """Stop a running backup OR restore.

        A BACKUP stops between volumes and its partial set is CLEANED, so it can
        never be mistaken for a good backup.

        A RESTORE (2026-07-29, ruling item 15 -- this path used to ignore the stop
        entirely) stops at the next boundary in reassembly, the 14 merge steps, or
        a pre-swap stage: all of those run on a disposable staging dir and a working
        copy, so the abort is FREE and COMPLETE and the live corpus is byte-identical.
        The atomic swap itself is uninterruptible by design (there is no sound undo
        for it), so a stop arriving after it stops only the remaining post-swap work
        -- the re-index, whose durable cursor resumes it later. The UI must state
        which of the two happened rather than implying an undo that does not exist."""
        with self._lock:
            self._pause_requested = False
        self._stop.set()

    def pause(self) -> None:
        """Stop a running backup (between volumes) KEEPING the finished volumes +
        the resume log — starting the same backup again continues where it left
        off (P0.1 resumable). No effect on a restore/verify."""
        with self._lock:
            if self._mode != "backup":
                return
            self._pause_requested = True
        self._stop.set()

    def _cleanup_partial(self, destp: Path) -> None:
        # A cancelled FIRST build vanishes entirely (never mistakable for a good
        # backup); a cancelled incremental REFRESH keeps the previous complete,
        # signed set fully restorable (crash-safe refresh semantics).
        from src.backup.stream_backup import cleanup_cancelled_build

        cleanup_cancelled_build(destp)

    def status(self) -> dict:
        with self._lock:
            return {
                "state": self._state,
                "mode": self._mode,
                "dest": self._dest,
                "progress": dict(self._progress),
                "error": self._error,
                "summary": self._summary,
                "running": self._alive(),
            }


_MANAGER: VolumeBackupManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_volume_manager() -> VolumeBackupManager:
    """Process-wide singleton so the job is visible across requests + in /api/jobs."""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = VolumeBackupManager()
        return _MANAGER
