"""
Corpus-integrity / counter-drift sweep — the "are the numbers still trustworthy?" log.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Recursive-augmentation log #5 (maintainer 2026-07-02): silent data drift — orphan
rows, foreign-key breaks, maintained counters that disagree with a live COUNT, a
stale search index — makes analytics quietly WRONG in a way the maintainer only
catches by eye. This surfaces those facts on demand so a wrong number is caught by
the log, not by the reader.

Honesty + safety: read-only, network-free, counts + names only (no score). Every scan
is BOUNDED (the standing discipline) and runs under the shared statement deadline, so
a huge corpus reports honestly instead of freezing. Counter-drift is a SAMPLED
detector by default (the highest-mention keywords, where drift matters most) with an
explicit ``full`` mode; it reports the drift, it does not fix it (the reconcile passes
own that).
"""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.database.maintenance import (
    StatementTimeout,
    deadline_expired,
    deadline_left_s,
    statement_deadline,
)
from src.monitoring.secret_scrub import log_failure, record_text

_LOG = logging.getLogger(__name__)


def _budget_spent(session: Session, exc: BaseException) -> bool:
    """Is this failure the statement deadline's own interrupt? (INT-1)

    The deadline is not a degraded read, it is the budget running out -- and it surfaces
    as a plain "interrupted" error that the handlers below used to swallow, so the sweep
    carried on, every later check was interrupted too, and the report read `drift: false,
    timed_out: false` having checked nothing. Re-raised, that error reaches the enclosing
    :func:`statement_deadline`, which turns it into the typed StatementTimeout the report
    records.

    The SAME pair the deadline itself translates (elapsed AND an interrupt), and nothing
    wider: any OTHER error -- a missing table, say -- is still a degraded read after the
    budget has run out, because the deadline would re-raise it untyped and the sweep
    would 500 where it used to degrade."""
    return deadline_expired(session) and "interrupt" in str(exc).lower()


def _scalar(session: Session, sql: str, params: dict[str, Any] | None = None) -> int | None:
    try:
        row = session.execute(text(sql), params or {}).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception as exc:  # noqa: BLE001 - a diagnostic must degrade, never crash
        if _budget_spent(session, exc):
            raise  # the budget ran out: the enclosing deadline types it (INT-1)
        return None


#: Where the exact scans keep their place between builds. ``load`` returns the saved cursor (``{}`` when there is none or it cannot be read)
#: and ``save`` writes it back; both must never raise. ``None`` for a caller that has nowhere to keep it: the scan then starts from the
#: beginning every time, as before, and a check the budget cuts says so.
class CursorStore(Protocol):
    def load(self) -> dict[str, Any]: ...

    def save(self, state: dict[str, Any]) -> None: ...


_CURSOR_KEY = "diagnostics.integrity.cursor.v1"

#: Rows a range scan starts with before it has measured anything, and how long one range should take. The SIZE of the next range is derived
#: from how long the last one took, so a large corpus gets small ranges and a small one a single range; these two are only where it starts and
#: what it steers toward (a statement the deadline can stop, since a bare count over a whole table is ONE progress opcode and cannot be).
_FIRST_RANGE_ROWS = 50_000
_RANGE_TARGET_S = 1.0
#: A range may grow by at most this factor per step, so one fast range (a warm cache) cannot ask for a table's worth next.
_RANGE_GROWTH = 4


class KvCursorStore:
    """The cursor kept in the app-state key-value store. Never raises: an unreadable cursor is an absent one, an unwritable one is logged."""

    def load(self) -> dict[str, Any]:
        try:
            from src.config.kv_store import kv_get_json

            blob = kv_get_json(_CURSOR_KEY)
            return blob if isinstance(blob, dict) else {}
        except Exception as exc:  # noqa: BLE001 - a diagnostic cursor must never break the sweep
            log_failure(_LOG, "corpus-integrity: could not read the saved cursor", exc, level=logging.DEBUG)
            return {}

    def save(self, state: dict[str, Any]) -> None:
        try:
            from src.config.kv_store import kv_set_json

            kv_set_json(_CURSOR_KEY, state)
        except Exception as exc:  # noqa: BLE001
            log_failure(_LOG, "corpus-integrity: could not save the cursor", exc, level=logging.WARNING)


