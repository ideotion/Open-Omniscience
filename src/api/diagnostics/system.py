"""
System, storage, network and integrity reports.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Part of the mechanical ``src/api/diagnostics.py`` -> package split (Q1139 = a,
2026-09-16): this file is lines 3009-3467 of the pre-split module, verbatim. The
routes, their paths, their methods and their order are unchanged; ``__init__``
imports the submodules in the original file order so the decorators still
register on one router in that order.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import Depends, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.database.session import get_db
from src.utils.export_envelope import envelope

from ._base import router


@router.get("/network")
def network_preflight_log() -> JSONResponse:
    """The network-targets diagnostics log (maintainer↔developer channel):
    source preflight verdicts + feed/calendar preflight verdicts + the full
    calendar verdict store — everything needed to optimize the default
    install's source/feed/calendar lists from REAL verdicts."""
    from src.events.feeds import load_verdicts
    from src.monitoring import feed_preflight
    from src.monitoring.preflight import recent_results as source_results

    payload = {
        "sources": source_results(),
        "feeds": feed_preflight.recent_results(),
        "calendar_verdicts": load_verdicts(),
        "method": (
            "Verbatim verdict logs: data/source_preflight.jsonl + "
            "data/feed_preflight.jsonl + the per-feed calendar checks. "
            "Robots verdicts use the standard taxonomy (allowed/disallowed/"
            "blocked/missing/unreachable); nothing is inferred."
        ),
    }
    count = len(payload["sources"]) + len(payload["feeds"]) + len(payload["calendar_verdicts"])
    body = envelope(kind="network-preflight", query={}, count=count, payload=payload)
    fname = f"oo-network-preflight-{datetime.now().strftime('%Y%m%d')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


@router.get("/columnar")
def columnar_status() -> dict:
    """Observability for the derived data-architecture stores (Slice 4 + 6b).

    Honest, network-free: the COLUMNAR engine mode (``persisted`` encrypted /
    ``memory`` fallback / ``unavailable``) and the offline IP-geo DB vintage. Lets the
    maintainer SEE whether persisted-encrypted analytics are active before deciding
    whether to bundle the per-OS crypto extension that enables them. No score."""
    from src.analytics import columnar, map_serve, rollup_serve
    from src.database.connect import get_passphrase
    from src.geo import ip_geo

    return {
        "columnar": columnar.status(get_passphrase()),
        # The in-memory windowed rollup serve — AUTOMATIC when duckdb is available; this
        # shows the mode (auto/forced) + whether it's built, so the self-tuning is visible.
        "rollup_serve": rollup_serve.status(),
        # The in-memory D4 map-coverage serve — AUTOMATIC when duckdb is available since
        # P1.11 (OO_COLUMNAR_MAP_SERVE overrides: 0 off / 1 on); shows the mode + build state.
        "map_serve": map_serve.status(),
        "ip_geo": ip_geo.freshness() | {"attribution": ip_geo.ATTRIBUTION},
        "method": (
            "Derived stores are disposable accelerators; the encrypted SQLCipher store is "
            "always the source of truth. The columnar store is encrypted-under-the-same-"
            "passphrase OR in-memory, never plaintext. Counts/state only, no score."
        ),
    }


@router.get("/elections-floor")
def elections_coverage_floor() -> dict:
    """The elections coverage floor (K13's elections component) — network-free.

    Maintainer ruling 2026-07-14 (V1_PATHWAY §4.5(1)): the vertical must cover at least
    every country whose official or major language is one of the twelve UI languages.
    This reports that floor as a DENOMINATOR and what the shipped calendar reaches of it,
    with the four states kept apart (covered · only-a-passed-projection · present-but-
    dateless · missing) because a single "covered" count would let the floor be cleared by
    entries that tell a reader nothing. Counts only, no score; the country mapping's own
    verification status rides every answer, since the share is measured against a
    denominator that has not yet been checked against a primary source."""
    from src.civic.coverage_floor import floor_coverage

    return floor_coverage()


