"""
Retroactive QUARANTINE job.

NAV-SOUP SPECIMEN ruling (2026-07-20) row 5 EXECUTION SCOPE + the 2026-07-23 field-feedback S3.2
sign-off (A2/A3): legacy non-article junk sits in the DB (predating the #659 ingest-door filter
and the PROSE GATE), and "the Slice-4a retroactive QUARANTINE carry-over is what removes it". This
module is the resumable job chassis (mirrors ``ReindexJobManager``: state machine, worker thread,
persisted cursor, batching, progress/ETA, pause/resume/cancel) that runs it.

WRITE IS OPT-IN, DRY-RUN IS THE DEFAULT (the binding S3 execution gate): :func:`default_quarantine_
candidates_batch` takes a ``write: bool = False`` parameter. With ``write=False`` (the default,
byte-identical to the original scaffold's behaviour) it only DETECTS candidates (the #659 URL-shape
rules via ``classify_non_article`` + the opt-in PROSE GATE) and reports them in the batch's tally --
a dry-run count + a bounded id sample, no side effect. With ``write=True`` it ADDITIONALLY stamps
each detected candidate's ``Article.quarantined``/``quarantine_reason``/``quarantine_criteria_
version``/``quarantined_at`` columns -- REVERSIBLE by construction (a stamp, never a delete; nothing
about the row, its keywords, or its provenance is touched otherwise) and idempotent (an
already-quarantined row is skipped, never re-stamped/double-counted).

``QuarantineJobManager`` IS now wired into the app (:func:`get_quarantine_manager` + ``/api/jobs``,
mirroring ``ReindexJobManager``'s own wiring) -- but STARTING A REAL WRITE RUN is still a deliberate
choice per call (``write=True`` on ``start()``/the endpoint; the default stays dry-run/detection-
only), consistent with the brief's own binding order: S3.1's calibration report ships and is
REVIEWED before any real write executes against a maintainer's corpus.

NOT covered by this module (explicitly out of scope, a follow-up): quarantined articles' existing
KEYWORD MENTIONS are left exactly as they are -- a "Re-index the whole corpus" / "Clean up
keywords" pass (the existing reindex job) is the honest, separate, real-cost way to clear their
contribution from keyword aggregates; running it is the operator's own choice after a quarantine
batch, never chained automatically here.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

_BATCH = 300  # candidates scanned per loop iteration (mirrors ReindexJobManager's _BATCH)
_STATE_FILE = "quarantine_job.json"  # OWN state file -- never touches reindex_job.json


def _default_session():
    from src.database.session import SessionLocal

    return SessionLocal()


def default_quarantine_candidates_batch(
    session: Any,
    *,
    after_id: int = 0,
    limit: int = _BATCH,
    include_prose_gate: bool = True,
    write: bool = False,
    criteria_version: str | None = None,
) -> dict[str, Any]:
    """The default per-batch WORK FUNCTION: DETECT already-flagged non-article candidates (the
    #659 URL-shape rules via ``classify_non_article``, plus the opt-in NAV-SOUP PROSE GATE for
    ``>= _ARTICLE_MIN_WORDS`` bodies) ordered by id after ``after_id`` -- a resumable, chunked
    version of :func:`src.analytics.non_article_scan.scan_non_article_candidates`.

    ``write=False`` (the default): DRY-RUN, no database mutation -- "quarantining" here means
    reporting a candidate's id in ``quarantined_ids``, exactly the original scaffold's behaviour.
    ``write=True``: additionally STAMPS each detected candidate (idempotent -- an already-
    quarantined row, per ``Article.quarantined is True``, is skipped and never re-counted/
    re-stamped, so re-running over the same range after a partial write is always safe).
    ``criteria_version`` defaults to :data:`src.analytics.criteria_calibration.CRITERIA_VERSION`
    when not given."""
    from src.analytics.criteria_calibration import CRITERIA_VERSION
    from src.database.models import Article
    from src.ingest.non_article import _ARTICLE_MIN_WORDS, classify_non_article
    from src.services.prose_gate import prose_gate_verdict

    criteria_version = criteria_version or CRITERIA_VERSION

    q = (
        session.query(
            Article.id, Article.url, Article.word_count, Article.content,
            Article.language, Article.detected_language, Article.quarantined,
        )
        .filter(Article.id > after_id)
        .order_by(Article.id)
        .limit(limit)
    )
    quarantined_ids: list[int] = []
    by_reason: dict[str, int] = {}
    to_write: dict[int, str] = {}  # id -> signal, for rows NOT already quarantined
    already_quarantined = 0
    scanned = 0
    last_id = after_id
    for aid, url, wc, content, lang, detected, is_quarantined in q:
        scanned += 1
        last_id = int(aid)
        verdict = classify_non_article(url or "", word_count=wc)  # URL-shape rules (text=None)
        signal: str | None = verdict.signal if verdict is not None else None
        if signal is None and include_prose_gate and wc is not None and wc >= _ARTICLE_MIN_WORDS:
            prose_verdict = prose_gate_verdict(content or "", language=lang or detected)
            signal = prose_verdict.signal if prose_verdict is not None else None
        if signal is not None:
            quarantined_ids.append(int(aid))
            by_reason[signal] = by_reason.get(signal, 0) + 1
            if is_quarantined:
                already_quarantined += 1  # idempotent: already stamped, never re-counted as new
            else:
                to_write[int(aid)] = signal

    newly_written = 0
    if write and to_write:
        now = datetime.now(UTC)
        for aid, signal in to_write.items():
            # A targeted, no-load UPDATE (the batch already read every candidate's
            # columns above; no second content decrypt). synchronize_session=False --
            # this session never re-reads these rows again in the same batch.
            session.query(Article).filter(Article.id == aid).update(
                {
                    "quarantined": True,
                    "quarantine_reason": signal,
                    "quarantine_criteria_version": criteria_version,
                    "quarantined_at": now,
                },
                synchronize_session=False,
            )
        session.commit()
        newly_written = len(to_write)

    return {
        "scanned": scanned,
        "quarantined": len(quarantined_ids),
        "quarantined_ids": quarantined_ids,
        "already_quarantined": already_quarantined,
        "newly_written": newly_written,
        "by_reason": by_reason,
        "last_id": last_id,
        "done": scanned < limit,
        "write": write,
    }


class QuarantineJobManager:
    """A pausable, resumable retroactive-quarantine job -- the SAME chassis shape as
    ``ReindexJobManager`` (state machine, worker thread, persisted cursor, batching, progress/ETA,
    pause/resume/cancel), for the NAV-SOUP SPECIMEN ruling's row-5 carry-over. ``write`` (default
    False, dry-run detection only) is fixed for the LIFETIME of one run -- a resume ALWAYS continues
    in the mode the run started in (persisted alongside the cursor), never silently flipping a
    dry-run into a real write or vice versa."""

    def __init__(self, *, state_path: Path | None = None) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state = "idle"  # idle|running|paused|done|error|cancelled
        self._cursor = 0  # after_id: the last article id scanned (resume point)
        self._total = 0  # total articles at start (for percent + ETA)
        self._done = 0  # articles scanned so far (for percent + ETA)
        self._done_at_start = 0  # _done when the current run began (honest run-rate ETA)
        self._tally: dict[str, int] = {}  # quarantined / by-reason / write counts
        self._write = False  # dry-run by default; fixed for a run's lifetime, persisted across resumes
        self._error: str | None = None
        self._cancelled = False
        self._started_at: float | None = None
        self._session_factory: Callable[[], Any] | None = None  # test seam
        self._work_fn: Callable[..., dict[str, Any]] | None = None  # test seam
        self._state_path_override = state_path
        self._load_persisted()

    # -- persistence -------------------------------------------------------- #
    def _state_path(self) -> Path:
        if self._state_path_override is not None:
            return self._state_path_override
        from src.paths import data_dir

        return data_dir() / _STATE_FILE

    def _save(self) -> None:
        """Persist the resume cursor (best-effort; a write hiccup never breaks the job)."""
        try:
            p = self._state_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps({
                    "cursor": self._cursor, "total": self._total, "done": self._done,
                    "tally": self._tally, "state": self._state, "write": self._write,
                }),
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
        """On first construction, restore an INTERRUPTED run as PAUSED (never silently lost) --
        same resume-on-restart guarantee as ``ReindexJobManager``."""
        try:
            d = json.loads(self._state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if d.get("state") not in ("running", "paused"):
            return
        self._cursor = max(0, int(d.get("cursor") or 0))
        self._total = max(0, int(d.get("total") or 0))
        self._done = max(0, int(d.get("done") or 0))
        self._tally = {str(k): int(v) for k, v in (d.get("tally") or {}).items()}
        self._write = bool(d.get("write", False))
        self._state = "paused"

    # -- lifecycle ---------------------------------------------------------- #
    def _alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _count_articles(self, session_factory) -> int:
        try:
            from src.database.models import Article

            sess = (session_factory or _default_session)()
            try:
                return int(sess.query(Article.id).count())
            finally:
                sess.close()
        except Exception:  # noqa: BLE001 - a count hiccup must never stop the job
            return 0

    def start(
        self, *, _session_factory=None, _work_fn=None, _cursor: int = 0, _total: int = 0,
        _done: int = 0, write: bool = False,
    ) -> dict:
        """Launch the worker. RuntimeError if already running. ``_work_fn`` overrides the default
        batch function (a test seam). ``write`` (default False, dry-run detection only) is fixed
        for this run's lifetime -- ``resume()`` always passes through the SAME mode the run
        started in, never a caller-supplied override, so a paused run can never silently resume
        in a different mode than it started."""
        with self._lock:
            if self._alive():
                raise RuntimeError("A quarantine job is already running.")
            self._stop.clear()
            self._cancelled = False
            self._state = "running"
            self._cursor = max(0, _cursor)
            self._done = max(0, _done)
            self._done_at_start = self._done
            self._total = max(0, _total)
            if _cursor <= 0:
                self._tally = {}
            # The caller supplies the mode explicitly every time: a genuinely fresh
            # external start passes the operator's own choice; resume() (below) always
            # passes through the PRESERVED mode of the run being resumed -- never
            # silently reset to the default, even when a paused/errored run's cursor
            # happens to still be 0.
            self._write = bool(write)
            self._error = None
            self._started_at = time.monotonic()
            self._session_factory = _session_factory
            self._work_fn = _work_fn
            if not self._total:
                self._total = self._count_articles(_session_factory)
            self._save()
            self._thread = threading.Thread(target=self._run, daemon=True, name="quarantine-job")
            self._thread.start()
            return self.status()

    def _run(self) -> None:
        try:
            work = self._work_fn or default_quarantine_candidates_batch
            session = (self._session_factory or _default_session)()
            try:
                with self._lock:
                    after = self._cursor
                    write = self._write
                    self._save()
                while True:
                    if self._stop.is_set():
                        break
                    r = work(session, after_id=after, limit=_BATCH, write=write)
                    after = int(r["last_id"])
                    with self._lock:
                        self._tally["scanned"] = self._tally.get("scanned", 0) + int(r.get("scanned", 0))
                        self._tally["quarantined"] = self._tally.get("quarantined", 0) + int(
                            r.get("quarantined", 0)
                        )
                        self._tally["already_quarantined"] = self._tally.get(
                            "already_quarantined", 0
                        ) + int(r.get("already_quarantined", 0))
                        self._tally["newly_written"] = self._tally.get("newly_written", 0) + int(
                            r.get("newly_written", 0)
                        )
                        for sig, cnt in (r.get("by_reason") or {}).items():
                            self._tally[f"reason:{sig}"] = self._tally.get(f"reason:{sig}", 0) + int(cnt)
                        self._done += int(r.get("scanned", 0))
                        self._cursor = after
                        self._save()
                    if r.get("done"):
                        break
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
        self._stop.set()

    def resume(self) -> dict:
        with self._lock:
            if self._state not in ("paused", "error", "cancelled"):
                raise RuntimeError("Nothing paused to resume.")
            sf, wf = self._session_factory, self._work_fn
            cur, tot, done = self._cursor, self._total, self._done
            tally = dict(self._tally)
            w = self._write  # ALWAYS preserve the mode the paused run was in
        out = self.start(_session_factory=sf, _work_fn=wf, _cursor=cur, _total=tot, _done=done, write=w)
        with self._lock:
            self._tally = tally
            self._save()
        return out

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
        self._stop.set()
        if not self._alive():
            with self._lock:
                self._state = "cancelled"
                self._clear_state()

    def status(self) -> dict:
        with self._lock:
            total = self._total
            done = self._done
            eta_s = None
            recent = done - self._done_at_start
            if self._started_at is not None and recent > 0 and total and done < total:
                elapsed = max(0.001, time.monotonic() - self._started_at)
                rate = recent / elapsed
                if rate > 0:
                    eta_s = round((total - done) / rate)
            return {
                "state": self._state,
                "articles_total": total,
                "articles_done": done,
                "percent": round(100 * done / total, 1) if total else 0.0,
                "tally": dict(self._tally),
                "eta_seconds": eta_s,
                "error": self._error,
                "running": self._alive(),
                "dry_run": not self._write,  # honest: reflects the ACTUAL mode this run is in
            }


_manager: QuarantineJobManager | None = None


def get_quarantine_manager() -> QuarantineJobManager:
    """The module-level singleton (mirrors ``src.analytics.reindex_job.get_reindex_manager``),
    wired into ``/api/jobs`` (S3.2, 2026-07-23 field-feedback workflow). Starting a REAL WRITE
    run is still a deliberate per-call choice (``write=True``) -- the default stays dry-run/
    detection-only, per the brief's binding execution gate."""
    global _manager
    if _manager is None:
        _manager = QuarantineJobManager()
    return _manager
