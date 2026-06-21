"""
Server-side .eml FOLDER import as a pausable, task-manager-visible job (brief §2.B).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer needs to import a FOLDER of 20 GB+ newsletters (field test 2026-06-20):
the browser file-picker can't select a folder, and a synchronous request would block.
This runs a server-side folder path as a background JOB, mirroring the download managers
(DumpDownloadManager / FolderBackupManager): a worker thread, pause via a stop-event,
idempotent resume, progress + a rule-of-three ETA, surfaced in /api/jobs.

It is a DB-WRITER job (kind="import"), so it takes the SINGLE-WRITER GATE per batch
commit (via the gated SessionLocal) and arbitrates with the scrape exactly like any
other writer — never a silent collision. ZERO network (local disk read). Resume is
idempotent: the corpus dedups by content hash, and we also remember processed file
paths in-memory so a resume continues progress instead of re-scanning from zero.
"""

from __future__ import annotations

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
    """Every ``.eml`` (case-insensitive) under ``folder``, recursively, sorted."""
    out = {p.resolve() for p in folder.rglob("*.eml") if p.is_file()}
    out |= {p.resolve() for p in folder.rglob("*.EML") if p.is_file()}
    return sorted(out)


class NewsletterImportManager:
    """ONE pausable server-side .eml folder import at a time. In-memory state; the
    corpus (content-hash dedup) is the durable progress — a resume re-imports nothing
    that's already stored, and the processed-paths set keeps progress continuous."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state = "idle"  # idle|running|paused|done|error|cancelled
        self._folder: str | None = None
        self._files: list[Path] = []
        self._done: set[str] = set()  # processed paths (resume + progress)
        self._tally: dict[str, int] = {}
        self._error: str | None = None
        self._cancelled = False
        self._started_at: float | None = None
        self._session_factory = None  # test seam

    def _alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        folder: str,
        *,
        _files: list[Path] | None = None,
        _session_factory=None,
        _done: set[str] | None = None,
    ) -> dict:
        """Validate the folder + launch the worker. RuntimeError if already running,
        ValueError on a bad folder. ``_done`` (resume) is the already-processed set."""
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
            self._done = set(_done) if _done else set()  # set BEFORE the thread reads it
            self._tally = {}  # resume() restores the carried tally after this returns
            self._error = None
            self._started_at = time.monotonic()
            self._session_factory = _session_factory
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
                chunk_raws: list[bytes] = []
                chunk_paths: list[str] = []
                for fp in files:
                    if self._stop.is_set():
                        break
                    key = str(fp)
                    if key in self._done:
                        continue
                    try:
                        chunk_raws.append(Path(fp).read_bytes())
                        chunk_paths.append(key)
                    except OSError:
                        with self._lock:
                            self._done.add(key)
                            self._tally["unreadable"] = self._tally.get("unreadable", 0) + 1
                        continue
                    if len(chunk_raws) >= _FILE_CHUNK:
                        self._ingest_chunk(session, source, chunk_raws, chunk_paths)
                        chunk_raws, chunk_paths = [], []
                if chunk_raws and not self._stop.is_set():
                    self._ingest_chunk(session, source, chunk_raws, chunk_paths)
                with self._lock:
                    if self._stop.is_set():
                        self._state = "cancelled" if self._cancelled else "paused"
                    else:
                        self._state = "done"
            finally:
                session.close()
        except Exception as exc:  # noqa: BLE001 - surface the failure, never crash the thread
            with self._lock:
                self._state = "error"
                self._error = str(exc)

    def _ingest_chunk(self, session, source, raws: list[bytes], paths: list[str]) -> None:
        tally = ingest_emails(session, source, raws)
        with self._lock:
            for k, v in tally.items():
                self._tally[k] = self._tally.get(k, 0) + int(v)
            self._done.update(paths)

    def pause(self) -> None:
        self._stop.set()  # the worker stops between chunks; state -> paused

    def resume(self) -> dict:
        with self._lock:
            if self._state not in ("paused", "error", "cancelled"):
                raise RuntimeError("Nothing paused to resume.")
            folder, files, sf = self._folder, list(self._files), self._session_factory
            done = set(self._done)
            tally = dict(self._tally)
        if folder is None:
            raise RuntimeError("No previous import to resume.")
        out = self.start(folder, _files=files, _session_factory=sf, _done=done)
        with self._lock:  # carry the prior tally forward (progress continues)
            self._tally = tally
        return out

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
        self._stop.set()

    def status(self) -> dict:
        with self._lock:
            total = len(self._files)
            done = len(self._done)
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
