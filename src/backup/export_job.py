"""ONE server-side export job: the corpus volumes, then the large-data copy (R701).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. The export dialog used to chain two jobs from the BROWSER: allocate the
dated folder, start the volume job and poll it, check on the page that it was a finished
backup of this folder, then start the folder copy. A page reload between the two phases
meant the copy never started -- the client's closure that would have started it was gone --
and the folder read «Backup incomplete» (the 2026-09-27 re-walk, J-1). The record written
into the folder made that visible; this module removes the cause. The page starts ONE job
and reads ONE status, and a reload re-attaches to it.

WHAT IT IS. A thin orchestrator over the two managers that already do the work:
:class:`src.backup.volume_job.VolumeBackupManager` and
:class:`src.backup.folder_backup.FolderBackupManager`. It does no I/O of its own beyond the
dated folder and its request record. It waits on each manager IN-PROCESS (no HTTP), with
a bounded wait per turn of its loop, and between the two phases it applies the SAME
data-safety gate the page used to apply (field 2026-07-14), unchanged: the volume job must
be ``done``, in ``backup`` mode, and its destination must resolve to THIS folder. If not,
the folder phase never starts and the export ends ``failed`` with a named reason -- a
partial backup must never be followed by a step that makes it look complete.

THE PASSPHRASE (a non-negotiable). It is held only until the volumes phase has STARTED --
in a one-slot holder the worker empties, never in the background job's kwargs (those live
as long as the thread) -- and is never written to the request record, the status, a log,
an exception text or argv. A failure in the one function that holds it reaches the record
only through :mod:`src.monitoring.secret_scrub`. The status carries phase names, counts and
the folder; never the request body. Resuming the volumes phase asks for the passphrase
again; the folder phase needs none.

THE RECORD IS THE RESUME CURSOR. ``oo-export-request.json`` names the phase the export is
in (:func:`src.backup.export_folder.update_export_phase`). Pause in either phase and resume
continues in the SAME dated folder: a resume never allocates. A process restart kills the
job and nothing restarts it (that would need the passphrase, and an export is never silent):
the reopened panel reads the record and offers «Resume export».

STOPPING. Registered as a :class:`~src.jobs.background.BackgroundJob` kind, so the task
manager lists one export row and :func:`~src.jobs.background.stop_all_jobs` (R689) stops it
on the app's shutdown: a stop asked by a shutdown PAUSES the running phase (the volumes and
the copied files are kept, the record names the phase); a stop asked from the task manager's
Cancel cancels it. Not ``is_writer``: it reads the corpus. A restore REFUSES while it runs
(R712, :func:`src.backup.merge.export_refusal`), because switching the corpus under an export
that is reading it is wrong in both directions.

The two older start routes (``/v2/volumes/start``, ``/folder/start``) stay, unchanged and
with the guards they have today, for the advanced panel only (R713); the main export dialog
uses only this job.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from src.backup.export_folder import (
    UNFINISHED_PHASES,
    ExportFolderError,
    allocate_export_folder,
    is_export_folder_name,
    read_export_request,
    update_export_phase,
    write_export_request,
)
from src.jobs.background import BackgroundJob, register_job, stop_all_count
from src.monitoring.secret_scrub import exception_text

_LOG = logging.getLogger(__name__)

KIND = "backup-export"
#: The task manager's row label; translated by the page like every registry label.
LABEL = "Backup export"

PHASE_VOLUMES = "volumes"
PHASE_FOLDER = "folder"

#: One turn of the wait loop: how long the orchestrator waits on a manager before it
#: looks again. A pause or a cancel wakes it at once.
_POLL_S = 0.1
#: How long a phase may take to honour a pause or a cancel before the export stops
#: waiting for it and says so. The volume job stops between volumes and the copy between
#: files, so this is generous; it bounds the wait rather than describing a normal stop.
_STOP_WAIT_S = 60.0

#: The data-safety gate's refusal (field 2026-07-14), the sentence the page used to throw.
UNCONFIRMED = (
    "The corpus backup could not be confirmed — aborting before the large-data files so you "
    "never get a partial backup that looks complete."
)
NEEDS_PASSPHRASE = "Resuming the corpus backup needs the passphrase again."
NOTHING_TO_RESUME = "Nothing to resume: this export is not paused or unfinished."


class ExportJobManager:
    """ONE export at a time, from the dated folder to the last copied file."""

    def __init__(self, *, volume_manager: Any = None, folder_manager: Any = None) -> None:
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._vol_override = volume_manager
        self._fold_override = folder_manager
        self._job = BackgroundJob("backup-export", LABEL, self._worker, cancellable=True)
        self._state = "idle"  # idle | running | paused | done | failed | cancelled
        self._phase: str | None = None
        self._phases: list[str] = []
        self._dest: str | None = None
        self._request: dict[str, Any] = {}
        self._reason: str | None = None
        self._error: str | None = None
        self._stop_asked: str | None = None  # "pause" | "cancel"
        self._stop_seq = 0
        #: The passphrase, for the volumes phase only: emptied by the worker the moment that
        #: phase has started (or the export ends without starting it).
        self._secret: list[str] = []
        #: Test seams handed to the managers (the volume job's ``_backup_fn``, the folder
        #: job's ``_items`` / ``_targets``), kept for a resume of the same folder.
        self._seams: dict[str, Any] = {}
        self._started_at: float | None = None

    # -- the two managers ---------------------------------------------------- #
    def _vol(self) -> Any:
        if self._vol_override is not None:
            return self._vol_override
        from src.backup.volume_job import get_volume_manager

        return get_volume_manager()

    def _fold(self) -> Any:
        if self._fold_override is not None:
            return self._fold_override
        from src.backup.folder_backup import get_folder_manager

        return get_folder_manager()

    def live(self) -> bool:
        """Whether an export is running now (its worker is alive)."""
        with self._lock:
            return self._state == "running" or self._job._alive()

    # -- start / resume ------------------------------------------------------ #
    def start(
        self,
        parent: str,
        *,
        corpus: bool,
        categories: list[str] | None,
        inside: bool = False,
        passphrase: str = "",
        verify_after_write: bool = True,
        include_newsletters: bool = True,
        _backup_fn: Any = None,
        _items: Any = None,
        _targets: Any = None,
    ) -> dict:
        """Allocate the dated folder, record the request and run the export.

        ValueError for a request that cannot run (nothing chosen, no passphrase for a
        corpus, an unusable destination); RuntimeError while an export already runs.
        """
        from src.backup.folder_backup import _CATEGORIES

        cats: list[str] = []
        for c in categories or []:
            if c in _CATEGORIES and c not in cats:
                cats.append(c)
        want_corpus = bool(corpus)
        inside = bool(inside) and want_corpus and bool(cats)
        if not want_corpus and not cats:
            raise ValueError("Choose at least one thing to back up.")
        if want_corpus and not passphrase:
            raise ValueError("the corpus backup is always encrypted: a passphrase is required")
        with self._lock:
            if self.live():
                raise RuntimeError("A backup export is already running.")
            try:
                dest = allocate_export_folder(parent)
            except ExportFolderError as exc:
                raise ValueError(str(exc)) from None
            phases = ([PHASE_VOLUMES] if want_corpus else []) + ([PHASE_FOLDER] if cats and not inside else [])
            request = {
                "corpus": want_corpus,
                "categories": cats,
                "inside": inside,
                "verify_after_write": bool(verify_after_write),
                "include_newsletters": bool(include_newsletters),
            }
            write_export_request(
                dest, corpus=want_corpus, categories=cats, inside=inside,
                phase=phases[0], verify_after_write=bool(verify_after_write),
            )
            seams = {"_backup_fn": _backup_fn, "_items": _items, "_targets": _targets}
            return self._begin(dest, phases, request, passphrase if want_corpus else "", seams)

    def resume(
        self,
        folder: str | None = None,
        *,
        passphrase: str = "",
        verify_after_write: bool | None = None,
    ) -> dict:
        """Continue a paused or unfinished export IN ITS OWN FOLDER, from the phase its record names.

        ``folder`` is the dated folder (after a restart the page names it); left out, the
        export this process last ran. Never allocates. ValueError when the folder is not an
        export with a record, or the volumes phase is to be resumed without the passphrase
        (:data:`NEEDS_PASSPHRASE`); RuntimeError while one runs, or when nothing is left.
        """
        with self._lock:
            if self.live():
                raise RuntimeError("A backup export is already running.")
            target = folder or self._dest
            if not target:
                raise RuntimeError(NOTHING_TO_RESUME)
            dest = Path(target)
            if not is_export_folder_name(dest.name) or not dest.is_dir():
                raise ValueError(f"{dest} is not a dated export folder.")
            req = read_export_request(dest)
            if req is None:
                raise ValueError(
                    f"{dest} carries no export request, so what is left to do there is not known."
                )
            phase = _resume_phase(dest, req)
            if phase is None:
                raise RuntimeError(NOTHING_TO_RESUME)
            owed = [] if req.get("inside") else list(req.get("categories") or [])
            phases = [PHASE_VOLUMES] + ([PHASE_FOLDER] if owed else []) if phase == PHASE_VOLUMES else [PHASE_FOLDER]
            if phase == PHASE_VOLUMES and not passphrase:
                raise ValueError(NEEDS_PASSPHRASE)
            same = self._dest is not None and _same_path(self._dest, dest)
            verify = verify_after_write
            if verify is None:
                verify = req.get("verify_after_write")
            request = {
                "corpus": bool(req.get("corpus")),
                "categories": list(req.get("categories") or []),
                "inside": bool(req.get("inside")),
                "verify_after_write": True if verify is None else bool(verify),
                "include_newsletters": bool(self._request.get("include_newsletters", True)) if same else True,
            }
            update_export_phase(dest, phase)
            seams = dict(self._seams) if same else {}
            return self._begin(dest, phases, request, passphrase if phase == PHASE_VOLUMES else "", seams)

    def _begin(self, dest: Path, phases: list[str], request: dict, passphrase: str, seams: dict) -> dict:
        """Set the job up and start its worker. Call under ``self._lock``."""
        register_job(self._job)  # (re)registered: the registry is the task manager's and the shutdown's list
        self._dest = str(dest)
        self._phases = list(phases)
        self._phase = phases[0] if phases else None
        self._request = request
        self._reason = None
        self._error = None
        self._stop_asked = None
        self._wake.clear()
        self._secret = [passphrase] if passphrase and PHASE_VOLUMES in phases else []
        self._seams = seams
        self._stop_seq = stop_all_count()
        self._started_at = time.time()
        self._state = "running"
        try:
            self._job.start()
        except Exception as exc:
            self._secret = []
            self._state = "failed"
            self._reason = "not-started"
            self._error = f"{type(exc).__name__}: the export could not start its worker"
            raise
        return self.status()

    # -- controls ------------------------------------------------------------ #
    def pause(self) -> dict:
        """Pause the running phase (kept on the drive; Resume continues it in this folder)."""
        with self._lock:
            if self.live():
                self._stop_asked = self._stop_asked or "pause"
                self._wake.set()
        return self.status()

    def cancel(self) -> dict:
        """Cancel the running phase. A cancelled corpus phase removes its partial volume set,
        as the volume job's own cancel always has."""
        with self._lock:
            if self.live():
                self._stop_asked = "cancel"
                self._wake.set()
        return self.status()

    # -- the worker ---------------------------------------------------------- #
    def _worker(self, ctx: Any) -> dict:
        try:
            for phase in list(self._phases):
                with self._lock:
                    self._phase = phase
                update_export_phase(self._dest or "", phase)
                ended = self._run_volumes(ctx) if phase == PHASE_VOLUMES else self._run_folder(ctx)
                if ended:
                    return {"state": self._state}
                asked = self._stop_wanted(ctx)
                if asked and phase != self._phases[-1]:
                    # A pause or a cancel that arrived as a phase ended takes effect at the
                    # boundary: the next phase never starts.
                    nxt = self._phases[self._phases.index(phase) + 1]
                    self._end_stopped(asked, nxt)
                    return {"state": self._state}
            update_export_phase(self._dest or "", "done")
            with self._lock:
                self._state = "done"
                self._phase = None
            return {"state": "done"}
        except Exception as exc:  # noqa: BLE001 - the export ends failed; the class only (a passphrase may have been in play)
            self._secret = []
            _LOG.warning("backup export ended on an internal error (%s)", type(exc).__name__)
            with self._lock:
                self._state = "failed"
                self._reason = "internal"
                self._error = f"{type(exc).__name__}: the export stopped on an internal error"
            return {"state": "failed"}
        finally:
            self._secret = []

    def _run_volumes(self, ctx: Any) -> bool:
        """The corpus phase, then the data-safety gate. True when the export ended here."""
        vol = self._vol()
        dest = self._dest or ""
        req = self._request
        pw = self._secret.pop() if self._secret else ""
        self._secret = []
        if not pw:
            return self._fail("passphrase-missing", NEEDS_PASSPHRASE)
        try:
            vol.start_backup(
                dest,
                pw,
                include_newsletters=bool(req.get("include_newsletters", True)),
                include_blobs=list(req.get("categories") or []) if req.get("inside") else None,
                verify_after_write=bool(req.get("verify_after_write", True)),
                _backup_fn=self._seams.get("_backup_fn"),
            )
        except Exception as exc:  # noqa: BLE001 - a refusal is the export's failure, written without the passphrase
            text = exception_text(exc, pw, typed=False)
            pw = ""
            return self._fail("volumes-refused", f"The corpus backup did not start: {text}")
        pw = ""  # the volumes phase has started: this orchestrator holds no passphrase from here on
        st = self._wait(ctx, vol)
        if st is None:
            return self._fail("stop-timeout", "The corpus backup did not stop in time.")
        state = st.get("state")
        if state == "paused":
            return self._end_stopped("pause", PHASE_VOLUMES)
        if state == "cancelled":
            return self._end_stopped("cancel", PHASE_VOLUMES)
        if state == "error":
            return self._fail("volumes-error", f"The corpus backup failed: {st.get('error') or 'no reason was recorded'}")
        # THE DATA-SAFETY GATE, moved here from the page unchanged: done, backup, THIS folder.
        if not (state == "done" and st.get("mode") == "backup" and st.get("dest") and _same_path(str(st["dest"]), dest)):
            return self._fail("volumes-unconfirmed", UNCONFIRMED)
        return False

    def _run_folder(self, ctx: Any) -> bool:
        """The large-data copy into the same folder. True when the export ended here."""
        fold = self._fold()
        dest = self._dest or ""
        try:
            fold.start(
                dest,
                list(self._request.get("categories") or []),
                _items=self._seams.get("_items"),
                _targets=self._seams.get("_targets"),
            )
        except (ValueError, RuntimeError) as exc:
            return self._fail("folder-refused", f"The large-data copy did not start: {exception_text(exc, typed=False)}")
        st = self._wait(ctx, fold)
        if st is None:
            return self._fail("stop-timeout", "The large-data copy did not stop in time.")
        state = st.get("state")
        if state == "paused":
            return self._end_stopped("pause", PHASE_FOLDER)
        if state == "cancelled":
            return self._end_stopped("cancel", PHASE_FOLDER)
        if state != "done":
            return self._fail("folder-error", f"The large-data copy failed: {st.get('error') or 'no reason was recorded'}")
        return False

    def _stop_wanted(self, ctx: Any) -> str | None:
        """``pause`` or ``cancel`` when a stop is asked: the panel's, or the job registry's.

        A registry stop during a shutdown (``stop_all_jobs``) PAUSES -- the work is kept and
        the record names the phase to resume; any other registry stop is the task manager's
        Cancel."""
        with self._lock:
            if self._stop_asked:
                return self._stop_asked
            if ctx.stopping:
                return "pause" if stop_all_count() != self._stop_seq else "cancel"
            return None

    def _wait(self, ctx: Any, mgr: Any) -> dict | None:
        """Wait IN-PROCESS for ``mgr``'s job to end; the final status, or None when a stop
        was asked and not honoured within :data:`_STOP_WAIT_S`. Bounded per turn."""
        asked: str | None = None
        deadline = 0.0
        while True:
            st = mgr.status()
            if st.get("state") != "running" and not st.get("running"):
                break
            if asked is None:
                asked = self._stop_wanted(ctx)
                if asked is not None:
                    deadline = time.monotonic() + _STOP_WAIT_S
                    if asked == "cancel":
                        mgr.cancel()
                    else:
                        mgr.pause()
            elif time.monotonic() > deadline:
                return None
            self._wake.wait(_POLL_S)
            self._wake.clear()
        return dict(st)

    # -- endings -------------------------------------------------------------- #
    def _fail(self, reason: str, text: str) -> bool:
        _LOG.warning("backup export failed: %s", reason)
        with self._lock:
            self._state = "failed"
            self._reason = reason
            self._error = text
        return True

    def _end_stopped(self, how: str, phase: str) -> bool:
        if how == "cancel":
            update_export_phase(self._dest or "", "cancelled")
            with self._lock:
                self._state = "cancelled"
                self._phase = phase
            return True
        update_export_phase(self._dest or "", phase)
        with self._lock:
            self._state = "paused"
            self._phase = phase
        return True

    # -- status ---------------------------------------------------------------- #
    def status(self) -> dict:
        """Phase names, counts and the folder. Never the request body: no secret is here."""
        with self._lock:
            phase, dest, state = self._phase, self._dest, self._state
            out: dict[str, Any] = {
                "kind": KIND,
                "mode": "backup",
                "state": state,
                "running": state == "running",
                "phase": phase,
                "phases": list(self._phases),
                "dest": dest,
                "parent": str(Path(dest).parent) if dest else None,
                "folder": Path(dest).name if dest else None,
                "requested": {
                    "corpus": bool(self._request.get("corpus")),
                    "categories": list(self._request.get("categories") or []),
                    "inside": bool(self._request.get("inside")),
                },
                "reason": self._reason,
                "error": self._error,
                "needs_passphrase": state in ("paused", "failed") and phase == PHASE_VOLUMES,
                "started_at": self._started_at,
            }
        out["progress"] = self._phase_progress(phase, dest)
        return out

    def _phase_progress(self, phase: str | None, dest: str | None) -> dict:
        """The running phase's own progress counts, only when that manager is on THIS folder."""
        if not phase or not dest:
            return {}
        try:
            st = self._vol().status() if phase == PHASE_VOLUMES else self._fold().status()
        except Exception:  # noqa: BLE001 - a status that cannot be read is no progress
            return {}
        if st.get("mode") != "backup" or not st.get("dest") or not _same_path(str(st["dest"]), dest):
            return {}
        prog = st.get("progress")
        return dict(prog) if isinstance(prog, dict) else {}


