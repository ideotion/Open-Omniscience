"""
The debug bundle and the all-diagnostics archive (members, manifest, job, volumes).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Part of the mechanical ``src/api/diagnostics.py`` -> package split (Q1139 = a,
2026-09-16): this file is lines 3468-5424 of the pre-split module, verbatim. The
routes, their paths, their methods and their order are unchanged; ``__init__``
imports the submodules in the original file order so the decorators still
register on one router in that order.
"""

from __future__ import annotations

import contextlib
import json
import os
import pathlib
import threading
from datetime import datetime

from fastapi import Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.database.maintenance import StatementTimeout, deadline_expired, statement_deadline
from src.database.models import Article, Keyword, KeywordMention, Source
from src.database.read_snapshot import read_only_db
from src.database.session import get_db
from src.jobs.background import BackgroundJob, register_job
from src.utils.export_envelope import app_version, envelope

from ._base import _LOG, _MAX_KEYWORDS_PER_LANG, api_dir, package_source, router
from .corpus import (
    article_length,
    bulletin_language,
    bulletin_language_selftest,
    card_audit,
    criteria_calibration,
    home_card_diagnostics,
    keyword_engine,
    keyword_growth,
    leads_quality,
    lemma_preview,
    month_occupancy,
    non_article_scan,
    power_profile,
    power_profile_selftest,
)
from .dates import date_extraction_log
from .evals import (
    _run_journal_raw,
    ir_eval_selftest,
    keyword_triage_selftest,
    kpi,
    merge_diag,
    perception_eval_live_last,
    perception_eval_selftest,
    recursive_loop,
    run_journal,
    run_timeline,
    search_timing,
    search_timing_selftest,
)
from .keywords import keyword_log, keyword_selftest
from .performance import (
    ai_activity,
    ai_activity_selftest,
    benchmark_report,
    bulletin_preview,
    llm_throughput_selftest,
    performance_report,
)
from .sources import (
    qualification_integrity,
    source_audit,
    source_audit_selftest,
    source_qualification_export,
)
from .system import (
    _p0_validation_last,
    _session_forensics_text,
    columnar_status,
    corpus_integrity_report,
    data_dir_persistence_report,
    elections_coverage_floor,
    external_freshness,
    frontend_errors,
    law_coverage,
    law_ingest,
    network_preflight_log,
    request_latency,
    schema_drift_report,
    session_forensics_report,
    slow_queries,
    soak_window_report,
    stall_forensics_report,
    storage_composition_report,
    storage_footprint_report,
    windows_locks_report,
    write_gate_report,
)


def _debug_bundle_member_budget_s() -> float:
    """Per-member wall-clock budget for the debug bundle (OO_DEBUG_BUNDLE_MEMBER_BUDGET_S,
    default 20s). A member exceeding it is recorded ``{skipped: budget}`` and abandoned, so
    one slow/hung member never stalls the whole bundle. Non-positive/non-finite/invalid ->
    20s; CAPPED to 1 h so a fat-fingered huge value can never overflow ``Thread.join()``'s
    timeout (an OverflowError there would escape the per-member guard and 500 the whole
    bundle) nor emit a non-finite, JSON-invalid ``budget_s``."""
    import math

    try:
        v = float(os.environ.get("OO_DEBUG_BUNDLE_MEMBER_BUDGET_S", "20"))
    except ValueError:
        return 20.0
    if not math.isfinite(v) or v <= 0:
        return 20.0
    return min(v, 3600.0)


@router.get("/debug-bundle")
def debug_bundle(db: Session = Depends(read_only_db)) -> JSONResponse:
    """ONE downloadable bundle with everything a developer needs to diagnose a
    live install remotely (maintainer-ruled 2026-06-10: "I'll click every
    download/scrape/refresh button and send you the log"). Sections:

    runtime · corpus shape · scheduler state + run history · every network
    verdict (sources / market feeds / calendars) · per-click import outcomes ·
    law + wiki tracking states · the rolling WARNING+ error log. Verbatim
    records, no inference; generated only on click.

    HARDENED (S8): the DB is opened READ-ONLY (a ``query_only`` WAL snapshot, so the
    bundle can never take the write gate); EVERY member is individually guarded (a
    raising member records ``{error}``, never aborts the bundle). NON-DB members (which can
    block on a loopback socket or a file read but never touch the DB) run under a per-member
    wall-clock BUDGET on a daemon thread — a member that hangs records ``{skipped: budget}``
    instead of stalling the whole export (the 100 GB field corpus made single members slow
    enough to matter). DB members run INLINE (never on a worker thread — a shared SQLite
    connection is unsafe to touch concurrently), bounded by a statement deadline inside the
    thunk so a runaway query is aborted rather than scanned to the end.
    """
    import json as _json
    import platform
    import sys as _sys
    import threading

    from src.database.maintenance import statement_deadline
    from src.events.feeds import load_imports, load_verdicts
    from src.monitoring import feed_preflight
    from src.monitoring.collect_perf import recent_samples as _collect_perf_samples
    from src.monitoring.errorlog import recent_errors
    from src.monitoring.errorlog import summary as error_log_summary
    from src.monitoring.field_test import recent_results as _field_test_results
    from src.monitoring.forensics import session_forensics as _session_forensics
    from src.monitoring.integrity import corpus_integrity as _corpus_integrity
    from src.monitoring.latency import summary as _latency_summary
    from src.monitoring.preflight import recent_results as source_results
    from src.monitoring.schema_drift import schema_drift as _schema_drift
    from src.monitoring.slowquery import summary as _slowquery_summary
    from src.monitoring.storage import storage_composition as _storage_composition
    from src.paths import data_dir as _data_dir
    from src.scheduler.runlog import recent_runs
    from src.scheduler.runner import get_scheduler

    budget = _debug_bundle_member_budget_s()

    def _err_str(exc) -> str:
        try:
            return str(exc)[:300]
        except Exception:  # noqa: BLE001 - even a broken __str__ must still yield a marker
            return f"<{type(exc).__name__}: unrenderable>"

    def _bounded(fn):
        """Run a DB thunk under a statement deadline (SQL opcode interrupt) so a runaway
        query on the shared connection is aborted instead of scanning a 100 GB table to the
        end. Only for members that do NOT already open their own deadline (avoids nesting —
        an inner deadline's ``finally`` would clear this one's progress handler)."""
        with statement_deadline(db, budget):
            return fn()

    def _member(name: str, thunk, *, threaded: bool = True):
        """Guard ONE bundle member so a failing/slow member never aborts or stalls the whole
        bundle. A raising member records ``{error}`` (even if its exception ``__str__`` is
        itself broken) either way.

        NON-DB members (``threaded=True``, the default) run in a daemon thread with a
        wall-clock BUDGET: they can block on I/O (a loopback socket, a file read) and never
        touch the shared DB connection, so abandoning one past budget as ``{skipped: budget}``
        is safe. DB members (``threaded=False``) run INLINE, because a shared SQLite
        connection can NOT be touched from a lingering worker thread — pysqlite serialises
        statements (a second thread BLOCKS, it does not error) and a SQLAlchemy Session is
        not thread-safe, and ``statement_deadline`` bounds only SQL opcodes, never the Python
        materialisation around them, so a DB worker could not be cleanly abandoned mid-query.
        DB members are instead bounded INSIDE the thunk (``_bounded`` or the member's own
        internal deadline), so they can never hang the bundle and never leave a stray
        progress handler on the connection for the next member."""
        if not threaded:
            try:
                return thunk()
            except Exception as exc:  # noqa: BLE001 - one failing member must not abort the bundle
                return {"error": _err_str(exc)}
        box: dict = {}

        def _run() -> None:
            try:
                box["value"] = thunk()
            except Exception as exc:  # noqa: BLE001 - one failing member must not abort the bundle
                box["error"] = _err_str(exc)

        t = threading.Thread(target=_run, name=f"dbg:{name}", daemon=True)
        t.start()
        t.join(budget)
        if t.is_alive():
            return {"skipped": "budget", "budget_s": budget}
        if "error" in box:
            return {"error": box["error"]}
        return box.get("value")

    # -- runtime ----------------------------------------------------------- #
    def _has(mod: str) -> bool:
        import importlib.util

        return importlib.util.find_spec(mod) is not None

    from src.database.models import CommodityPrice, LawDocument, WikiPage
    from src.ingest import kill_switch_active

    # Each member is a thunk run through _member (individual guard + budget). The DB-bound
    # ones read the shared read-only snapshot; the rest read in-memory/file state.
    # A trivial single-row read, computed INLINE + bounded (never hangs) so the threaded
    # runtime member never touches the shared DB connection from a worker thread.
    def _read_schema_rev():
        from sqlalchemy import text as _text

        try:
            return _bounded(
                lambda: db.execute(_text("SELECT version_num FROM alembic_version")).scalar()
            )
        except Exception:  # noqa: BLE001
            return None

    schema_rev = _read_schema_rev()

    def _runtime() -> dict:
        llm: dict = {"available": False}
        try:
            from src.llm.ollama import OllamaClient

            client = OllamaClient()
            if client.is_available():
                llm = {"available": True, "models": client.list_installed()}
        except Exception as exc:  # noqa: BLE001 - loopback-only, best-effort
            llm = {"available": False, "error": str(exc)[:200]}
        db_file = _data_dir() / "open_omniscience.db"
        return {
            "python": _sys.version.split()[0],
            "platform": platform.platform(),
            "schema_revision": schema_rev,
            "extras": {m: _has(m) for m in ("numpy", "scipy", "pandas", "zstandard", "lz4")},
            "llm": llm,
            "db_bytes": db_file.stat().st_size if db_file.exists() else None,
            "kill_switch": kill_switch_active(),
        }

    def _corpus() -> dict:
        return {
            "articles": int(db.query(func.count(Article.id)).scalar() or 0),
            "sources": int(db.query(func.count(Source.id)).scalar() or 0),
            "keywords": int(db.query(func.count(Keyword.id)).scalar() or 0),
            "price_points": int(db.query(func.count(CommodityPrice.id)).scalar() or 0),
        }

    def _law_docs() -> list:
        return [
            {
                "title": d.title,
                "jurisdiction": d.jurisdiction,
                "url": d.url,
                "last_status": d.last_status,
                "last_checked_at": d.last_checked_at.isoformat() if d.last_checked_at else None,
            }
            for d in db.query(LawDocument)
            .order_by(LawDocument.jurisdiction, LawDocument.title)
            .all()
        ]

    def _wiki_pages() -> list:
        return [
            {
                "wiki": p.wiki,
                "title": p.title,
                "missing": p.missing,
                "baseline": p.baseline_revid is not None,
                "last_checked_at": p.last_checked_at.isoformat() if p.last_checked_at else None,
            }
            for p in db.query(WikiPage).order_by(WikiPage.wiki, WikiPage.title).all()
        ]

    def _import_results() -> list:
        imports_path = _data_dir() / "import_results.jsonl"
        out: list = []
        if imports_path.exists():
            for ln in imports_path.read_text(encoding="utf-8").splitlines()[-50:]:
                try:
                    out.append(_json.loads(ln))
                except ValueError:
                    continue
        return out

    # The error window drives the envelope count; guarded like every other member, and the
    # count degrades to 0 if the member itself failed/skipped (never a crash on len()).
    errors_val = _member("errors", lambda: recent_errors(300))
    count = len(errors_val) if isinstance(errors_val, list) else 0

    # DB members run INLINE (threaded=False — the shared connection is unsafe on a worker
    # thread); the non-self-bounding ones are wrapped in _bounded (a statement deadline).
    # corpus_integrity/storage_composition/slow_queries open their OWN deadline internally,
    # so they are NOT wrapped (nesting would let the inner finally clear the outer handler).
    payload = {
        "runtime": _member("runtime", _runtime),
        "corpus": _member("corpus", lambda: _bounded(_corpus), threaded=False),
        "scheduler": _member(
            "scheduler",
            lambda: {"status": get_scheduler().status(), "recent_runs": recent_runs(30)},
        ),
        "network": _member(
            "network",
            lambda: {
                "sources": source_results(),
                "feeds": feed_preflight.recent_results(),
                "calendar_verdicts": load_verdicts(),
            },
        ),
        "imports": _member("imports", _import_results),
        "calendar_imports": _member(
            "calendar_imports",
            lambda: {
                k: {"events": len(v.get("events", {})), "imported_at": v.get("imported_at")}
                for k, v in load_imports().items()
            },
        ),
        "law_documents": _member("law_documents", lambda: _bounded(_law_docs), threaded=False),
        "wiki_pages": _member("wiki_pages", lambda: _bounded(_wiki_pages), threaded=False),
        # Collection-performance timeline + end-of-pass bottleneck classification
        # (download rate, in-flight fetches, writer-gate contention, CPU/memory).
        # The bandwidth governor's own log — what to read when collection is slow.
        "collect_perf": _member("collect_perf", _collect_perf_samples),
        # TEMPORARY (0.0.8 live-test cycle): automated field-test outcomes —
        # see src/monitoring/field_test.py for purpose + the OO_FIELD_TEST=0
        # opt-out. Will be removed when the cycle ends.
        "field_test": _member("field_test", _field_test_results),
        "errors": errors_val,
        # Honest metadata so a reader can tell whether the error window is CURRENT
        # (the rolling file survives reinstalls, so old-session errors can look
        # live). "*_this_session" counts are since the latest boot marker, so a
        # clean current run reads zero — the direct answer to "is the data-loss
        # happening now?" (P0-5; field test 2026-06-22).
        "error_log": _member("error_log", error_log_summary),
        # Recursive-augmentation logs #2-#5 (maintainer 2026-07-02): so the bundle the
        # operator sends carries the diagnostics that catch bugs automatically — the
        # loop-block/latency log, the slow-query log, live schema drift, and the
        # corpus-integrity/counter-drift sweep. Each is individually guarded (a failing
        # member records its own error, never aborts the bundle); the DB ones are bounded
        # by a statement deadline, request_latency by the wall-clock budget.
        "request_latency": _member("request_latency", _latency_summary),
        "slow_queries": _member(
            "slow_queries", lambda: _slowquery_summary(db), threaded=False
        ),
        "schema_drift": _member(
            "schema_drift", lambda: _bounded(lambda: _schema_drift(db)), threaded=False
        ),
        "corpus_integrity": _member(
            "corpus_integrity", lambda: _corpus_integrity(db), threaded=False
        ),
        # Session forensics (2026-07-09 field event): data-dir inventory (what IS the
        # disk usage — orphaned PLAINTEXT backup staging detected loudly), the previous
        # session's clean/unclean-end verdict (+ the collector's last RSS sample = the
        # OOM-inference flight recorder), and the last unlock's own phase timings with
        # the -wal size before open. Automates the three questions the 2026-07-09
        # root-cause needed the maintainer's terminal for.
        "session_forensics": _member("session_forensics", _session_forensics),
        # Storage composition (P1.5): per-table/per-index bytes via dbstat — names what
        # the on-disk GB actually IS (the 130-GB-in-days field event). Deadline-bounded;
        # degrades to {available:false, reason} where dbstat is not compiled in.
        "storage_composition": _member(
            "storage_composition", lambda: _storage_composition(db), threaded=False
        ),
        # P0 data-safety validation (S1.2): the LAST saved report from the push-button
        # backup/restore/unlock/collector acceptance run (read-only here — never runs a
        # backup; {available:false} until the operator runs it explicitly).
        "p0_validation": _member("p0_validation", _p0_validation_last),
        "method": (
            "Verbatim runtime facts, tracking states, network verdicts, per-click "
            "import outcomes and the rolling WARNING+ error log. Nothing inferred; "
            "exported only on the operator's click. Each member is individually guarded; "
            "a failed member shows {error}, a slow non-DB member {skipped: budget}."
        ),
    }
    body = envelope(kind="debug-bundle", query={}, count=count, payload=payload)
    fname = f"oo-debug-bundle-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