@router.get("/freshness")
def external_freshness() -> dict:
    """Self-report the freshness of every registered external artifact (network-free).

    A production install can surface — via the existing maintainer↔dev "click & send the
    bundle" channel — exactly which bundled/pinned things are stale (the IP-geo DB, the
    model catalog, the DuckDB↔crypto-extension coupling, …). Reads the registry
    (configs/external_artifacts.yml); makes NO network call (the 'is upstream newer?'
    watch is a separate consented scheduled job). Counts/state only, no score."""
    from src.maintenance import registry as R

    return R.summary()


# -- Recursive-augmentation logs (maintainer 2026-07-02): the app surfaces the
# diagnostics that let a developer find bugs WITHOUT the operator spotting each by eye.
# All read-only, local, no score. -------------------------------------------------- #


class _FrontendError(BaseModel):
    """A browser error the UI captured (recursive-augmentation log #1). Small,
    no-PII by contract — error text + which function/endpoint only."""

    kind: str = Field(default="error", max_length=40)
    message: str = Field(default="", max_length=500)
    source: str | None = Field(default=None, max_length=300)
    endpoint: str | None = Field(default=None, max_length=300)
    lineno: int | None = None
    ui_lang: str | None = Field(default=None, max_length=16)


@router.post("/frontend-error")
def report_frontend_error(err: _FrontendError) -> dict:
    """Receive a browser-side error (window.onerror / unhandledrejection / a failed
    fetch) into the rolling log so the "browser-unverified" debt is OBSERVABLE — a
    ``t is not defined`` or a dead click shows in the debug bundle instead of the
    operator finding it one tab at a time. Loopback-only, best-effort, throttled."""
    from src.monitoring.errorlog import note_frontend_error

    note_frontend_error(
        err.kind,
        err.message,
        source=err.source,
        endpoint=err.endpoint,
        lineno=err.lineno,
        ui_lang=err.ui_lang,
    )
    return {"ok": True}


# response_model=None: the handler returns a dict OR a text Response, and FastAPI
# cannot build a response model for that union. Keeping the dict return (rather than
# wrapping it in a JSONResponse) is deliberate — the bundle member calls this function
# directly, and the archive writer's dict path carries `_member_default`, so
# session-forensics.json stays byte-identical to what it was before the text sibling.
@router.get("/session-forensics", response_model=None)
def session_forensics_report(download: bool = Query(False)) -> dict | Response:
    """Session forensics (2026-07-09 field event): the data-dir inventory (per-entry
    sizes; orphaned PLAINTEXT backup staging detected loudly), the previous session's
    clean/unclean-end verdict with the collector's last RSS sample (the honest OOM
    inference), and the last unlock's own phase timings + the -wal size before open.
    Local diagnostics only — sizes and app-owned names, never file contents.

    ``download=1`` returns the same facts as a dated PLAIN-TEXT attachment (2026-08-23
    field ask). This is a deliberate exception to the 2026-07-20 button-consolidation
    ruling, whose rationale was that the ratchet guarantees the bundle carries every
    report: it does, and `session-forensics.txt` is now in it — but this is the one
    file that explains a crash, and making an operator sit through a full bundle run
    to send it is the wrong cost for that question."""
    from src.monitoring.forensics import render_text as _render
    from src.monitoring.forensics import session_forensics as _sf

    payload = _sf()
    if download:
        fname = f"oo-session-forensics-{datetime.now().strftime('%Y%m%d-%H%M')}.txt"
        return Response(
            content=_render(payload),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )
    return payload


def _session_forensics_text() -> Response:
    """The text rendering as a bundle member. Returns a ``Response`` so the archive
    writer's own encoder writes the bytes verbatim instead of JSON-quoting them."""
    from src.monitoring.forensics import render_text as _render

    return Response(content=_render(), media_type="text/plain; charset=utf-8")


