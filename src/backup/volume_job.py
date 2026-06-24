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
from pathlib import Path
from typing import Any, Callable

_LOG = logging.getLogger(__name__)


class VolumeBackupManager:
    """ONE volume backup OR restore at a time — you don't run two giant crypto+IO jobs
    concurrently. The destination directory is the durable artifact; a cancelled backup's
    partial volume set is removed so it can never be mistaken for a good backup."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state = "idle"  # idle|running|cancelled|done|error
        self._mode = "backup"  # backup|restore
        self._dest: str | None = None
        self._progress: dict[str, Any] = {}
        self._error: str | None = None
        self._summary: dict[str, Any] | None = None

    def _alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

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
            if self._alive():
                raise RuntimeError("A volume backup/restore is already running.")
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
        _restore_fn: Callable[..., dict] | None = None,
    ) -> dict:
        with self._lock:
            if self._alive():
                raise RuntimeError("A volume backup/restore is already running.")
            srcp = Path(src)
            if not srcp.is_dir():
                raise ValueError(f"{srcp} is not a folder to restore from.")
            self._stop.clear()
            self._state, self._mode, self._dest = "running", "restore", str(srcp)
            self._error, self._summary = None, None
            self._progress = {"phase": "verifying"}
            self._thread = threading.Thread(
                target=self._run_restore,
                args=(srcp, passphrase, allow_unverified, _restore_fn),
                daemon=True,
                name="volume-restore",
            )
            self._thread.start()
            return self.status()

    def _run_restore(self, srcp, passphrase, allow_unverified, restore_fn):
        try:
            if restore_fn is not None:
                summary = restore_fn(srcp, passphrase)
                with self._lock:
                    self._state, self._summary = "done", summary
                    self._progress = {"phase": "done"}
                return
            from src.backup.artifact import cleanup_staging, read_volume_backup
            from src.backup.merge import run_restore

            self._on_prog({"phase": "reassembling"})
            staged = read_volume_backup(srcp, passphrase)  # verify + parity-recover + reassemble
            try:
                self._on_prog({"phase": "merging"})
                report = run_restore(staged, commit=True, allow_unverified=allow_unverified)
                with self._lock:
                    self._state, self._summary = "done", {"report": report}
                    self._progress = {"phase": "done"}
            finally:
                cleanup_staging(staged)
        except Exception as exc:  # noqa: BLE001
            _LOG.exception("volume restore failed")
            with self._lock:
                self._state, self._error = "error", str(exc)

    # -- controls ----------------------------------------------------------- #
    def cancel(self) -> None:
        """Stop a running backup (between volumes). A restore is not interruptible
        mid-merge (the merge is atomic); cancel only affects a build."""
        self._stop.set()

    def _cleanup_partial(self, destp: Path) -> None:
        for pat in ("vol-*.ooenc", "par-*.oopar"):
            for p in destp.glob(pat):
                p.unlink(missing_ok=True)
        (destp / "volumes.json").unlink(missing_ok=True)

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