#: The physical mentions table, named once: ``PRAGMA foreign_key_check`` takes a table (a view has no foreign keys), and the foreign-key sweep
#: leaves this one to the two dangling-mention checks. Every READ below goes through the ``keyword_mentions_all`` view (R96).
_MENTIONS_TABLE = "keyword_mentions"


#: The exact scans: (check, the table whose id range is walked, the statement over one range). Each counts the rows of its range that break the
#: rule; the sum over the ranges is the whole-table figure.
_RANGE_SCANS = (
    (
        "orphan_keywords",
        "keywords",
        "SELECT COUNT(*) FROM keywords k WHERE k.id > :lo AND k.id <= :hi "
        "AND NOT EXISTS (SELECT 1 FROM keyword_mentions_all m WHERE m.keyword_id = k.id)",
    ),
    (
        "dangling_mentions_missing_article",
        "keyword_mentions_all",
        "SELECT COUNT(*) FROM keyword_mentions_all m WHERE m.id > :lo AND m.id <= :hi "
        "AND NOT EXISTS (SELECT 1 FROM articles a WHERE a.id = m.article_id)",
    ),
    (
        "dangling_mentions_missing_keyword",
        "keyword_mentions_all",
        "SELECT COUNT(*) FROM keyword_mentions_all m WHERE m.id > :lo AND m.id <= :hi "
        "AND NOT EXISTS (SELECT 1 FROM keywords k WHERE k.id = m.keyword_id)",
    ),
)

_TABLE_NAME = re.compile(r"^[A-Za-z0-9_]+$")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _range_scan(
    session: Session, check: str, table: str, sql: str, saved: dict[str, Any], progress: dict[str, Any], stop_at: float | None = None
) -> int | None:
    """Count one exact check in id ranges, from where the last build stopped, until it finishes or the budget runs out.

    Returns ``(value, progress)``: ``value`` is the whole-table figure when the scan reached the end THIS build, else ``None`` (not established);
    ``progress`` says where it is (``state`` complete or partial, the highest id it has through, the largest id it is walking to, the tally so
    far) and carries the last COMPLETED figure with its date and the id it was through, so a reader sees an older result as old. A pass walks to
    the largest id the table had when the pass began: rows added after that are the next pass's, and the progress says which id that was.
    The cursor only moves past a range whose statement finished, so an interrupted range is simply done again next build. ``stop_at`` (a
    ``time.monotonic()`` instant) is this check's share of the budget: it stops between ranges there, so the checks after it still get a turn.
    ``progress[check]`` is written before any interrupt is re-raised, so a check cut mid-range still says where it stands."""
    prev = saved.get(check) if isinstance(saved.get(check), dict) else {}
    pending = prev.get("pending") if isinstance(prev.get("pending"), dict) else None
    last_complete = prev.get("last_complete") if isinstance(prev.get("last_complete"), dict) else None
    if pending is not None:
        through, nxt, tally = int(pending.get("through_id", 0)), int(pending.get("next_id", 0)), int(pending.get("tally", 0))
        step, started = int(pending.get("step") or _FIRST_RANGE_ROWS), str(pending.get("started_at") or _now_iso())
    else:
        top = _scalar(session, f"SELECT MAX(id) FROM {table}")  # nosec B608 - `table` is one of three constants above
        if top is None:
            progress[check] = {"state": "unreadable", "last_complete": last_complete}
            return None
        through, nxt, tally, step, started = top, 0, 0, _FIRST_RANGE_ROWS, _now_iso()
    interrupted: BaseException | None = None
    while nxt < through:
        if deadline_expired(session) or (stop_at is not None and time.monotonic() >= stop_at):
            break
        hi = min(nxt + max(1, step), through)
        t0 = time.monotonic()
        try:
            n = _scalar(session, sql, {"lo": nxt, "hi": hi})
        except Exception as exc:  # noqa: BLE001 - the budget's own interrupt: keep the place, then let the deadline type it
            interrupted = exc
            break
        if n is None:
            break  # a missing or damaged table: degraded, and the cursor stays where it was
        tally += n
        nxt = hi
        took = max(time.monotonic() - t0, 1e-3)
        step = max(1, min(step * _RANGE_GROWTH, int(step * _RANGE_TARGET_S / took)))
    done = nxt >= through
    if done:
        last_complete = {"value": tally, "through_id": through, "started_at": started, "at": _now_iso()}
        saved[check] = {"last_complete": last_complete}
        progress[check] = {"state": "complete", "through_id": through, "next_id": through, "tally": tally, "last_complete": last_complete}
    else:
        saved[check] = {
            "pending": {"through_id": through, "next_id": nxt, "tally": tally, "step": step, "started_at": started},
            "last_complete": last_complete,
        }
        progress[check] = {
            "state": "partial", "through_id": through, "next_id": nxt, "tally_so_far": tally,
            "started_at": started, "last_complete": last_complete,
        }
    if interrupted is not None:
        raise interrupted
    return tally if done else None