def _p0_validation_last() -> dict:
    """The newest saved P0 validation report (S1.2) — for the debug bundle / the
    all-diagnostics archive. Read-only: it NEVER runs a backup; an operator triggers
    a fresh run explicitly via POST /api/diagnostics/p0-validation. Returns an honest
    ``available:false`` stub when none has been run, never a fabricated pass."""
    from src.monitoring.p0_validation import last_p0_validation_report

    return last_p0_validation_report()


@router.get("/data-dir-persistence")
def data_dir_persistence_report() -> dict:
    """Honest assessment of whether the corpus survives a restart (A11): a RAM-backed (tmpfs)
    data folder or a Qubes disposable VM is PROVABLY volatile; everything else is 'unknown'
    (never a guess). ``at_risk`` + ``note`` drive the one-time nudge toward the opt-in
    persistent OO_DATA_DIR. Never 'stop using disposable VMs' — only how to keep the corpus."""
    from src.monitoring.forensics import data_dir_persistence as _dp

    return _dp()


@router.get("/law-coverage")
def law_coverage(
    download: bool = Query(False), db: Session = Depends(get_db)
) -> JSONResponse:
    """Per-jurisdiction law-tracking coverage/freshness (S5 of the law-vertical
    brief 2026-07-17): "the maintainer's next 'is law working?' is answered by
    one JSON." Counts + verdict tallies + freshness ages, no score. THE
    COMPLETENESS PRINCIPLE: a tracked-document count is an entry point, never a
    coverage claim — see ``src.law.coverage`` for the full caveat. With
    ``download=1`` it returns as a dated attachment."""
    from src.law.coverage import law_coverage_report

    payload = law_coverage_report(db)
    body = envelope(
        kind="law-coverage",
        query={},
        count=payload.get("documents", 0),
        payload=payload,
    )
    if download:
        fname = f"oo-law-coverage-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
        return JSONResponse(
            body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
        )
    return JSONResponse(body)


@router.get("/law-ingest")
def law_ingest(
    download: bool = Query(False), db: Session = Depends(get_db)
) -> JSONResponse:
    """Law-ingest reliability (ruling 34c, field feedback 2026-08-07).

    The 2026-08-07 law fixes are self-healing and invisible: the strip stage re-reads a
    tracked document's baseline on its next successful poll, and the corpus sync clears a
    publication date that was really a poll date. Both are correct; neither is reported
    anywhere, so "has this actually reached all 23 documents?" had no answer -- and the
    documents most likely to be missed are the ones whose portal cannot be fetched.

    Read-only and network-free: every field comes from stored data or a bundled fixture.
    See ``src.law.ingest_report`` for why chrome residue is NOT a pre-strip detector.
    With ``download=1`` it returns as a dated attachment."""
    from src.law.ingest_report import law_ingest_report

    payload = law_ingest_report(db)
    body = envelope(
        kind="law-ingest",
        query={},
        count=payload.get("documents", 0),
        payload=payload,
    )
    if download:
        fname = f"oo-law-ingest-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
        return JSONResponse(
            body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
        )
    return JSONResponse(body)


@router.get("/storage-footprint")
def storage_footprint_report(download: bool = Query(False)) -> JSONResponse:
    """The COMPLETE on-disk footprint across ALL app stores, ITEMIZED per component (A12b):
    the database triple (db/-wal/-shm) + wiki_dumps + osm_regions + backup/restore staging +
    other data-folder contents + the Ollama model store (which lives OUTSIDE data_dir, so a
    data-dir-only total missed it) + a grand total. Answers "how much disk is this app using"
    in one payload. Sizes only, symlinks never followed, file contents never read; no score.
    With ``download=1`` it returns as a dated attachment."""
    from src.monitoring.forensics import storage_footprint as _sf

    payload = _sf()
    body = envelope(
        kind="storage-footprint",
        query={},
        count=len(payload.get("components") or []),
        payload=payload,
    )
    if download:
        fname = f"oo-storage-footprint-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
        return JSONResponse(
            body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
        )
    return JSONResponse(body)