def _same_path(a: str | Path, b: str | Path) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def _resume_phase(dest: Path, req: dict[str, Any]) -> str | None:
    """The phase a resume continues: the record's cursor, or -- for a record written before
    the export was one job -- what the folder shows is still owed."""
    phase = req.get("phase")
    if phase in UNFINISHED_PHASES:
        return str(phase)
    if phase is not None:
        return None  # done or cancelled
    from src.backup.export_summary import _folder_manifest, _volume_manifest

    if req.get("corpus") and _volume_manifest(dest) is None:
        return PHASE_VOLUMES
    owed = [] if req.get("inside") else list(req.get("categories") or [])
    if owed and _folder_manifest(dest) is None:
        return PHASE_FOLDER
    return None


_MANAGER: ExportJobManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_export_manager() -> ExportJobManager:
    """Process-wide singleton, so a reloaded page re-attaches to the export."""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = ExportJobManager()
        return _MANAGER


def running_export_label() -> str | None:
    """The export's label while one runs (R712: a restore refuses and names it), else None. Never raises,
    and never creates the manager."""
    try:
        m = _MANAGER
        return LABEL if (m is not None and m.live()) else None
    except Exception:  # noqa: BLE001 - unreadable: named, as running_writer_jobs names an unreadable job
        return LABEL
