"""
Retroactive QUARANTINE job -- SCAFFOLDING ONLY, not wired to run, not wired to any real write.

NAV-SOUP SPECIMEN ruling (2026-07-20) row 5 EXECUTION SCOPE: the ruling's finding (a) is that
legacy non-article junk already sits in the DB (predating the #659 ingest-door filter and the
PROSE GATE this session added), and that "the Slice-4a retroactive QUARANTINE carry-over is what
removes it". This module builds the MECHANISM that COULD run that carry-over -- reusing
``ReindexJobManager``'s resumable-job CHASSIS SHAPE (state machine, worker thread, persisted
cursor, batching, progress/ETA, pause/resume/cancel) -- but per the 0.3 gate's own scope, actually
EXECUTING a quarantine against real data needs separate maintainer sign-off. So, explicitly:

  * this manager is BUILT, TESTED (on a throwaway in-memory DB), and IMPORTABLE, but
  * NOTHING in the running app constructs/starts it: there is no ``get_quarantine_manager()``
    singleton wired into ``/api/jobs``, no startup call, no cron/scheduler entry -- unlike
    ``ReindexJobManager``, which IS live-wired (``src/analytics/reindex_job.get_reindex_manager``,
    consumed by the jobs API). A maintainer who wants to run this imports the class directly.
  * the default WORK FUNCTION (:func:`default_quarantine_candidates_batch`) does NOT write to the
    database at all -- there is no ``quarantined`` column on ``Article`` yet (adding one is a
    schema decision for the sign-off session, row 5, not this build). It DETECTS candidates
    (reusing ``classify_non_article`` URL-shape rules + the opt-in PROSE GATE from this session)
    and reports them in the batch's tally as a DRY-RUN count + a bounded id sample -- i.e. running
    this job today is equivalent to a resumable, chunked version of
    ``scan_non_article_candidates(..., include_prose_gate=True)``, with NO side effect.
  * idempotency (the chassis's own correctness net, per ``ReindexJobManager``'s docstring) is
    satisfied BY CONSTRUCTION here: re-scanning the same id range just re-detects the same
    candidates and re-reports the same tally -- there is no persisted mutation to double-apply.
    When a real write step is wired in later (behind the ``_work_fn`` test seam below, once a
    ``quarantined``/``quarantine_reason`` column exists), THAT function must itself be a no-op on
    an already-quarantined row, exactly as the setup note requires -- this scaffold's job is to
    make that swap-in point exist, not to pre-empt the schema decision.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

_BATCH = 300  # candidates scanned per loop iteration (mirrors ReindexJobManager's _BATCH)
_STATE_FILE = "quarantine_job.json"  # OWN state file -- never touches reindex_job.json


def _default_session():
    from src.database.session import SessionLocal

    return SessionLocal()


def default_quarantine_candidates_batch(
    session: Any, *, after_id: int = 0, limit: int = _BATCH, include_prose_gate: bool = True,
) -> dict[str, Any]:
    """The default per-batch WORK FUNCTION: DETECT already-flagged non-article candidates (the
    #659 URL-shape rules via ``classify_non_article``, plus the opt-in NAV-SOUP PROSE GATE for
    ``>= _ARTICLE_MIN_WORDS`` bodies) ordered by id after ``after_id`` -- a resumable, chunked
    version of :func:`src.analytics.non_article_scan.scan_non_article_candidates`.

    THIS BUILD NEVER WRITES TO THE DATABASE: there is no ``quarantined`` column on ``Article`` yet
    (a schema decision for the maintainer sign-off session, not this build). "Quarantining" here
    means reporting a candidate's id in ``quarantined_ids`` -- a DRY-RUN detection tally, not a
    mutation. Idempotent by construction (no persisted state to double-apply): re-running over the
    same range just re-detects the same candidates."""
    from src.database.models import Article
    from src.ingest.non_article import _ARTICLE_MIN_WORDS, classify_non_article
    from src.services.prose_gate import prose_gate_verdict

    q = (
        session.query(
            Article.id, Article.url, Article.word_count, Article.content,
            Article.language, Article.detected_language,
        )
        .filter(Article.id > after_id)
        .order_by(Article.id)
        .limit(limit)
    )
    quarantined_ids: list[int] = []
    by_reason: dict[str, int] = {}
    scanned = 0
    last_id = after_id
    for aid, url, wc, content, lang, detected in q:
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
    return {
        "scanned": scanned,
        "quarantined": len(quarantined_ids),
        "quarantined_ids": quarantined_ids,
        "by_reason": by_reason,
        "last_id": last_id,
        "done": scanned < limit,
    }


class QuarantineJobManager:
    """A pausable, resumable retroactive-quarantine DETECTION job -- the SAME chassis shape as
    ``ReindexJobManager`` (state machine, worker thread, persisted cursor, batching, progress/ETA,
    pause/resume/cancel), for the NAV-SOUP SPECIMEN ruling's row-5 carry-over. See the module
    docstring: BUILD-ONLY -- no singleton getter is wired into the app, and the default work
    function never writes to the database (dry-run detection tally only)."""

    def __init__(self, *, state_path: Path | None = None) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state = "idle"  # idle|running|paused|done|error|cancelled
        self._cursor = 0  # after_id: the last article id scanned (resume point)
        self._total = 0  # total articles at start (for percent + ETA)
        self._done = 0  # articles scanned so far (for percent + ETA)
        self._done_at_start = 0  # _done when the current run began (honest run-rate ETA)
        self._tally: dict[str, int] = {}  # quarantined / by-reason counts (dry-run, never a write)
        self._error: str | None = None
        self._cancelled = False
        self._started_at: float | None = None
        self._session_factory: Callable[[], Any] | None = None  # test seam
        self._work_fn: Callable[..., dict[str, Any]] | None = None  # test seam / future real-write swap-in
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
                    "tally": self._tally, "state": self._state,
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
        self, *, _session_factory=None, _work_fn=None, _cursor: int = 0, _total: int = 0, _done: int = 0,
    ) -> dict:
        """Launch the worker. RuntimeError if already running. ``_work_fn`` overrides the default
        detection-only batch function (the seam a future real-write quarantine would use, once a
        schema for it exists and a maintainer has signed off -- see the module docstring)."""
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
                    self._save()
                while True:
                    if self._stop.is_set():
                        break
                    r = work(session, after_id=after, limit=_BATCH)
                    after = int(r["last_id"])
                    with self._lock:
                        self._tally["scanned"] = self._tally.get("scanned", 0) + int(r.get("scanned", 0))
                        self._tally["quarantined"] = self._tally.get("quarantined", 0) + int(
                            r.get("quarantined", 0)
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
        out = self.start(_session_factory=sf, _work_fn=wf, _cursor=cur, _total=tot, _done=done)
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
                "dry_run": True,  # ALWAYS true in this build: detection only, never a DB write
            }


# Deliberately NO module-level singleton / get_quarantine_manager() here (unlike
# ReindexJobManager's get_reindex_manager()) -- per the module docstring, this scaffolding is not
# wired into the app: no /api/jobs entry, no startup construction, no scheduler/cron entry. A
# maintainer who wants to run it constructs QuarantineJobManager(...) directly.