@router.get("/storage-composition")
def storage_composition_report(
    download: bool = Query(False), db: Session = Depends(get_db)
) -> JSONResponse:
    """Per-table / per-index BYTES of the live store via SQLite dbstat (P1.5) — names
    what the on-disk gigabytes actually ARE (mentions vs articles vs FTS shadow tables vs
    indexes), complementing session forensics' file-level inventory. Read-only,
    deadline-bounded; degrades to an honest ``{available: false, reason}`` block when
    dbstat is not compiled into this SQLite/SQLCipher build — never a 500. Counts/bytes
    only, no score. With ``download=1`` it returns as a dated attachment."""
    from src.monitoring.storage import storage_composition as _sc

    payload = _sc(db)
    body = envelope(
        kind="storage-composition",
        query={},
        count=len(payload.get("tables") or []),
        payload=payload,
    )
    if download:
        fname = f"oo-storage-composition-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
        return JSONResponse(
            body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
        )
    return JSONResponse(body)


@router.get("/windows-locks")
def windows_locks_report(download: bool = Query(False)) -> JSONResponse:
    """Why Windows refused to replace the corpus during a restore — who holds the files.

    A Windows restore fails with ``[WinError 32]`` when anything at all has the
    database or its ``-wal`` open, because Windows will not unlink or replace an
    open file; the OS names the FILE and never the holder, which leaves an
    operator unable to tell a bug in this app from a program they could close.

    This asks that question directly and changes nothing doing it: each corpus
    file is opened for READ with sharing disabled — the same exclusivity the swap
    needs — and closed immediately; our own handles are listed; other processes
    are swept within a stated budget; and Defender's real-time state and
    exclusion paths are read. Off Windows it reports honestly that none of it
    applies rather than a clean bill of health. Read-only, zero network, no score.
    With ``download=1`` it returns as a dated attachment."""
    from src.monitoring.windows_locks import windows_lock_report

    payload = windows_lock_report()
    body = envelope(
        kind="windows-locks",
        query={},
        count=len(payload.get("files") or []),
        payload=payload,
    )
    if download:
        fname = f"oo-windows-locks-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
        return JSONResponse(
            body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
        )
    return JSONResponse(body)


@router.get("/frontend-errors")
def frontend_errors(limit: int = Query(200, ge=1, le=2000)) -> dict:
    """The captured browser errors (log #1) + the rolling-log summary counts."""
    from src.monitoring.errorlog import recent_errors
    from src.monitoring.errorlog import summary as _summary

    records = [r for r in recent_errors(limit=2000) if r.get("level") == "FRONTEND"]
    return {"errors": records[-limit:], "summary": _summary()}


@router.get("/write-gate")
def write_gate_report() -> dict:
    """WHO is holding the single-writer gate, and who is holding a connection.

    S2.6 (2026-09-02 crash analysis). Two different pins, kept apart because they
    answer different questions and a reader who conflates them looks in the wrong
    place:

    * ``gate`` -- the WRITE window. ``holder``/``held_for_s`` name the current
      hold; ``max_hold_holder`` retains the name of the longest one after it is
      released, because a peak with no name cannot be acted on. Under FIFO
      handoff ``max_wait_s`` now measures a real hold rather than starvation.
    * ``pool`` -- checked-out CONNECTIONS, oldest first. A long-lived read
      transaction pins the WAL with the gate free the whole time, which is the
      shape the field's three-hour WAL growth had; the top row is the candidate.

    An empty ``pool`` list means nothing is checked out RIGHT NOW -- a returned
    connection is deliberately not listed, so no innocent thread is named.
    Read-only, in-memory, no statement text and no stack (the write gate's own
    watchdog captures a stack on demand, only for a hold past its threshold).
    """
    from src.database import pool_watch
    from src.database.writer import write_gate_stats

    return {
        "gate": write_gate_stats(),
        "pool": pool_watch.checked_out(),
        "method": (
            "gate counters read under the gate's own lock; pool rows recorded by "
            "SQLAlchemy checkout/checkin listeners and forgotten on checkin"
        ),
        "caveat": (
            "A point-in-time reading. An empty pool list means nothing is checked "
            "out at this instant, never that nothing ever was."
        ),
    }


