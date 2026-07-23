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

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.database.maintenance import StatementTimeout, statement_deadline


def _scalar(session: Session, sql: str) -> int | None:
    try:
        row = session.execute(text(sql)).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:  # noqa: BLE001 - a diagnostic must degrade, never crash
        return None


def corpus_integrity(session: Session, *, sample: int = 500, full: bool = False) -> dict[str, Any]:
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

    try:
        with statement_deadline(session):
            # -- orphan / dangling row tallies (index-backed EXISTS) -------------- #
            report["orphan_keywords"] = _scalar(
                session,
                "SELECT COUNT(*) FROM keywords k "
                "WHERE NOT EXISTS (SELECT 1 FROM keyword_mentions m WHERE m.keyword_id = k.id)",
            )
            report["dangling_mentions_missing_article"] = _scalar(
                session,
                "SELECT COUNT(*) FROM keyword_mentions m "
                "WHERE NOT EXISTS (SELECT 1 FROM articles a WHERE a.id = m.article_id)",
            )
            report["dangling_mentions_missing_keyword"] = _scalar(
                session,
                "SELECT COUNT(*) FROM keyword_mentions m "
                "WHERE NOT EXISTS (SELECT 1 FROM keywords k WHERE k.id = m.keyword_id)",
            )

            # -- counter drift (sampled by default) ------------------------------ #
            # Recompute the true mention/article counts for the highest-mention
            # keywords and compare to the maintained counters. Drift here means the
            # reconcile pass is due; the exact live aggregate is the source of truth.
            scope = "" if full else f"ORDER BY mention_count DESC LIMIT {int(sample)}"
            checked = 0
            mention_drift = 0
            article_drift = 0
            worst: list[dict[str, Any]] = []
            try:
                rows = session.execute(
                    text(
                        "SELECT k.id, k.term, k.mention_count, k.article_count, "  # nosec B608 - `scope` is a constant "ORDER BY mention_count DESC LIMIT <int>" built from int(sample); no user input
                        "COALESCE(SUM(m.count),0) AS live_mentions, "
                        "COUNT(m.article_id) AS live_articles "
                        "FROM keywords k LEFT JOIN keyword_mentions m ON m.keyword_id = k.id "
                        f"GROUP BY k.id {scope}"
                    )
                ).fetchall()
            except StatementTimeout:
                raise
            except Exception as exc:  # noqa: BLE001 - a missing/corrupt table degrades, never 500
                rows = []
                report["counter_drift_error"] = str(exc)[:200]
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
            report["counter_drift"] = {
                "mode": "full" if full else "sampled",
                "checked": checked,
                "sample": None if full else int(sample),
                "keywords_with_mention_drift": mention_drift,
                "keywords_with_article_drift": article_drift,
                "examples": worst,
            }

            # (FTS presence/health/staleness is probed OUTSIDE this shared deadline — see
            #  below — so its authoritative sqlite_master read and its own bounded row COUNT
            #  never race the counter-drift scan for the shared budget.)

            # -- foreign-key integrity (bounded) --------------------------------- #
            try:
                fk_rows = session.execute(text("PRAGMA foreign_key_check")).fetchall()
                report["foreign_key_violations"] = len(fk_rows)
                report["foreign_key_violation_tables"] = sorted(
                    {str(r[0]) for r in fk_rows[:5000]}
                )
            except Exception:  # noqa: BLE001
                report["foreign_key_violations"] = None
    except StatementTimeout:
        timed_out = True

    # -- FTS presence / health / staleness (D4) --------------------------------- #
    # Probed OUTSIDE the shared counter-drift deadline (which has now exited, restoring the
    # progress handler): presence comes from sqlite_master — authoritative, and the SAME
    # source the schema-drift probe reads, so the two can no longer disagree — and the row
    # COUNT gets its OWN bounded budget. The old COUNT-based presence mislabelled a slow or
    # damaged index as "absent" (the 2026-07-09 contradiction: integrity said absent while
    # schema-drift said present, fts_rows null). fts_status also detects post-crash corruption
    # (healthy=false) so a re-index can heal it.
    from src.database.fts import fts_status

    fts = fts_status(session)
    arts = None
    try:
        with statement_deadline(session, seconds=15):
            _a = session.execute(text("SELECT count(*) FROM articles")).scalar()
        arts = int(_a) if _a is not None else 0
    except Exception:  # noqa: BLE001 - a slow/failed article count degrades only the delta
        arts = None
    fts_rows = fts.get("rows")
    report["fts"] = {
        "present": fts.get("present"),
        "healthy": fts.get("healthy"),
        "articles": arts,
        "fts_rows": fts_rows,
        "count_status": fts.get("count_status"),
        "error": fts.get("error"),
        "delta": None if (arts is None or fts_rows is None) else arts - fts_rows,
        "note": (
            "Presence is read from the schema, never a COUNT (which on a large FTS index can "
            "time out and would then be misread as absent). article_fts is kept in sync by "
            "triggers; a large delta means the index is stale (re-run the FTS rebuild); "
            "healthy=false means the index is damaged (a re-index heals it)."
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

    report["timed_out"] = timed_out
    report["drift"] = bool(
        (report.get("orphan_keywords") or 0)
        or (report.get("dangling_mentions_missing_article") or 0)
        or (report.get("dangling_mentions_missing_keyword") or 0)
        or (report.get("counter_drift", {}).get("keywords_with_mention_drift") or 0)
        or (report.get("counter_drift", {}).get("keywords_with_article_drift") or 0)
        or (report.get("foreign_key_violations") or 0)
    )
    report["method"] = (
        "Read-only, deadline-guarded SQLite sweep. Orphan/dangling tallies are exact "
        "(index-backed); counter drift is sampled over the top-mention keywords unless "
        "full=1. Reports drift, never fixes it (the reconcile/prune passes own that). "
        "Counts/names only, no score."
    )
    return report
