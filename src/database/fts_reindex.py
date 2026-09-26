"""The search re-index for Arabic, Chinese and Japanese (Q506 🔒 = b, Q507 = a; brief S04-07 S8).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT IT DOES. Since the sync triggers index through ``fts_norm`` (Arabic folded, CJK
segmented), every article written from then on is searchable by word. Every article
indexed BEFORE then still holds its text raw in the index: its Chinese sentences are one
token each and its vocalised Arabic is shredded into letters. This job walks every article
once, in id order, and re-indexes the ones whose index entry differs from what the
transform writes today -- deleting the old entry with EXACTLY the values it was indexed
with (read back from its ``article_fts_norm`` row, or raw when it has none) and inserting
the new one.

The same run covers the days the segmenters change: an article indexed before a segmenter
was installed is segmented; one indexed under an older dictionary is re-segmented when the
new one splits it differently; and one indexed by a segmenter that has since been removed
is indexed the way new articles now are, without it, and counted as such. None of that
needs the old segmenter, because a segmented entry's exact values are kept.

WHY A JOB, AND WHY THIS SHAPE. Only the article text can say whether it needs anything,
and reading every article's text is the corpus-scaled cost the boot path was fixed to stop
paying (``fts.ensure_fts``). So it runs in the background, in time-bounded steps that each
hold the single-writer gate briefly, parks while an import owns the machine, persists its
cursor so a pause or a restart resumes where it stopped, and is visible in the task
manager. A step reads and rewrites inside ONE hold of the gate: an article updated between
a read and its rewrite would otherwise be deleted with stale values, which corrupts the
index.
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.database.corpus_lease import corpus_lease
from src.database.fts_norm import (
    ARABIC,
    JA_SUDACHI,
    SEGMENTERS,
    ZH_JIEBA,
    index_entry,
    indexed_values,
)

_LOG = logging.getLogger(__name__)

_STATE_FILE = "search_reindex_job.json"
_REPORT_FILE = "search_reindex_report.json"
_FETCH = 50  # articles read per round trip inside a step
_STEP_BUDGET_S = 0.5  # how long one step may hold the writer gate
_EXCLUSIVE_POLL_S = 2.0

REFUSED_RUNNING = "already-running"
REFUSED_NOTHING_PAUSED = "nothing-paused"
REFUSED_NOT_UPGRADED = "index-not-upgraded"  # the store's triggers still index raw

_BIT_NAMES = {ARABIC: "arabic", ZH_JIEBA: "chinese", JA_SUDACHI: "japanese"}


class SearchReindexRefused(RuntimeError):
    """A start or resume the job cannot honour; ``code`` says why."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _max_id(conn) -> int:
    row = conn.exec_driver_sql("SELECT max(id) FROM articles").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _count(conn) -> int:
    row = conn.exec_driver_sql("SELECT count(*) FROM articles").fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def reindex_step(conn, *, after_id: int | None, caps: int, budget_s: float = _STEP_BUDGET_S,
                 fetch: int = _FETCH) -> tuple[int | None, bool, dict[str, int]]:
    """One bounded step, on a connection whose transaction the caller owns (under the gate).

    Returns ``(last_id, exhausted, tally)``. ``after_id`` None starts before the first
    article (a rowid may be 0)."""
    tally: dict[str, int] = {}

    def add(key: str, n: int = 1) -> None:
        tally[key] = tally.get(key, 0) + n

    deadline = time.monotonic() + budget_s
    last = after_id
    select = (
        "SELECT a.id, a.title, a.content, COALESCE(n.mask, 0), n.title, n.content FROM articles a "
        "LEFT JOIN article_fts_norm n ON n.article_id = a.id "
    )
    while True:
        if last is None:
            rows = conn.exec_driver_sql(select + "ORDER BY a.id LIMIT ?", (fetch,)).fetchall()
        else:
            rows = conn.exec_driver_sql(select + "WHERE a.id > ? ORDER BY a.id LIMIT ?", (last, fetch)).fetchall()
        if not rows:
            return last, True, tally
        for aid, title, content, old, kept_title, kept_content in rows:
            aid, old = int(aid), int(old)
            last = aid
            add("articles_checked")
            new, new_title, new_content = index_entry(title, content, caps)
            # The fold is this code's own and deterministic, so an entry whose mask did not
            # change and holds no segmenter output cannot have changed either.
            if new == old and not (new & SEGMENTERS):
                continue
            old_title, old_content = indexed_values(title, content, old, kept_title, kept_content)
            if new == old and (new_title, new_content) == (old_title, old_content):
                continue
            conn.exec_driver_sql(
                "INSERT INTO article_fts(article_fts, rowid, title, content) VALUES ('delete', ?, ?, ?)",
                (aid, old_title, old_content),
            )
            conn.exec_driver_sql(
                "INSERT INTO article_fts(rowid, title, content) VALUES (?, ?, ?)", (aid, new_title, new_content)
            )
            if new:
                keep = bool(new & SEGMENTERS)
                conn.exec_driver_sql(
                    "INSERT OR REPLACE INTO article_fts_norm(article_id, mask, title, content) VALUES (?, ?, ?, ?)",
                    (aid, new, new_title if keep else None, new_content if keep else None),
                )
            else:
                conn.exec_driver_sql("DELETE FROM article_fts_norm WHERE article_id = ?", (aid,))
            add("articles_reindexed")
            for bit, name in _BIT_NAMES.items():
                if (new | old) & bit:
                    add(name)
            if old & SEGMENTERS & ~new:
                # indexed by a segmenter this install no longer has: now indexed as new
                # articles are, without it
                add("unsegmented_by_a_missing_segmenter")
        if time.monotonic() >= deadline:
            return last, False, tally


