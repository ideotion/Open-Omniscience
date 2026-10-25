"""
Retroactive article QUARANTINE -- API endpoints (S3.2, 2026-07-23 field-feedback workflow).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Starts/controls the resumable background job (:mod:`src.analytics.quarantine_job`) that
detects already-flagged non-article junk (the #659 URL-shape rules + the NAV-SOUP prose
gate) and, when explicitly asked (``write=True``), stamps it REVERSIBLY (a flag, never a
delete -- an already-quarantined row's rows/keywords/provenance stay fully intact).

``write=False`` (the endpoint's default) is pure DETECTION, byte-identical to running the
scaffold before this slice. Starting a REAL WRITE run is a deliberate per-call choice --
the binding execution gate from the brief: the S3.1 criteria-calibration report ships and
is reviewed BEFORE any real write executes against a maintainer's corpus. Local disk/DB
work only, no network -- never airplane/consent-gated (mirrors the reindex job's own
"local DB work" posture). Pause/resume/cancel are ALSO reachable through the generic
``/api/jobs/{job_id}/...`` dispatcher (job_id="quarantine") for the task-manager UI.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.monitoring.secret_scrub import http_detail

router = APIRouter(prefix="/api/quarantine", tags=["quarantine"])


@router.post("/start")
def quarantine_start(
    write: bool = Query(False),
    include_prose_gate: bool = Query(True),
    include_stubs: bool = Query(False),
    include_host_mismatch: bool = Query(False),
) -> dict:
    """Start the retroactive quarantine job. ``write=False`` (default): pure detection,
    no database mutation. ``write=True``: additionally stamps each detected candidate,
    idempotently (an already-quarantined row is skipped, never re-stamped). 409 if a run
    is already in progress.

    ``include_prose_gate`` (default True = unchanged) selects the CRITERIA the run applies.
    The nav-soup prose gate is independent of the URL-shape rules and fires only on bodies
    the >= _ARTICLE_MIN_WORDS guard KEEPS, so it reaches a different, larger population than
    the URL rules do. ``include_prose_gate=false`` runs the URL-shape rules ALONE -- which is
    what an operator wants when the corpus's long-body prose has not been measured and the
    agreed scope is the drop path only. It is part of the run-lifetime mode: a pause/resume
    or an app restart continues under the SAME criteria, never a silently different set.

    ``include_stubs`` (default False) adds the thin-body menu / subscriber-prompt signals. Run it
    with ``write=False`` first: that is the per-signal count the operator reviews before a write.

    ``include_host_mismatch`` (default False) also COUNTS and SAMPLES articles stored on a site other
    than their source's own. It is report-only: it is a fact about where a page lives, not a verdict,
    so it marks nothing even with ``write=true`` (see :mod:`src.ingest.host_mismatch`)."""
    from src.analytics.quarantine_job import get_quarantine_manager

    try:
        # Forwarded only when asked for, so the manager is called exactly as before otherwise.
        extra: dict[str, Any] = {"include_stubs": True} if include_stubs else {}
        if include_host_mismatch:
            extra["include_host_mismatch"] = True
        return get_quarantine_manager().start(
            write=write, include_prose_gate=include_prose_gate, **extra
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=http_detail(exc)) from exc


@router.get("/status")
def quarantine_status() -> dict:
    """Live state of the (single) background quarantine job -- for the UI + /api/jobs."""
    from src.analytics.quarantine_job import get_quarantine_manager

    return get_quarantine_manager().status()


def _sample_row(article_id: int, rows: dict, host_signal: bool) -> dict:
    """One sampled article: id, title, URL and whether it is already marked; for the host-mismatch
    signal also its source's domain and the two registrable sites that were compared."""
    from src.ingest.host_mismatch import check_host

    if article_id not in rows:
        return {"id": article_id, "present": False}
    r = rows[article_id]
    row = {"id": article_id, "title": r[1], "url": r[2], "already_marked": bool(r[3])}
    if host_signal:
        pair = check_host(r[2], r[4])
        row |= {"source_domain": r[4], "source_site": pair.source_site, "article_site": pair.article_site}
    return row


@router.get("/samples")
def quarantine_samples(
    signal: str | None = Query(None), limit: int = Query(20, ge=1)
) -> dict:
    """A bounded spot-check of what this process's current or last run's rules picked: per signal, up to
    ``limit`` articles' id, title and URL, and whether each is already marked. READ-ONLY and local:
    it never starts a run, writes, or fetches, and it returns no body, snippet or keywords. The sample
    is the candidates with the smallest hash of (signal, id), so the same corpus gives the same rows;
    it is a spot-check, not an error rate. ``limit`` above the kept sample is clamped, and says so."""
    from src.analytics.quarantine_job import SAMPLE_PER_SIGNAL, _default_session, get_quarantine_manager
    from src.database.models import Article, Source

    mgr = get_quarantine_manager()
    kept = mgr.sample_ids()
    tally = mgr.status()["tally"]
    wanted = {signal: kept.get(signal, [])} if signal else kept
    n = min(limit, SAMPLE_PER_SIGNAL)
    session = _default_session()
    try:
        out: dict[str, dict] = {}
        for sig, ids in wanted.items():
            ids = ids[:n]
            rows = {
                int(r[0]): r
                for r in session.query(
                    Article.id, Article.title, Article.url, Article.quarantined, Source.domain
                ).outerjoin(Source, Source.id == Article.source_id).filter(Article.id.in_(ids))
            } if ids else {}
            host_signal = sig == "host_mismatch"  # report-only: its count is not a "reason:" tally

            out[sig] = {
                "candidates": int(tally.get("host:mismatch" if host_signal else f"reason:{sig}", 0)),
                "shown": len(ids),
                "rows": [_sample_row(i, rows, host_signal) for i in ids],
            }
            if host_signal:
                out[sig]["unknown"] = int(tally.get("host:unknown", 0))
                out[sig]["note"] = (
                    "a page on another site than its source's own is a fact about where it lives, not "
                    "a verdict: it may be a syndicated item, a redirect or a wire feed. Nothing is marked "
                    "for it, even with write=true. 'unknown' counts articles whose source or URL has no "
                    "readable site and are not counted as mismatches."
                )
    finally:
        session.close()
    return {
        "signals": out,
        "note": None if out else (
            "no sample is held: no run has been made since this process started, or the last one "
            "finished or was cancelled before a restart (only a running or paused run is restored)"
        ),
        "limit": n,
        "clamped": limit > SAMPLE_PER_SIGNAL,
        "method": (
            "the candidates with the smallest hash of (signal, id) in the last run: a spot-check of "
            "what the rules pick, not an error rate and not a verdict; titles and URLs only"
        ),
        "run": {"state": mgr.status()["state"], "dry_run": mgr.status()["dry_run"]},
    }


@router.post("/{action}")
def quarantine_action(action: str) -> dict:
    """Pause / resume / cancel the running background quarantine job. A resume always
    continues in the SAME write/dry-run mode the paused run was in (never a silent flip)."""
    from src.analytics.quarantine_job import get_quarantine_manager

    mgr = get_quarantine_manager()
    if action == "pause":
        mgr.pause()
        return mgr.status()
    if action == "resume":
        try:
            return mgr.resume()
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=http_detail(exc)) from exc
    if action == "cancel":
        mgr.cancel()
        return mgr.status()
    raise HTTPException(status_code=400, detail=f"unknown action {action!r}")
