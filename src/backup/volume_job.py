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
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

# "Progress everywhere" (field-feedback Session A §4 item 2): run_restore's
# internal stage names (src/backup/merge.py) mapped onto the phase-string
# vocabulary _uxVolPhase already understands on the frontend. "merge"/
# "reindex" alias to the EXISTING "merging"/"reindexing" phases (whose own
# granular progress_cb/reindex_progress_cb immediately overwrite this coarse
# ping with real N-of-M data) rather than introducing near-duplicate names;
# every other stage gets its own honest, distinct phase name.
_STAGE_TO_PHASE = {"merge": "merging", "reindex": "reindexing"}


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
            else:
                self._cleanup_partial(destp)
                with self._lock:
                    self._state = "cancelled"
        except Exception as exc:  # noqa: BLE001 - surface the failure, never crash the thread
            _LOG.exception("volume backup failed")
            with self._lock:
                self._state, self._error = "error", str(exc)

    # -- restore ------------------------------------------------------------ #
    def start_restore(
        self,
        src: str,
        passphrase: str,
        *,
        allow_unverified: bool = False,
        corpus_passphrase: str | None = None,
        _restore_fn: Callable[..., dict] | None = None,
    ) -> dict:
        with self._lock:
            self._reap_or_reject()
            srcp = Path(src)
            if not srcp.is_dir():
                raise ValueError(f"{srcp} is not a folder to restore from.")
            self._stop.clear()
            self._pause_requested = False
            self._state, self._mode, self._dest = "running", "restore", str(srcp)
            self._error, self._summary = None, None
            self._progress = {"phase": "verifying"}
            self._thread = threading.Thread(
                target=self._run_restore,
                args=(srcp, passphrase, allow_unverified, corpus_passphrase, _restore_fn),
                daemon=True,
                name="volume-restore",
            )
            self._thread.start()
            return self.status()

    def _run_restore(self, srcp, passphrase, allow_unverified, corpus_passphrase, restore_fn):
        try:
            if restore_fn is not None:
                summary = restore_fn(srcp, passphrase)
                with self._lock:
                    self._state, self._summary = "done", summary
                    self._progress = {"phase": "done"}
                return
            from src.backup.artifact import cleanup_staging, read_volume_backup
            from src.backup.merge import import_cache_mb, run_restore

            # "Import owns the machine" (field-feedback Session A §4, ruled):
            # a large volume restore competes for the single-writer gate and
            # CPU with any in-flight background collection pass, so
            # collection is paused for the restore's WHOLE duration
            # (reassemble + merge + re-index) and resumed afterward. A
            # THROUGHPUT courtesy, never a correctness requirement -- a
            # pause/resume hiccup must never abort or corrupt an otherwise-
            # good restore, so both sides are best-effort.
            from src.scheduler.runner import (
                pause_for_exclusive_operation,
                resume_after_exclusive_operation,
            )

            was_paused = False
            try:
                was_paused = pause_for_exclusive_operation()
            except Exception:  # noqa: BLE001 - the pause is a courtesy, never load-bearing
                _LOG.warning("pausing background collection for the restore failed", exc_info=True)

            try:
                self._on_prog({"phase": "reassembling", "own_the_machine": True})
                staged = read_volume_backup(
                    srcp, passphrase, corpus_passphrase=corpus_passphrase
                )  # verify + parity-recover + reassemble
                try:
                    self._on_prog({"phase": "merging", "own_the_machine": True})

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
                            }
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
                        })

                    from src.analytics.reindex_parallel import all_cores_worker_count

                    def _stage_prog(name: str) -> None:
                        # A coarse "now doing: X" ping for stages B/D/E/G,
                        # which have no callback of their own (§4 item 2).
                        self._on_prog({"phase": _stage_phase_name(name), "own_the_machine": True})

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
                    _reindex_workers = all_cores_worker_count() if was_paused else None
                    _merge_cache_mb = import_cache_mb() if was_paused else None

                    report = run_restore(
                        staged,
                        commit=True,
                        allow_unverified=allow_unverified,
                        progress_cb=_merge_prog,
                        reindex_progress_cb=_reindex_prog,
                        stage_progress_cb=_stage_prog,
                        reindex_workers=_reindex_workers,
                        merge_cache_mb=_merge_cache_mb,
                    )
                    with self._lock:
                        self._state, self._summary = "done", {"report": report}
                        self._progress = {"phase": "done"}
                finally:
                    cleanup_staging(staged)
            finally:
                try:
                    resume_after_exclusive_operation(was_paused)
                except Exception:  # noqa: BLE001 - the resume is a courtesy, never load-bearing
                    _LOG.warning(
                        "resuming background collection after the restore failed", exc_info=True
                    )
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
            with self._lock:
                self._state, self._error = "error", detail

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
        """Stop a running backup (between volumes) and CLEAN its partial set so it
        can never be mistaken for a good backup. A restore is not interruptible
        mid-merge (the merge is atomic); cancel only affects a build."""
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