def _segmenter_versions() -> dict[str, str | None]:
    """The installed version of each segmenter package and dictionary (None: not installed)."""
    from importlib.metadata import PackageNotFoundError, version

    out: dict[str, str | None] = {}
    for dist in ("jieba", "sudachipy", "sudachidict_core"):
        try:
            out[dist] = version(dist)
        except PackageNotFoundError:
            out[dist] = None
    return out


def _default_session():
    from src.database.session import SessionLocal

    return SessionLocal()


def _import_owns_the_machine() -> bool:
    try:
        from src.scheduler.runner import exclusive_window_open, get_scheduler

        if exclusive_window_open():
            return True
        return bool(get_scheduler().holds_exclusive())
    except Exception:  # noqa: BLE001 - a courtesy check is never load-bearing
        return False


def _data_path(name: str) -> Path:
    from src.paths import data_dir

    return data_dir() / name


def last_report() -> dict | None:
    """The report the last COMPLETED run wrote, or None."""
    try:
        return json.loads(_data_path(_REPORT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class SearchReindexJobManager:
    """ONE pausable, resumable search re-index at a time."""

    def __init__(self, *, state_path: Path | None = None, report_path: Path | None = None) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state = "idle"  # idle|running|paused|done|error|cancelled
        self._cursor: int | None = None
        self._max_id = 0
        self._total = 0  # articles in the store when the run began, for the task manager
        self._tally: dict[str, int] = {}
        self._error: str | None = None
        self._cancelled = False
        self._parked = False
        self._started_at: float | None = None
        self._cursor_at_start: int | None = None
        self._session_factory: Callable[[], Any] | None = None
        self._budget_s = _STEP_BUDGET_S
        self._state_path_override = state_path
        self._report_path_override = report_path
        self._load_persisted()

    # -- persistence ------------------------------------------------------- #
    def _state_path(self) -> Path:
        return self._state_path_override or _data_path(_STATE_FILE)

    def _report_file(self) -> Path:
        return self._report_path_override or _data_path(_REPORT_FILE)

    def _save(self) -> None:
        try:
            p = self._state_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "state": self._state,
                        "cursor": self._cursor,
                        "max_id": self._max_id,
                        "total": self._total,
                        "tally": self._tally,
                    }
                ),
                encoding="utf-8",
            )
            tmp.replace(p)
        except OSError:
            pass

    def _clear_state(self) -> None:
        with contextlib.suppress(OSError):
            self._state_path().unlink(missing_ok=True)

    def _load_persisted(self) -> None:
        """Restore an INTERRUPTED run as PAUSED, never silently lost."""
        try:
            d = json.loads(self._state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if d.get("state") not in ("running", "paused", "error"):
            return
        try:
            cur = d.get("cursor")
            self._cursor = None if cur is None else int(cur)
            self._max_id = max(0, int(d.get("max_id") or 0))
            self._total = max(0, int(d.get("total") or 0))
            self._tally = {str(k): int(v) for k, v in (d.get("tally") or {}).items()}
        except (TypeError, ValueError):
            return
        self._state = "paused"

    # -- lifecycle --------------------------------------------------------- #
    def _alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, *, _session_factory=None, _budget_s: float | None = None) -> dict:
        """Start a fresh run, or CONTINUE a paused one (never discarded by a start)."""
        with self._lock:
            if self._alive():
                raise SearchReindexRefused(REFUSED_RUNNING)
            if self._state not in ("paused", "error"):
                self._cursor = None
                self._max_id = 0
                self._total = 0
                self._tally = {}
            self._stop.clear()
            self._cancelled = False
            self._state = "running"
            self._error = None
            self._cursor_at_start = self._cursor
            self._started_at = time.monotonic()
            self._session_factory = _session_factory
            if _budget_s is not None:
                self._budget_s = float(_budget_s)
            self._save()
            self._thread = threading.Thread(target=self._run, daemon=True, name="search-reindex-job")
            self._thread.start()
            return self.status()

    def resume(self) -> dict:
        with self._lock:
            if self._state not in ("paused", "error"):
                raise SearchReindexRefused(REFUSED_NOTHING_PAUSED)
        return self.start(_session_factory=self._session_factory)

    def pause(self) -> None:
        self._stop.set()

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
        self._stop.set()
        if not self._alive():
            with self._lock:
                self._state = "cancelled"
                self._clear_state()

    def join(self, timeout: float | None = None) -> None:
        t = self._thread
        if t is not None:
            t.join(timeout)

    # -- the worker -------------------------------------------------------- #
    def _park(self) -> None:
        try:
            while not self._stop.is_set() and _import_owns_the_machine():
                with self._lock:
                    self._parked = True
                self._stop.wait(_EXCLUSIVE_POLL_S)
        finally:
            with self._lock:
                self._parked = False

    def _run(self) -> None:
        from src.database.fts import _store_caps
        from src.database.fts_norm import register
        from src.database.writer import write_lock

        session = (self._session_factory or _default_session)()
        started = time.monotonic()
        try:
            conn = session.connection()
            register(conn.connection.dbapi_connection)
            caps = _store_caps(conn)
            if not caps:
                with self._lock:
                    self._state = "error"
                    self._error = REFUSED_NOT_UPGRADED
                    self._save()
                return
            with self._lock:
                if not self._max_id:
                    self._max_id = _max_id(conn)
                    self._total = _count(conn)
            session.commit()
            finished = False
            while not self._stop.is_set():
                self._park()
                if self._stop.is_set():
                    break
                with corpus_lease("search-reindex"), write_lock():
                    conn = session.connection()
                    last, exhausted, tally = reindex_step(
                        conn, after_id=self._cursor, caps=caps, budget_s=self._budget_s
                    )
                    session.commit()
                with self._lock:
                    self._cursor = last
                    for k, n in tally.items():
                        self._tally[k] = self._tally.get(k, 0) + n
                    self._save()
                if exhausted:
                    finished = True
                    break
            with self._lock:
                if finished:
                    self._state = "done"
                    self._write_report(caps, time.monotonic() - started)
                    self._clear_state()
                elif self._cancelled:
                    self._state = "cancelled"
                    self._clear_state()
                else:
                    self._state = "paused"
                    self._save()
        except Exception:  # noqa: BLE001 - surface the failure, never crash the thread
            _LOG.exception("search re-index job failed")
            with contextlib.suppress(Exception):
                session.rollback()
            with self._lock:
                self._state = "error"
                self._error = "failed"  # a code: the log holds the exception, not the API
                self._save()
        finally:
            with contextlib.suppress(Exception):
                session.close()

    def _write_report(self, caps: int, seconds: float) -> None:
        from src.database.fts_norm import available_mask

        report = {
            "finished_at": datetime.now(UTC).isoformat(),
            "articles_checked": self._tally.get("articles_checked", 0),
            "articles_reindexed": self._tally.get("articles_reindexed", 0),
            "by_script": {name: self._tally.get(name, 0) for name in _BIT_NAMES.values()},
            "unsegmented_by_a_missing_segmenter": self._tally.get("unsegmented_by_a_missing_segmenter", 0),
            "seconds_this_run": round(seconds, 1),
            "transforms": {name: bool(caps & bit) for bit, name in _BIT_NAMES.items()},
            "installed_now": {name: bool(available_mask() & bit) for bit, name in _BIT_NAMES.items()},
            # A later run that re-segments articles is explained by a change here.
            "segmenter_versions": _segmenter_versions(),
            "method": (
                "Every article's title and text were read once, in id order. An article was "
                "re-indexed when what the search index holds for it differs from what the index "
                "transform writes today (Arabic folded; Chinese segmented by jieba; Japanese by "
                "sudachipy when it is installed), including when a newer dictionary splits it "
                "differently. by_script counts re-indexed articles whose entry involves that "
                "script before or after; one article can count under more than one."
            ),
        }
        try:
            p = self._report_file()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(p)
        except OSError:
            _LOG.warning("could not write the search re-index report", exc_info=True)

    def status(self) -> dict:
        with self._lock:
            cur, top = self._cursor, self._max_id
            checked = self._tally.get("articles_checked", 0)
            percent = round(100 * min(cur or 0, top) / top, 1) if top and cur is not None else 0.0
            return {
                "state": self._state,
                "cursor": cur,
                "max_id": top,
                # A COUNT for people; the percent above is the cursor's place in the id range.
                "articles_total": self._total,
                "articles_checked": min(checked, self._total) if self._total else checked,
                "percent": percent,
                "tally": dict(self._tally),
                "error": self._error,
                "running": self._alive(),
                "parked_for_exclusive": self._parked,
            }


def refusal_code(mgr: SearchReindexJobManager) -> str:
    """Why ``mgr`` refuses right now, from its STATE (never from an exception's text)."""
    return REFUSED_RUNNING if mgr.status()["running"] else REFUSED_NOTHING_PAUSED


_MANAGER: SearchReindexJobManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_search_reindex_manager() -> SearchReindexJobManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = SearchReindexJobManager()
        return _MANAGER