def _fk_scan(session: Session, saved: dict[str, Any], progress: dict[str, Any], stop_at: float | None = None) -> int | None:
    """``PRAGMA foreign_key_check`` one table at a time, from the tables the last build had not reached.

    A table at a time because the whole-database pragma is one statement the deadline cannot stop and one that never finished on a 14 GB corpus.
    The mentions table is left to the two dangling-mention checks, which are the same two foreign keys counted exactly in ranges; it is named in
    the progress, never silently dropped."""
    prev = saved.get("foreign_key_violations") if isinstance(saved.get("foreign_key_violations"), dict) else {}
    pending = prev.get("pending") if isinstance(prev.get("pending"), dict) else None
    last_complete = prev.get("last_complete") if isinstance(prev.get("last_complete"), dict) else None
    try:
        names = [str(r[0]) for r in session.execute(text("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")).fetchall()]
    except Exception as exc:  # noqa: BLE001
        progress["foreign_key_violations"] = {"state": "unreadable", "last_complete": last_complete}
        if _budget_spent(session, exc):
            raise
        return None
    names = [n for n in names if _TABLE_NAME.match(n) and n != _MENTIONS_TABLE]
    done_tables: dict[str, int] = {k: int(v) for k, v in (pending or {}).get("tables", {}).items() if k in names}
    bad: set[str] = {str(t) for t in (pending or {}).get("violating_tables", [])}
    started = str((pending or {}).get("started_at") or _now_iso())
    interrupted: BaseException | None = None
    for name in names:
        if name in done_tables:
            continue
        if deadline_expired(session) or (stop_at is not None and time.monotonic() >= stop_at):
            break
        try:
            rows = session.execute(text(f'PRAGMA foreign_key_check("{name}")')).fetchall()  # nosec B608 - `name` matched [A-Za-z0-9_]+ above
        except Exception as exc:  # noqa: BLE001
            if _budget_spent(session, exc):
                interrupted = exc
            break
        done_tables[name] = len(rows)
        if rows:
            bad.add(name)
    finished = all(n in done_tables for n in names)
    total = sum(done_tables.values())
    if finished:
        last_complete = {"value": total, "tables": len(names), "started_at": started, "at": _now_iso()}
        saved["foreign_key_violations"] = {"last_complete": last_complete}
        progress["foreign_key_violations"] = {
            "state": "complete", "tables_checked": len(names), "violating_tables": sorted(bad),
            "left_to_the_mention_checks": [_MENTIONS_TABLE], "last_complete": last_complete,
        }
    else:
        saved["foreign_key_violations"] = {
            "pending": {"tables": done_tables, "violating_tables": sorted(bad), "started_at": started},
            "last_complete": last_complete,
        }
        progress["foreign_key_violations"] = {
            "state": "partial", "tables_checked": len(done_tables), "tables_total": len(names),
            "tally_so_far": total, "violating_tables": sorted(bad), "started_at": started,
            "left_to_the_mention_checks": [_MENTIONS_TABLE], "last_complete": last_complete,
        }
    if interrupted is not None:
        raise interrupted
    return total if finished else None


