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

STOPPING. A stop is forwarded to the running phase and the export reads ``stopping``
until that phase's job has really ended -- however long it takes, since until then it is
still writing into the folder -- and then ``paused`` or ``cancelled``. A Cancel outranks a
Pause, and a paused export can be cancelled.

Registered as a :class:`~src.jobs.background.BackgroundJob` kind, so the task manager
lists one export row and :func:`~src.jobs.background.stop_all_jobs` (R689) stops it
on the app's shutdown: a stop asked by a shutdown PAUSES the running phase (the volumes and
the copied files are kept, the record names the phase); a stop asked from the task manager's
Cancel cancels it. Not ``is_writer``: it reads the corpus. A restore REFUSES while it runs
(R712, :func:`src.backup.merge.export_refusal`), because switching the corpus under an export
that is reading it is wrong in both directions -- and an export refuses to start or
resume while a restore runs (:data:`RESTORE_RUNNING`).

The two older start routes (``/v2/volumes/start``, ``/folder/start``) stay, unchanged and
with the guards they have today, for the advanced panel only (R713); the main export dialog
uses only this job.
"""

from __future__ import annotations

import logging
import os
import stat
import threading
import time
from pathlib import Path
from typing import Any

from src.backup import restore_marker
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
from src.monitoring.secret_scrub import record_text

_LOG = logging.getLogger(__name__)

KIND = "backup-export"
#: The task manager's row label; translated by the page like every registry label.
LABEL = "Backup export"

PHASE_VOLUMES = "volumes"
PHASE_FOLDER = "folder"

#: One turn of the wait loop: how long the orchestrator waits on a manager before it
#: looks again. A pause or a cancel wakes it at once. There is NO overall deadline on a
#: stop: a phase that has been asked to stop and is still running is still writing into
#: the folder, so the export stays ``stopping`` -- live, and refusing a restore (R712) --
#: until that phase's own job has ended, and then settles as ``paused`` or ``cancelled``.
#: (A 60 s cut-off used to end the export ``failed`` while the phase ran on underneath.)
_POLL_S = 0.1

# Every sentence the export writes as its OWN error or refusal is one of these fixed
# strings, and the page translates each one whole (ooServerText in app-core.js). A
# manager's own message (the volume job's, the folder copy's) is passed through
# UNCHANGED, never prefixed, with the phase in a separate field (``error_phase``), so
# the page's whole-message rules still recognise it -- the wrong-passphrase sentence
# among them.
#: The data-safety gate's refusal (field 2026-07-14), the sentence the page used to throw.
UNCONFIRMED = (
    "The corpus backup could not be confirmed — aborting before the large-data files so you "
    "never get a partial backup that looks complete."
)
#: The large-data phase's job is not the one this export started (an advanced-panel copy
#: started in its place, or into another folder): the export does not claim it.
FOLDER_UNCONFIRMED = (
    "The large-data copy could not be confirmed as this export's own, so this export does not "
    "count it as done."
)
NEEDS_PASSPHRASE = "Resuming the corpus backup needs the passphrase again."
NOTHING_TO_RESUME = "Nothing to resume: this export is not paused or unfinished."
ALREADY_RUNNING = "A backup export is already running."
#: R712 the other way round: an export does not start while a restore runs.
RESTORE_RUNNING = (
    "A restore is in progress, so the export did not start: it would read a corpus that is "
    "being switched. Let the restore finish, then export again."
)
NO_CATEGORIES = (
    "This export's record names no large-data category this app knows, so there is nothing to copy."
)
NOT_AN_EXPORT_FOLDER = "This folder is not a dated export folder."
NO_RECORD = "This folder carries no export request, so what is left to do there is not known."
INTERNAL = "The export stopped on an internal error."
INTERRUPTED = "The export stopped unexpectedly before it finished."

#: The states in which the export is live: a phase is running, or has been asked to stop
#: and has not stopped yet.
_LIVE_STATES = ("running", "stopping")


class ExportJobManager:
    """ONE export at a time, from the dated folder to the last copied file."""

    def __init__(self, *, volume_manager: Any = None, folder_manager: Any = None) -> None:
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._vol_override = volume_manager
        self._fold_override = folder_manager
        self._job = BackgroundJob("backup-export", LABEL, self._worker, cancellable=True)
        self._state = "idle"  # idle | running | stopping | paused | done | failed | cancelled
        self._phase: str | None = None
        self._phases: list[str] = []
        self._dest: str | None = None
        self._request: dict[str, Any] = {}
        self._reason: str | None = None
        self._error: str | None = None
        self._error_phase: str | None = None
        self._stop_asked: str | None = None  # "pause" | "cancel"
        self._stop_seq = 0
        #: The passphrase, for the volumes phase only: emptied by the worker the moment that
        #: phase has started (or the export ends without starting it).
        self._secret: list[str] = []
        #: Test seams handed to the managers (the volume job's ``_backup_fn``, the folder
        #: job's ``_items`` / ``_targets``), kept for a resume of the same folder.
        self._seams: dict[str, Any] = {}
        self._started_at: float | None = None
        #: The ``started_at`` the running phase's manager answered its start with: the
        #: identity of THAT job, so a later status of a different job is never taken for it.
        self._sub_started: float | None = None

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
        """Whether an export is running now: a phase runs, or is stopping, or the worker is alive."""
        with self._lock:
            return self._state in _LIVE_STATES or self._job._alive()

    def _restore_running(self) -> bool:
        """Whether a restore runs now (R712 the other way round): the shared marker every
        restore path enters (:mod:`src.backup.restore_marker`), then -- for the window before
        a worker has entered it -- the import queue and the two managers' own restore modes.
        An unreadable one counts as running."""
        if restore_marker.restore_in_progress():
            return True  # every restore path, the synchronous single-file one included
        try:
            from src.backup import import_queue

            q = import_queue._MANAGER
            if q is not None and getattr(q, "_state", None) == "running":
                return True
            for mgr in (self._vol(), self._fold()):
                st = mgr.status()
                if st.get("mode") == "restore" and (st.get("running") or st.get("state") == "running"):
                    return True
        except Exception:  # noqa: BLE001 - an unknown answer is not a go-ahead
            return True
        return False

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
        lanes: bool = False,
        _backup_fn: Any = None,
        _items: Any = None,
        _targets: Any = None,
    ) -> dict:
        """Allocate the dated folder, record the request and run the export.

        ValueError for a request that cannot run (nothing chosen, no passphrase for a
        corpus, an unusable destination); RuntimeError while an export already runs, or
        while a restore runs (:data:`RESTORE_RUNNING`).
        """
        cats = _known_categories(categories)
        want_corpus = bool(corpus)
        inside = bool(inside) and want_corpus and bool(cats)
        # R729: the living-source stores ride inside the corpus artifact, so only with it.
        lanes = bool(lanes) and want_corpus
        if not want_corpus and not cats:
            raise ValueError("Choose at least one thing to back up.")
        if want_corpus and not passphrase:
            raise ValueError("the corpus backup is always encrypted: a passphrase is required")
        # restore_marker.LOCK first (R712): the check and going live are one step against a
        # restore's entry into its marker, so neither can slip past the other.
        with restore_marker.LOCK, self._lock:
            if self.live():
                raise RuntimeError(ALREADY_RUNNING)
            if self._restore_running():
                raise RuntimeError(RESTORE_RUNNING)
            try:
                dest = allocate_export_folder(parent)
            except ExportFolderError as exc:
                raise ValueError(record_text(exc, passphrase, typed=False)) from None
            phases = ([PHASE_VOLUMES] if want_corpus else []) + ([PHASE_FOLDER] if cats and not inside else [])
            request = {
                "corpus": want_corpus,
                "categories": cats,
                "inside": inside,
                "lanes": lanes,
                "verify_after_write": bool(verify_after_write),
                "include_newsletters": bool(include_newsletters),
            }
            write_export_request(
                dest, corpus=want_corpus, categories=cats, inside=inside,
                phase=phases[0], verify_after_write=bool(verify_after_write), lanes=lanes,
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
        """Continue a paused or unfinished export IN ITS OWN FOLDER.

        ``folder`` is the dated folder (after a restart the page names it); left out, the
        export this process last ran. Never allocates. The phase is the one the record
        names; for a record that says ``done`` or ``cancelled`` (or none) but whose folder
        still lacks the large-data files it asked for, the large-data phase into the same
        folder (:func:`_resume_plan`). ValueError when the folder is not an export with a
        record, its record names no known category to copy (:data:`NO_CATEGORIES`), or the
        volumes phase is to be resumed without the passphrase (:data:`NEEDS_PASSPHRASE`);
        RuntimeError while one runs, while a restore runs, or when nothing is left.
        """
        # The FOLDER is read before any lock is taken: it sits on a drive anyone may write
        # to, and a read that blocks (a FIFO planted as a manifest) must hang this request
        # alone, never every restore and status call waiting on the locks below. Then, under
        # them, the record is read again and must say the same.
        with self._lock:
            target = folder or self._dest
        if not target:
            raise RuntimeError(NOTHING_TO_RESUME)
        dest = Path(target)
        if not is_export_folder_name(dest.name) or not dest.is_dir():
            raise ValueError(NOT_AN_EXPORT_FOLDER)
        req = read_export_request(dest)  # its categories are the known ones only; never blocks
        if req is None:
            raise ValueError(NO_RECORD)
        plan = _resume_plan(dest, req)
        # restore_marker.LOCK first (R712): the check and going live are one step against a
        # restore's entry into its marker, so neither can slip past the other.
        with restore_marker.LOCK, self._lock:
            if self.live():
                raise RuntimeError(ALREADY_RUNNING)
            if self._restore_running():
                raise RuntimeError(RESTORE_RUNNING)
            if read_export_request(dest) != req:
                raise RuntimeError(NOTHING_TO_RESUME)  # the record moved under us: read it again from the start
            if plan is None:
                raise RuntimeError(NOTHING_TO_RESUME)
            phase, owed = plan
            if phase == PHASE_FOLDER and not owed:
                raise ValueError(NO_CATEGORIES)
            phases = [PHASE_VOLUMES] + ([PHASE_FOLDER] if owed else []) if phase == PHASE_VOLUMES else [PHASE_FOLDER]
            if phase == PHASE_VOLUMES and not passphrase:
                raise ValueError(NEEDS_PASSPHRASE)
            same = self._dest is not None and _same_path(self._dest, dest)
            verify = verify_after_write
            if verify is None:
                verify = req.get("verify_after_write")
            request = {
                "corpus": bool(req.get("corpus")),
                "categories": list(req.get("categories") or []) if phase == PHASE_VOLUMES else list(owed),
                "inside": bool(req.get("inside")) and phase == PHASE_VOLUMES,
                "lanes": bool(req.get("lanes")) and phase == PHASE_VOLUMES,
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
        self._error_phase = None
        self._stop_asked = None
        self._sub_started = None
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
            self._error = INTERNAL
            _LOG.warning("backup export could not start its worker (%s)", type(exc).__name__)
            raise
        return self.status()

    # -- controls ------------------------------------------------------------ #
    def pause(self) -> dict:
        """Pause the running phase (kept on the drive; Resume continues it in this folder).
        A Cancel already asked outranks it."""
        with self._lock:
            if self._state in _LIVE_STATES:
                self._stop_asked = self._stop_asked or "pause"
                self._wake.set()
        return self.status()

    def cancel(self, folder: str | None = None) -> dict:
        """Cancel the export. While a phase runs (or is stopping on a Pause), the LAST
        explicit request wins and a Cancel outranks a Pause: the running phase is
        cancelled, and a corpus phase removes its partial volume set, as the volume job's
        own cancel always has.

        An export that is NOT running -- paused, or failed, here or (``folder``) after a
        restart, read from its record -- is cancelled here and now, never through a flag a
        worker may already have stopped reading: its partial volumes are removed the same
        way and its record says ``cancelled``, so «Resume export» is no longer offered for
        it. Large-data files already copied stay."""
        with self._lock:
            mine = folder is None or (self._dest is not None and _same_path(folder, self._dest))
            if mine and self._state in _LIVE_STATES:
                # The live export -- however its folder is spelled -- is cancelled through the
                # job, never by rewriting its record from the {dir} path under the running worker.
                self._stop_asked = "cancel"
                self._wake.set()
                return self.status()
            target = folder or self._dest
            if target:
                self._cancel_stopped(Path(target), mine)
        return self.status()

    def _cancel_stopped(self, dest: Path, mine: bool) -> None:
        """Cancel an export that is not running, from its record. Call under ``self._lock``."""
        if not is_export_folder_name(dest.name) or not dest.is_dir():
            return
        req = read_export_request(dest)
        phase = req.get("phase") if req else None
        if mine and self._state in ("paused", "failed") and self._phase:
            phase = self._phase
        if phase not in UNFINISHED_PHASES:
            return
        self._cancel_paused(phase, str(dest))
        update_export_phase(dest, "cancelled")
        self._forget_manager_pause(phase, str(dest))
        if mine and self._state in ("paused", "failed"):
            self._state = "cancelled"
            self._phase = phase

    def _forget_manager_pause(self, phase: str | None, dest: str) -> None:
        """The phase's own manager still reads ``paused`` on this folder after the export is
        cancelled, and the advanced panel would offer to resume it: it is told the job was
        cancelled. Only the manager's job on THIS folder, and only while it is paused."""
        try:
            mgr = self._vol() if phase == PHASE_VOLUMES else self._fold() if phase == PHASE_FOLDER else None
            forget = getattr(mgr, "forget_paused", None)
            if forget is not None:
                forget(dest)
        except Exception as exc:  # noqa: BLE001 - the class only; the export still ends cancelled
            _LOG.warning("backup export: the phase's paused job could not be closed (%s)", type(exc).__name__)

    def _cancel_paused(self, phase: str | None, dest: str) -> None:
        """A paused corpus phase's partial volumes are removed on a cancel, as a running
        one's are; the large-data files are not (nothing about them is misleading)."""
        if phase != PHASE_VOLUMES:
            return
        try:
            if self._vol().status().get("running"):
                return  # another volume job is at work: not this export's to clean
            from src.backup.volumes import MANIFEST_NAME

            if not _regular_or_absent(Path(dest) / MANIFEST_NAME):
                _LOG.warning("backup export: the cancelled folder's volume index is not a regular file; nothing was removed")
                return  # a FIFO or a link planted there: the cleanup would read it
            from src.backup.stream_backup import cleanup_cancelled_build

            cleanup_cancelled_build(Path(dest))
        except Exception as exc:  # noqa: BLE001 - the class only; the export still ends cancelled
            _LOG.warning("backup export: the cancelled corpus phase could not be cleaned (%s)", type(exc).__name__)

    # -- the worker ---------------------------------------------------------- #
    def _worker(self, ctx: Any) -> dict:
        """The export's thread. Whatever ends it -- including a ``BaseException`` the inner
        handler does not take -- it never leaves the export ``running`` or ``stopping``:
        a state stuck there would refuse every restore for the life of the process."""
        try:
            return self._work(ctx)
        finally:
            self._secret = []
            with self._lock:
                if self._state in _LIVE_STATES:
                    self._state = "failed"
                    self._reason = "interrupted"
                    self._error = INTERRUPTED
                    self._error_phase = self._phase

    def _work(self, ctx: Any) -> dict:
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
                    self._end_stopped(asked, nxt, ctx)
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
                self._error = INTERNAL
                self._error_phase = self._phase
            return {"state": "failed"}

    def _run_volumes(self, ctx: Any) -> bool:
        """The corpus phase, then the data-safety gate. True when the export ended here."""
        vol = self._vol()
        dest = self._dest or ""
        req = self._request
        pw = self._secret.pop() if self._secret else ""
        self._secret = []
        asked = self._stop_wanted(ctx)  # read under the lock, right before the phase starts
        if asked:
            pw = ""
            return self._end_stopped(asked, PHASE_VOLUMES, ctx)
        if not pw:
            return self._fail("passphrase-missing", NEEDS_PASSPHRASE, PHASE_VOLUMES)
        try:
            began = vol.start_backup(
                dest,
                pw,
                include_newsletters=bool(req.get("include_newsletters", True)),
                include_blobs=list(req.get("categories") or []) if req.get("inside") else None,
                verify_after_write=bool(req.get("verify_after_write", True)),
                _backup_fn=self._seams.get("_backup_fn"),
                # Passed only when asked for, so a volume job that predates R729 runs as before.
                **({"include_lanes": True} if req.get("lanes") else {}),
            )
        except Exception as exc:  # noqa: BLE001 - a refusal is the export's failure, written without the passphrase
            text = record_text(exc, pw, typed=False)
            pw = ""
            return self._fail("volumes-refused", text, PHASE_VOLUMES)
        pw = ""  # the volumes phase has started: this orchestrator holds no passphrase from here on
        self._note_started(began)
        st = self._wait(ctx, vol)
        if not self._ours(st):
            return self._fail("volumes-unconfirmed", UNCONFIRMED, PHASE_VOLUMES)
        state = st.get("state")
        if state in ("paused", "cancelled"):
            return self._end_phase_stopped(ctx, state, PHASE_VOLUMES)
        if state == "error":
            return self._fail("volumes-error", str(st.get("error") or UNCONFIRMED), PHASE_VOLUMES)
        # THE DATA-SAFETY GATE, moved here from the page unchanged: done, backup, THIS folder
        # -- and now also THIS job (the started_at its start answered with).
        if state != "done":
            return self._fail("volumes-unconfirmed", UNCONFIRMED, PHASE_VOLUMES)
        return False

    def _run_folder(self, ctx: Any) -> bool:
        """The large-data copy into the same folder. True when the export ended here."""
        fold = self._fold()
        dest = self._dest or ""
        cats = _known_categories(self._request.get("categories"))
        if not cats:
            # Never an empty list: the folder job reads "none known" as EVERY category.
            return self._fail("no-categories", NO_CATEGORIES, PHASE_FOLDER)
        # A stop that landed after the last boundary check: the copy never starts, rather
        # than starting and pausing at once. Read under the lock, right before the start.
        asked = self._stop_wanted(ctx)
        if asked:
            return self._end_stopped(asked, PHASE_FOLDER, ctx)
        try:
            began = fold.start(
                dest,
                cats,
                _items=self._seams.get("_items"),
                _targets=self._seams.get("_targets"),
            )
        except (ValueError, RuntimeError) as exc:
            return self._fail("folder-refused", record_text(exc, typed=False), PHASE_FOLDER)
        self._note_started(began)
        st = self._wait(ctx, fold)
        if not self._ours(st):
            return self._fail("folder-unconfirmed", FOLDER_UNCONFIRMED, PHASE_FOLDER)
        state = st.get("state")
        if state in ("paused", "cancelled"):
            return self._end_phase_stopped(ctx, state, PHASE_FOLDER)
        if state != "done":
            return self._fail("folder-error", str(st.get("error") or FOLDER_UNCONFIRMED), PHASE_FOLDER)
        return False

    def _note_started(self, began: Any) -> None:
        with self._lock:
            self._sub_started = began.get("started_at") if isinstance(began, dict) else None

    def _ours(self, st: dict) -> bool:
        """Whether ``st`` is the status of the job THIS export started for its running
        phase: a backup, into this folder, with the ``started_at`` its start answered with.
        A job that is not -- the advanced panel's copy started into the same folder in the
        poll window, say -- is never counted as this export's phase."""
        with self._lock:
            started, dest = self._sub_started, self._dest
        return bool(
            st.get("mode") == "backup"
            and dest
            and st.get("dest")
            and _same_path(str(st["dest"]), dest)
            and started is not None
            and st.get("started_at") == started
        )

    def _stop_wanted(self, ctx: Any) -> str | None:
        """``pause`` or ``cancel`` when a stop is asked: the panel's, or the job registry's.
        A Cancel from either outranks a Pause from either.

        A registry stop during a shutdown (``stop_all_jobs``) PAUSES -- the work is kept and
        the record names the phase to resume; any other registry stop is the task manager's
        Cancel."""
        with self._lock:
            asked = {self._stop_asked}
            if ctx.stopping:
                asked.add("pause" if stop_all_count() != self._stop_seq else "cancel")
        if "cancel" in asked:
            return "cancel"
        return "pause" if "pause" in asked else None

    def _wait(self, ctx: Any, mgr: Any) -> dict:
        """Wait IN-PROCESS for ``mgr``'s job to end, and return its last status.

        Bounded per turn, unbounded overall: a stop is forwarded to the manager (again,
        when a Pause becomes a Cancel) and the export reads ``stopping`` until the job has
        ended. It also ends when the manager's status stops being THIS export's job."""
        forwarded: str | None = None
        while True:
            st = mgr.status()
            if not self._ours(st):
                break
            if st.get("state") != "running" and not st.get("running"):
                break
            asked = self._stop_wanted(ctx)
            if asked is not None and asked != forwarded and forwarded != "cancel":
                forwarded = asked
                with self._lock:
                    self._state = "stopping"
                if asked == "cancel":
                    mgr.cancel()
                else:
                    mgr.pause()
            self._wake.wait(_POLL_S)
            self._wake.clear()
        return dict(st)

    # -- endings -------------------------------------------------------------- #
    def _fail(self, reason: str, text: str, phase: str | None = None) -> bool:
        _LOG.warning("backup export failed: %s", reason)
        with self._lock:
            self._state = "failed"
            self._reason = reason
            self._error = text
            self._error_phase = phase
        return True

    def _end_phase_stopped(self, ctx: Any, state: str, phase: str) -> bool:
        """A phase that ended paused or cancelled. A Cancel asked while it was stopping on a
        Pause still cancels: the last explicit request wins."""
        return self._end_stopped("cancel" if state == "cancelled" else "pause", phase, ctx)

    def _end_stopped(self, how: str, phase: str, ctx: Any) -> bool:
        """End the export paused or cancelled in ``phase``.

        A PAUSE becomes ``paused`` only under the lock, with the stop ask read again at that
        moment: a Cancel that landed while the record was being written (the export read
        ``stopping`` and accepted it) is never lost -- it turns the ending into a cancel.
        A CANCEL always takes the cancel path: a corpus phase's partial volumes are removed
        (also those a PAUSED run left, when a resumed corpus phase is cancelled before it
        starts) and the record says ``cancelled``."""
        dest = self._dest or ""
        if how == "pause":
            update_export_phase(dest, phase)
            with self._lock:
                if self._stop_wanted(ctx) != "cancel":
                    self._state = "paused"
                    self._phase = phase
                    return True
        self._cancel_paused(phase, dest)
        update_export_phase(dest, "cancelled")
        self._forget_manager_pause(phase, dest)
        with self._lock:
            self._state = "cancelled"
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
                "running": state in _LIVE_STATES,
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
                # The phase the error came from, beside it: the error is a manager's own
                # sentence, unprefixed, so the page can still translate it whole.
                "error_phase": self._error_phase,
                "needs_passphrase": state in ("paused", "failed") and phase == PHASE_VOLUMES,
                "started_at": self._started_at,
            }
        out["progress"] = self._phase_progress(phase, dest)
        return out

    def _phase_progress(self, phase: str | None, dest: str | None) -> dict:
        """The running phase's own progress counts, only when that manager runs THIS export's job."""
        if not phase or not dest:
            return {}
        try:
            st = self._vol().status() if phase == PHASE_VOLUMES else self._fold().status()
        except Exception:  # noqa: BLE001 - a status that cannot be read is no progress
            return {}
        if not self._ours(st):
            return {}
        prog = st.get("progress")
        return dict(prog) if isinstance(prog, dict) else {}