#: Marks a value the encoder could not serialise, IN PLACE, naming its type. Never a
#: silent ``str()`` of the object (which would write "<Query object at 0x7f…>" into a
#: report as if it were data) and never an exception that discards the whole member.
_UNSERIALISABLE = "__oo_unserialisable__"


def _member_default(obj: object) -> object:
    """``json.dumps(default=)``: replace an unserialisable value with a STATED marker.

    Field bundle 2026-08-02: ``card-audit.json`` ran for 2,396 s -- 40 minutes, 41% of
    the entire bundle's wall time -- and then raised "Object of type Query is not JSON
    serializable" at the encode step. Every byte of that work was discarded, and the
    error named the type without saying where it sat, so the next run could only
    reproduce it by spending the 40 minutes again.

    Both halves of that are fixed here: the member is still WRITTEN (one bad leaf can no
    longer destroy an expensive report), and the leaf says what it was, so the offending
    producer is identifiable from the artefact instead of by re-running it.

    Deliberately NOT ``default=str``: a stringified ORM object is indistinguishable from
    a real string field, which is the fabrication this project forbids -- a reader must
    be able to tell a value that could not be encoded from one that was.
    """
    return {
        _UNSERIALISABLE: True,
        "type": type(obj).__name__,
        "module": type(obj).__module__,
        "note": (
            "this value could not be encoded as JSON and was replaced in place; the "
            "surrounding keys locate the field that produced it"
        ),
    }


def _member_bytes(value) -> bytes:
    """Encode any diagnostics endpoint return (a plain dict, a JSONResponse, or a
    StreamingResponse) into the bytes to write into the all-diagnostics ZIP."""
    if isinstance(value, (dict, list)):
        return json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), default=_member_default
        ).encode("utf-8")
    body_iter = getattr(value, "body_iterator", None)
    if body_iter is not None:
        # A streamed response (the keyword log digest): drain it for real. This sync
        # handler runs in a worker thread (no running loop), so a private loop is safe
        # — the exact pattern performance_report uses to time streamed bodies.
        import asyncio

        async def _drain(it) -> bytes:
            parts: list[bytes] = []
            async for chunk in it:
                parts.append(chunk.encode("utf-8") if isinstance(chunk, str) else chunk)
            return b"".join(parts)

        return asyncio.run(_drain(body_iter))
    return bytes(getattr(value, "body", b""))  # JSONResponse / Response


# D5 (field diagnostics 2026-09-11, maintainer request): a PER-MEMBER byte cap, so no
# single member can make the whole archive unsendable again. The manifest already
# recorded `bytes` per member, so the builder always knew every size -- it just never
# acted on one. 12 MB by default: comfortably above every healthy member measured in the
# field (the largest after B2's cap is under 1 MB) while staying under the common 25 MB
# attachment limit even if two members ran large at once. 0 disables the cap entirely.
def _all_diag_member_max_bytes() -> int:
    try:
        mb = float(os.environ.get("OO_DIAG_MEMBER_MAX_MB", "12"))
    except ValueError:
        mb = 12.0
    return 0 if mb <= 0 else int(mb * 1024 * 1024)


# How much of a streamed member is held in RAM before it spills to disk. Deliberately far
# below the cap: the point is that RAM stays bounded no matter how big the member gets.
_MEMBER_SPOOL_MAX = 4 * 1024 * 1024


def _write_member(zf, name: str, value) -> int:
    """Write one archive member, STREAMING a streamed body instead of materialising it.

    Field diagnostics 2026-09-11 (B2). The old path was
    ``zf.writestr(name, _member_bytes(value))``, and on the 73.2 MB keyword-log digest
    that held three copies of the member at once: the list of chunks ``_drain``
    accumulates, the joined ``bytes`` it returns, and whatever ``writestr`` buffers --
    on a machine with 4,093.8 MB of RAM, beside a member whose own construction had
    already pushed RSS up by 3.4 GB. Capping that member (above) is the real fix; this
    is the net beneath it, so the NEXT large member does not repeat the shape.

    Returns the number of UNCOMPRESSED bytes written, which is what the manifest's
    ``bytes`` field has always meant -- counted as they go past rather than by
    measuring a buffer, so the figure stays honest without a buffer existing.
    """
    cap = _all_diag_member_max_bytes()

    body_iter = getattr(value, "body_iterator", None)
    if body_iter is None:
        payload = _member_bytes(value)
        if cap and len(payload) > cap:
            return _write_member_omission(zf, name, len(payload), cap)
        zf.writestr(name, payload)
        return len(payload)

    # A streamed response (the keyword log digest). This sync handler runs in a worker
    # thread with no running loop, so a private loop is safe -- the same pattern
    # ``_member_bytes`` itself uses, kept identical on purpose.
    import asyncio
    import shutil
    import tempfile

    # SPOOLED, not buffered: a member's final size is unknown until its last chunk, and
    # the cap cannot be enforced by truncating mid-write -- half a JSON document is
    # invalid, which is strictly worse than an honest omission. So it is spilled to a
    # SpooledTemporaryFile, which keeps the common (small) member entirely in RAM and
    # sends only a large one to disk. That bounds RAM at _MEMBER_SPOOL_MAX rather than at
    # the member's size, which is the property B2 bought and this must not give back.
    with tempfile.SpooledTemporaryFile(max_size=_MEMBER_SPOOL_MAX, suffix=".oodiag") as spool:
        async def _pump() -> int:
            total = 0
            async for chunk in body_iter:
                buf = chunk.encode("utf-8") if isinstance(chunk, str) else chunk
                spool.write(buf)
                total += len(buf)
            return total

        written = asyncio.run(_pump())
        if cap and written > cap:
            return _write_member_omission(zf, name, written, cap)
        spool.seek(0)
        # force_zip64: a member that grows past 4 GB must fail on its own terms rather
        # than silently corrupt the archive.
        with zf.open(name, "w", force_zip64=True) as fh:
            shutil.copyfileobj(spool, fh, length=1024 * 1024)
    return written