#: The checks whose results the verdict is read from, and the report key each lives at.
_VERDICT_CHECKS = (
    ("orphan_keywords", ("orphan_keywords",)),
    ("dangling_mentions_missing_article", ("dangling_mentions_missing_article",)),
    ("dangling_mentions_missing_keyword", ("dangling_mentions_missing_keyword",)),
    ("counter_drift_mentions", ("counter_drift", "keywords_with_mention_drift")),
    ("counter_drift_articles", ("counter_drift", "keywords_with_article_drift")),
    ("foreign_key_violations", ("foreign_key_violations",)),
)


def _verdict(report: dict[str, Any]) -> tuple[bool | None, list[str], list[str]]:
    """``drift`` from the checks that COMPLETED, never from a blank (INT-1).

    True when any completed check found drift; False only when EVERY check completed
    and none did; None ("not established") when none found drift but at least one did
    not complete -- a sweep that ran out of budget has not shown there is no drift.
    Returns the verdict, the checks that found drift, and the checks that did not
    complete."""
    found: list[str] = []
    incomplete: list[str] = []
    for name, path in _VERDICT_CHECKS:
        v: Any = report
        for k in path:
            v = v.get(k) if isinstance(v, dict) else None
        if v is None:
            incomplete.append(name)
        elif v:
            found.append(name)
    if found:
        return True, found, incomplete
    return (None if incomplete else False), found, incomplete