def _same_path(a: str | Path, b: str | Path) -> bool:
    """Whether ``a`` and ``b`` are the same folder: by identity on the drive when both exist
    (``os.path.samefile``: a different spelling on a case-insensitive drive is the SAME
    folder), else by their resolved, case-normalised spelling."""
    try:
        if os.path.exists(a) and os.path.exists(b):
            return os.path.samefile(a, b)
        return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))
    except OSError:
        return False


def _regular_or_absent(p: Path) -> bool:
    """Whether ``p`` is absent or a regular file (never a link, a FIFO or a device)."""
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode)


def _known_categories(categories: list[str] | None) -> list[str]:
    """The large-data categories this app knows, in order, once each."""
    from src.backup.folder_backup import _CATEGORIES

    cats: list[str] = []
    for c in categories or []:
        if c in _CATEGORIES and c not in cats:
            cats.append(c)
    return cats


def _resume_plan(dest: Path, req: dict[str, Any]) -> tuple[str, list[str]] | None:
    """The phase a resume continues, and the large-data categories it owes.

    The record's cursor when it names an unfinished phase. Otherwise -- the record says
    ``done`` or ``cancelled``, or predates the cursor -- what the FOLDER shows is still
    owed: a corpus with no ``volumes.json`` (a record with no cursor only: a done or
    cancelled export's corpus is not restarted by a copy button), then large-data files
    with no complete copy's manifest. The folder phase then runs over EVERY category the
    request owes, not only the absent ones: the copy's manifest is rewritten whole by
    each complete pass, so a pass over a subset would drop the rest from it -- while the
    files already there are skipped by size, so only what is missing is actually copied.
    """
    from src.backup.export_summary import _folder_manifest, _volume_manifest, missing_members

    owed = [] if req.get("inside") else _known_categories(req.get("categories"))
    phase = req.get("phase")
    if phase in UNFINISHED_PHASES:
        return str(phase), owed
    miss = missing_members(
        req, corpus_present=_volume_manifest(dest) is not None, copy_done=_folder_manifest(dest) is not None
    )
    if phase is None and miss["corpus"]:
        return PHASE_VOLUMES, owed
    if miss["categories"]:
        return PHASE_FOLDER, owed
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
