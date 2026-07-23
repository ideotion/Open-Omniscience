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
import logging
import threading
import time
from pathlib import Path

from src.ingest.email import NEWSLETTER_SOURCE_DOMAINS, ingest_emails

_LOG = logging.getLogger("ingest.import_job")

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
        # S3.3/S3.5 (2026-07-23): captured ONCE at the TRUE start of a logical import
        # (never re-captured on a resume -- see start()'s ``if _cursor <= 0`` gate below)
        # so a pause/resume sequence's eventual completion scans/reports EVERY article
        # the WHOLE logical import added, not just the last resume's increment.
        self._quarantine_before_id: int | None = None
        self._quarantine_baseline_attempted = False  # disambiguates "not yet tried" (None,
        # False -> attempt now) from "tried and failed" (None, True -> skip quarantine/
        # report for this whole logical run; NEVER guess a value like 0, which would
        # make Article.id > 0 match every PRE-EXISTING article too)
        self._corpus_before: dict | None = None
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
                        "quarantine_before_id": self._quarantine_before_id,
                        "quarantine_baseline_attempted": self._quarantine_baseline_attempted,
                        "corpus_before": self._corpus_before,
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
        self._quarantine_before_id = d.get("quarantine_before_id")
        self._quarantine_baseline_attempted = bool(d.get("quarantine_baseline_attempted", False))
        self._corpus_before = d.get("corpus_before")
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
                # a genuinely FRESH import (never a resume) starts a NEW logical run --
                # _run() below captures its own before-id/corpus-delta baseline once,
                # fresh, at the true start of THIS import.
                self._quarantine_before_id = None
                self._quarantine_baseline_attempted = False
                self._corpus_before = None
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
                # S3.3/S3.5 (2026-07-23 field-feedback workflow): captured ONCE, at the
                # TRUE start of the WHOLE logical import (self._quarantine_before_id is
                # None only on a genuinely fresh start() -- see start()'s _cursor<=0
                # gate), and PERSISTED across every pause/resume of the same import --
                # never re-captured on a resume. This is what lets a paused-then-resumed
                # run's eventual completion scan/report EVERY article the whole logical
                # import added, not just the last resume's increment (a real gap an
                # earlier fresh-per-_run-call design would have left: articles stored by
                # an EARLIER, paused-before-completion run would otherwise never be
                # auto-screened at all). Best-effort: a snapshot hiccup must never abort
                # an otherwise-good import.
                if not self._quarantine_baseline_attempted:
                    try:
                        from sqlalchemy import func as _func

                        from src.backup.merge import _corpus_snapshot
                        from src.database.models import Article

                        before_id = int(session.query(_func.max(Article.id)).scalar() or 0)
                        before_snap = _corpus_snapshot(session)
                        with self._lock:
                            self._quarantine_before_id = before_id
                            self._corpus_before = before_snap
                            self._quarantine_baseline_attempted = True
                            self._save()
                    except Exception:  # noqa: BLE001 - never abort a good import; NEVER
                        # guess a fallback id (0 would make Article.id > 0 match every
                        # pre-existing article too) -- a failed capture just means the
                        # quarantine/report hook is skipped for this whole logical run.
                        with self._lock:
                            self._quarantine_baseline_attempted = True
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
                if not self._stop.is_set():
                    # A complete import bulk-loaded articles → many small FTS segments;
                    # merge them so search MATCH stays fast (keyword-engine P1.4).
                    from src.database.fts import optimize_after_bulk

                    optimize_after_bulk(session)

                    # S3.3 (import-time screening): scan ONLY the articles added across
                    # the WHOLE logical import (Article.id > self._quarantine_before_id,
                    # captured ONCE at the true start and preserved across every resume
                    # -- never a pre-existing article, and never silently skipping an
                    # earlier paused run's articles either). Skipped entirely if the
                    # baseline capture failed (self._quarantine_before_id stays None) --
                    # NEVER guessed. Best-effort either way: never turns a successful
                    # import into a failure.
                    quarantine_summary: dict | None = None
                    if self._quarantine_before_id is not None:
                        try:
                            from src.analytics.quarantine_job import (
                                default_quarantine_candidates_batch,
                            )
                            from src.database.models import Article as _Article

                            new_ids = [
                                int(a.id)
                                for a in session.query(_Article.id)
                                .filter(_Article.id > self._quarantine_before_id)
                                .all()
                            ]
                            if new_ids:
                                quarantine_summary = default_quarantine_candidates_batch(
                                    session, article_ids=new_ids, write=True
                                )
                        except Exception:  # noqa: BLE001 - never abort a good import
                            _LOG.warning("quarantine scan after the import failed", exc_info=True)

                    # S3.5 (field-feedback A1): persist a standalone, downloadable
                    # JSON+Markdown report for this run -- the newsletter path had NONE
                    # before this (unlike the restore-merge path's DB-column report).
                    # Best-effort.
                    try:
                        from src.backup.import_reports import persist_import_report
                        from src.backup.merge import _corpus_snapshot

                        report: dict = {"kind": "newsletter", "tally": dict(self._tally)}
                        if self._corpus_before is not None:
                            report["corpus_delta"] = {
                                "before": self._corpus_before,
                                "after": _corpus_snapshot(session),
                            }
                        if quarantine_summary is not None:
                            report["quarantine_summary"] = quarantine_summary
                        persist_import_report("newsletter", report)
                    except Exception:  # noqa: BLE001 - never abort a good import
                        _LOG.warning("persisting the newsletter import report failed", exc_info=True)
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