def corpus_integrity(
    session: Session, *, sample: int = 500, full: bool = False, cursor: CursorStore | None = None
) -> dict[str, Any]:
    """Sweep the corpus for silent drift. Read-only, bounded, deadline-guarded.

    - orphan keywords (a keyword with zero mentions — the prune target);
    - dangling mentions (a mention whose article or keyword row is gone — FK breaks);
    - counter drift (Keyword.mention_count / article_count vs the live aggregate),
      SAMPLED over the top-``sample`` keywords by mention_count unless ``full``;
    - FTS staleness (the search index row count vs the article count);
    - a bounded ``PRAGMA foreign_key_check`` tally.
    """
    bind = session.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", "")
    if dialect != "sqlite":
        return {
            "supported": False,
            "dialect": dialect,
            "note": "integrity introspection is implemented for SQLite (the app's store).",
        }

    report: dict[str, Any] = {"supported": True, "dialect": dialect}
    timed_out = False
    saved: dict[str, Any] = cursor.load() if cursor is not None else {}
    progress: dict[str, Any] = {}

    try:
        with statement_deadline(session):
            # -- counter drift (sampled by default) ------------------------------ #
            # Recompute the true mention/article counts for the highest-mention
            # keywords and compare to the maintained counters. Drift here means the
            # reconcile pass is due; the exact live aggregate is the source of truth.
            # SAMPLED: the top-``sample`` keywords are picked FIRST (an index-only read of ``mention_count``) and only
            # those are joined to their mentions. The earlier form grouped EVERY keyword and sorted afterwards: on the
            # 4.09 M keywords of the 2026-11-07 Windows run it never finished inside the budget. The rows are the same.
            if full:
                source_rows = "keywords"
            else:
                source_rows = (
                    "(SELECT id, term, mention_count, article_count FROM keywords "
                    f"ORDER BY mention_count DESC LIMIT {int(sample)})"
                )
            checked = 0
            mention_drift = 0
            article_drift = 0
            worst: list[dict[str, Any]] = []
            # C5: whether the query actually ran, tracked explicitly rather than inferred
            # from an empty `rows` -- a genuinely clean sample of `sample` keywords also
            # yields zero drift, so "0 drifting" is ambiguous with "never looked" unless
            # the two are told apart by a flag, not by the numbers themselves.
            drift_count_status = "ok"
            try:
                rows = session.execute(
                    text(
                        "SELECT k.id, k.term, k.mention_count, k.article_count, "  # nosec B608 - `source_rows` is a constant or built from int(sample); no user input
                        "COALESCE(SUM(m.count),0) AS live_mentions, "
                        "COUNT(m.article_id) AS live_articles "
                        f"FROM {source_rows} k LEFT JOIN keyword_mentions_all m ON m.keyword_id = k.id "
                        "GROUP BY k.id"
                    )
                ).fetchall()
            except StatementTimeout:
                raise
            except Exception as exc:  # noqa: BLE001 - a missing/corrupt table degrades, never 500
                if _budget_spent(session, exc):
                    raise  # the budget ran out: the enclosing deadline types it (INT-1)
                rows = []
                drift_count_status = "error"
                report["counter_drift_error"] = record_text(exc, limit=200, typed=False)
                # C5 reconciliation: this failure previously reached only the report
                # dict, never the standard `logging` module -- so it never landed in
                # app_errors.jsonl and `errorlog.interrupted_errors_total` (which scans
                # THAT log for "interrupted") stayed 0 even when this field read
                # literally "interrupted". Logging it here is what makes the two
                # counters agree, and is a real fact worth keeping regardless (a
                # missing/corrupt table or an uncaught interrupt is a genuine problem,
                # not merely a degraded diagnostic read).
                log_failure(_LOG, "corpus-integrity: counter-drift query failed", exc, level=logging.WARNING)
            for kid, term, mc, ac, live_m, live_a in rows:
                checked += 1
                dm = abs(int(mc or 0) - int(live_m or 0))
                da = abs(int(ac or 0) - int(live_a or 0))
                if dm:
                    mention_drift += 1
                if da:
                    article_drift += 1
                if (dm or da) and len(worst) < 25:
                    worst.append(
                        {
                            "keyword_id": int(kid),
                            "term": term,
                            "mention_count": int(mc or 0),
                            "live_mentions": int(live_m or 0),
                            "article_count": int(ac or 0),
                            "live_articles": int(live_a or 0),
                        }
                    )
            # C5: on the error path the counts were never computed -- report them as
            # `None` (the fts_status `count_status` shape, copied exactly), never as a
            # fabricated zero indistinguishable from a genuinely clean sample.
            ok = drift_count_status == "ok"
            report["counter_drift"] = {
                "mode": "full" if full else "sampled",
                "count_status": drift_count_status,
                "checked": checked if ok else None,
                "sample": None if full else int(sample),
                "keywords_with_mention_drift": mention_drift if ok else None,
                "keywords_with_article_drift": article_drift if ok else None,
                "examples": worst,
            }

            # (FTS presence/health/staleness is probed OUTSIDE this shared deadline — see
            #  below — so its authoritative sqlite_master read and its own bounded row COUNT
            #  never race the counter-drift scan for the shared budget.)

            # -- the resumable checks: orphan / dangling tallies in id ranges, foreign keys a table at a time ------ #
            # They run AFTER the one-statement sampled drift read, and each takes an equal share of what is left of
            # the budget (recomputed as each one finishes, so time a quick check leaves goes to the next): one long
            # walk over a 25 M-row table must not starve the others, which on the 2026-11-07 corpus left the drift
            # read and the foreign-key check never run. A check that did not reach the end reads None (not
            # established) with its place in ``scan_progress``, never a partial tally dressed as the figure.
            resumable: list[str] = [c for c, _t, _q in _RANGE_SCANS] + ["foreign_key_violations"]
            for i, check in enumerate(resumable):
                left = deadline_left_s(session)
                stop_at = None if left is None else time.monotonic() + max(left, 0.0) / (len(resumable) - i)
                if check == "foreign_key_violations":
                    report[check] = _fk_scan(session, saved, progress, stop_at)
                    report["foreign_key_violation_tables"] = progress[check].get("violating_tables") or []
                else:
                    _c, table, sql = next(r for r in _RANGE_SCANS if r[0] == check)
                    report[check] = _range_scan(session, check, table, sql, saved, progress, stop_at)
            # A range scan that stops between ranges raises nothing: the budget running out is read here, not inferred.
            if deadline_expired(session):
                timed_out = True
    except StatementTimeout:
        timed_out = True
    # A check the budget never reached says so, rather than vanishing from the progress.
    for check in [c for c, _t, _q in _RANGE_SCANS] + ["foreign_key_violations"]:
        progress.setdefault(check, {"state": "not reached"})

    # -- FTS presence / health / staleness (D4) --------------------------------- #
    # Probed OUTSIDE the shared counter-drift deadline (which has now exited, restoring the
    # progress handler): presence comes from sqlite_master — authoritative, and the SAME
    # source the schema-drift probe reads, so the two can no longer disagree — and the row
    # COUNT gets its OWN bounded budget. The old COUNT-based presence mislabelled a slow or
    # damaged index as "absent" (the 2026-07-09 contradiction: integrity said absent while
    # schema-drift said present, fts_rows null). fts_status also detects post-crash corruption
    # (healthy=false) so a re-index can heal it.
    from src.database.fts import fts_status

    # The article count is taken BEFORE the index's: a row ingested between the two reads can then only
    # push ``delta`` below zero (an index ahead of a count), never read as a document the index missed.
    arts = None
    try:
        with statement_deadline(session, seconds=15):
            _a = session.execute(text("SELECT count(*) FROM articles")).scalar()
        arts = int(_a) if _a is not None else 0
    except Exception:  # noqa: BLE001 - a slow/failed article count degrades only the delta
        arts = None
    fts = fts_status(session)
    fts_rows = fts.get("rows")
    indexed = fts.get("indexed_documents")
    report["fts"] = {
        "present": fts.get("present"),
        "healthy": fts.get("healthy"),
        "articles": arts,
        "fts_rows": fts_rows,
        "indexed_documents": indexed,
        "indexed_status": fts.get("indexed_status"),
        "index_state": fts.get("index_state"),
        "count_status": fts.get("count_status"),
        "error": fts.get("error"),
        "delta": None if (arts is None or indexed is None) else arts - indexed,
        "note": (
            "fts_rows reads articles, not the index; indexed_documents is the index's own count; "
            "delta = articles - indexed_documents (large: rebuild); healthy=false: damaged, empty or partial (re-index heals)."
        ),
    }

    # The automatic keyword-cleanup run (prune orphans + reconcile language) is
    # freshness-gated and off the request path; surface its last run + tally here so the
    # cleanup is visible in the diagnostics ("automatic AND part of the logs").
    try:
        from src.analytics.store import keyword_cleanup_state

        report["auto_cleanup"] = keyword_cleanup_state()
    except Exception:  # noqa: BLE001
        report["auto_cleanup"] = {"last_run": None}

    # DB-10 §1a/§3: the off-peak incremental-vacuum pass is likewise freshness-gated
    # and off the request path; surface its last run + tally for the same reason.
    try:
        from src.database.maintenance import incremental_vacuum_state

        report["auto_incremental_vacuum"] = incremental_vacuum_state()
    except Exception:  # noqa: BLE001
        report["auto_incremental_vacuum"] = {"last_run": None}

    if cursor is not None:
        cursor.save(saved)
    report["scan_progress"] = progress
    report["timed_out"] = timed_out
    drift, found, incomplete = _verdict(report)
    report["drift"] = drift
    report["drift_found_in"] = found
    report["incomplete_checks"] = incomplete
    report["complete_checks"] = [name for name, _ in _VERDICT_CHECKS if name not in incomplete]
    report["verdict"] = ("drift" if drift else ("no drift" if drift is False else
                         "not established: " + ", ".join(incomplete) + " did not complete"
                         + ("; " + ", ".join(report["complete_checks"]) + " did" if report["complete_checks"] else "")))
    report["method"] = (
        "Read-only, deadline-guarded SQLite sweep. Orphan/dangling tallies are exact "
        "(index-backed); counter drift is sampled over the top-mention keywords unless "
        "full=1. Reports drift, never fixes it (the reconcile/prune passes own that). "
        "Counts/names only, no score. The verdict is read from COMPLETED checks only: "
        "drift=true if any found drift, false only if all completed clean, null when a "
        "check did not complete (incomplete_checks names them; timed_out says whether "
        "the budget ran out)."
    )
    return report
