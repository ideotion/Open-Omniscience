"""Storage composition — what the on-disk gigabytes actually ARE (P1.5, SCALE_ROADMAP).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 2026-07-09 field event grew the data folder to ~130 GB with an 11.7 GB database and
~120 GB of unidentified growth. Session forensics (:mod:`src.monitoring.forensics`) names
the FILES; this module names the INSIDE of the database file — per-table and per-index
byte totals via SQLite's ``dbstat`` virtual table — so the growth conversation ("which
table is the 11.7 GB? how much is mentions vs articles vs FTS shadow tables vs indexes?")
runs on measured numbers, and the P0.1 backup / P1.5 retention rulings are informed by
what the bytes actually are.

HONESTY + SAFETY:
  * counts/bytes only — never a score, never a recommendation;
  * READ-ONLY (dbstat walks btree pages; it writes nothing);
  * degrade, never 500: ``dbstat`` needs the SQLITE_ENABLE_DBSTAT_VTAB compile flag —
    absent (some SQLCipher builds), the report says ``{"available": false, reason}``
    honestly; a deadline abort reports itself the same way (the walk visits every page of
    the file, which through the SQLCipher codec can exceed the statement deadline on a
    very large corpus — stated in the caveat, never a hang).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.database.maintenance import StatementTimeout, statement_deadline

_LOG = logging.getLogger(__name__)

_METHOD = (
    "SQLite dbstat virtual table: per-btree page and byte totals, indexes grouped under "
    "their table (FTS/shadow tables appear under their own names). Bytes are on-disk "
    "pages including per-btree free space; the -wal/-shm files are NOT inside the main "
    "file (see session forensics for the file-level inventory). Counts/bytes only, "
    "no score."
)
_CAVEAT = (
    "dbstat walks the whole file's page structure through the SQLCipher codec — on a "
    "very large corpus this is a deliberate, on-demand measurement (bounded by the "
    "statement deadline; an abort is reported, never a hang)."
)


def _rows(session: Session, sql: str) -> list:
    return list(session.execute(text(sql)))


def _pragma(session: Session, name: str) -> int | None:
    try:
        # `name` is a module-internal constant pragma name, never user input.
        row = session.execute(text(f"PRAGMA {name}")).fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except Exception:  # noqa: BLE001 - a diagnostic read degrades, never raises
        return None


def _last_wal_checkpoint() -> dict[str, Any] | None:
    """The most recent REAL checkpoint measurement, lifted out of the scheduler run log.

    The scheduler already measures a TRUNCATE checkpoint every pass and persists it to
    ``scheduler_runs.jsonl`` — but it was only ever readable from the bundle's *scheduler*
    section, so the one member an operator opens to judge WAL health could not say whether
    a checkpoint had recently completed, or been blocked by a long-lived reader
    (``busy: 1`` — the starvation signature). Best-effort: a missing/unreadable log yields
    None, never an exception into the diagnostic.
    """
    try:
        from src.scheduler.runlog import recent_runs

        for run in recent_runs(limit=50):
            ck = (run.get("hygiene") or {}).get("wal_checkpoint")
            # S2.5: a gate-busy SKIP is also a dict, and taking it here would
            # report "the most recent real checkpoint measurement" for a
            # checkpoint that never ran -- with no busy flag and no
            # wal_bytes_after to contradict it. It is surfaced separately by
            # _last_wal_checkpoint_skip so the absence still has a reason.
            if isinstance(ck, dict) and "skipped" not in ck:
                out = dict(ck)
                when = run.get("finished_at") or run.get("started_at")
                if when:
                    out["run_at"] = when
                return out
    except Exception:  # noqa: BLE001 - a diagnostic read degrades, never raises
        return None
    return None


def _last_wal_checkpoint_skip() -> dict[str, Any] | None:
    """The most recent checkpoint that was REFUSED, with its reason.

    Reported beside ``last_checkpoint`` rather than folded into it: a WAL that
    has not been reclaimed because a writer held the gate, and one that has not
    been reclaimed because a reader pinned it (``busy: 1``), point at different
    subsystems, and a reader who cannot tell them apart looks in the wrong one.
    """
    try:
        from src.scheduler.runlog import recent_runs

        for run in recent_runs(limit=50):
            ck = (run.get("hygiene") or {}).get("wal_checkpoint")
            if isinstance(ck, dict) and "skipped" in ck:
                out = dict(ck)
                when = run.get("finished_at") or run.get("started_at")
                if when:
                    out["run_at"] = when
                return out
    except Exception:  # noqa: BLE001 - a diagnostic read degrades, never raises
        return None
    return None


def _wal_history(session: Session) -> dict[str, Any] | None:
    """The recorded ``wal_bytes`` series — the only view that can show a WAL growing
    across days, which is exactly what a single point-in-time reading cannot.

    Bounded to a 30-day response (storage retention is infinite by ruling; the READ
    window is a query-time concern). ``recording_began_at`` travels with it so an empty
    window reads as "not recorded yet", never as "the WAL was fine".
    """
    try:
        from src.database.snapshots import metric_history

        hist = metric_history(session, metric="wal_bytes", days=30)
        if hist.get("error"):
            return None
        series = hist.get("series") or []
        out: dict[str, Any] = {
            "series": series,
            "recording_began_at": hist.get("recording_began_at"),
            "days": 30,
        }
        if series:
            values = [int(p["n"]) for p in series]
            out["min_bytes"] = min(values)
            out["max_bytes"] = max(values)
            out["n"] = len(values)
        return out
    except Exception:  # noqa: BLE001 - a diagnostic read degrades, never raises
        return None


def storage_composition(session: Session) -> dict[str, Any]:
    """Per-table / per-index byte composition of the live SQLite store.

    Returns ``{"available": false, "reason": …}`` (plus whatever PRAGMA-level facts were
    readable) when dbstat is unavailable, the backend is not SQLite, or the deadline
    aborts the walk — an honest degrade block, never an exception to the caller."""
    bind = session.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", "")
    if dialect != "sqlite":
        return {
            "available": False,
            "dialect": dialect,
            "reason": "storage composition is implemented for SQLite (the app's store).",
        }

    out: dict[str, Any] = {"available": True, "dialect": dialect}
    # File-level page facts (cheap PRAGMAs — readable even where dbstat is not).
    page_size = _pragma(session, "page_size")
    page_count = _pragma(session, "page_count")
    freelist = _pragma(session, "freelist_count")
    out["page_size"] = page_size
    out["page_count"] = page_count
    out["freelist_pages"] = freelist
    # DB-10 instrument: is the freelist even RECLAIMABLE without a full VACUUM? auto_vacuum
    # (0 none / 1 full / 2 incremental) is a CREATE-time seam — a corpus created with 'none'
    # can only reclaim via a full VACUUM (rewrites the whole file), infeasible at scale.
    av = _pragma(session, "auto_vacuum")
    out["auto_vacuum"] = {0: "none", 1: "full", 2: "incremental"}.get(av) if av is not None else None
    # WAL VISIBILITY (STORAGE_5TB_PLAN §3 Phase-A: "surface WAL size … so an unbounded -wal is
    # VISIBLE"). journal_size_limit is the resting ceiling we set (session.py); wal_bytes is the
    # -wal file's ACTUAL size right now (a -wal much larger than the limit ⇒ a checkpoint is not
    # completing — the classic reader-starvation hazard, now diagnosable). Both degrade to None.
    jsl = _pragma(session, "journal_size_limit")
    out["journal_size_limit"] = jsl if (jsl is not None and jsl >= 0) else None
    # wal_autocheckpoint is the OTHER half of WAL sizing, and was never read in
    # production: it is the page threshold at which a WRITER checkpoints on its own,
    # BETWEEN our inter-pass TRUNCATE checkpoints. A store where it is 0/negative has
    # automatic checkpointing DISABLED and grows its -wal until the scheduler's next
    # pass — a state indistinguishable from a healthy one in every export produced
    # before this. Reported in SQLite's own unit (pages) and, when page_size is known,
    # resolved to bytes so it is directly comparable with journal_size_limit/wal_bytes.
    wac = _pragma(session, "wal_autocheckpoint")
    out["wal_autocheckpoint_pages"] = wac
    if wac is not None:
        out["wal_autocheckpoint_bytes"] = (wac * page_size) if (wac > 0 and page_size) else None
        if wac <= 0:
            out["wal_autocheckpoint_note"] = (
                "automatic checkpointing is DISABLED on this connection — the -wal grows "
                "until an explicit checkpoint runs (the scheduler's inter-pass TRUNCATE)."
            )
    try:
        main_db = None
        for row in _rows(session, "PRAGMA database_list"):
            if len(row) >= 3 and str(row[1]) == "main" and row[2]:
                main_db = str(row[2])
                break
        if main_db:
            wal = Path(main_db + "-wal")
            out["wal_bytes"] = wal.stat().st_size if wal.exists() else 0
            if out.get("journal_size_limit") and out["wal_bytes"] > 4 * out["journal_size_limit"]:
                out["wal_note"] = (
                    "the -wal is much larger than journal_size_limit — a checkpoint may be "
                    "starved (a long-lived reader blocks it), the workload's known WAL-growth "
                    "hazard. The inter-pass TRUNCATE checkpoint should reclaim it when writers idle."
                )
    except Exception:  # noqa: BLE001 - WAL visibility is best-effort; never break the diagnostic
        pass
    # Did a checkpoint actually complete, and when? (present only when the scheduler has
    # run at least once and recorded one — absence is honest, never a fabricated "ok".)
    last_ck = _last_wal_checkpoint()
    if last_ck is not None:
        out["last_checkpoint"] = last_ck
    # ...and the most recent REFUSAL, if any: an un-reclaimed WAL whose
    # checkpoint never got the write gate is a different finding from one whose
    # TRUNCATE ran and reported busy=1 (a reader pinning it).
    last_skip = _last_wal_checkpoint_skip()
    if last_skip is not None:
        out["last_checkpoint_skipped"] = last_skip
    # Is it growing ACROSS DAYS? No single reading can answer that.
    hist = _wal_history(session)
    if hist is not None:
        out["wal_history"] = hist
    # The storage guard (rank 1/2/6): engagements, the limits it derived from THIS machine,
    # the last drain and the named pin report, plus six hours of WAL and free-disk samples.
    # Carried here so every bundle shows it without a new export section.
    try:
        from src.scheduler.storage_guard import storage_guard

        out["storage_guard"] = storage_guard.state(detail=True)
    except Exception:  # noqa: BLE001 - visibility is best-effort; never break the diagnostic
        pass
    if page_size and page_count is not None:
        out["db_bytes"] = page_size * page_count
    if page_size and freelist is not None:
        out["free_bytes"] = page_size * freelist  # reclaimable only via (in)cremental vacuum
        if out.get("auto_vacuum") == "none":
            out["free_bytes_note"] = (
                "auto_vacuum=none: these freelist bytes are reclaimable ONLY by a full VACUUM "
                "(rewrites the whole file, ~2x disk, exclusive writer) — infeasible at scale. See "
                "docs/design/DB10_RETENTION_VACUUM_MEMO.md (the irreversible CREATE-time seam ruling)."
            )

    # name -> (type, parent table) so indexes/shadow btrees group under their table.
    try:
        master = {
            str(name): (str(typ), str(tbl))
            for name, typ, tbl in _rows(
                session, "SELECT name, type, tbl_name FROM sqlite_master WHERE name IS NOT NULL"
            )
        }
    except Exception as exc:  # noqa: BLE001
        out["available"] = False
        out["reason"] = f"sqlite_master unreadable: {str(exc)[:200]}"
        return out

    # The dbstat walk itself — aggregated form first (one row per btree; far fewer rows),
    # the GROUP BY fallback for older SQLite, and an honest unavailable block otherwise.
    per_btree: dict[str, tuple[int, int]] = {}
    try:
        with statement_deadline(session):
            try:
                rows = _rows(
                    session, "SELECT name, pageno, pgsize FROM dbstat('main', 1)"
                )
                per_btree = {str(n): (int(p or 0), int(b or 0)) for n, p, b in rows}
            except StatementTimeout:
                raise
            except Exception:  # noqa: BLE001 - aggregated form unsupported -> GROUP BY
                rows = _rows(
                    session,
                    "SELECT name, COUNT(*) AS pages, SUM(pgsize) AS bytes "
                    "FROM dbstat GROUP BY name",
                )
                per_btree = {str(n): (int(p or 0), int(b or 0)) for n, p, b in rows}
    except StatementTimeout as exc:
        out["available"] = False
        out["reason"] = (
            f"aborted by the statement deadline ({exc}); the page walk exceeds the "
            "deadline on this corpus — the PRAGMA-level totals above still stand."
        )
        out["method"] = _METHOD
        out["caveat"] = _CAVEAT
        return out
    except Exception as exc:  # noqa: BLE001 - dbstat not compiled in -> honest unavailable
        out["available"] = False
        out["reason"] = (
            "dbstat virtual table unavailable (needs the SQLITE_ENABLE_DBSTAT_VTAB "
            f"compile flag in this SQLite/SQLCipher build): {str(exc)[:200]}"
        )
        out["method"] = _METHOD
        out["caveat"] = _CAVEAT
        # The bundled sqlcipher3 never has dbstat, so on the operator's store the split
        # above can never be taken. A SAMPLED estimate of the article-text share is the
        # one number DB-10 §6 / D47 (b) / D45 need, and it needs no compile flag.
        est = content_share_estimate(session, out.get("db_bytes"))
        if est is not None:
            out["estimate"] = est
        return out

    # Group: every index btree under its parent table; shadow/system btrees keep their
    # own names (their sqlite_master tbl_name points at themselves or their FTS parent).
    tables: dict[str, dict[str, Any]] = {}
    for name, (pages, nbytes) in per_btree.items():
        typ, parent = master.get(name, ("unknown", name))
        if typ == "index":
            t = tables.setdefault(
                parent, {"name": parent, "bytes": 0, "pages": 0, "indexes": []}
            )
            t["indexes"].append({"name": name, "bytes": nbytes, "pages": pages})
        else:
            t = tables.setdefault(name, {"name": name, "bytes": 0, "pages": 0, "indexes": []})
            t["bytes"] += nbytes
            t["pages"] += pages
    report = []
    for t in tables.values():
        idx_bytes = sum(i["bytes"] for i in t["indexes"])
        t["indexes"].sort(key=lambda i: -i["bytes"])
        t["index_bytes"] = idx_bytes
        t["total_bytes"] = t["bytes"] + idx_bytes
        report.append(t)
    report.sort(key=lambda t: -t["total_bytes"])
    out["tables"] = report
    out["measured_bytes"] = sum(t["total_bytes"] for t in report)
    out["method"] = _METHOD
    out["caveat"] = _CAVEAT
    return out


# --------------------------------------------------------------------------- #
# The sampled estimate for stores WITHOUT dbstat (the encrypted production build).
# --------------------------------------------------------------------------- #
_ESTIMATE_PROBES = 400
# D45's measured cliff: an articles-row UPDATE costs one 16 KiB WAL page up to ~16.3 KB of
# stored payload, then several (DECISIONS_2026-09-22 D45).
_ROW_CLIFF_BYTES = 16300

_ESTIMATE_METHOD = (
    "Sampled, not measured (a store of {n} articles or fewer is read in full, and says "
    "'exact'): up to {n} articles picked at evenly spaced ids between the "
    "smallest and largest id (one index seek each), their text measured in BYTES "
    "(length(CAST(content AS BLOB)) plus length(compressed_content)), and the mean "
    "multiplied by the article count (probes that land on an id already sampled are dropped, so 'sampled' can be below the probe count). The share is that product over the file size. "
    "Row counts for the derived tables are max(rowid), an UPPER bound (deleted rows "
    "leave gaps). Counts/bytes only, no score."
)
_ESTIMATE_CAVEAT = (
    "An estimate: it counts the text payload only, not the page slack or the indexes on "
    "articles, and the sample is spread by id, which follows insertion order. "
    "'remainder_bytes' is everything else in the file — the full-text index, the keyword "
    "and other derived rows, and every index — and cannot be split further without dbstat."
)


def _scalar(session: Session, sql: str, params: dict | None = None):
    row = session.execute(text(sql), params or {}).fetchone()
    return row[0] if row else None


def content_share_estimate(session: Session, db_bytes: int | None) -> dict[str, Any] | None:
    """How much of the file is article text, sampled — for builds without dbstat.

    Also answers D45's own question (how many article rows sit above the WAL-page cliff,
    and whether ingest stores the text twice, raw AND compressed). Read-only, bounded by
    the statement deadline; None when the articles table is unreadable, an honest
    ``aborted`` block on a deadline."""
    try:
        with statement_deadline(session):
            lo = _scalar(session, "SELECT min(id) FROM articles")
            hi = _scalar(session, "SELECT max(id) FROM articles")
            if lo is None or hi is None:
                return {"articles": 0, "method": _ESTIMATE_METHOD.format(n=_ESTIMATE_PROBES)}
            n_articles = int(_scalar(session, "SELECT count(*) FROM articles") or 0)
            lo, hi = int(lo), int(hi)
            exact = n_articles <= _ESTIMATE_PROBES
            payloads: list[int] = []
            both = 0
            compressed_only = 0

            def _take(row_id: int, raw_len, comp_len) -> None:
                nonlocal both, compressed_only
                raw, comp = int(raw_len or 0), comp_len
                payloads.append(raw + int(comp or 0))
                if comp is not None and raw > 0:
                    both += 1
                elif comp is not None:
                    compressed_only += 1

            if exact:
                # Every row: exact, and no dearer than the probes it replaces.
                for row in session.execute(
                    text(
                        "SELECT id, length(CAST(content AS BLOB)), length(compressed_content) "
                        "FROM articles"
                    )
                ):
                    _take(int(row[0]), row[1], row[2])
            else:
                k = _ESTIMATE_PROBES
                step = (hi - lo) / (k - 1)
                seen: set[int] = set()
                for i in range(k):
                    probe = session.execute(
                        text(
                            "SELECT id, length(CAST(content AS BLOB)), "
                            "length(compressed_content) "
                            "FROM articles WHERE id >= :p ORDER BY id LIMIT 1"
                        ),
                        {"p": lo + round(i * step)},
                    ).fetchone()
                    if probe is None or int(probe[0]) in seen:
                        continue
                    seen.add(int(probe[0]))
                    _take(int(probe[0]), probe[1], probe[2])
            present = {
                str(r[0])
                for r in _rows(session, "SELECT name FROM sqlite_master WHERE type='table'")
            }
            derived = {}
            for table in (
                "keyword_mentions",
                "keywords",
                "article_mentioned_places",
                "article_entities",
            ):
                if table in present:  # module-constant names, never user input
                    derived[table] = _scalar(session, f"SELECT max(rowid) FROM {table}")  # nosec B608 - table is one of four fixed module-constant names, never input
    except StatementTimeout as exc:
        return {
            "aborted": True,
            "reason": f"stopped before the sample finished, by the statement deadline or the memory guard ({exc})",
            "method": _ESTIMATE_METHOD.format(n=_ESTIMATE_PROBES),
        }
    except Exception as exc:  # noqa: BLE001 - a diagnostic degrades, never raises
        _LOG.debug("content share estimate unavailable: %s", exc)
        return None

    sampled = len(payloads)
    out: dict[str, Any] = {
        "articles": n_articles,
        "sampled": sampled,
        "exact": exact,
        "method": _ESTIMATE_METHOD.format(n=_ESTIMATE_PROBES),
        "caveat": _ESTIMATE_CAVEAT,
    }
    if not sampled:
        return out
    mean = sum(payloads) / sampled
    text_bytes = int(mean * n_articles)
    out["mean_text_bytes_per_article"] = int(mean)
    out["article_text_bytes"] = text_bytes
    if db_bytes:
        out["article_text_share"] = round(text_bytes / db_bytes, 3)
        if text_bytes > db_bytes:
            out["exceeds_file"] = (
                "the extrapolated text is larger than the file: the sample over-represents "
                "large articles, or the file holds compressed pages. Read the share as an "
                "upper bound, not a measurement."
            )
        else:
            out["remainder_bytes"] = int(db_bytes) - text_bytes
    over = sum(1 for p in payloads if p > _ROW_CLIFF_BYTES)
    out["row_cliff"] = {
        "cliff_bytes": _ROW_CLIFF_BYTES,
        "sampled_over": over,
        "share_over": round(over / sampled, 3),
        "note": (
            "D45: an UPDATE of a row above the cliff writes several WAL pages instead of one. "
            "A LOWER BOUND: only the text columns are counted, so a row whose text plus its "
            "url, title and other columns crosses the cliff is counted below it."
        ),
    }
    out["text_stored_twice"] = {
        "sampled_raw_and_compressed": both,
        "sampled_compressed_only": compressed_only,
        "note": "D45: rows holding both the plain and the compressed text pay for it twice.",
    }
    out["derived_rows_upper_bound"] = derived
    return out
