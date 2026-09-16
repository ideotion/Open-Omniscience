"""
Corpus-shape reports and the card-audit job.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Part of the mechanical ``src/api/diagnostics.py`` -> package split (Q1139 = a,
2026-09-16): this file is lines 1614-2143 of the pre-split module, verbatim. The
routes, their paths, their methods and their order are unchanged; ``__init__``
imports the submodules in the original file order so the decorators still
register on one router in that order.
"""

from __future__ import annotations

import os
from datetime import datetime

from fastapi import Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.heavy import guarded_read
from src.database.session import get_db
from src.jobs.background import BackgroundJob, register_job

from ._base import router


@router.get("/bulletin-language")
def bulletin_language(download: bool = Query(False)) -> JSONResponse:
    """Would a bulletin read in the operator's language, and does it say what the record knows?

    Per locale: how many of the sentences this app writes have a translation, which
    have none (verbatim, so the report IS the worklist), and which have a broken
    frame. Beside it, the render-integrity checks that need the same double render —
    determinism, unresolved frame holes, and every section, article title and
    reference number in the record found in the document.

    Measured on the newest PERSISTED edition when there is one, and on a synthetic
    record when there is not; the report says which, because coverage over a
    synthetic record is a statement about the renderer and coverage over a real one
    is a statement about a corpus. Read-only: it renders an existing record, so no
    DB write, no model and no network are involved."""
    from src.monitoring.bulletin_language import bulletin_language_report, stored_prose

    out = bulletin_language_report()
    # The prose the computing modules WRITE INTO a record: a single edition cannot
    # exhibit all of it (a period with no alert carries no alert caveat), so the
    # worklist would look complete while half the possible sentences had no entry.
    out["stored_prose"] = {
        "bulletin": stored_prose(),
        "card_producers": stored_prose(packages=("briefing",)),
        "note": (
            "Harvested from source, not from this edition: these are the sentences the "
            "computing modules can store in a record and the renderer prints verbatim. A "
            "candidate set rather than an exact total — it can miss a sentence composed at "
            "runtime from two halves, and it can include a method string that belongs to a "
            "selftest payload and never reaches a document."
        ),
    }
    headers = {}
    if download:
        fname = f"oo-bulletin-language-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(out, headers=headers)


@router.get("/bulletin-language-selftest")
def bulletin_language_selftest() -> dict:
    """Prove the translation layer's four properties, with no DB, catalog or model.

    English is identity, a missing translation falls back AND is reported, a frame
    whose holes were changed is refused rather than printed, and an entry copied
    from the English is not counted as coverage. Runs anywhere the app runs."""
    from src.monitoring.bulletin_language import run_bulletin_language_selftest

    return run_bulletin_language_selftest()


