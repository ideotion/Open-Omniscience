"""
Signals API: statistical manipulation-pattern signals + the FDR mechanism self-test.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The measurement engines already live in ``src.analytics.concentration`` (the flood/bury
manipulation-pattern cards, card #4) and ``src.stats.fdr`` (the Benjamini-Hochberg
multiple-testing spine). This router is their read-only EXPLORATION surface — the
endpoints that let the operator dig into a Home Lead's full evidence, plus the FDR
self-test — none of which existed before. Nothing here re-implements a statistic: every
handler delegates to the pure/analytics module and returns its method+caveat verbatim.

HONESTY carries through unchanged from the modules: distinct SOURCES (not article count)
measure a topic's breadth; the innocent-twin explanation is stated in every caveat; the
"absence of a flag is NOT absence of manipulation" note rides the bury result; the whole
family of (source, topic) comparisons is Benjamini-Hochberg-corrected so the many tests
cannot manufacture a finding; counts + statistics only, never a composite score.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.database.session import get_db

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("/fdr-selftest")
def signals_fdr_selftest(download: bool = Query(False)) -> JSONResponse:
    """Prove the Benjamini-Hochberg FDR mechanism on hand-computed fixtures.

    The multiple-testing correction is the shared spine under the flood/bury manipulation
    cards and the lunar screen; if the step-up were wrong, every screen that reports
    "survived multiple-testing correction" would be quietly fabricating. This runs the
    correction on fixtures with known answers (the canonical step-up recovery, the
    all-reject / none-reject boundaries, order-invariance, the adjusted-<=-q equivalence,
    the BH-Yekutieli conservatism, and the input validation) and returns pass/fail per
    case — so a regression reddens both this export and CI. No DB, no network, no score.
    With ``download=1`` it comes back as a dated attachment (mirrors the ir-eval /
    keyword self-tests)."""
    from src.signals.fdr import fdr_selftest

    log = fdr_selftest()
    headers = {}
    if download:
        fname = f"oo-fdr-selftest-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(log, headers=headers)


@router.get("/bury")
def signals_bury(
    window_days: int = Query(30, ge=1, le=365, description="Recent window scanned"),
    fdr_q: float = Query(0.05, gt=0.0, le=1.0, description="Benjamini-Hochberg FDR level"),
    z_min: float = Query(3.0, ge=0.0, le=20.0, description="Effect gate: |z| the gap must clear"),
    max_items: int = Query(12, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict:
    """Sources UNDER-covering a topic that is big across the rest of the corpus (the BURY
    half of manipulation-pattern card #4 — the inverse of the flood card's Home Lead).

    For every (source with enough articles, topic broad across the corpus) pair, a
    two-proportion z-test compares the source's share of the topic against the
    rest-of-corpus share (one-sided: is the source BELOW?). The whole family of pairs is
    corrected with Benjamini-Hochberg FDR at ``fdr_q`` so screening thousands of pairs
    cannot manufacture a finding; a pair is surfaced only if it BOTH survives FDR AND clears
    the effect gate ``z <= -z_min``. The overwhelming innocent explanation — specialization
    (a different beat, region or language) — is stated in the caveat, and "absence of a flag
    is NOT absence of manipulation" rides the result. Distinct SOURCES measure a topic's
    breadth. Reads the denormalised ``source_id`` only (no content decrypt). Counts +
    statistics only, never a score."""
    from src.analytics.concentration import find_buried_topics

    return find_buried_topics(
        db, window_days=window_days, fdr_q=fdr_q, z_min=z_min, max_items=max_items
    )


@router.get("/flood")
def signals_flood(
    recent_days: int = Query(7, ge=1, le=90, description="Recent window scanned"),
    baseline_days: int = Query(84, ge=7, le=730, description="Prior-period baseline length"),
    z_min: float = Query(2.5, ge=0.0, le=20.0, description="Effect gate: z the jump must clear"),
    min_share: float = Query(0.25, gt=0.0, le=1.0, description="Min recent share to be a flood"),
    max_items: int = Query(12, ge=1, le=50),
    db: Session = Depends(get_db),
) -> dict:
    """A SOURCE flooding a single topic far above its OWN history (the flood half of
    manipulation-pattern card #4 — the exploration surface behind the Home Lead).

    A two-proportion z-test of a source's recent share of a keyword vs its own prior share;
    it fires only on a real jump above the source's own baseline (a source that always
    covers a beat heavily does not flag — no jump, no z). Volume is not importance: a
    genuinely big story legitimately dominates coverage, so the shape is "this source, this
    topic, far above its own norm", never a claim it was deliberate — stated in the caveat.
    Reads the denormalised ``source_id`` only (no content decrypt). Counts + statistics
    only, never a score."""
    from src.analytics.concentration import find_flooded_topics

    return find_flooded_topics(
        db,
        recent_days=recent_days,
        baseline_days=baseline_days,
        z_min=z_min,
        min_share=min_share,
        max_items=max_items,
    )
