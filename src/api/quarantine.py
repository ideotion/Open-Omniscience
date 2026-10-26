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

import contextlib
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.monitoring.secret_scrub import http_detail

router = APIRouter(prefix="/api/quarantine", tags=["quarantine"])


@router.post("/start")
def quarantine_start(
    write: bool = Query(False),
    include_prose_gate: bool = Query(True),
    include_stubs: bool = Query(False),
    include_host_mismatch: bool = Query(False),
    confirm: bool = Query(False, description="must be true with write=true: the write is a bulk hide with no reverse route"),
) -> dict:
    """Start the retroactive quarantine job. ``write=False`` (default): pure detection,
    no database mutation. ``write=True``: additionally stamps each detected candidate,
    idempotently (an already-quarantined row is skipped, never re-stamped); it needs ``confirm=true``, because the
    stamp hides every detected article and no route reverses it (400 otherwise). 409 if a run
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

    if write and not confirm:
        # The stamp hides every detected article from the readers that honour it, and no route un-stamps one:
        # the data is kept, the hiding is not undoable from here. A dry run (the default) needs nothing.
        raise HTTPException(
            status_code=400,
            detail="confirm=true is required with write=true: the write hides every detected article and no route reverses it.",
        )
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


def _sample_row(article_id: int, rows: dict, host_signal: bool, confirmed: dict | None = None) -> dict:
    """One sampled article: id, title, URL and whether it is already marked; for the host-mismatch
    signals also its source's domain and the two registrable sites that were compared, and, for a pair
    a person has confirmed, when and with what note."""
    from src.ingest.host_mismatch import check_host

    if article_id not in rows:
        return {"id": article_id, "present": False}
    r = rows[article_id]
    row = {"id": article_id, "title": r[1], "url": r[2], "already_marked": bool(r[3])}
    if host_signal:
        pair = check_host(r[2], r[4])
        row |= {"source_domain": r[4], "source_site": pair.source_site, "article_site": pair.article_site}
        hit = (confirmed or {}).get((int(r[5]), pair.article_site))
        if hit is not None:
            row |= {"state": "confirmed", "confirmed_at": hit[0], "note": hit[1]}
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
    from src.database.models import Article, HostMismatchConfirmed, Source

    mgr = get_quarantine_manager()
    kept = mgr.sample_ids()
    status = mgr.status()
    tally = status["tally"]
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
                    Article.id, Article.title, Article.url, Article.quarantined, Source.domain,
                    Article.source_id,
                ).outerjoin(Source, Source.id == Article.source_id).filter(Article.id.in_(ids))
            } if ids else {}
            host_signal = sig in ("host_mismatch", "host_confirmed")  # report-only: not a "reason:" tally
            confirmed: dict = {}
            if host_signal and rows:
                confirmed = {
                    (int(sid), site): (at.isoformat() if at else None, note)
                    for sid, site, at, note in session.query(
                        HostMismatchConfirmed.source_id, HostMismatchConfirmed.article_site,
                        HostMismatchConfirmed.confirmed_at, HostMismatchConfirmed.note,
                    ).filter(HostMismatchConfirmed.source_id.in_({int(r[5]) for r in rows.values()}))
                }

            measured = not host_signal or bool(status.get("include_host_mismatch"))
            tally_key = {"host_mismatch": "host:mismatch", "host_confirmed": "host:confirmed"}.get(sig, f"reason:{sig}")
            out[sig] = {
                "candidates": int(tally.get(tally_key, 0)) if measured else None,
                "shown": len(ids),
                "rows": [_sample_row(i, rows, host_signal, confirmed) for i in ids],
            }
            if host_signal and not measured:
                out[sig]["unknown"] = None
                out[sig]["note"] = (
                    "this run did not ask for host-mismatch (start it with include_host_mismatch=true): "
                    "the counts are not measured, which is not the same as zero."
                )
            elif host_signal:
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


@router.get("/raw-id-sources")
def quarantine_raw_id_sources(limit: int = Query(50, ge=1, le=200)) -> dict:
    """Stored sources whose NAME is a bare Wikidata identifier (``Q11858063``) and how many articles
    sit under each. READ-ONLY and local: no request is made and nothing is renamed, marked or
    quarantined. A bare identifier as a name is a display and attribution defect of the SOURCE row,
    not a verdict on its articles; naming the label is the separate, consented
    ``POST /api/sources/resolve-qid-names`` (at most one Wikidata request per 10 s), which also
    renames nothing without review. Use this first to see how many sources and articles it concerns."""
    from sqlalchemy import func

    from src.analytics.quarantine_job import _default_session
    from src.catalog.qid_labels import looks_like_bare_qid
    from src.database.models import Article, Source

    session = _default_session()
    try:
        rows = [(int(i), n, d, e) for i, n, d, e in session.query(Source.id, Source.name, Source.domain, Source.enabled)]
        flagged = [r for r in rows if looks_like_bare_qid(r[1])]
        shown = sorted(flagged)[:limit]
        counts = dict(
            session.query(Article.source_id, func.count(Article.id))
            .filter(Article.source_id.in_([r[0] for r in shown])).group_by(Article.source_id)
        ) if shown else {}
        return {
            "examined": len(rows),
            "raw_id_sources": len(flagged),
            "shown": len(shown),
            "rows": [
                {"source_id": i, "name": n, "domain": d, "enabled": bool(e), "articles": int(counts.get(i, 0))}
                for i, n, d, e in shown
            ],
            "articles_in_shown": sum(int(counts.get(r[0], 0)) for r in shown),
            "method": (
                "a source whose whole name is a Wikidata Q-id (the same test the label resolver uses); "
                "local read, nothing fetched, renamed or marked; rows are the lowest source ids first "
                "(not the largest sources), and each article count includes quarantined articles"
            ),
        }
    finally:
        session.close()


@router.get("/source-furniture")
def quarantine_source_furniture(
    source_id: int = Query(..., ge=1),
    sample: int = Query(200, ge=10, le=1000),
    min_share: float = Query(0.3, gt=0.0, le=1.0),
) -> dict:
    """Short lines that repeat across ONE source's stored bodies (menu entries, ad slots, banners):
    candidates for a person to read and, if they are furniture, to add to the rule lists by hand.
    READ-ONLY and local; it marks and strips nothing, and a repeated line is not a verdict on the
    articles that carry it (a recurring column title is a repeated line too)."""
    from src.analytics.quarantine_job import _default_session
    from src.database.models import Article, Source
    from src.ingest.furniture import learn_repeated_lines

    session = _default_session()
    try:
        src = session.query(Source.id, Source.name, Source.domain).filter(Source.id == source_id).first()
        if src is None:
            raise HTTPException(status_code=404, detail="No such source.")
        total = session.query(Article.id).filter(Article.source_id == source_id).count()
        texts = [c for (c,) in session.query(Article.content).filter(Article.source_id == source_id)
                 .order_by(Article.id.desc()).limit(sample)]
        learned = learn_repeated_lines(texts, min_share=min_share)
        return {
            "source": {"id": src[0], "name": src[1], "domain": src[2]},
            "articles_in_source": total,
            "sampled": len(texts),
            **learned,
            "min_share": min_share,
            "method": (
                f"the {len(texts)} newest articles of this source (not a random sample, so a recent template "
                "change shows more than an old one); a line is listed when it is at most "
                "12 words and appears in at least min_share of the non-empty bodies read (the examined count) and in 3 or more of them; "
                "'known' lines are ones the rules already strip. Local read, nothing marked or removed"
            ),
        }
    finally:
        session.close()


class HostPairBody(BaseModel):
    source_id: int = Field(ge=1)
    article_site: str = Field(min_length=1, max_length=255)
    #: Free text, shown as typed and never parsed. The bound keeps one row small (a restore JOINS the notes
    #: of one pair from several corpora, so the stored note can legitimately grow past it).
    note: str | None = Field(default=None, max_length=2000)


def _canonical_site(site: str, source_domain: str | None) -> str | None:
    """The article site exactly as :func:`src.ingest.host_mismatch.check_host` would name it (the one
    normaliser), or None when the text names no readable site."""
    from src.ingest.host_mismatch import check_host

    return check_host(f"https://{site.strip()}/", source_domain).article_site


def _pair_is_a_current_mismatch(session, source_id: int, domain: str | None, site: str) -> bool:
    """True when at least one stored article of this source lives on ``site`` while the source's own
    site differs. Stops at the first such article; an unreadable or same-site URL never counts."""
    from sqlalchemy import or_

    from src.database.models import Article
    from src.ingest.host_mismatch import check_host

    # A cheap pre-filter only; check_host decides. A stored URL may spell an IDN host in Unicode while the
    # site is the punycode form check_host names, so both spellings of the first label are tried.
    label = site.split(".")[0]
    needles = {label}
    with contextlib.suppress(UnicodeError, ValueError):
        needles.add(label.encode("ascii").decode("idna"))
    q = (
        session.query(Article.url)
        .filter(Article.source_id == source_id, or_(*[Article.url.contains(n) for n in sorted(needles)]))
        .yield_per(500)
    )
    for (url,) in q:
        c = check_host(url, domain)
        if c.state == "mismatch" and c.article_site == site:
            return True
    return False


@router.post("/host-pairs")
def quarantine_host_pair_confirm(body: HostPairBody) -> dict:
    """Record that ``source_id`` legitimately publishes on ``article_site``. Loopback and local: no
    request is made, no article is marked. Refused (409) unless the pair is a mismatch right now, so the
    table cannot collect pairs the report would never show. Confirming again keeps the FIRST
    ``confirmed_at`` and replaces the note only when a new one is given."""
    from datetime import UTC, datetime

    from src.analytics.quarantine_job import _default_session
    from src.database.models import HostMismatchConfirmed, Source

    session = _default_session()
    try:
        src = session.query(Source.id, Source.domain).filter(Source.id == body.source_id).first()
        if src is None:
            raise HTTPException(status_code=404, detail="No such source.")
        site = _canonical_site(body.article_site, src[1])
        if site is None:
            raise HTTPException(status_code=422, detail="That is not a readable site name.")
        existing = (
            session.query(HostMismatchConfirmed)
            .filter(HostMismatchConfirmed.source_id == body.source_id, HostMismatchConfirmed.article_site == site)
            .first()
        )
        if existing is None and not _pair_is_a_current_mismatch(session, body.source_id, src[1], site):
            raise HTTPException(
                status_code=409,
                detail="Nothing to confirm: no stored article of this source lives on that site while "
                "the source's own site differs.",
            )
        if existing is None:
            existing = HostMismatchConfirmed(
                source_id=body.source_id, article_site=site,
                confirmed_at=datetime.now(UTC).replace(tzinfo=None), note=body.note,
            )
            session.add(existing)
        elif body.note is not None:
            existing.note = body.note
        session.commit()
        return {
            "source_id": body.source_id, "article_site": site,
            "confirmed_at": existing.confirmed_at.isoformat(), "note": existing.note,
        }
    finally:
        session.close()


@router.delete("/host-pairs")
def quarantine_host_pair_unconfirm(source_id: int = Query(..., ge=1), article_site: str = Query(..., min_length=1)) -> dict:
    """Withdraw a confirmation. Idempotent: ``removed`` is 0 when there was none."""
    from src.analytics.quarantine_job import _default_session
    from src.database.models import HostMismatchConfirmed

    session = _default_session()
    try:
        from src.database.models import Source

        domain = session.query(Source.domain).filter(Source.id == source_id).scalar()
        # The same normaliser POST stored it under, so any spelling of the site withdraws it.
        site = _canonical_site(article_site, domain) or article_site.strip().lower()
        removed = (
            session.query(HostMismatchConfirmed)
            .filter(HostMismatchConfirmed.source_id == source_id, HostMismatchConfirmed.article_site == site)
            .delete(synchronize_session=False)
        )
        session.commit()
        return {"removed": int(removed)}
    finally:
        session.close()


@router.get("/host-pairs")
def quarantine_host_pairs(source_id: int | None = Query(None, ge=1)) -> dict:
    """Every confirmed pair (or one source's), with when and the note as typed. Read-only and local."""
    from src.analytics.quarantine_job import _default_session
    from src.database.models import HostMismatchConfirmed

    session = _default_session()
    try:
        q = session.query(
            HostMismatchConfirmed.source_id, HostMismatchConfirmed.article_site,
            HostMismatchConfirmed.confirmed_at, HostMismatchConfirmed.note,
        ).order_by(HostMismatchConfirmed.confirmed_at, HostMismatchConfirmed.id)
        if source_id is not None:
            q = q.filter(HostMismatchConfirmed.source_id == source_id)
        rows = [
            {"source_id": int(sid), "article_site": site, "confirmed_at": at.isoformat() if at else None, "note": note}
            for sid, site, at, note in q
        ]
        return {"confirmed": len(rows), "rows": rows}
    finally:
        session.close()


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