@router.get("/lemma-preview")
def lemma_preview(
    top_n: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict:
    """S5.4: what lemmatization (OO_FAMILY_LEMMA, ON by default since 2026-07-18) MERGES
    among the top keywords — the precision-review instrument surfaced in the Diagnostics
    panel so the maintainer eyeballs the candidate conflations (and notes a wrong one for
    the _MISLEMMA_DENYLIST, or opts out entirely with OO_FAMILY_LEMMA=0). Read-only, no
    score; honest 'unavailable' when the optional simplemma is absent."""
    from src.analytics.engine_report import lemma_preview_report

    return lemma_preview_report(db, top_n=top_n)


@router.get("/home-cards")
def home_card_diagnostics(download: bool = Query(False), db: Session = Depends(get_db)) -> JSONResponse:
    """Home-card (Lead) CLICK diagnostics (field report 2026-06-22): for every card the
    briefing currently produces, what clicking it loads — its EXACT corpus (article_ids,
    "hard-linked") or a fuzzy TEXT SEARCH of the card's seed term ("search-fallback").
    A search-fallback whose live count differs wildly from the card's own n means the
    click LOSES the card's corpus (the 'no hard linking' bug). Read-only, no score; with
    ``download=1`` it comes back as a dated attachment to send back for the fix loop."""
    from src.briefing.card_diagnostics import card_click_diagnostics

    log = card_click_diagnostics(db)
    headers = {}
    if download:
        fname = f"oo-home-cards-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


@router.get("/keyword-engine")
def keyword_engine(download: bool = Query(False), db: Session = Depends(get_db)) -> JSONResponse:
    """Keyword-engine efficacy + performance report.

    Composition · entity precision · cross-language TRANSLATION coverage (tracks the
    ring work) · tag coverage · per-language functional status · the self-test ·
    indicative timings (extraction + grouped-query). Bounded, read-only, NO score —
    diff two of these over time to see whether an optimization landed. With
    ``download=1`` it returns as a dated attachment."""
    from src.analytics.engine_report import keyword_engine_report
    from src.monitoring.kpi import record_translation_coverage

    report = keyword_engine_report(db)
    # Write the ring-coverage figure down where the scan is MADE. Until 2026-09-07 this
    # report was computed, streamed and forgotten, so KPI K6 ("cross-language translation
    # coverage") could only ever answer "not-measurable-here" — a metric listed on the
    # board and structurally unwatchable. Best-effort by construction: a failed write
    # records nothing and K6 then says so, rather than breaking this diagnostic.
    record_translation_coverage(report)
    headers = {}
    if download:
        fname = f"oo-keyword-engine-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(report, headers=headers)


@router.get("/power-profile")
def power_profile(
    profile: str = Query("optimized"), download: bool = Query(False)
) -> JSONResponse:
    """§7: the published power-profile knob table + the effective values for ``profile`` (Low /
    Optimized / Max). Read-only, no score. A profile changes RESOURCE SPEND only — never data
    visibility or a caveat; Optimized IS the current default (selecting it changes nothing), and
    Low/Max are PROVISIONAL until measured on the GAMMA harness. Degrades loudly on a bad profile
    name. ``download=1`` returns a dated attachment. (The active-profile CHIP + suggest-a-lower-
    level proposal are browser-gated; this endpoint is the inspectable table.)

    The three SETTING-backed knobs (``collect_parallelism``, ``qualification_per_pass``,
    ``llm_keep_alive``) report their LIVE persisted value (source ``"override"``) rather than the
    profile-table suggestion, since nothing today rewrites the persisted setting on a profile
    switch — the persisted value is always what's genuinely in effect (2026-07-26 hardware
    diagnostics: a field export showed this diagnostic reporting a stale/wrong effective
    ``collect_parallelism`` for exactly this reason)."""
    from src.config.power_profiles import live_setting_overrides, power_profile_report

    report = power_profile_report(active_profile=profile, overrides=live_setting_overrides())
    headers = {}
    if download:
        fname = f"oo-power-profile-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(report, headers=headers)


@router.get("/power-profile-selftest")
def power_profile_selftest(download: bool = Query(False)) -> JSONResponse:
    """§7: prove the power-profile mechanism — Optimized is byte-identical to the current defaults,
    an explicit override wins, an unknown profile fails loud, no score leaks. Deterministic, no
    env/DB/network. ``download=1`` returns a dated attachment."""
    from src.config.power_profiles import run_power_profile_selftest

    log = run_power_profile_selftest()
    headers = {}
    if download:
        fname = f"oo-power-profile-selftest-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


@router.get("/article-length")
def article_length(download: bool = Query(False), db: Session = Depends(get_db)) -> JSONResponse:
    """Article-length + cited-source DISTRIBUTIONS, per content type and language
    (Home "Latest in your corpus" slice S0).

    The evidence needed to pick honest thresholds for the Home substance filter
    (min words AND min cited-sources) — no export carried this before. Counts only,
    NO score; word counts for unsegmented languages (zh/ja/th) are flagged so a
    word-gate is never applied to them blindly. With ``download=1`` it returns as a
    dated attachment to send back for calibration."""
    from src.analytics.article_length import article_length_report

    report = article_length_report(db)
    headers = {}
    if download:
        fname = f"oo-article-length-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(report, headers=headers)


@router.get("/month-occupancy")
def month_occupancy(
    sample: int = Query(400, ge=1, le=5000),
    download: bool = Query(False),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """How much of the MONTH-NAME stopword ban is not actually about dates.

    The stoplist bans 82 month forms language-agnostically, which suppresses datelines
    and also deletes the planet Mars, the March on Washington and Theresa May from the
    keyword index. The 2026-09-05 design of record proposes making the block DATE-AWARE
    instead -- drop a month token only where the date extractor claimed its span -- and
    says one number decides it: how many occurrences fall OUTSIDE any claimed date span.

    This is that number, over a uniformly-drawn sample, with its n. Read-only, counts
    only, NO score and NO recommendation -- the ruling is the maintainer's. Every
    caveat that bounds it (unigrams only, so it is a FLOOR; a missed dateline counts as
    outside, so it over-states) rides in the payload rather than in this docstring."""
    from src.analytics.month_occupancy import month_occupancy_report

    report = month_occupancy_report(db, sample=sample)
    headers = {}
    if download:
        fname = f"oo-month-occupancy-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(report, headers=headers)


@router.get("/non-article-scan")
def non_article_scan(download: bool = Query(False), db: Session = Depends(get_db)) -> JSONResponse:
    """Retroactive NON-ARTICLE scan (Slice 4a review half): per-reason counts + a bounded id sample
    of the already-stored URL-shaped non-articles (nav/index/tag/tool/section/homepage pages the
    #659 ingest filter now stops going forward). The operator's REVIEW data before a reversible
    quarantine.

    READ-ONLY, COUNT-ONLY — classifies each article on its stored url + word_count via the #659
    classifier (text=None → URL-shape rules only; Article.content is NEVER decrypted). A conservative
    UNDERCOUNT (the boilerplate-wall rule needs the body) that never flags a real article. Plain
    ``def`` → threadpool. ``download=1`` returns a dated attachment."""
    from src.analytics.non_article_scan import scan_non_article_candidates

    report = scan_non_article_candidates(db)
    headers = {}
    if download:
        fname = f"oo-non-article-scan-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(report, headers=headers)


@router.get("/criteria-calibration")
def criteria_calibration(
    download: bool = Query(False),
    top_n: int = Query(100, ge=1, le=1000),
    prose_gate_limit: int = Query(2000, ge=1, le=20000),
    prose_gate_after_id: int = Query(0, ge=0),
    prose_gate_scope: str = Query("all"),
    resume: bool = Query(False),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """S3.1 (2026-07-23 field-feedback workflow) — the TEMPORARY criteria-calibration report:
    the top ``top_n`` disregarded/would-be-disregarded articles under the CURRENT
    extraction-validity criteria, with per-article detail (id, title, url, source, word
    count, function-word density, sentence-punctuation density, which criterion fired) plus
    per-criterion/per-source/per-language aggregates — a REPORT over the existing detectors
    (``classify_non_article`` + the prose gate), never new judging.

    Iterative loop: review these specimens, adjust the criteria if needed (propose → review
    → apply), re-export. No retroactive quarantine executes against real data until this
    report has been reviewed and the criteria agreed (0.3 gate row 5). Bounded: at most
    ``top_n`` article rows decrypted for detail + one bounded, resumable prose-gate batch
    (``prose_gate_limit``, chunked via ``prose_gate_after_id``). Plain ``def`` → threadpool.
    ``download=1`` returns a dated attachment.

    ``prose_gate_scope`` picks the population that arm walks — ``all`` (every ≥100-word body,
    what a DEFAULT quarantine run's prose gate would reach) or ``index_pages`` (only those
    whose URL is also listing-shaped, the population row 5's Tier B is about). ``resume=1``
    carries the cursor across calls so repeated runs advance through the population instead
    of re-measuring the first batch; the running totals ride in ``prose_gate_progress``."""
    from src.analytics.criteria_calibration import calibration_report
    from src.analytics.non_article_scan import PROSE_GATE_SCOPES

    if prose_gate_scope not in PROSE_GATE_SCOPES:
        raise HTTPException(
            status_code=400,
            detail=f"prose_gate_scope must be one of {list(PROSE_GATE_SCOPES)}",
        )
    report = calibration_report(
        db,
        top_n=top_n,
        prose_gate_limit=prose_gate_limit,
        prose_gate_after_id=prose_gate_after_id,
        prose_gate_scope=prose_gate_scope,
        resume=resume,
    )
    headers = {}
    if download:
        fname = f"oo-criteria-calibration-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(report, headers=headers)


@router.get("/keyword-growth")
def keyword_growth(download: bool = Query(False), db: Session = Depends(get_db)) -> JSONResponse:
    """The vocabulary-growth curve: cumulative distinct keywords vs cumulative words
    added (maintainer ask 2026-06-24, at 909k keywords).

    The SHAPE diagnoses the junk fraction: a curve that bends over = the vocabulary is
    saturating (new articles reuse known words); a near-straight line (Heaps beta ~ 1) =
    new keywords are still minted for almost every word added (markup/code/unsegmented
    junk). Read DECRYPT-FREE from keyword_mentions (the denormalised observed_on +
    covering index) — no article decrypt. Counts only, NO score. With ``download=1`` it
    returns as a dated attachment to send back for the keyword-reduction loop."""
    from src.analytics.keyword_growth import keyword_growth_curve

    curve = keyword_growth_curve(db)
    headers = {}
    if download:
        fname = f"oo-keyword-growth-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(curve, headers=headers)


def _leads_quality_budget_s() -> float:
    """How long the Leads producer pass inside this member may run
    (``OO_LEADS_QUALITY_BUDGET_S``).

    DELIBERATELY BELOW ``_all_diag_db_member_deadline_s()`` (300 s), and that ordering
    is the fix rather than an implementation detail. The statement deadline wrapped
    around this member DOES fire -- and ``run_all``'s per-producer ``except Exception``
    catches it, logs "producer failed", and continues, once per producer, which is how
    an export sat 69 minutes on a member that was nominally bounded. Expiring first
    means the loop stops itself with a ``break`` nothing can intercept, and the
    statement deadline stays where it belongs: the backstop for a single runaway query.
    """
    import math

    try:
        v = float(os.environ.get("OO_LEADS_QUALITY_BUDGET_S", "240"))
    except ValueError:
        return 240.0
    return v if math.isfinite(v) and v > 0 else 240.0


@router.get("/leads-quality")
def leads_quality(download: bool = Query(False), db: Session = Depends(get_db)) -> JSONResponse:
    """S6.1 (Leads-calibration, 2026-07-18): export the CURRENT Home Leads feed as a
    bounded, real-facts report -- producer, key, bucket, n, independent sources, the
    card's own disclosed signal fields verbatim, and the major-floor fact. The
    maintainer re-runs this on the live corpus and sends it back, exactly like the
    keyword-log measurement loop. Read-only; runs the SAME run_all() pass Home uses,
    writes nothing. With ``download=1`` it returns as a dated attachment."""
    from src.analytics.leads_quality import leads_quality_report

    report = leads_quality_report(db, budget_s=_leads_quality_budget_s())
    headers = {}
    if download:
        fname = f"oo-leads-quality-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(report, headers=headers)


# --------------------------------------------------------------------------- #
#  CARD-SYSTEM AUDIT — the deep per-card fact bundle (src/briefing/card_audit.py).
#
#  The THIRD tier beside /home-cards (click plumbing) and /leads-quality (feed
#  composition), which both stay exactly as they are. This one carries, per card:
#  the trigger arithmetic RE-EVALUATED, the article_ids resolved against the live
#  corpus, independence via the existing near-dup/shared-origin primitives, the
#  non-fabrication checks, keyword facts, provenance mix, cross-card overlaps and
#  the disclosed ordering facts -- PLUS an inventory row for EVERY registered
#  producer distinguishing ok / no-signal / ERROR, the three states run_all
#  collapses into one indistinguishable empty list.
#
#  Two surfaces, deliberately: the GET below is SUMMARY depth (no article content,
#  bounded, guarded+deadlined) and is the all-diagnostics bundle member; the deep
#  standard/full-depth run is a cancellable BackgroundJob, because reading article
#  content through the SQLCipher codec must never sit on the request thread.
# --------------------------------------------------------------------------- #


@router.get("/card-audit")
def card_audit(
    depth: str = Query("summary", pattern="^(summary|standard|full)$"),
    determinism: bool = Query(True),
    download: bool = Query(False),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Deep card-system audit at SUMMARY depth — the validate-and-optimize instrument
    for the card/Lead system, built to be re-run each round and diffed against the
    previous export.

    Reports, per card: the ``trigger`` arithmetic recomputed (a row that cannot be
    mechanically checked says so with its reason, and is never counted as a pass),
    the ``article_ids`` resolved against the live corpus, independence (distinct
    sources · near-identical copies · shared origins, via the existing primitives),
    the non-fabrication checks, keyword facts, provenance mix and the disclosed
    ordering facts. PLUS an inventory row for EVERY registered producer stating
    ``ok`` / ``no-signal`` / ``error`` — so a producer that crashes on every run is
    no longer indistinguishable from a quiet one.

    Read-only; writes nothing. Counts are exact and uncapped — every bounded list
    states its exact total beside it. ``depth`` above ``summary`` carries article
    CONTENT and is better run as the background job (``POST /card-audit/run``), which
    is why this endpoint's own default is ``summary``."""
    from src.briefing.card_audit import audit_report_env_defaults, card_audit_report

    bounds = audit_report_env_defaults()
    budget = bounds.pop("determinism_budget_s", None)

    def _compute() -> dict:
        return card_audit_report(
            db,
            depth=depth,
            determinism=determinism,
            # Dimension 6 is ON by default here too. The bundle member cannot afford an
            # unbounded second producer pass, so it carries a MEASURED budget: if the
            # first pass already exceeded it the report says {"ran": false, "skipped":
            # "budget"} with both numbers -- an honest, visible skip, never a silent
            # default-off (OO_CARD_AUDIT_DETERMINISM_BUDGET_S raises it).
            determinism_budget_s=budget,
            **bounds,
        )

    report = guarded_read(db, "card-audit", _compute)
    headers = {}
    if download:
        fname = f"oo-card-audit-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(report, headers=headers)


@router.get("/card-audit/preflight")
def card_audit_preflight(
    depth: str = Query("standard", pattern="^(summary|standard|full)$"),
    excerpt_chars: int = Query(2000, ge=0, le=200000),
    max_articles_per_card: int = Query(40, ge=0, le=500),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Size ESTIMATE for a deep card-audit run, so the operator sees roughly how large
    a ``full`` run will be before starting it. Runs the real producer pass and sizes
    from the REAL card/article counts (exact) times measured per-row JSON costs (an
    estimate, stated as one). Cheap and read-only; never writes a report."""
    from src.briefing.card_audit import estimate_card_audit

    return JSONResponse(
        guarded_read(
            db,
            "card-audit-preflight",
            lambda: estimate_card_audit(
                db,
                depth=depth,
                excerpt_chars=excerpt_chars,
                max_articles_per_card=max_articles_per_card,
            ),
        )
    )


class CardAuditRunBody(BaseModel):
    depth: str = Field(
        "standard",
        description=(
            "summary (no article content) | standard (a bounded excerpt per article) | "
            "full (complete article content -- operator-chosen only)"
        ),
    )
    excerpt_chars: int = Field(2000, ge=0, le=200000)
    max_articles_per_card: int = Field(40, ge=0, le=500)
    max_linked_rows: int = Field(25, ge=0, le=200)
    max_coordination_articles: int = Field(60, ge=0, le=500)
    determinism: bool = Field(
        True,
        description=(
            "run the producer pass twice and diff it (dimension 6). ON by default; the "
            "deep job carries no budget, so an explicitly-requested run pays the second "
            "pass rather than skipping it."
        ),
    )


def _card_audit_worker(ctx, **kwargs) -> dict:
    from src.briefing.card_audit import card_audit_worker

    return card_audit_worker(ctx, **kwargs)


_CARD_AUDIT_JOB = register_job(
    BackgroundJob(
        "card-audit", "card-system audit (deep)", _card_audit_worker,
        is_writer=False, cancellable=True,
    )
)


@router.post("/card-audit/run")
def card_audit_run(body: CardAuditRunBody) -> JSONResponse:
    """Start a DEEP card-audit run as a BACKGROUND job.

    A deep run reads article content through the SQLCipher codec, so it never sits on
    the request thread (a multi-minute synchronous handler would freeze the whole
    single-worker server). Read-only on the corpus; stops cooperatively at the next
    card boundary when cancelled. Poll ``/card-audit/status``, fetch via
    ``/card-audit/download``. An already-running job returns its status with
    ``started:false`` rather than a 409."""
    if body.depth not in ("summary", "standard", "full"):
        raise HTTPException(status_code=400, detail=f"unknown depth {body.depth!r}")
    try:
        st = _CARD_AUDIT_JOB.start(**body.model_dump())
        st["started"] = True
    except RuntimeError:
        st = _CARD_AUDIT_JOB.status()
        st["started"] = False
    return JSONResponse(st)


@router.get("/card-audit/status")
def card_audit_status() -> JSONResponse:
    """Live status of the deep card-audit job (state, progress, and when done the
    ready report filename + summary in ``result``). No score."""
    st = _CARD_AUDIT_JOB.status()
    res = st.get("result") or {}
    st["ready"] = bool(st.get("state") == "done" and res.get("path"))
    st["download_filename"] = res.get("filename")
    return JSONResponse(st)


@router.post("/card-audit/cancel")
def card_audit_cancel() -> JSONResponse:
    """Ask a running deep card-audit to stop at its next safe point (between cards).
    Idempotent; no partial report is written."""
    _CARD_AUDIT_JOB.cancel()
    return JSONResponse(_CARD_AUDIT_JOB.status())


@router.get("/card-audit/download")
def card_audit_download() -> Response:
    """Serve the finished deep card-audit report. 404 until a run has completed.

    NOTE: at ``standard``/``full`` depth this file carries corpus CONTENT — the report's
    own ``content_notice`` block states exactly what it contains, so the operator knows
    before sharing it."""
    st = _CARD_AUDIT_JOB.status()
    res = st.get("result") or {}
    path = res.get("path")
    if st.get("state") != "done" or not path or not os.path.exists(path):
        raise HTTPException(
            status_code=404,
            detail=(
                "no card-audit report is ready — start one with "
                "POST /api/diagnostics/card-audit/run"
            ),
        )
    return FileResponse(
        path, media_type="application/json",
        filename=res.get("filename") or "oo-card-audit.json",
    )