@router.get("/soak-window")
def soak_window_report(db: Session = Depends(get_db)) -> dict:
    """The multi-day soak reading: five signals, each with the window it actually read.

    The 0.3 gate's row 7 and the 0.4 board both ask for a multi-day collector soak, and
    nothing here could answer it after the fact -- collect_perf is a ring covering about
    one pass, the latency reservoir keeps the last 512 requests per route, the error log
    is a rolling 2,000 records. This composes the DURABLE readings instead and states,
    per block, what window it covers: process uptime is the soak's clock, the
    memory-guard and write-gate counters are process-cumulative and align with it, the
    hourly wal_bytes series is filtered back down to it, and the two rolling windows say
    so rather than being read as if they spanned the soak.

    Verdict-free by construction: ``window.reaches_bar`` says whether the window is long
    enough to be read against the gate's 72-hour bar, and what the numbers mean inside it
    is the maintainer's reading. Read-only, local, counts and timings only.
    """
    from src.monitoring.soak_window import soak_window as _soak

    return _soak(db)


@router.get("/request-latency")
def request_latency() -> dict:
    """Per-route latency percentiles + the event-loop-block watchdog events (log #2).
    The freeze family (unlock / restore / task-manager) points at itself here."""
    from src.monitoring.latency import summary as _summary

    return _summary()


@router.get("/stall-forensics")
def stall_forensics_report(limit: int = Query(50, ge=1, le=200)) -> dict:
    """Requests that blew the stall budget, each with what the machine was doing.

    The 2026-07-21 field brief recorded a cluster of multi-hour requests and 503s on
    one afternoon and could not say why: the instruments that would have known are
    windowed, so the evidence had aged out before anyone read the export. This log
    takes the reading AT the stall -- single-writer gate, event loop, slowest
    statement -- and files the cause classes those readings support. Correlation,
    never proof: a stall none of the three can see is filed ``undetermined`` rather
    than assigned to the nearest class. In-memory and bounded; a restart empties it.
    """
    from src.monitoring.stall_forensics import report as _report

    return _report(limit=limit)


@router.get("/slow-queries")
def slow_queries(explain: int = Query(1, ge=0, le=1), db: Session = Depends(get_db)) -> dict:
    """The slow-query ring buffer + aggregate, and (explain=1) an EXPLAIN QUERY PLAN
    over the heavy analytics on the live store (log #3). Shows scan-vs-index."""
    from src.monitoring.slowquery import summary as _summary

    return _summary(db if explain else None)


@router.get("/schema-drift")
def schema_drift_report(db: Session = Depends(get_db)) -> dict:
    """Live DB schema vs the models + migration head (log #4). A missing index at
    scale is a silent perf bug; this catches it in one glance."""
    from src.monitoring.schema_drift import schema_drift as _drift

    return _drift(db)


@router.get("/integrity")
def corpus_integrity_report(
    sample: int = Query(500, ge=10, le=20000),
    full: int = Query(0, ge=0, le=1),
    db: Session = Depends(get_db),
) -> dict:
    """Corpus-integrity / counter-drift sweep (log #5): orphan/dangling rows, maintained
    counters vs the live aggregate, FTS staleness, FK violations. Bounded + deadline-
    guarded; reports drift, never fixes it."""
    from src.monitoring.integrity import corpus_integrity as _integrity

    return _integrity(db, sample=sample, full=bool(full))
