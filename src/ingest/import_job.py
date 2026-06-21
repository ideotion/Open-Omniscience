"""
Server-side .eml FOLDER import as a pausable, task-manager-visible job (brief §2.B).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer needs to import a FOLDER of 20 GB+ newsletters (field test 2026-06-20):
the browser file-picker can't select a folder, and a synchronous request would block.
This runs a server-side folder path as a background JOB, mirroring the download managers
(DumpDownloadManager / FolderBackupManager): a worker thread, pause via a stop-event,
resume from a PERSISTED cursor, progress + a rule-of-three ETA, surfaced in /api/jobs.

It is a DB-WRITER job (kind="import"), so it takes the SINGLE-WRITER GATE per batch
commit (via the gated SessionLocal) and arbitrates with the scrape exactly like any
other writer — never a silent collision. ZERO network (local disk read).

RESUME is robust two ways: (1) a small on-disk cursor (the count of files processed,
in stable sorted order) so a resume — even after an APP RESTART — continues instead of
re-scanning a 100k-file folder from zero; and (2) the corpus dedups by content hash, so
even if the folder changed under us a re-processed message is never stored twice.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from src.ingest.email import NEWSLETTER_SOURCE_DOMAINS, ingest_emails

# Files whose bytes are read into memory per ingest call — bounds RAM on a 20 GB+
# folder (we never hold the whole folder in memory). ingest_emails then batches its
# own commits within each chunk.
_FILE_CHUNK = 500
_IMPORT_SOURCE_DOMAIN = NEWSLETTER_SOURCE_DOMAINS[0]  # "newsletters.import.local"
_IMPORT_SOURCE_NAME = "Imported newsletters (.eml)"
_STATE_FILE = "newsletter_import.json"


def _default_session():
    from src.database.session import SessionLocal

    return SessionLocal()


def _import_source(session):
    """The dedicated, DISABLED, filterable .eml import source (created on demand)."""
    from src.database.models import Source

    src = session.query(Source).filter_by(domain=_IMPORT_SOURCE_DOMAIN).first()
    if src is None:
        src = Source(name=_IMPORT_SOURCE_NAME, domain=_IMPORT_SOURCE_DOMAIN, enabled=False)
        session.add(src)
        session.commit()
        session.refresh(src)
    return src


def _eml_files(folder: Path) -> list[Path]:
    """Every ``.eml`` (case-insensitive) under ``folder``, recursively, sorted (the
    stable order the resume cursor counts against)."""
    out = {p.resolve() for p in folder.rglob("*.eml") if p.is_file()}
    out |= {p.resolve() for p in folder.rglob("*.EML") if p.is_file()}
    return sorted(out)


class NewsletterImportManager:
    """ONE pausable server-side .eml folder import at a time. Progress is a CURSOR (the
    count of files processed in sorted order), persisted to ``data_dir()`` so a resume
    survives an app restart; the corpus's content-hash dedup is the correctness net."""

    def __init__(self, *, state_path: Path | None = None) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state = "idle"  # idle|running|paused|done|error|cancelled
        self._folder: str | None = None
        self._files: list[Path] = []
        self._cursor = 0  # next file index to process
        self._tally: dict[str, int] = {}
        self._error: str | None = None
        self._cancelled = False
        self._started_at: float | None = None
        self._session_factory = None  # test seam
        self._state_path_override = state_path
        self._load_persisted()

    # -- persistence -------------------------------------------------------- #
    def _state_path(self) -> Path:
        if self._state_path_override is not None:
            return self._state_path_override
        from src.paths import data_dir

        return data_dir() / _STATE_FILE

    def _save(self) -> None:
        """Persist the resume cursor (best-effort; a write hiccup never breaks import)."""
        try:
            p = self._state_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps(
                    {
                        "folder": self._folder,
                        "cursor": self._cursor,
                        "total": len(self._files),
                        "tally": self._tally,
                        "state": self._state,
                    }
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _clear_state(self) -> None:
        try:
            self._state_path().unlink(missing_ok=True)
        except OSError:
            pass

    def _load_persisted(self) -> None:
        """On first construction (app start), restore an INTERRUPTED import as PAUSED so
        the user can resume it from the task manager / Settings."""
        try:
            raw = self._state_path().read_text(encoding="utf-8")
            d = json.loads(raw)
        except (OSError, ValueError):
            return
        if d.get("state") not in ("running", "paused"):
            return
        folder = d.get("folder")
        if not folder or not Path(folder).is_dir():
            return
        self._folder = folder
        self._files = _eml_files(Path(folder))
        self._cursor = min(int(d.get("cursor") or 0), len(self._files))
        self._tally = dict(d.get("tally") or {})
        self._state = "paused"  # an interrupted run is resumable, never silently lost

    # -- lifecycle ---------------------------------------------------------- #
    def _alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        folder: str,
        *,
        _files: list[Path] | None = None,
        _session_factory=None,
        _cursor: int = 0,
    ) -> dict:
        """Validate the folder + launch the worker. RuntimeError if already running,
        ValueError on a bad folder. ``_cursor`` (resume) is where to continue."""
        with self._lock:
            if self._alive():
                raise RuntimeError("A folder import is already running.")
            p = Path(folder).expanduser()
            if not p.is_dir():
                raise ValueError(f"{p} is not a folder on this machine.")
            files = _files if _files is not None else _eml_files(p)
            self._stop.clear()
            self._cancelled = False
            self._state = "running"
            self._folder = str(p)
            self._files = files
            self._cursor = max(0, min(_cursor, len(files)))
            if _cursor <= 0:
                self._tally = {}
            self._error = None
            self._started_at = time.monotonic()
            self._session_factory = _session_factory
            self._save()
            self._thread = threading.Thread(
                target=self._run, args=(files, _session_factory), daemon=True, name="newsletter-import"
            )
            self._thread.start()
            return self.status()

    def _run(self, files: list[Path], session_factory) -> None:
        try:
            session = (session_factory or _default_session)()
            try:
                source = _import_source(session)
                i = self._cursor
                while i < len(files):
                    if self._stop.is_set():
                        break
                    chunk = files[i : i + _FILE_CHUNK]
                    raws: list[bytes] = []
                    unreadable = 0
                    for fp in chunk:
                        try:
                            raws.append(Path(fp).read_bytes())
                        except OSError:
                            unreadable += 1
                    if raws:
                        tally = ingest_emails(session, source, raws)
                    else:
                        tally = {}
                    i += len(chunk)  # the whole chunk is now processed (readable or not)
                    with self._lock:
                        for k, v in tally.items():
                            self._tally[k] = self._tally.get(k, 0) + int(v)
                        if unreadable:
                            self._tally["unreadable"] = self._tally.get("unreadable", 0) + unreadable
                        self._cursor = i
                        self._save()
                with self._lock:
                    if self._stop.is_set():
                        self._state = "cancelled" if self._cancelled else "paused"
                    else:
                        self._state = "done"
                    self._save()
                    if self._state in ("done", "cancelled"):
                        self._clear_state()
            finally:
                session.close()
        except Exception as exc:  # noqa: BLE001 - surface the failure, never crash the thread
            with self._lock:
                self._state = "error"
                self._error = str(exc)
                self._save()

    def pause(self) -> None:
        self._stop.set()  # the worker stops between chunks; state -> paused (persisted)

    def resume(self) -> dict:
        with self._lock:
            if self._state not in ("paused", "error", "cancelled"):
                raise RuntimeError("Nothing paused to resume.")
            folder, files, sf, cursor = self._folder, list(self._files), self._session_factory, self._cursor
            tally = dict(self._tally)
        if folder is None:
            raise RuntimeError("No previous import to resume.")
        out = self.start(folder, _files=files, _session_factory=sf, _cursor=cursor)
        with self._lock:  # carry the prior tally forward (progress continues)
            self._tally = tally
            self._save()
        return out

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
        self._stop.set()
        if not self._alive():  # already idle/paused — clear the persisted state now
            with self._lock:
                self._state = "cancelled"
                self._clear_state()

    def status(self) -> dict:
        with self._lock:
            total = len(self._files)
            done = self._cursor
            eta_s = None
            if self._started_at is not None and done > 0 and done < total:
                elapsed = max(0.001, time.monotonic() - self._started_at)
                rate = done / elapsed  # files/s (rule of three)
                if rate > 0:
                    eta_s = round((total - done) / rate)
            return {
                "state": self._state,
                "folder": self._folder,
                "files_total": total,
                "files_done": done,
                "percent": round(100 * done / total, 1) if total else 0.0,
                "tally": dict(self._tally),
                "eta_seconds": eta_s,
                "error": self._error,
                "running": self._alive(),
            }


_MANAGER: NewsletterImportManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_import_manager() -> NewsletterImportManager:
    """Process-wide singleton so the job is visible across requests + in /api/jobs."""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = NewsletterImportManager()
        return _MANAGER
