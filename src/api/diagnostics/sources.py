"""
Source quality, audit and qualification-integrity reports.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Part of the mechanical ``src/api/diagnostics.py`` -> package split (Q1139 = a,
2026-09-16): this file is lines 2144-2304 of the pre-split module, verbatim. The
routes, their paths, their methods and their order are unchanged; ``__init__``
imports the submodules in the original file order so the decorators still
register on one router in that order.
"""

from __future__ import annotations

import os
from datetime import datetime

from fastapi import Depends, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from src.database.session import get_db

from ._base import router


# --------------------------------------------------------------------------- #
# TEMPORARY / REMOVABLE diagnostic — Source & article quality triage bundle.
# THROWAWAY: delete this endpoint + its Settings→Diagnostics button once the
# external analyst has used the export to decide, per source, exclude/optimise/keep.
# --------------------------------------------------------------------------- #
@router.get("/source-quality")
def source_quality(
    download: bool = Query(True),
    seed: int = Query(20260713),
    db: Session = Depends(get_db),
) -> Response:
    """TEMPORARY diagnostic: ONE ZIP with everything an analyst needs to decide, per source,
    whether to EXCLUDE it (bad source) / OPTIMIZE the extractor (a mangled real article) / KEEP it
    (a genuine edge). Detects non-articles THREE independent ways (per-article keyword-stat
    outliers · a text sample from three selectors · per-source keyword fingerprints).

    READ-ONLY, EXPORT-ONLY (no writes to any table), no network, NO composite score — every flag is
    a deduced candidate with its raw value + cohort baseline + n. Plain ``def`` → runs in the
    threadpool (off the event loop); COUNT-ONLY over the whole corpus (the codec decrypts each
    article page once, the documented diagnostic cost); Article.content is decrypted ONLY for the
    bounded text heads of the SAMPLED subset. Private newsletter/mailbox bodies are gated behind
    ``OO_QUALITY_INCLUDE_NEWSLETTER_TEXT`` (default off → counts+metadata only). ``seed`` fixes the
    random-per-source control for reproducibility."""
    import io
    import zipfile

    from src.analytics.source_quality import build_quality_report_files

    include_nl = os.getenv("OO_QUALITY_INCLUDE_NEWSLETTER_TEXT", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    files = build_quality_report_files(
        db,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        seed=seed,
        include_newsletter_text=include_nl,
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in files.items():
            z.writestr(name, data)
    fname = f"oo-source-quality-{datetime.now().strftime('%Y%m%d-%H%M')}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/source-audit")
def source_audit(
    download: bool = Query(False),
    with_furniture: bool = Query(True),
    recency_window: bool = Query(True),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Part-1 Phase-1 STANDING source auditor (FLAG-ONLY this session, ruling Q2a). Per-source
    extraction-VALIDITY status (healthy/watch/degraded/failing) = the categorical rollup of a LIST of
    cohort-relative criteria, each carrying its value + the same-language cohort baseline + n — NEVER
    a blended score. Audits whether a source's scrapes are usable ARTICLES (vs nav/stub/paywall/
    wrong-DOM pages), NEVER editorial merit: terse or atypical prose is legitimate variety and can
    never reach degraded/failing for it (only the furniture-repetition extraction-failure signature,
    corroborated, can).

    READ-ONLY, COUNT-ONLY — reuses the source_quality collectors, so Article.content is never
    decrypted (``with_furniture`` adds a bounded, seeded per-source keyword query). Plain ``def`` →
    threadpool (off the event loop). The ``auto_demote_candidate`` field is computed with the
    auto-demote machinery DEFAULT-OFF (so it is always False here) — this session FLAGS only; enabling
    auto-demote is a later maintainer action gated on the Phase-0 calibration, and even then fires
    only on the extraction-failure signature, never on structural style, never on an allowlisted
    source. A per-region flag-distribution self-audit rides along (the de-US-centring guardrail).
    ``OO_SOURCE_AUDIT_ALLOWLIST`` (comma-separated domains) caps a trusted atypical source at 'watch'.
    ``download=1`` returns a dated attachment.

    ``recency_window`` (RC06, 2026-09-15; default on) adds a SECOND verdict per source over
    the last 90 days BESIDE the whole-history one above -- never replacing it, each with its
    own n and its own cohort. The 90 days are a LABELLED ASSUMPTION: RC06 came back blank and
    takes its register default, while the answer sheet's Q1108 proposes six months over the
    whole history; both answers stand and the payload says so."""
    from src.analytics.source_audit import audit_sources, paired_verdicts

    allow = {d.strip() for d in os.getenv("OO_SOURCE_AUDIT_ALLOWLIST", "").split(",") if d.strip()}
    report = audit_sources(db, allowlist=allow, with_furniture=with_furniture)
    if recency_window:
        # RC06 = a (2026-09-15): BESIDE, never replacing. It is its own key, carrying its own
        # window, its own n per source and its own caveat -- merging it into the rows above
        # would make one verdict look like a correction of the other, and neither corrects
        # anything: a source broken for years and fixed last month, and one that worked for
        # years and broke last month, need both numbers to be told apart.
        #
        # Opt-OUT rather than opt-in, and it costs a second whole-corpus pass: the report is
        # an on-demand diagnostic, and a recency verdict nobody asked for by name is a
        # recency verdict nobody reads. `recency_window=0` turns it off for a caller that
        # only wants the historical rollup.
        report["recency_window"] = paired_verdicts(db)
    headers = {}
    if download:
        fname = f"oo-source-audit-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(report, headers=headers)


@router.get("/qualification-integrity")
def qualification_integrity(db: Session = Depends(get_db)) -> JSONResponse:
    """0.4 Row A's closing clause, as a number: is a previously-DISQUALIFIED source still
    disqualified?

    Row A closes on a committed import at scale, and its clause exists because "a pass that
    only counts ``qualified`` rows cannot see the inversion this row exists to catch" -- the
    2026-07-24 defect, where the merge's column allowlist dropped the qualification stamp and
    a known-bad source arrived carrying ``server_default='unqualified'``, indistinguishable
    from never-judged. Row E asks for tooling because on tens of thousands of sources a
    by-hand spot-check "is exactly the shape of check that gets reported as done without
    being done".

    The attempt log is the "before": ``evaluate_and_stamp`` writes the attempt row and
    ``Source.status`` in one transaction, so for any judged source the two must agree. That
    makes this answerable AFTER an import rather than only around one. Both directions are
    counted apart (laundered / demoted), the examined disqualified sources are NAMED, and a
    corpus with no judgements reports ``not-measurable-here`` rather than a clean bill of
    health. Read-only; counts and names, never a score."""
    from src.catalog.qualification_integrity import qualification_integrity_report

    return JSONResponse(qualification_integrity_report(db))


@router.get("/source-qualification-export")
def source_qualification_export(
    download: bool = Query(False),
    fmt: str = Query("json", pattern="^(json|yaml)$"),
    db: Session = Depends(get_db),
) -> Response:
    """REMEMBER what this instance qualified, so a fresh install does not re-earn it.

    Emits the overlay ``configs/source_qualification.yml`` -- the file the seeder adopts at
    boot -- plus the split the 2026-09-04 ask asks to see: of the sources that shipped with
    the app, how many are qualified, how many disqualified, and how many are still awaiting a
    verdict. Same schema out as in, so what one instance exports is exactly what the next
    fresh install adopts.

    READ-ONLY: it reports verdicts already reached and never judges, fetches or stamps
    anything. Plain ``def`` -> threadpool, off the event loop.

    ``fmt=yaml`` returns the overlay file itself, ready to commit; ``json`` (the default, and
    what the all-diagnostics bundle carries) adds the scope, basis and pending figures that
    explain what the file does and does not contain.
    """
    from src.catalog.qualification_export import build_overlay_export, to_overlay_yaml

    report = build_overlay_export(db)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    if fmt == "yaml":
        headers = {"Content-Disposition": f'attachment; filename="source_qualification-{stamp}.yml"'}
        return Response(to_overlay_yaml(report), media_type="text/yaml", headers=headers)
    headers = {}
    if download:
        headers["Content-Disposition"] = (
            f'attachment; filename="oo-source-qualification-{stamp}.json"'
        )
    return JSONResponse(report, headers=headers)


@router.get("/source-audit-selftest")
def source_audit_selftest(download: bool = Query(False)) -> JSONResponse:
    """Prove the auditor's PURE mechanism (flag_criteria / derive_status / should_auto_demote /
    region self-audit) — no DB, no network, no score. The load-bearing checks: the extraction-failure
    source is failing; an atypical-but-valid (terse-prose) source is NOT (never worse than watch);
    auto-demote is default-off and never fires on an allowlisted source; a small cohort gets no
    baseline. A regression reddens both this endpoint and CI. ``download=1`` returns a dated
    attachment."""
    from src.analytics.source_audit import run_source_audit_selftest

    log = run_source_audit_selftest()
    headers = {}
    if download:
        fname = f"oo-source-audit-selftest-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)