def _write_member_omission(zf, name: str, actual: int, cap: int) -> int:
    """Replace an over-cap member with a RECORD of what was omitted, and why.

    Field diagnostics 2026-09-11 (D5, the generalising half). The maintainer could not
    upload the bundle because ONE member reached 73.2 MB. B2 fixed that member; this
    stops the NEXT one doing it again, whichever member it turns out to be.

    THE OMISSION IS NEVER SILENT AND THE MEMBER IS NEVER TRUNCATED. A truncated JSON
    document is invalid, so it would cost the operator the member AND the ability to tell
    that anything was lost -- the exact silent-truncation failure several other findings
    in this batch are about. What lands instead is a small JSON naming the member, its
    real size, the cap that excluded it, the env var that raises the cap, and the fact
    that the member's own endpoint still serves it in full. The manifest's ``bytes`` then
    reports what was actually written, so the archive's own accounting stays true.
    """
    payload = json.dumps(
        {
            "omitted": True,
            "member": name,
            "bytes_uncompressed": actual,
            "cap_bytes": cap,
            "reason": (
                f"this member is {actual:,} bytes, over the {cap:,}-byte per-member cap "
                "for the diagnostics archive, so it was left out rather than truncated "
                "(a truncated JSON member would be invalid and would hide its own loss)"
            ),
            "how_to_get_it": (
                "raise or disable the cap with OO_DIAG_MEMBER_MAX_MB (0 disables it), or "
                "call this member's own endpoint directly -- the archive is a convenience "
                "bundle of endpoints that each still serve their full output"
            ),
        },
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    zf.writestr(name + ".omitted.json", payload)
    return len(payload)


def _fixity_bundle_member(db: Session) -> dict:
    """The BOUNDED fixity-audit bundle member (transversal audit 09, C2). Calls the
    real ``GET /api/integrity/fixity`` endpoint function directly (its own
    ``guarded_read`` heavy-cap/single-flight wrapping applies unchanged), capped at
    ``limit=500`` so a re-hash of every stored article never dominates the whole
    bundle's wall time. Degrades honestly (never raises into the bundle build) if the
    sibling router can't be imported for any reason."""
    try:
        from src.api.integrity import get_fixity

        return get_fixity(limit=500, db=db)
    except Exception as exc:  # noqa: BLE001 - one member's failure must not sink the bundle
        return {"available": False, "reason": _all_diag_err_str(exc)}


#: THE LIGHT PROFILE (maintainer 2026-09-22, ruling R28 -- the reconciliation of two
#: standing rulings): which members a LIGHT bundle declines, and the MEASURED reason for
#: each. The 2026-09-02 crash brief, its own §3 ruling 4 (docs/design/
#: AUTONOMOUS_SESSION_BRIEF_2026-09-02_CRASH_ROOT_CAUSE.md -- NOT `R4` of
#: docs/ledger/RULINGS_INDEX.md, which is an unrelated ruling about export messages), says
#: the bundle "still runs EVERY member -- the bundle is the maintainer's only evidence
#: channel"; ruling R27 (2026-09-22) says members needing more than half the machine's RAM
#: decline below the floor. Both stand. THE TOGGLE IS THE RECONCILIATION: EVERY MEMBER
#: remains the DEFAULT and the only automatic behaviour, and a decline happens solely
#: because the operator asked for one. Nothing declines itself.
#:
#: THE RULE THE SET FOLLOWS, so the next member is classified rather than argued about:
#: light drops what MEASURES THE MACHINE or RE-READS THE WHOLE CORPUS; it keeps everything
#: that REPORTS THE DATA. An operator running light is asking "what is in my corpus and
#: what went wrong", not "how fast is this disk".
#:
#: EVERY REASON IS A READING FROM THE OPERATOR'S OWN 2026-09-11 BUNDLE (72 members), not an
#: estimate -- see docs/audit/15_FIELD_INSTANCE_SLOWNESS_2026-09-21.md §3.7 and F12.
_LIGHT_DECLINED: dict[str, str] = {
    "keyword-log-digest.json": (
        "measured a 3,322.8 MB peak RSS rise on the operator's 4 GB instance -- the ONLY "
        "member in that 72-member run with a peak rise above 0.0 MB, so on a small machine "
        "this one member forces swapping by itself (finding F12)"
    ),
    "source-audit.json": (
        "measured 297.9 s on the operator's instance, and the ledger already records it as "
        "categorically unable to finish inside its 300 s deadline at that source count "
        "(OPEN_QUEUE.md, the 2 uncompletable members)"
    ),
    "benchmark.json": (
        "it RUNS a benchmark rather than reporting a reading: ~50 MB written to a temp dir "
        "and 305.3 s measured on the operator's instance, where it still ended "
        "partial-deadline. A bundle taken to diagnose a slow machine should not spend its "
        "wall clock timing that machine"
    ),
    "fixity.json": (
        "re-hashes stored article bodies through the SQLCipher codec -- its own docstring "
        "calls it one of the heaviest reads, and it scales with the corpus rather than with "
        "the question being asked"
    ),
}

#: The profiles a caller may ask for. ``full`` is the default everywhere and is byte-identical
#: to the behaviour before the toggle existed.
_BUNDLE_PROFILES = ("full", "light")


def resolve_bundle_profile(requested: str | None) -> str:
    """Normalise a requested bundle profile; anything unrecognised is FULL.

    FULL ON ANYTHING UNRECOGNISED, deliberately and in that direction: a typo, a stale
    client or a future profile name must never silently produce a SMALLER bundle than the
    operator believes they asked for. An unexpectedly complete bundle costs time; an
    unexpectedly incomplete one costs the evidence the 2026-09-02 brief calls the
    maintainer's only channel.
    """
    # A NON-STRING IS THE COMMON CASE, NOT AN EDGE CASE. Called directly rather than
    # through FastAPI -- which is how the sync `/all` route is driven by its own tests and
    # by the bundle's internal callers -- a ``Query("full")`` default arrives as the Query
    # SENTINEL OBJECT, not as text. This module already carries that lesson three times
    # about ``Query(False)`` being truthy; this is the same trap one type over, and it was
    # live-reproduced here (`AttributeError: 'Query' object has no attribute 'strip'`)
    # before this line existed. Resolving it to FULL is also the right answer: an
    # unrecognised request must never shrink the bundle.
    if not isinstance(requested, str):
        return "full"
    v = requested.strip().lower()
    return v if v in _BUNDLE_PROFILES else "full"


def _all_diagnostics_members(db: Session) -> list[tuple[str, object]]:
    """The ordered (filename, generator) list for the all-diagnostics archive — the SINGLE
    source of truth shared by the synchronous ``/all`` endpoint and the background job, so the
    two can never drift out of sync (the A2 contract lesson). Each generator is the same
    function its own button calls; the full keyword CORPUS dump is deliberately NOT here (it
    has its own sized/paged 'All keywords' export) — this carries the bounded log DIGEST."""
    # The split (Q1139) put these readers in submodules imported AFTER this one, so
    # `__init__` can keep the original route order. They are imported HERE, at call
    # time, which is exactly when the single-file module resolved them as globals.
    from .ai import ai_diagnostics, qualification_assist_last, qualification_assist_selftest
    from .ai_check import ai_check_last
    from .keyword_triage import keyword_triage_last, keyword_triage_proposal
    from .model_bench import model_bench_last
    from .perception import perception_extract_last
    from .source_tags import source_tags_last, source_tags_selftest

    return [
        ("debug-bundle.json", lambda: debug_bundle(db=db)),
        ("home-cards.json", lambda: home_card_diagnostics(download=False, db=db)),
        ("keyword-engine.json", lambda: keyword_engine(download=False, db=db)),
        ("keyword-selftest.json", lambda: keyword_selftest(download=False)),
        # EVERY Query()-defaulted parameter passed EXPLICITLY: called directly (not
        # through FastAPI) the default IS the Query sentinel object, and Query(False)
        # is TRUTHY. `run_journal` proved it in the field -- limit reached a slice as a
        # Query and the member died with "slice indices must be integers". The repo
        # already had this lesson from `ai.json`; these three call sites had not
        # applied it. Anything with a Query() default belongs in the call, always.
        ("keyword-log-digest.json",
         # per_lang/page are the route's OWN declared defaults, not numbers chosen
         # here: passing anything else would silently change what this member exports.
         lambda: keyword_log(
             db=db, digest=True, fmt="json", per_lang=_MAX_KEYWORDS_PER_LANG, page=1
         )),
        (
            "date-extraction.json",
            lambda: date_extraction_log(
                db=db, scan=1500, sample=60, days=None, lang=None, content_chars=1200
            ),
        ),
        ("network.json", lambda: network_preflight_log()),
        ("performance.json", lambda: performance_report(selftest=True, db=db)),
        ("benchmark.json", lambda: benchmark_report(repeats=2, db=db)),
        ("columnar.json", lambda: columnar_status()),
        ("freshness.json", lambda: external_freshness()),
        ("elections-floor.json", lambda: elections_coverage_floor()),
        # Recursive-augmentation logs #1-#5 (maintainer 2026-07-02).
        ("request-latency.json", lambda: request_latency()),
        # S2.6 (2026-09-02): the two pins, named. Point-in-time and in-memory, so
        # it is cheap and the bundle carries it beside the latency log the stalls
        # show up in.
        ("write-gate.json", lambda: write_gate_report()),
        # Cause attribution for the requests the latency log shows as stalls. Cheap:
        # an in-memory ring read, no DB work, so it needs no deadline of its own.
        ("stall-forensics.json", lambda: stall_forensics_report(limit=200)),
        ("slow-queries.json", lambda: slow_queries(explain=1, db=db)),
        ("schema-drift.json", lambda: schema_drift_report(db=db)),
        ("corpus-integrity.json", lambda: corpus_integrity_report(sample=500, full=0, db=db)),
        # The Q310 duplicate-key scan (gate row K's artifact). It calls the SCAN, not
        # the endpoint: importing a diagnostics slice from here would register that
        # slice's route at THIS module's import position, and the Q1139 split guard
        # pins every route's position (it caught exactly that, by name). Both callers
        # go through `scan_live_corpus`, so there is one path and one schema. One
        # GROUP BY per country column, under the DB member deadline the wrapper
        # already applies.
        ("country-code-duplicates.json", lambda: _country_code_scan(db)),
        # transversal audit 09 (2026-07-25), C2: fold the local fixity audit in, as
        # 08's own Action Plan C2 originally asked ("fold a fixity pass into the
        # gate-row-3 diagnostics bundle rather than treating it as a separate ask").
        # A re-hash of every stored article is one of the heaviest reads (its own
        # docstring says so), so this member is BOUNDED (limit=500, matching
        # corpus-integrity's own sample bound above) -- the standalone
        # GET /api/integrity/fixity endpoint still defaults to a full-corpus audit
        # for a direct, deliberate operator run. Reuses the endpoint's OWN
        # guarded_read wrapping (single-flight/heavy-cap), the same code path a
        # direct HTTP GET would take.
        ("fixity.json", lambda: _fixity_bundle_member(db=db)),
        ("frontend-errors.json", lambda: frontend_errors(limit=500)),
        # download=False EXPLICITLY: called directly, `Query(False)` is a sentinel
        # OBJECT and truthy, which would have put the TEXT in the .json member.
        ("session-forensics.json", lambda: session_forensics_report(download=False)),
        # The SAME facts rendered for a human (2026-08-23 field ask). It rides beside
        # the JSON rather than replacing it: the JSON is what a tool reads, the text is
        # what an operator pastes into a chat when something went wrong.
        ("session-forensics.txt", lambda: _session_forensics_text()),
        # A12b: itemized footprint across ALL stores incl. the external Ollama model store.
        ("storage-footprint.json", lambda: storage_footprint_report(download=False)),
        # P1.5: per-table/per-index bytes (dbstat) — what the on-disk GB actually IS.
        ("storage-composition.json", lambda: storage_composition_report(download=False, db=db)),
        ("windows-locks.json", lambda: windows_locks_report(download=False)),
        # S4 (2026-09-07): the soak window -- the durable readings composed with the
        # window each one actually covers, so a multi-day run can be read after it ends.
        ("soak-window.json", lambda: soak_window_report(db=db)),
        # S1.2: the last P0 data-safety validation report (read-only; never runs a backup).
        ("p0-validation.json", lambda: _p0_validation_last()),
        # The 0.4 release acceptance run's last report (2026-09-18; read-only, never runs
        # one) -- so the bundle taken at the end of the run carries the run's own record.
        ("release-run.json", lambda: _release_run_last()),
        ("chronology.json", lambda: _chronology_member()),
        # §6 recursive-improvement loop instruments: the two cheap, decrypt-light DATA reports
        # that were missing from the bundle, plus the loop SELF-INVENTORY (are the loop's own
        # mechanism-proof gates green?). Kept last so a heavy corpus never delays them.
        ("article-length.json", lambda: article_length(download=False, db=db)),
        # Slice 2 of the 2026-09-05 keyword-translation plan: the one number that decides
        # whether the month-name ban should become date-aware. Sample passed EXPLICITLY --
        # a Query(...) default is a sentinel object when the route is called directly.
        ("month-occupancy.json", lambda: month_occupancy(sample=400, download=False, db=db)),
        ("keyword-growth.json", lambda: keyword_growth(download=False, db=db)),
        ("recursive-loop.json", lambda: recursive_loop(download=False)),
        ("kpi.json", lambda: kpi(download=False)),
        # §4 search-instrumentation: the per-search phase-timing aggregate (empty-honest until
        # instrument_search is wired into the search endpoint on the operator's rig).
        ("search-timing.json", lambda: search_timing(download=False)),
        # The import/export RUN JOURNAL (2026-07-31). Rides the bundle rather than the
        # backup archive on purpose: _build_backup_zip hashes members and THEN writes
        # them, and an EXPORT's own journal is appended to between those two reads --
        # over minutes, for a 17 GB set -- so every such backup would carry a member
        # its own restore rejects as "sha256 mismatch (corrupted or altered)". The
        # bundle is a read-at-one-moment snapshot, with no hash to contradict.
        ("run-journal.json", lambda: run_journal(download=False, limit=20)),
        # ...and the raw lines behind it. The summary is the answer; this is the
        # evidence, and a stall is a SHAPE across hundreds of beats (swap climbing
        # while CPU flatlines; the gate held with waiters piling up) that no summary
        # substitutes for. Bounded, with what was dropped stated.
        ("run-journal-raw.json", lambda: _run_journal_raw()),
        ("run-timeline.json", lambda: run_timeline(max_runs=4)),
        # The MERGE diagnostic (2026-08-06). Every Query()-defaulted parameter passed
        # EXPLICITLY, per the ai.json/run_journal lesson three members above: called
        # directly, a Query(True) default is the sentinel OBJECT, which is truthy, so
        # omitting `probe` would run the benchmark by accident rather than by choice.
        # It IS wanted here -- the per-row cost at the operator's real row size is the
        # number that named the 5 KB/row allocation -- so it is passed as True, on
        # purpose and visibly. ~50 MB written to a swept temp dir, deleted in a finally.
        ("merge-diag.json", lambda: merge_diag(download=False, probe=True)),
        # 2026-07-17 completeness fix (maintainer: "all diagnostics should comprise ALL
        # diagnostics"): the read-only reports + cheap deterministic selftests that had
        # accumulated OUTSIDE the bundle since the #645 membership pass. Deliberate
        # exclusions are now DOCUMENTED in the manifest's "excluded" block instead of
        # silent, and test_repo_invariants ratchets every future GET endpoint into
        # either the bundle or that block.
        # `recency_window=False` is PASSED, not defaulted: this call site bypasses FastAPI,
        # so an unpassed Query default arrives as a sentinel object rather than its apparent
        # value. It is False because the windowed verdict (RC06) costs a SECOND whole-corpus
        # pass on top of what is already the most expensive member in a bundle that runs
        # under a per-member deadline -- doubling it here to ship a figure nobody asked for
        # by name is how a bundle starts timing out. It is one request away on the endpoint.
        ("source-audit.json",
         lambda: source_audit(download=False, with_furniture=True, recency_window=False, db=db)),
        ("non-article-scan.json", lambda: non_article_scan(download=False, db=db)),
        # S3.1 (2026-07-23 field-feedback workflow): the TEMPORARY criteria-calibration
        # report. A smaller prose_gate_limit than the endpoint's own default (500 vs 2000)
        # keeps this bundle member's content-decrypt bounded — the standalone endpoint
        # still defaults fuller for a direct diagnostic run.
        #
        # ``resume=True`` and the ``index_pages`` scope are what make this member's prose arm
        # able to FINISH. It used to pass ``prose_gate_after_id=0`` literally, so every bundle
        # re-measured the same lowest-id 500 articles: ``done`` could not become true on any
        # corpus over 500, and both 2026-08-23 field reports stopped at ``last_id: 695``
        # having flagged 0. The scope points it at the population the article clean-up is
        # actually about (0.3 gate row 5's Tier B — listing-shaped URLs the word guard keeps,
        # 451 articles at release scale) rather than at whatever ascending id ordered first.
        # The ``all`` scope stays reachable on the endpoint, with its own cursor.
        ("criteria-calibration.json", lambda: criteria_calibration(
            download=False, top_n=100, prose_gate_limit=500, prose_gate_after_id=0,
            prose_gate_scope="index_pages", resume=True, db=db,
        )),
        ("lemma-preview.json", lambda: lemma_preview(top_n=500, db=db)),
        # The bulletin's own language coverage + the render-integrity checks. Renders a
        # persisted record (or the synthetic sample when there is none), so it costs no
        # query and works on a fresh install.
        ("bulletin-language.json", lambda: bulletin_language(download=False)),
        ("bulletin-language-selftest.json", lambda: bulletin_language_selftest()),
        ("power-profile.json", lambda: power_profile(profile="optimized", download=False)),
        ("data-dir-persistence.json", lambda: data_dir_persistence_report()),
        ("ir-eval-selftest.json", lambda: ir_eval_selftest(download=False)),
        ("perception-eval-selftest.json", lambda: perception_eval_selftest(download=False)),
        ("keyword-triage-selftest.json", lambda: keyword_triage_selftest(download=False)),
        # Section 8 real run (2026-07-20 ruling): the last saved keyword-triage JSONL run,
        # summarised (read-only; never RUNS a triage -- that is its own background job).
        ("keyword-triage-run.json", lambda: keyword_triage_last()),
        # The reviewable PROPOSAL built from that run: junk verdicts grouped per language,
        # with the evidence and what was held back. Cheap (a streamed log read + one
        # indexed term lookup), read-only, and it applies nothing -- the artifact a human
        # judges before any stoplist ever changes. Query() default passed EXPLICITLY.
        ("keyword-triage-proposal.json", lambda: keyword_triage_proposal(download=False, db=db)),
        # The sibling LLM source-tag-assignment run: selftest + last saved summary.
        ("source-tags-selftest.json", lambda: source_tags_selftest(download=False)),
        ("source-tags-run.json", lambda: source_tags_last()),
        # B6 (2026-07-24 Session B): the last saved LIVE perception-eval-against-model
        # run (read-only; never RUNS an eval -- that is a POST, /perception-eval-live).
        ("perception-eval-live.json", lambda: perception_eval_live_last()),
        # B6.2/B6.3: the last saved who/where/when EXTRACTION sweep summary (read-only;
        # never RUNS a sweep -- that is its own background job, /perception-extract/run).
        ("perception-extract-run.json", lambda: perception_extract_last()),
        # The last saved side-by-side TRANSLATION comparison (read-only; never runs a
        # probe -- that is a POST). Carries corpus excerpts, and the payload says so.
        # E-S2 (2026-08-01): the newest COMPARATIVE model-bench artifact, summarised
        # (every metric, without the hundreds of per-term answers per pair). Read-only
        # -- running the bench is a heavy operator job, never a bundle member.
        ("model-bench.json", lambda: model_bench_last(full=False)),
        # The one-button AI check (maintainer 2026-08-09): the last run's report, so a
        # debug bundle carries what this machine measured about its own model rather
        # than sending somebody to run five diagnostics by hand. Read-only -- RUNNING it
        # is a background job of its own, never a bundle member.
        ("ai-check.json", lambda: ai_check_last()),
        # What the bench COULD cover on this machine. Read-only, and pointedly WITHOUT
        # the endpoint's `wake`: a bundle reports what it can see and starts nothing.
        # It answers the first question every one of the 10 August field reports raised
        # — "why is this bench so short" — without the reader having to run anything.
        # B7.1: the whole dual-backend AI stack snapshot -- backend/hardware facts,
        # active model, context settings, and every AI job's last saved summary.
        # Called DIRECTLY, so both arguments are passed explicitly: a FastAPI default
        # (Depends/Query) is only resolved when FastAPI itself calls the function, and
        # Query(False) is a truthy object — a bare ai_diagnostics() here would take the
        # measure_corpus branch and hand article_length_report a Depends sentinel. The
        # file's own convention for a db-taking member (leads_quality below) is the fix.
        ("ai.json", lambda: ai_diagnostics(measure_corpus=False, db=db)),
        # B7.2: the qualification-assist self-test + the newest saved proposals run
        # (across every source ever checked -- read-only, never runs a new check).
        ("qualification-assist-selftest.json", lambda: qualification_assist_selftest(download=False)),
        ("qualification-assist-run.json", lambda: qualification_assist_last(source_id=None)),
        ("search-timing-selftest.json", lambda: search_timing_selftest(download=False)),
        ("power-profile-selftest.json", lambda: power_profile_selftest(download=False)),
        ("source-audit-selftest.json", lambda: source_audit_selftest(download=False)),
        # What this instance would contribute to the shipped qualification overlay, and
        # the split of its app-provided sources (judged vs still pending). Read-only.
        ("source-qualification-export.json",
         lambda: source_qualification_export(download=False, fmt="json", db=db)),
        # 0.4 Row A's closing clause (Row E's tooling): does every judged source still
        # carry the verdict its own history recorded? Read-only, and cheap -- the exact
        # re-read runs only over the candidates the grouped query surfaced.
        ("qualification-integrity.json", lambda: qualification_integrity(db=db)),
        # The concurrency sweep's own MECHANISM (2026-08-09). The sweep itself is an
        # operator action needing a live model; this proves it really runs concurrently
        # -- a bench that silently ran serially would still publish a plausible curve.
        ("llm-throughput-selftest.json", llm_throughput_selftest),
        # What the background AI has been doing lately, read from the sweeps' own
        # logs (2026-08-09). Bounded tail reads, so a long-running sweep cannot make
        # this member grow without limit.
        ("ai-activity.json", lambda: ai_activity(recent=12, hours=24, db=db)),
        ("ai-activity-selftest.json", ai_activity_selftest),
        # S5 (law-vertical brief 2026-07-17): per-jurisdiction law-tracking coverage/
        # freshness — "is law working?" answered by one JSON, in the bundle by default.
        ("law-coverage.json", lambda: law_coverage(download=False, db=db)),
        # Ruling 34c (2026-08-07): did the law fixes actually reach the data? The strip
        # re-read and the poll-date clear both heal quietly on a document's next
        # successful poll, so an unreachable portal never heals and nothing said so.
        ("law-ingest.json", lambda: law_ingest(download=False, db=db)),
        # S6.1 (Leads-calibration, 2026-07-18): the CURRENT Home Leads feed as a
        # bounded, real-facts report — the measurement loop for the card system.
        ("leads-quality.json", lambda: leads_quality(download=False, db=db)),
        # The DEEP card-system audit at SUMMARY depth (no article content): the
        # per-card trigger arithmetic recomputed, corpus fidelity, independence,
        # non-fabrication checks, and — the reason it exists — an inventory row for
        # EVERY registered producer distinguishing ok / no-signal / ERROR, so a
        # producer crashing on every run stops being indistinguishable from a quiet
        # one. Bounded via audit_report_env_defaults(); the content-carrying
        # standard/full depths are the separate background job, never this member.
        ("card-audit.json",
         lambda: card_audit(depth="summary", determinism=True, download=False, db=db)),
        # Bulletin Layer A (2026-08-01), weekly: the deterministic period record. It
        # rides the bundle because its masthead IS corpus-health evidence — sources
        # that actually contributed, days with any ingest, language and country
        # spread, and the disclosures naming what no window can see. Weekly, so the
        # scan stays bounded; a long-cadence edition is a deliberate operator run.
        # On hardware below the gate this member is a stated refusal, not a figure.
        ("bulletin-weekly.json", lambda: bulletin_preview(cadence="weekly", download=False, db=db)),
    ]



def _all_diag_db_member_deadline_s() -> float:
    """Per-member statement deadline (SQL VM opcode interrupt) for a DB-touching
    all-diagnostics member, ``OO_ALL_DIAG_DB_MEMBER_DEADLINE_S`` (generous default -- a
    diagnostics run is not a UI request). Clamped finite/positive so a bad env value can
    never overflow ``Thread.join`` downstream nor emit a non-finite, JSON-invalid budget
    (the same S8-lesson clamp as the debug-bundle budget)."""
    import math

    try:
        v = float(os.environ.get("OO_ALL_DIAG_DB_MEMBER_DEADLINE_S", "300"))
    except ValueError:
        return 300.0
    if not math.isfinite(v) or v <= 0:
        return 300.0
    return min(v, 3600.0)


def _all_diag_nondb_member_deadline_s() -> float:
    """Per-member wall-clock budget for a NON-DB all-diagnostics member run on a daemon
    thread, ``OO_ALL_DIAG_NONDB_MEMBER_DEADLINE_S`` (same generous default + clamp)."""
    import math

    try:
        v = float(os.environ.get("OO_ALL_DIAG_NONDB_MEMBER_DEADLINE_S", "300"))
    except ValueError:
        return 300.0
    if not math.isfinite(v) or v <= 0:
        return 300.0
    return min(v, 3600.0)


def _member_touches_db(fn) -> bool:
    """True if this member's thunk closes over a ``db`` free variable -- i.e. it reads
    the shared DB connection. Determined from the ACTUAL closure (``fn.__code__``), never
    a hand-maintained allow-list that could silently drift from ``_all_diagnostics_members``
    as members are added. The S8 house lesson: a DB-touching member must run INLINE, never
    on a worker thread sharing the connection (pysqlite/sqlcipher serialise statements --
    a second thread BLOCKS, it does not error -- and a SQLAlchemy Session is not
    thread-safe), so this is the dispatch key for the deadline strategy below."""
    code = getattr(fn, "__code__", None)
    return code is not None and "db" in code.co_freevars


def _rss_peak_kb() -> int | None:
    """Process PEAK resident-set size in KB -- ``ru_maxrss``, one syscall, no dependency.
    Linux reports KB already; macOS reports bytes, normalized here.

    This is a HIGH-WATER MARK that NEVER FALLS, which is why S6.2 stopped using it as the
    per-member delta: after the first big member the process peak is already set, so every
    later member's "delta" is 0 whatever it really allocated. It is kept, under its own
    name, because it answers a different and still-useful question -- did THIS member push
    the process past everything it had ever done. None (never fabricated) where unreadable."""
    try:
        import resource
        import sys as _sys

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(rss / 1024) if _sys.platform == "darwin" else int(rss)
    except Exception:  # noqa: BLE001 - best-effort instrumentation, never fatal
        return None


class _RssProbe:
    """CURRENT resident-set size in KB -- rises AND falls, so a delta across a member
    measures that member (S6.2).

    RESOLVED ONCE, before anything is measured, because the instrument perturbs what it
    reads. The 2026-09-03 portability measurement ran each candidate five times on one
    workload: ``/proc`` and ONE HOISTED ``psutil.Process`` both reported 31.9 MB freed,
    5/5, agreeing to the hundredth of a MB, while a fresh ``psutil.Process()`` per read
    reported 0 MB and a forking ``ps -o rss=`` reported -0.1 MB -- the fork prevents the
    allocator returning the pages, so those two would have made an honest release read as
    "the trim freed nothing" on every platform they answered on.

    Order: ``merge_diag._rss_current_mb`` (``/proc/self/statm``, Linux, no dependency and
    no fork -- REUSED rather than re-implemented), then one hoisted ``psutil.Process``
    where ``/proc`` is absent, then nothing. ``basis`` NAMES which instrument answered, so
    a platform where no current reading exists says so instead of having a high-water
    figure published under the current-RSS name.
    """

    def __init__(self) -> None:
        self._proc = None
        self.basis = "unavailable"
        try:
            from src.monitoring.merge_diag import _rss_current_mb

            if _rss_current_mb() is not None:
                self.basis = "proc"
                return
        except Exception:  # noqa: BLE001 - an absent /proc is a platform fact
            pass
        try:
            import psutil

            proc = psutil.Process()
            proc.memory_info()  # prove it reads before claiming the basis
            self._proc = proc
            self.basis = "psutil"
        except Exception:  # noqa: BLE001 - absent psutil is a platform fact, not a failure
            self._proc = None

    def kb(self) -> int | None:
        """The current reading in KB, or None -- never a fabricated 0."""
        try:
            if self.basis == "proc":
                from src.monitoring.merge_diag import _rss_current_mb

                mb = _rss_current_mb()
            elif self.basis == "psutil" and self._proc is not None:
                mb = self._proc.memory_info().rss / 1024.0 / 1024.0
            else:
                return None
        except Exception:  # noqa: BLE001 - a reading is best-effort, never fatal
            return None
        return None if mb is None else int(mb * 1024)


# Trim only after a member that actually moved the resident set: ``malloc_trim`` walks the
# allocator's arenas, so running it after each of ~59 members would be noise on the wall
# clock and would report a freed figure for members that allocated nothing. The threshold is
# a stated choice, not a measurement -- what IS measured is the freed amount it reports.
_ALL_DIAG_TRIM_AFTER_KB = 64 * 1024  # 64 MiB


def _trim_after_heavy_member(probe: "_RssProbe", rss_after: int | None) -> dict | None:
    """Return the allocator's arena memory to the OS between heavy members, and report what
    that actually freed (S6.2). Reuses ``hygiene._malloc_trim`` rather than writing a second
    one. ``None`` when nothing was attempted; ``freed_kb: None`` -- never 0 -- when the
    call was made but the release could not be measured."""
    try:
        from src.scheduler.hygiene import _malloc_trim
    except Exception:  # noqa: BLE001 - instrumentation is never a hard dependency
        return None
    if not _malloc_trim():
        return None
    after = probe.kb()
    freed = (rss_after - after) if (rss_after is not None and after is not None) else None
    return {"trimmed": True, "freed_kb": freed}


_ALL_DIAG_DEADLINE_SENTINEL = object()


def _run_nondb_member_bounded(fn, budget_s: float):
    """Run a NON-DB member thunk on a daemon thread under a wall-clock budget (S8: safe
    ONLY because these members never touch the shared DB connection -- they may block on a
    socket or a file read, and abandoning the thread past budget cannot corrupt anything
    shared). Returns the thunk's value, or ``_ALL_DIAG_DEADLINE_SENTINEL`` if it is still
    running past ``budget_s`` (the thread is simply abandoned -- daemon, so it never blocks
    process exit). A raised exception inside the thunk is re-raised here so the caller's
    normal per-member except-block handles it uniformly with the inline DB path."""
    import threading

    box: dict = {}

    def _run() -> None:
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001 - re-raised on the caller's side below
            box["error"] = exc

    t = threading.Thread(target=_run, name="all-diag-member", daemon=True)
    t.start()
    t.join(budget_s)
    if t.is_alive():
        return _ALL_DIAG_DEADLINE_SENTINEL
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _all_diag_err_str(exc: Exception) -> str:
    """Render a member's exception for the envelope/error-file -- even a broken ``__str__``
    must still yield a marker (S8 lesson: a failed member must never be silently lost)."""
    try:
        return str(exc)[:300]
    except Exception:  # noqa: BLE001
        return f"<{type(exc).__name__}: unrenderable>"


# RATCHET (2026-07-17) + RUNTIME COVERAGE (DIAGNOSE-THE-DIAGNOSTICS, 2026-07-20): the
# SINGLE source of truth for "every GET diagnostics route is either a bundle member or a
# documented exemption" -- shared by test_repo_invariants' CI-time ratchet (which imports
# these two dicts rather than hand-duplicating them) AND the manifest's runtime coverage
# block below, so the CI-time check and the artifact's own self-description can never
# silently diverge from each other.
_DIAG_COVERAGE_MAP: dict[str, str] = {
    "/keywords": "keyword-log-digest.json",  # digest form; full dump exempt below
    "/keyword-selftest": "keyword-selftest.json",
    "/ir-eval-selftest": "ir-eval-selftest.json",
    "/perception-eval-selftest": "perception-eval-selftest.json",
    "/perception-eval-live/last": "perception-eval-live.json",
    "/keyword-triage-selftest": "keyword-triage-selftest.json",
    "/recursive-loop": "recursive-loop.json",
    "/merge": "merge-diag.json",
    "/kpi": "kpi.json",
    "/search-timing": "search-timing.json",
    "/run-journal": "run-journal.json",
    "/run-timeline": "run-timeline.json",
    "/search-timing-selftest": "search-timing-selftest.json",
    "/lemma-preview": "lemma-preview.json",
    "/bulletin-language": "bulletin-language.json",
    "/bulletin-language-selftest": "bulletin-language-selftest.json",
    "/home-cards": "home-cards.json",
    "/keyword-engine": "keyword-engine.json",
    "/power-profile": "power-profile.json",
    "/power-profile-selftest": "power-profile-selftest.json",
    "/article-length": "article-length.json",
    "/month-occupancy": "month-occupancy.json",
    "/non-article-scan": "non-article-scan.json",
    "/criteria-calibration": "criteria-calibration.json",  # S3.1 of the 2026-07-23 field-feedback workflow
    "/keyword-growth": "keyword-growth.json",
    "/source-audit": "source-audit.json",
    "/source-audit-selftest": "source-audit-selftest.json",
    "/source-qualification-export": "source-qualification-export.json",
    "/qualification-integrity": "qualification-integrity.json",
    "/dates": "date-extraction.json",
    "/performance": "performance.json",
    "/benchmark": "benchmark.json",
    "/network": "network.json",
    "/columnar": "columnar.json",
    "/freshness": "freshness.json",
    "/elections-floor": "elections-floor.json",
    "/session-forensics": "session-forensics.json",
    "/data-dir-persistence": "data-dir-persistence.json",
    "/storage-footprint": "storage-footprint.json",
    "/storage-composition": "storage-composition.json",
    "/windows-locks": "windows-locks.json",
    "/frontend-errors": "frontend-errors.json",
    "/request-latency": "request-latency.json",
    "/soak-window": "soak-window.json",  # S4 (2026-09-07): the multi-day soak reading
    "/write-gate": "write-gate.json",  # S2.6 (2026-09-02): who holds the gate / a connection
    "/stall-forensics": "stall-forensics.json",
    "/slow-queries": "slow-queries.json",
    "/schema-drift": "schema-drift.json",
    "/integrity": "corpus-integrity.json",
    "/country-code-duplicates": "country-code-duplicates.json",
    "/debug-bundle": "debug-bundle.json",
    "/p0-validation/last": "p0-validation.json",
    "/release-run/last": "release-run.json",  # the 0.4 release acceptance run (2026-09-18)
    "/chronology": "chronology.json",  # sessions, gaps, stretches, the run's phases (2026-09-18)
    "/law-coverage": "law-coverage.json",  # S5 of the law-vertical brief 2026-07-17
    "/law-ingest": "law-ingest.json",  # ruling 34c (field feedback 2026-08-07)
    "/leads-quality": "leads-quality.json",  # S6.1 of the Leads-calibration brief 2026-07-18
    "/card-audit": "card-audit.json",  # the DEEP card-system audit (summary depth)
    "/bulletin-preview": "bulletin-weekly.json",  # Bulletin Layer A, weekly period
    "/keyword-triage/last": "keyword-triage-run.json",
    "/keyword-triage/proposal": "keyword-triage-proposal.json",
    "/llm-throughput-selftest": "llm-throughput-selftest.json",
    "/ai-activity": "ai-activity.json",
    "/ai-activity-selftest": "ai-activity-selftest.json",
    "/source-tags-selftest": "source-tags-selftest.json",
    "/source-tags/last": "source-tags-run.json",
    "/perception-extract/last": "perception-extract-run.json",
    "/ai": "ai.json",
    "/qualification-assist-selftest": "qualification-assist-selftest.json",
    "/qualification-assist/last": "qualification-assist-run.json",
    "/model-bench/last": "model-bench.json",
    "/ai-check/last": "ai-check.json",
    # transversal audit 09 (2026-07-25), C2: /fixity is a genuine diagnostic-shaped
    # report (a local re-hash audit) that happened to live in the SIBLING
    # src/api/integrity.py router -- see _DIAG_SIBLING_FILES below, which is what
    # makes this path (and integrity.py's three functional exemptions right below)
    # visible to the scan at all.
    "/fixity": "fixity.json",
}
_DIAG_COVERAGE_EXEMPT: dict[str, str] = {
    "/source-quality": "whole-corpus decrypt ZIP export — own button (manifest 'excluded')",
    "/rollup-benchmark": "heavy operator-run benchmark (manifest 'excluded')",
    "/llm-bench": "heavy operator-run benchmark, needs a live model (manifest 'excluded')",
    "/llm-throughput": (
        "heavy operator-run concurrency sweep, needs a live model — minutes of real "
        "generation (manifest 'excluded'); its MECHANISM rides the bundle as "
        "llm-throughput-selftest.json"
    ),
    "/source-coverage-benchmark": "heavy operator-run benchmark (manifest 'excluded')",
    "/ir-eval": "needs an operator-graded gold-set file (manifest 'excluded')",
    "/gold-builder/sample": "interactive grading sampler, not a report (manifest 'excluded')",
    "/all": "the bundle itself",
    "/all-job/status": "job control", "/all-job/download": "job control",
    "/all-job/volumes": (
        "the bundle itself, re-packed — the SAME published archive split into "
        "attachment-sized zips, never a separate report that could disagree with it"
    ),
    "/all-job/volumes/{name}": "job control — one volume of the split bundle",
    "/p0-validation/status": "job control", "/p0-validation/download": "job control",
    "/release-run/status": "job control", "/release-run/download": "job control",
    "/discover-world/status": "job control",
    "/enrich-source-types/status": "job control",
    "/keyword-triage/status": "job control", "/keyword-triage/download": "job control",
    "/source-tags/status": "job control", "/source-tags/download": "job control",
    "/perception-extract/status": "job control", "/perception-extract/download": "job control",
    "/perception-extract/gate": "job control — a live, cheap gate preview, not a static report",
    "/ai-coordinator/status": "job control — the background-AI lane's live state",
    "/model-bench/status": "job control", "/model-bench/download": "job control",
    "/ai-check/status": "job control", "/ai-check/download": "job control",
    "/model-bench/batch": (
        "the frozen bench INPUT's own summary — the RESULTS ride the bundle as "
        "model-bench.json, and that member already states the batch digest it answered"
    ),
    "/model-bench/anchors": (
        "the interactive grading sitting (and its sample), not a report — the anchors' "
        "effect is reported inside model-bench.json as anchor accuracy"
    ),
    "/model-bench/gates": (
        "a LIVE per-language gate view computed from the bench artifact, not a static "
        "report — the artifact itself (model-bench.json) is the bundle member"
    ),
    "/card-audit/status": "job control", "/card-audit/download": "job control",
    "/card-audit/preflight": (
        "a live, cheap size ESTIMATE for a deep run, not a static report — the "
        "summary-depth audit itself is the bundle member (card-audit.json)"
    ),
    # src/api/integrity.py (transversal audit 09, C2): functional source-integrity
    # API endpoints a UI feature calls directly (coordination/prominence views) —
    # not diagnostic reports, unlike their sibling /fixity above.
    "/profile": "functional source-integrity API (src/api/integrity.py), not a diagnostic report",
    "/actors": "functional source-integrity API (src/api/integrity.py), not a diagnostic report",
    "/prominence": "functional source-integrity API (src/api/integrity.py), not a diagnostic report",
}
# transversal audit 09 (2026-07-25), C2: the completeness ratchet below was found
# structurally blind to any diagnostic-shaped GET route living in a SIBLING router
# file (integrity.py's own /fixity local audit was invisible to it) -- both the
# runtime coverage report AND the CI ratchet test now scan every file named here, in
# ADDITION to this module's own source, so a future diagnostic hiding in another
# router closes the SAME class of gap in one line rather than being independently
# rediscovered. Filenames are relative to this module's own directory (src/api/).
_DIAG_SIBLING_FILES: tuple[str, ...] = ("integrity.py",)


def _diagnostics_coverage_report() -> dict:
    """Recompute the route-vs-member-vs-exemption completeness comparison AT RUN TIME
    (maintainer ruling: "ensured in the log, not just in CI") -- reads THIS module's own
    source PLUS every ``_DIAG_SIBLING_FILES`` router (never anything unlisted), the same
    technique the CI ratchet uses, against the shared ``_DIAG_COVERAGE_MAP``/
    ``_DIAG_COVERAGE_EXEMPT`` above so the two checks cannot silently diverge. Degrades to
    ``{"available": False}`` rather than ever failing the whole bundle build over an
    introspection quirk."""
    import re as _re

    try:
        src = package_source()
        gets = set(_re.findall(r'@router\.get\("([^"]+)"', src))
        for _fname in _DIAG_SIBLING_FILES:
            gets |= set(
                _re.findall(
                    r'@router\.get\("([^"]+)"',
                    (api_dir() / _fname).read_text(encoding="utf-8"),
                )
            )
        covered = set(_DIAG_COVERAGE_MAP)
        exempt = set(_DIAG_COVERAGE_EXEMPT)
        unclassified = sorted(gets - covered - exempt)
        stale = sorted((covered | exempt) - gets)
        members_block = src.split("def _all_diagnostics_members", 1)[1].split("def _", 1)[0]
        missing_members = sorted(
            fname for fname in _DIAG_COVERAGE_MAP.values() if f'"{fname}"' not in members_block
        )
        return {
            "available": True,
            "total_get_routes": len(gets),
            "covered_routes": len(covered),
            "exempt_routes": len(exempt),
            "unclassified": unclassified,
            "stale_classifications": stale,
            "missing_bundle_members": missing_members,
            "complete": not unclassified and not stale and not missing_members,
        }
    except Exception as exc:  # noqa: BLE001 - a coverage-recompute glitch must not sink the run
        return {"available": False, "reason": _all_diag_err_str(exc)}


def _chronology_member() -> dict:
    """The install's chronology as a bundle member (read-only): the session ledger's
    sessions, gaps and suspends, the release run's phases and stretches, the summary."""
    try:
        from src.monitoring.chronology import chronology

        return chronology(anchor="run")
    except Exception as exc:  # noqa: BLE001 - a member that fails says so, never blanks
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"[:300]}


def _release_run_last() -> dict:
    """The newest 0.4 release-run report as a bundle member (read-only; never runs one).

    A named function with a LAZY import, for the same two reasons ``_country_code_scan``
    is one: the lambda in the members list reads as one call, and importing the route
    slice here would register its routes at the bundle's import position, which the
    Q1139 split guard pins by name."""
    from src.monitoring.release_run import last_release_run_report

    return last_release_run_report()


def _country_code_scan(db) -> dict:
    """The Q310 duplicate-key scan as a bundle member.

    A named function rather than an inline import so the lambda above reads as one
    call, and so a test can monkeypatch THIS name to prove the member is wired (the
    recorded "a test of a helper is not a test of its wiring" gap)."""
    from src.backup.country_codes import scan_live_corpus

    return scan_live_corpus(db)


def _corpus_counters_safe(db) -> dict:
    """A read-only articles/keywords/mentions snapshot for the manifest run header -- so a
    reader comparing logs across runs/machines knows what CORPUS SIZE produced each one.
    Bounded by the same DB-member statement deadline; degrades honestly if db is absent
    (the sync route's absorption-gated test path) or the read itself fails/times out."""
    if db is None:
        return {"available": False, "reason": "no database session"}
    try:
        with statement_deadline(db, _all_diag_db_member_deadline_s()):
            return {
                "available": True,
                "articles": int(db.query(func.count(Article.id)).scalar() or 0),
                "keywords": int(db.query(func.count(Keyword.id)).scalar() or 0),
                "mentions": int(db.query(func.count(KeywordMention.id)).scalar() or 0),
            }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": _all_diag_err_str(exc)}


def _schema_head_safe() -> str:
    """The migrations script directory's head revision (what the CODE expects), via
    alembic's ScriptDirectory API -- never a regex-scan, never a fabricated guess.
    'unavailable' on any failure (alembic missing, a branched/multi-head history, an
    unreadable migrations/ dir)."""
    try:
        from src.database.migrate import schema_head

        head = schema_head()
        return head if head else "unavailable"
    except Exception:  # noqa: BLE001
        return "unavailable"


def _disk_rotational_probe(target_dir) -> object:
    """Honest Linux-only probe of whether the disk backing ``target_dir`` is rotational
    (HDD) or not (SSD/NVMe), via ``/sys/block/*/queue/rotational`` -- the exact file the
    AMENDED ruling names. Resolves the SPECIFIC block device backing the directory via
    ``os.stat().st_dev`` -> ``/sys/dev/block/<major>:<minor>`` where possible (a partition
    node's queue/ lives on its parent whole-disk device); falls back to the first probed
    device in ``/sys/block/*`` if the precise resolution fails. Returns the honest string
    'unavailable' on non-Linux platforms or if sysfs is unreadable -- NEVER fabricated."""
    import sys as _sys

    if not _sys.platform.startswith("linux"):
        return "unavailable"
    try:
        st = os.stat(target_dir)
        major, minor = os.major(st.st_dev), os.minor(st.st_dev)
        node = pathlib.Path(f"/sys/dev/block/{major}:{minor}").resolve()
        for cand in (node / "queue" / "rotational", node.parent / "queue" / "rotational"):
            if cand.exists():
                val = cand.read_text(encoding="utf-8").strip()
                return "rotational" if val == "1" else "ssd/nvme"
    except Exception:  # noqa: BLE001 - fall through to the coarse scan below
        pass
    try:
        import glob as _glob

        for qpath in sorted(_glob.glob("/sys/block/*/queue/rotational")):
            dev = qpath.split("/")[3]
            if dev.startswith(("loop", "ram")):
                continue
            val = pathlib.Path(qpath).read_text(encoding="utf-8").strip()
            return "rotational" if val == "1" else "ssd/nvme"
    except Exception:  # noqa: BLE001
        pass
    return "unavailable"


def _cpu_model_safe() -> str:
    """Best-effort CPU model string, LOCAL reads only, zero network. 'unavailable' if the
    platform-specific source can't be read (never fabricated)."""
    import sys as _sys

    try:
        if _sys.platform.startswith("linux"):
            with open("/proc/cpuinfo", encoding="utf-8") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        elif _sys.platform == "darwin":
            import subprocess

            out = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=2,
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        else:
            import platform as _platform

            proc = _platform.processor()
            if proc:
                return proc
    except Exception:  # noqa: BLE001
        pass
    return "unavailable"


def _hardware_profile() -> dict:
    """LOCAL machine facts for the manifest run header (AMENDED ruling, 2026-07-20):
    cross-machine comparison is the point (the maintainer tests across several rigs incl.
    low/cheap/old laptops), so every measurement in the log needs the hardware it was taken
    on stated alongside it. All reads are LOCAL (stdlib os/platform/shutil + the already-
    depended-on psutil); zero network calls. Every field degrades to the honest string
    'unavailable' rather than a guess; an operator-set ``OO_MACHINE_LABEL`` (optional) makes
    logs from different machines distinguishable at a glance."""
    import platform as _platform
    import shutil as _shutil

    try:
        os_name = _platform.platform()
    except Exception:  # noqa: BLE001 - degrade honestly, never guess or crash the run
        os_name = "unavailable"
    try:
        kernel = _platform.release()
    except Exception:  # noqa: BLE001
        kernel = "unavailable"
    profile: dict = {
        "os": os_name,
        "kernel": kernel,
        "cpu_model": _cpu_model_safe(),
        "machine_label": os.environ.get("OO_MACHINE_LABEL") or None,
    }
    try:
        import psutil

        profile["cpu_physical_cores"] = psutil.cpu_count(logical=False) or "unavailable"
        profile["cpu_logical_cores"] = psutil.cpu_count(logical=True) or "unavailable"
        freq = psutil.cpu_freq()
        profile["cpu_freq_mhz"] = round(freq.current, 1) if freq and freq.current else "unavailable"
        vm = psutil.virtual_memory()
        sm = psutil.swap_memory()
        profile["ram_total_bytes"] = int(vm.total)
        profile["swap_total_bytes"] = int(sm.total)
    except Exception:  # noqa: BLE001 - psutil unavailable/unsupported on this platform
        for k in (
            "cpu_physical_cores", "cpu_logical_cores", "cpu_freq_mhz",
            "ram_total_bytes", "swap_total_bytes",
        ):
            profile.setdefault(k, "unavailable")
    try:
        target = str(_all_diagnostics_dir())
        profile["disk_free_bytes"] = int(_shutil.disk_usage(target).free)
    except Exception:  # noqa: BLE001
        target = "."
        profile["disk_free_bytes"] = "unavailable"
    profile["disk_rotational"] = _disk_rotational_probe(target)
    return profile


def _all_diagnostics_manifest(
    results: list[dict],
    *,
    db=None,
    run_started_at: float | None = None,
    run_ended_at: float | None = None,
    exclusive: dict | None = None,
    profile: str = "full",
) -> dict:
    import platform
    import sys as _sys

    run_started_iso = (
        datetime.fromtimestamp(run_started_at).isoformat(timespec="seconds")
        if run_started_at else None
    )
    run_ended_iso = (
        datetime.fromtimestamp(run_ended_at).isoformat(timespec="seconds")
        if run_ended_at else None
    )
    total_wall_s = (
        round(run_ended_at - run_started_at, 3)
        if (run_started_at is not None and run_ended_at is not None) else None
    )
    slowest_members = sorted(
        (
            {"file": r["file"], "wall_s": r["wall_s"]}
            for r in results if r.get("wall_s") is not None
        ),
        key=lambda r: r["wall_s"], reverse=True,
    )[:10]

    return {
        "export_schema": "oo-export-1",
        "kind": "all-diagnostics",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "python": _sys.version.split()[0],
        "platform": platform.platform(),
        # RUN HEADER (DIAGNOSE-THE-DIAGNOSTICS, 2026-07-20): the 0.3 gate row-3 tie-in --
        # a failed hour-long 5M-scale run must be diagnosable FROM THE ARCHIVE ITSELF, not
        # just from having watched it live. Corpus size + app/schema version + the hardware
        # it ran on + which member ate the wall time, all in one place.
        "run": {
            "app_version": app_version(),
            "schema_head": _schema_head_safe(),
            "corpus": _corpus_counters_safe(db),
            "hardware": _hardware_profile(),
            "started_at": run_started_iso,
            "ended_at": run_ended_iso,
            "total_wall_s": total_wall_s,
            "slowest_members": slowest_members,
            "runtime_coverage": _diagnostics_coverage_report(),
            # EXCLUSIVE HOLD (S6.1, 2026-09-03): what the run actually claimed, not what
            # it wished for. `held` says the hold was taken; `paused_collection` says the
            # continuous loop was RUNNING and got signalled -- the pause is bounded and
            # best-effort, so a pass already deep in a fetch may still have been finishing
            # while this bundle ran. A degrade carries its `reason` instead. Never a bare
            # "exclusive: true", which would assert an isolation the pause cannot confirm.
            "exclusive": exclusive
            if exclusive is not None
            else {"held": False, "reason": "not requested by this caller"},
        },
        "members": results,
        # THE PROFILE THIS RUN USED, and what it cost (the light/full toggle, 2026-09-22).
        # AT THE TOP LEVEL, not inside "run": a reader deciding whether this archive can
        # answer their question asks it before anything else, and gate row C's bar ("every
        # member non-zero") is only meaningful against a FULL run. `complete_profile` is
        # the one boolean a gate check should read -- never the member count, which a light
        # run keeps intact by design because the declined members are still listed.
        "profile": {
            "name": profile,
            "complete_profile": profile == "full",
            "declined": [
                {"file": r["file"], "reason": r.get("declined_reason")}
                for r in results if r.get("outcome") == "declined-light"
            ],
            "note": (
                "Every member ran; nothing was declined."
                if profile == "full"
                else "The operator chose the LIGHT profile. The members listed in "
                "'declined' were NOT collected, each for the stated reason, and their "
                "absence is a choice rather than a failure. Re-run under the FULL "
                "profile to collect them."
            ),
        },
        # HONESTY (2026-07-17): what is deliberately NOT in this archive, and why —
        # so "all diagnostics" states its own boundary instead of implying totality.
        "excluded": [
            {
                "endpoint": "/api/diagnostics/keywords",
                "reason": "the FULL keyword corpus dump has its own sized/paged export; "
                "the bounded keyword-log DIGEST is included instead",
            },
            {
                "endpoint": "/api/diagnostics/source-quality",
                "reason": "a whole-corpus decrypt pass producing a bulky per-source "
                "text-sample ZIP — run it from its own Diagnostics button",
            },
            {
                "endpoint": "/api/diagnostics/card-audit/preflight",
                "reason": "a live size ESTIMATE for a deep card-audit run, not a static "
                "report — the SUMMARY-depth audit itself IS a bundle member "
                "(card-audit.json); the deeper depths carry article CONTENT and are "
                "an operator-chosen background job",
            },
            {
                "endpoint": "/api/diagnostics/rollup-benchmark",
                "reason": "a heavy live-vs-rollup benchmark over the real corpus — "
                "operator-run from its own button",
            },
            {
                "endpoint": "/api/diagnostics/source-coverage-benchmark",
                "reason": "same class: a heavy operator-run benchmark",
            },
            {
                "endpoint": "/api/diagnostics/model-bench/run",
                "reason": "the comparative model bench loads every roster model in turn "
                "and can run for hours — operator-run from its own button on the machine "
                "that hosts the models. Its RESULT rides the bundle as model-bench.json",
            },
            {
                "endpoint": "/api/diagnostics/ir-eval",
                "reason": "needs an operator-graded gold-set file as input",
            },
            {
                "endpoint": "/api/diagnostics/gold-builder/sample",
                "reason": "an interactive grading sampler, not a report",
            },
            {
                "endpoint": "job control/status/download endpoints",
                "reason": "p0-validation, keyword-triage and source-tags each "
                "contribute their LAST saved report/summary as a member; starting/cancelling a "
                "job or downloading its raw dated JSONL log is not a report",
            },
        ],
        "note": (
            "Every diagnostics log in one archive (the maintainer↔developer channel). "
            "Deliberate exclusions are listed in 'excluded' with reasons. "
            "Generated only on click; nothing is transmitted by the app."
        ),
    }


def _write_all_diagnostics_zip(
    members, zf, *, progress=None, should_stop=None, journal_path=None, db=None,
    exclusive=None, profile="full",
) -> list[dict]:
    """Write every member (+ manifest) into the open ZipFile ``zf``; return the per-member
    results. Shared by the sync endpoint (an in-memory BytesIO) and the job (a file on disk).
    ``progress(done, total, name)`` reports live progress; ``should_stop()`` lets the job
    cancel cooperatively BETWEEN members (a single member — e.g. the benchmark — can't be
    interrupted mid-run). One failing log never aborts the bundle (a ``<name>.error.txt`` is
    written and recorded in the manifest).

    ENVELOPE (0.3 gate row 3 / DIAGNOSE-THE-DIAGNOSTICS, 2026-07-20): every member records
    ``{file, ok, outcome, started_at, wall_s, bytes, rss_basis[, error][, rss_delta_kb]
    [, rss_peak_rise_kb][, release]}`` -- ``ok`` is KEPT (True iff ``outcome == "ok"``) for
    any reader still on the old boolean.

    S6.2 (2026-09-03): ``rss_delta_kb`` was computed from ``ru_maxrss``, a process
    high-water mark that never falls, so every member after the first big one reported 0.
    It is now a CURRENT-RSS delta, the high-water rise keeps its own name
    (``rss_peak_rise_kb``), and ``rss_basis`` says which instrument answered so a platform
    with no current reading cannot be mistaken for one. After a member that actually moved
    the resident set, ``hygiene._malloc_trim`` returns the allocator's arenas to the OS and
    ``release.freed_kb`` records what that measured -- so a delta that survives a trim is a
    real retention rather than allocator noise.

    DEADLINES (S8 lesson): a member whose thunk closes over ``db`` (touches the shared
    connection) runs INLINE under a statement deadline — never threaded, because a shared
    SQLite/SQLCipher connection BLOCKS (not errors) under concurrent use and a statement
    deadline bounds only SQL VM opcodes, never the Python row-materialisation around them,
    so a DB worker could never be cleanly abandoned mid-query. A non-DB member runs on a
    daemon wall-clock-bounded thread. Either way a timeout records outcome
    ``skipped-deadline`` honestly and the bundle CONTINUES to the next member (never aborts).

    PROFILE (the light/full toggle, 2026-09-22): ``"light"`` DECLINES the members named in
    ``_LIGHT_DECLINED`` before they run, recording outcome ``declined-light`` and writing a
    ``<name>.declined.txt`` carrying that member's measured reason and the one sentence that
    undoes it. A decline is never a blank and never a zero standing on its own: the outcome
    names it, the marker file explains it, and the manifest lists it beside the profile that
    caused it, so a light bundle can never be read as a full one that came back empty.
    ``"full"`` (the default) declines nothing and is byte-identical to the behaviour before
    this parameter existed.

    JOURNAL: when ``journal_path`` is given (the background job path only — the sync route's
    in-memory BytesIO build has no durable file to journal against), a begin/end JSON line is
    appended + fsync'd around every member, so a HARD-killed run's last ``begin`` with no
    matching ``end`` NAMES the culprit member — a diagnosis the in-memory manifest (written
    only once, at the very end) cannot offer a crashed run."""
    import time as _time

    results: list[dict] = []
    total = len(members)
    run_started_at = _time.time()
    # Left open across the whole loop (appended + fsync'd per member) and closed in the
    # `finally` below -- a `with` here would have to wrap the entire member loop AND the
    # conditional-None case, which reads worse than the explicit open/close pair below.
    journal_fp = (
        open(journal_path, "a", encoding="utf-8")  # noqa: SIM115
        if journal_path is not None else None
    )
    # S6.2: resolved ONCE, before the first member is measured -- a memory instrument
    # rebuilt per reading perturbs the very thing it reads (measured 5/5).
    _rss = _RssProbe()
    try:
        for i, (name, fn) in enumerate(members):
            if should_stop is not None and should_stop():
                break
            if progress is not None:
                progress(i, total, name)
            started_t = _time.time()
            started_iso = datetime.now().isoformat(timespec="seconds")
            if journal_fp is not None:
                try:
                    journal_fp.write(
                        json.dumps(
                            {"event": "begin", "file": name, "i": i, "total": total,
                             "started_at": started_iso}
                        ) + "\n"
                    )
                    journal_fp.flush()
                    with contextlib.suppress(OSError):
                        os.fsync(journal_fp.fileno())
                except OSError:
                    # The journal is a diagnostic aid, not the bundle itself -- a write
                    # failure (e.g. ENOSPC on the sidecar's disk) must degrade the run to
                    # unjournaled rather than abort a hard-won hour-long bundle.
                    _LOG.warning(
                        "all-diagnostics journal write failed; disabling journal for the "
                        "rest of this run", exc_info=True
                    )
                    with contextlib.suppress(OSError):
                        journal_fp.close()
                    journal_fp = None

            rss_before = _rss.kb()
            peak_before = _rss_peak_kb()
            outcome = "ok"
            err: str | None = None
            nbytes = 0
            declined_reason = _LIGHT_DECLINED.get(name) if profile == "light" else None
            try:
                if declined_reason is not None:
                    # DECLINED BEFORE IT RUNS, which is the whole point: the cost this
                    # avoids is paid at the first byte, so a deadline or a byte cap would
                    # arrive far too late to keep a 4 GB machine out of swap.
                    outcome = "declined-light"
                    zf.writestr(
                        name + ".declined.txt",
                        (
                            f"{name} was NOT collected: this bundle ran under the LIGHT "
                            f"profile.\n\nWhy this member is in the light profile's "
                            f"declined set:\n  {declined_reason}\n\n"
                            "This is a choice the operator made, not a failure and not a "
                            "limit the app hit. Run the bundle again under the FULL "
                            "profile to collect it.\n"
                        ).encode(),
                    )
                elif db is not None and _member_touches_db(fn):
                    with statement_deadline(db, _all_diag_db_member_deadline_s()):
                        value = fn()
                        # S2.2: a member that STOPPED at the deadline and returned
                        # what it had is PARTIAL, not skipped. Recording
                        # "skipped-deadline" writes only a marker (see the branch
                        # below) and would DISCARD the payload -- home-cards' cards,
                        # card-audit's diagnoses -- which is the opposite of what an
                        # operator diagnosing a slow machine needs. Read the expiry
                        # INSIDE the block: leaving it restores the enclosing value.
                        if deadline_expired(db):
                            outcome = "partial-deadline"
                else:
                    value = _run_nondb_member_bounded(fn, _all_diag_nondb_member_deadline_s())
                    if value is _ALL_DIAG_DEADLINE_SENTINEL:
                        outcome = "skipped-deadline"
                if outcome in ("ok", "partial-deadline"):
                    # Streamed straight into the archive rather than materialised
                    # (field diagnostics 2026-09-11, B2 second half) -- see
                    # _write_member for why the old `writestr(_member_bytes(...))`
                    # cost three copies of the largest member.
                    nbytes = _write_member(zf, name, value)
                elif outcome == "skipped-deadline":
                    # NAMED, not an `else`. This branch used to be the catch-all, which
                    # made it a deadline marker for any outcome that was not ok -- so the
                    # declined-light member above would have shipped a file saying it
                    # "exceeded its wall-clock deadline and was abandoned", a fabricated
                    # cause for something the operator chose. An outcome that writes its
                    # own marker must name itself here.
                    marker = (
                        f"member exceeded its {_all_diag_nondb_member_deadline_s():.0f}s "
                        "wall-clock deadline and was abandoned (non-DB member)"
                    ).encode()
                    zf.writestr(name + ".skipped-deadline.txt", marker)
            except StatementTimeout as exc:
                outcome = "skipped-deadline"
                zf.writestr(name + ".skipped-deadline.txt", _all_diag_err_str(exc))
            except Exception as exc:  # noqa: BLE001 - one failing member must not abort the bundle
                outcome = "error"
                err = _all_diag_err_str(exc)
                zf.writestr(name + ".error.txt", err)

            wall_s = round(_time.time() - started_t, 3)
            rss_after = _rss.kb()
            peak_after = _rss_peak_kb()
            entry: dict = {
                "file": name,
                "ok": outcome == "ok",
                "outcome": outcome,
                "started_at": started_iso,
                "wall_s": wall_s,
                "bytes": nbytes,
            }
            if err is not None:
                entry["error"] = err
            if declined_reason is not None:
                # The reason travels IN the manifest, not only in the marker file: a reader
                # parsing manifest.json must be able to say why a member is absent without
                # opening a sidecar .txt, or the absence reads as a gap in the run.
                entry["declined_reason"] = declined_reason
            # S6.2: the delta is now CURRENT RSS, which rises and falls, so it measures
            # THIS member. ``rss_basis`` names the instrument, and the high-water rise
            # keeps its own name rather than being published as the same number under a
            # different meaning -- "did this member allocate 40 MB" and "did it push the
            # process past its all-time peak" are different questions and only one of them
            # can be answered after the first big member.
            entry["rss_basis"] = _rss.basis
            if rss_before is not None and rss_after is not None:
                entry["rss_delta_kb"] = rss_after - rss_before
            if peak_before is not None and peak_after is not None:
                entry["rss_peak_rise_kb"] = peak_after - peak_before
            if rss_before is not None and rss_after is not None \
                    and (rss_after - rss_before) >= _ALL_DIAG_TRIM_AFTER_KB:
                trim = _trim_after_heavy_member(_rss, rss_after)
                if trim is not None:
                    entry["release"] = trim
            results.append(entry)

            if journal_fp is not None:
                try:
                    journal_fp.write(
                        json.dumps(
                            {"event": "end", "file": name, "outcome": outcome, "wall_s": wall_s}
                        ) + "\n"
                    )
                    journal_fp.flush()
                    with contextlib.suppress(OSError):
                        os.fsync(journal_fp.fileno())
                except OSError:
                    _LOG.warning(
                        "all-diagnostics journal write failed; disabling journal for the "
                        "rest of this run", exc_info=True
                    )
                    with contextlib.suppress(OSError):
                        journal_fp.close()
                    journal_fp = None
    finally:
        if journal_fp is not None:
            journal_fp.close()

    run_ended_at = _time.time()
    manifest = _all_diagnostics_manifest(
        results, db=db, run_started_at=run_started_at, run_ended_at=run_ended_at,
        exclusive=exclusive, profile=profile,
    )
    zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    # Fold the durable journal into the finished archive as bundle-journal.jsonl -- the
    # sidecar on disk has done its job (any hard-kill forensics happen from the sidecar
    # ITSELF, before this point is ever reached); the caller removes the sidecar file.
    if journal_path is not None and pathlib.Path(journal_path).exists():
        zf.writestr(
            "bundle-journal.jsonl", pathlib.Path(journal_path).read_text(encoding="utf-8")
        )
    if progress is not None:
        progress(total, total, "done")
    return results



@router.get("/all")
def all_diagnostics(
    profile: str = Query("full", description="full | light"),
    db: Session = Depends(get_db),
) -> Response:
    """EVERY diagnostics log in ONE archive (maintainer field report 2026-06-22:
    "there should be the option to download all diagnostics logs at once").

    A single click instead of nine. Each member is generated by the same function its
    own button calls, wrapped so one failing log never aborts the bundle (it writes a
    ``<name>.error.txt`` and records it in the manifest). The full keyword CORPUS dump
    is NOT here — it has its own sized/paged export ("All keywords") — so this carries
    the bounded keyword-log DIGEST instead. Read-only, on-demand, never transmitted.

    NOTE (D2): at scale this synchronous build measured 36+ min and held a threadpool
    thread the whole time — the ``/all-job`` route runs the SAME build as a cancellable
    background JOB writing to a server-side file. This route is KEPT (absorption-gated) so
    the existing UI never breaks during the transition."""
    import io
    import zipfile

    buf = io.BytesIO()
    # S6.1: both entry points to this build take the hold, not just the job. The
    # PR-13 lesson in miniature -- a guard wired into one of two callers is the
    # gate-every-entry-point defect, and this route can run for 36+ minutes.
    with _bundle_exclusive_window() as excl, \
            zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        _write_all_diagnostics_zip(
            _all_diagnostics_members(db), z, db=db, exclusive=excl,
            profile=resolve_bundle_profile(profile),
        )
    fname = f"oo-all-diagnostics-{datetime.now().strftime('%Y%m%d-%H%M')}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# --------------------------------------------------------------------------- #
# All-diagnostics as a background JOB (D2 / field-test Item 10, measured 36+ min).
# The build runs the SAME members off the request thread, streams the zip to a
# server-side file under data_dir()/diagnostics/, and reports per-member progress. The
# synchronous /all route above is kept during the transition (absorption-gated).
# --------------------------------------------------------------------------- #


def _bundle_exclusive_window():
    """S6.1: hold the machine for the bundle's duration, so it never competes with a
    collection pass, the housekeeping lane or the rollup build.

    Uses ``runner.exclusive_window()`` -- the existing RE-ENTRANT, imbalance-proof
    mechanism -- rather than calling ``hold_exclusive``/``release_exclusive`` directly.
    That distinction is load-bearing, not stylistic: ``_exclusive_hold`` is a BOOLEAN, so a
    bundle started during a restore would clear the RESTORE's hold on its own release and
    put a manual "Run now" back on the machine mid-restore -- reinstating exactly the
    concurrency defect the 2026-07-24 lesson records. ``exclusive_window`` restores the flag
    to what it FOUND, so only the outermost block ever resumes.

    Yields the honest facts rather than an assumed exclusivity: ``paused_collection`` is
    ``was_paused``, i.e. whether the continuous loop was actually running and got signalled
    -- the pause is bounded and best-effort, and a pass already deep in a fetch may still be
    finishing. ``nested`` says the machine was already owned by an outer operation.

    Ruling 4 is unaffected: this changes what else may run, never which members do. Every
    member still runs.
    """
    import contextlib as _cl

    @_cl.contextmanager
    def _cm():
        try:
            from src.scheduler.runner import exclusive_window, exclusive_window_open
        except Exception:  # noqa: BLE001 - a bundle must never fail for want of the hold
            yield {"held": False, "reason": "scheduler unavailable"}
            return
        nested = False
        try:
            nested = bool(exclusive_window_open())
        except Exception:  # noqa: BLE001 - an unknown state is never claimed as ownership
            nested = False
        try:
            with exclusive_window() as was_paused:
                yield {
                    "held": True, "paused_collection": bool(was_paused), "nested": nested,
                }
        except Exception:  # noqa: BLE001 - the bundle is the evidence channel; never lose it
            _LOG.warning("all-diagnostics could not claim the machine", exc_info=True)
            yield {"held": False, "reason": "could not claim the machine"}

    return _cm()


def _all_diagnostics_dir():
    from src.paths import data_dir

    d = data_dir() / "diagnostics"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _all_diagnostics_worker(ctx, profile: str = "full") -> dict:
    """Build the all-diagnostics archive to a server-side file (D2). Read-only; opens its own
    session so it never borrows the request's. Writes to a ``.part`` file and atomically
    renames on success, so a cancelled/failed run never leaves a half-written archive that
    the download could serve."""
    import os as _os
    import zipfile

    from src.database.session import session_scope

    out_dir = _all_diagnostics_dir()
    fname = f"oo-all-diagnostics-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    final_path = out_dir / fname
    part_path = out_dir / (fname + ".part")
    # DURABLE JOURNAL sidecar (DIAGNOSE-THE-DIAGNOSTICS, 2026-07-20): begin/end lines
    # appended + fsync'd around every member as the build runs, so a HARD kill (OOM/kill
    # -9, not a cooperative cancel) leaves this file on disk with its last `begin` unmatched
    # by an `end` -- naming the culprit member for an hour-long 5M-scale run gone wrong. On
    # a clean finish it is folded into the zip as bundle-journal.jsonl and the sidecar is
    # removed (its job is done); on a hard kill it simply survives as forensic evidence.
    journal_path = out_dir / (fname + ".journal.jsonl")
    with _bundle_exclusive_window() as excl, session_scope() as db:
        members = _all_diagnostics_members(db)

        def _progress(done, total, name):
            ctx.set_progress(done=done, total=total, detail=name)

        with zipfile.ZipFile(part_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            results = _write_all_diagnostics_zip(
                members, z, progress=_progress, should_stop=lambda: ctx.stopping,
                journal_path=journal_path, db=db, exclusive=excl,
                profile=resolve_bundle_profile(profile),
            )
    if ctx.stopping:
        # Cancelled between members: drop the partial, never present it as a good archive.
        with contextlib.suppress(OSError):
            part_path.unlink()
        with contextlib.suppress(OSError):
            journal_path.unlink()
        return {"cancelled": True, "members": results}
    _os.replace(part_path, final_path)  # atomic publish
    with contextlib.suppress(OSError):
        journal_path.unlink()  # folded into the zip as bundle-journal.jsonl already
    # Keep only the newest archive (the channel is one-shot; old ones just consume disk).
    # Also sweep any stale ``.part``/``.journal.jsonl`` left by a PREVIOUS crashed/killed
    # run — this run's own part/journal were just renamed away/removed, and the job is
    # single-instance, so no live writer is touched (no orphaned staging accumulates
    # across hard-kills).
    for old in (
        *out_dir.glob("oo-all-diagnostics-*.zip"),
        *out_dir.glob("oo-all-diagnostics-*.zip.part"),
        *out_dir.glob("oo-all-diagnostics-*.journal.jsonl"),
    ):
        if old != final_path:
            with contextlib.suppress(OSError):
                old.unlink()
    return {
        "path": str(final_path),
        "filename": fname,
        "bytes": final_path.stat().st_size,
        "members": results,
    }


_ALL_DIAG_JOB = register_job(
    BackgroundJob(
        "all-diagnostics", "Building the all-diagnostics archive", _all_diagnostics_worker,
        is_writer=False, cancellable=True,
    )
)


@router.post("/all-job")
def all_diagnostics_job_start(
    profile: str = Query("full", description="full | light"),
) -> JSONResponse:
    """Start the all-diagnostics archive build as a BACKGROUND job (D2). Returns immediately;
    poll ``/all-job/status`` (or the task manager) for per-member progress, then GET
    ``/all-job/download`` for the finished file. 409-free: if one is already running, the
    current status is returned with ``started:false``.

    ``profile`` is PER RUN and defaults to ``full``; it is deliberately NOT a stored setting.
    A remembered "light" would quietly make a LATER bundle light too -- including the one
    taken to close a release gate whose bar is every member non-zero -- and the operator
    would have no reason to suspect it. Asking once per run costs a click; a sticky choice
    costs the evidence."""
    try:
        return JSONResponse(
            {"started": True, "job": _ALL_DIAG_JOB.start(profile=resolve_bundle_profile(profile))}
        )
    except RuntimeError:
        return JSONResponse({"started": False, "job": _ALL_DIAG_JOB.status()})


@router.get("/all-job/status")
def all_diagnostics_job_status() -> JSONResponse:
    """Live status of the background all-diagnostics build (state, per-member progress, and —
    when done — the ready filename/size). No score."""
    st = _ALL_DIAG_JOB.status()
    res = st.get("result") or {}
    st["ready"] = bool(st.get("state") == "done" and res.get("path"))
    st["download_filename"] = res.get("filename")
    st["download_bytes"] = res.get("bytes")
    return JSONResponse(st)


def _newest_all_diagnostics_archive() -> pathlib.Path | None:
    """The newest FINISHED archive on disk, or None.

    ``.part`` files are excluded: one is an in-flight or abandoned build, and serving a
    truncated zip as a finished archive would be the worst possible answer for an operator
    who is already trying to diagnose something. The glob alone cannot match one (a
    ``.part`` name does not end in ``.zip``); the suffix check states the requirement
    instead of leaving it resting on that.
    """
    try:
        files = [
            p for p in _all_diagnostics_dir().glob("oo-all-diagnostics-*.zip")
            if p.suffix == ".zip" and p.is_file()
        ]
        # A file can vanish between glob and stat (the worker sweeps old archives), so the
        # key is guarded rather than allowed to raise out of a sort.
        return max(files, key=lambda p: p.stat().st_mtime) if files else None
    except OSError:
        return None


@router.get("/all-job/download")
def all_diagnostics_job_download() -> FileResponse:
    """Serve the finished background all-diagnostics archive (D2). 404 until a build has
    completed successfully (run ``/all-job`` first).

    FALLS BACK TO DISK when the in-memory job result is gone. The job object lives only as
    long as the process, while the archive it published lives in ``data_dir()/diagnostics/``
    until a later build sweeps it — so an app restart between a finished build and the click
    that claims it used to strand a multi-hour archive that was sitting right there,
    answering 404 about a file on disk. This is not hypothetical for this app: an OOM during
    a large import is precisely when the operator most needs the bundle and least likely to
    have kept the process alive.

    It NEVER falls back while a build is RUNNING. The operator asked the NEW run a question,
    and the previous run's archive cannot answer it; handing it over silently would be a
    fabricated result — the one thing a diagnostic must not produce.
    """
    st = _ALL_DIAG_JOB.status()
    res = st.get("result") or {}
    path = res.get("path")
    if st.get("state") == "done" and path and os.path.exists(path):
        return FileResponse(
            path, media_type="application/zip",
            filename=res.get("filename") or "oo-all-diagnostics.zip",
        )
    if st.get("state") != "running":
        on_disk = _newest_all_diagnostics_archive()
        if on_disk is not None:
            return FileResponse(
                str(on_disk), media_type="application/zip", filename=on_disk.name,
            )
    raise HTTPException(
        status_code=404,
        detail="no all-diagnostics archive is ready — start one with POST /api/diagnostics/all-job",
    )


# --------------------------------------------------------------------------- #
# THE ARCHIVE IN PIECES THAT FIT THE CHANNEL (field session 2026-09-11).
#
# The bundle exists to get evidence from the maintainer to the developer, and it had
# outgrown the channel: neither the archive nor keyword-log-digest.json extracted and
# re-zipped on its own would upload. A cap on that member is one half; this is the
# other. src/api/diagnostics_volumes.py splits the FINISHED archive into plain zips
# that each fit an attachment limit and each open on their own.
#
# ADDITIVE BY CONSTRUCTION: the single-file download is untouched and stays the default
# path. These routes only ever READ the published archive, so an operator who can send
# one file is never made to collect several.
# --------------------------------------------------------------------------- #


def _all_diagnostics_volumes_dir():
    """Volumes live in a SUBDIRECTORY of the archive dir.

    Load-bearing, not tidiness: the worker sweeps old archives with a non-recursive
    ``glob("oo-all-diagnostics-*.zip")`` over the parent, and volume files are named
    ``oo-all-diagnostics.001of003.zip``. Beside the archives they would match that glob
    and be deleted by the next build -- or, worse, be picked up by
    ``_newest_all_diagnostics_archive`` and served as if one volume were the bundle.
    """
    d = _all_diagnostics_dir() / "volumes"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ONE splitter at a time. Two clicks (or a click and a scripted call) would otherwise
# race on one directory: the second call's staleness sweep deletes the first call's
# volumes WHILE it is still writing them, and whichever finishes last publishes a
# manifest naming files the other already removed. Cheap to hold -- the split is bounded
# file work on an archive that is already final, and a second caller simply waits and
# then finds the finished set rather than rebuilding it.
_ALL_DIAG_VOLUMES_LOCK = threading.Lock()


def _ensure_volume_set(src: pathlib.Path) -> dict:
    """The volume set for ``src``, built only if it is not already the current one.

    Idempotent on the SOURCE ARCHIVE NAME: a second click re-serves the set instead of
    re-splitting, and an archive newer than the set replaces it. The stale set is
    removed rather than left to accumulate volumes of two different bundles in one
    directory, where an operator collecting files by glob would mix them.
    """
    from src.api import diagnostics_volumes as dvol

    out = _all_diagnostics_volumes_dir()
    with _ALL_DIAG_VOLUMES_LOCK:
        with contextlib.suppress(Exception):
            current = dvol.load_manifest(out)
            if current.get("source") == src.name and dvol.verify_volume_set(out)["ok"]:
                return current
        for stale in out.iterdir():
            with contextlib.suppress(OSError):
                stale.unlink()
        return dvol.write_volume_set(src, out)


@router.get("/all-job/volumes")
def all_diagnostics_volumes() -> JSONResponse:
    """The finished archive split into size-bounded, independently-openable ZIP volumes.

    Returns the manifest: every volume's name, byte count and SHA-256, which volume
    carries each member, and -- when a member was too large to fit one volume at all --
    which members are split and how to rejoin them. Download each volume from
    ``/all-job/volumes/{name}``.

    404 until a build has finished, and it NEVER splits a ``.part`` file: the source is
    the same published archive the single-file download serves, so the two can never
    disagree about what the bundle contains.

    TWO COSTS, STATED RATHER THAN DISCOVERED. It holds a request thread while it reads
    and re-compresses the archive once (seconds for a typical bundle; the sibling ``/all``
    route already runs for far longer on the same machine, so this is not a new kind of
    load). And it roughly DOUBLES the archive's footprint on disk while both exist, which
    on a machine already short of space is a real cost -- the volumes are removed and
    rebuilt when a newer archive replaces them, never accumulated across builds.
    """
    # NEVER serve a stale archive while a build is RUNNING -- the same refusal the
    # single-file download already makes, for the same reason. The operator asked the
    # NEW run a question and the previous run's bundle cannot answer it; splitting it up
    # and handing over the pieces would be a fabricated result wearing a fresh timestamp,
    # which is the one thing a diagnostic must not produce. Checked HERE rather than
    # inherited: _newest_all_diagnostics_archive only skips `.part` files, so on its own
    # it would cheerfully return the previous archive mid-build.
    if _ALL_DIAG_JOB.status().get("state") == "running":
        raise HTTPException(
            status_code=409,
            detail=(
                "a build is running — its archive is not ready to split, and the previous "
                "one cannot answer what this run was started to ask"
            ),
        )
    src = _newest_all_diagnostics_archive()
    if src is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "no all-diagnostics archive is ready to split — start one with "
                "POST /api/diagnostics/all-job"
            ),
        )
    try:
        manifest = _ensure_volume_set(src)
    except Exception as exc:  # noqa: BLE001 - the reason must reach the operator, not a 500
        raise HTTPException(status_code=500, detail=f"could not split the archive: {exc}") from exc
    return JSONResponse(manifest)


@router.get("/all-job/volumes/{name}")
def all_diagnostics_volume_download(name: str) -> FileResponse:
    """Serve ONE volume of the current set by name.

    The name is resolved against the MANIFEST's volume list rather than against the
    filesystem, so a caller cannot reach a path the set does not name -- no traversal,
    and no serving of a leftover file that happens to sit in the directory.
    """
    from src.api import diagnostics_volumes as dvol

    out = _all_diagnostics_volumes_dir()
    try:
        manifest = dvol.load_manifest(out)
    except dvol.VolumeError as exc:
        raise HTTPException(
            status_code=404,
            detail="no volume set is ready — call GET /api/diagnostics/all-job/volumes first",
        ) from exc
    if name not in {v["name"] for v in manifest["volumes"]}:
        raise HTTPException(status_code=404, detail=f"{name!r} is not a volume of this set")
    path = out / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{name!r} is missing from the volume set")
    return FileResponse(str(path), media_type="application/zip", filename=name)
