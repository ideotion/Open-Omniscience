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

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.heavy import guarded_read
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

    # Heaviest of the manipulation scans (FDR family over ALL source×topic pairs, corpus-wide,
    # measured 27-111 s) with no cache — the cap + deadline stop it thrashing the one
    # connection during the Home poll storm (field test 2026-07-08, Item 8).
    key = f"bury|wd={window_days}|q={fdr_q}|z={z_min}|n={max_items}"
    return guarded_read(
        db,
        key,
        lambda: find_buried_topics(
            db, window_days=window_days, fdr_q=fdr_q, z_min=z_min, max_items=max_items
        ),
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

    key = f"flood|rd={recent_days}|bd={baseline_days}|z={z_min}|ms={min_share}|n={max_items}"
    return guarded_read(
        db,
        key,
        lambda: find_flooded_topics(
            db,
            recent_days=recent_days,
            baseline_days=baseline_days,
            z_min=z_min,
            min_share=min_share,
            max_items=max_items,
        ),
    )


# --------------------------------------------------------------------------- #
#  Cards batch E — the read/write exploration surfaces behind the new Home Leads.
#  Every handler delegates to a pure/analytics module and returns its method +
#  caveat verbatim. Counts + statistics only, never a composite score; the
#  producers auto-render as Home Leads through the generic card path.
# --------------------------------------------------------------------------- #


@router.get("/alerts")
def signals_alerts(
    within_hours: int = Query(48, ge=1, le=720, description="Fired-watch recency window"),
    hazard_max_age_hours: int = Query(48, ge=1, le=8760, description="Snapshot staleness cutoff"),
    convergence_lookback_days: int = Query(45, ge=1, le=3650),
    db: Session = Depends(get_db),
) -> dict:
    """The severity-tiered LOCAL alert layer (info / watch / urgent) — NO network.

    Aggregates cached hazard records (the provider's OWN severity), fired local watches, and
    recent space-time convergences into transparent tiers. 'Urgent' is ONLY ever a
    provider-declared red hazard alert; nothing is a fabricated urgency, no figure is a
    score. Reads the local hazards snapshot (which discloses its own age) — never fetches.

    POLLED endpoint (field test 2026-07-08, Item 8): served through a background-refreshed
    memo cache (:mod:`src.analytics.poll_cache`) so the 45-day space-time convergence scan
    that ``compute_alerts`` runs is NOT re-executed on every poll (the single-worker
    death-spiral driver). The cached value is the SAME real ``compute_alerts`` result — a
    visible ``as_of``/``cached`` discloses its age; a cold cache or a bind mismatch falls
    back to a live compute (once). The memoisation adds an as_of, it does not change WHAT
    is computed."""
    from src.analytics import poll_cache

    return poll_cache.get_alerts(
        db,
        within_hours=within_hours,
        hazard_max_age_hours=hazard_max_age_hours,
        convergence_lookback_days=convergence_lookback_days,
    )


class HazardSnapshotBody(BaseModel):
    """Records to cache locally (as returned by ``GET /api/hazards``), and/or a refresh flag."""

    records: list[dict] = []


@router.post("/hazards/snapshot")
def signals_hazards_snapshot(
    body: HazardSnapshotBody | None = None,
    refresh: bool = Query(
        False,
        description="Also fetch the open USGS/GDACS feeds through the guarded ethical path "
        "(kill-switch/robots/proxy honoured; refused while airplane mode is engaged) and "
        "merge the result before saving.",
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Update the LOCAL hazard snapshot the alert layer reads (NO producer ever fetches).

    Two population paths, both honest: post the ``records`` the app already fetched via
    ``GET /api/hazards`` (a pure local write, zero network here), and/or pass ``refresh=1``
    to pull the open feeds through the SAME guarded fetcher the hazards relay uses (the
    kill switch refuses it while airplane mode is engaged). A refresh that returns nothing
    (offline / all feeds failed) never overwrites a good snapshot with an empty one —
    failures are reported instead.

    2026-07-24 field-feedback A6 (ruled): every saved snapshot is ALSO ingested as corpus
    Articles (one per provider event id — see ``src.hazards.ingest``), zero-network (the
    records are already local), best-effort (an ingest hiccup never fails the snapshot
    save itself)."""
    from src.hazards.store import save_snapshot

    records = list((body.records if body else None) or [])
    failures: list[str] = []
    if refresh:
        try:
            from src.api.hazards import fetch_hazards

            fetched, failures = fetch_hazards(source="all")
            records = fetched or records
        except Exception as exc:  # noqa: BLE001 - a bad relay must not 500 the local write
            failures.append(f"refresh: {type(exc).__name__}: {exc}")
    if not records:
        return {"saved": False, "count": 0, "failures": failures,
                "note": "no records to save (offline or empty) — the previous snapshot is kept"}
    saved = save_snapshot(records)
    ingested: dict = {}
    try:
        from src.hazards.ingest import ingest_hazard_records

        ingested = ingest_hazard_records(db, saved["records"])
    except Exception as exc:  # noqa: BLE001 - the snapshot save must never fail on an ingest hiccup
        failures.append(f"corpus ingest: {type(exc).__name__}: {exc}")
    return {"saved": True, "count": len(saved["records"]), "saved_at": saved["saved_at"],
            "failures": failures, "ingested": ingested}


class DismissReasonBody(BaseModel):
    """An optional reason captured when a Lead is dismissed (the UI is Session F's)."""

    card_id: str
    reason: str = ""
    card_type: str | None = None


@router.post("/dismiss-reason")
def signals_record_dismiss_reason(body: DismissReasonBody) -> dict:
    """Capture an OPTIONAL reason when a Lead is dismissed — the evidence-tier feedback loop.

    Local-only, no schema, no score: the reason is stored in a small JSON file this router
    owns, SEPARATE from the dismissed-id set so it never risks the dismissal mechanic. A
    blank reason is still recorded (an explicit 'dismissed, no reason' is real feedback)."""
    from src.briefing.dismiss_reasons import record_reason

    if not (body.card_id or "").strip():
        raise HTTPException(status_code=400, detail="card_id is required")
    entry = record_reason(body.card_id, body.reason, card_type=body.card_type)
    return {"recorded": True, "entry": entry}


@router.get("/dismiss-reasons")
def signals_dismiss_reasons() -> dict:
    """Read-only aggregate of captured dismissal reasons (counts by card type + reason).

    Counts only, no score — an operator can see which card TYPES get dismissed and for
    WHAT reasons, and tune the producers accordingly."""
    from src.briefing.dismiss_reasons import reason_summary

    return reason_summary()


@router.get("/disputed-chronology")
def signals_disputed_chronology(
    lookback_days: int = Query(30, ge=1, le=365),
    min_sources: int = Query(2, ge=2, le=20, description="Distinct sources that must disagree"),
    tolerance_days: int = Query(2, ge=0, le=60, description="Dates within this many days agree"),
    db: Session = Depends(get_db),
) -> dict:
    """The SAME story dated differently across DISTINCT sources — the exploration surface.

    Within a near-duplicate story cluster, the deduced event dates disagree across distinct
    sources. Names a SHAPE, never a verdict: the innocent twins (date-extraction ambiguity,
    a timeline piece, an update date) ride the caveat; dates are deduced, never confirmed.
    No score."""
    from src.analytics.disputed_chronology import find_disputed_chronology

    key = f"disputed-chronology|lb={lookback_days}|ms={min_sources}|tol={tolerance_days}"
    return guarded_read(
        db,
        key,
        lambda: find_disputed_chronology(
            db, lookback_days=lookback_days, min_sources=min_sources, tolerance_days=tolerance_days
        ),
    )


@router.get("/story-propagation")
def signals_story_propagation(
    lookback_days: int = Query(21, ge=1, le=365),
    min_sources: int = Query(3, ge=2, le=50, description="Distinct sources the term must reach"),
    min_span_days: int = Query(2, ge=0, le=365, description="Min days first→last source"),
    db: Session = Depends(get_db),
) -> dict:
    """The temporal CASCADE of a topic across your sources — the exploration surface.

    Orders the distinct sources by WHEN each first carried a term (the diffusion cascade,
    with day-gaps). Names a SHAPE, never a cause or an origin claim (a shared wire or
    independent coverage look identical). Reads the denormalised keyword_mentions only. No
    score."""
    from src.analytics.story_propagation import find_story_propagation

    key = f"story-propagation|lb={lookback_days}|ms={min_sources}|span={min_span_days}"
    return guarded_read(
        db,
        key,
        lambda: find_story_propagation(
            db, lookback_days=lookback_days, min_sources=min_sources, min_span_days=min_span_days
        ),
    )


@router.get("/supply-chain-ripple")
def signals_supply_chain_ripple(
    window_days: int = Query(90, ge=7, le=730),
    r_min: float = Query(0.5, ge=0.0, le=1.0, description="Min positive correlation to surface"),
    fdr_q: float = Query(0.05, gt=0.0, le=1.0, description="Benjamini-Hochberg FDR level"),
    db: Session = Depends(get_db),
) -> dict:
    """Commodity / keyword coverage CO-MOVEMENT — the exploration surface.

    A Pearson correlation of daily coverage-volume series for each tracked commodity vs each
    frequent topic, with a native Fisher-z p-value; the whole pair family is Benjamini-
    Hochberg FDR-corrected so many comparisons cannot manufacture a co-movement. CO-OCCURRENCE,
    NEVER causation (the verbatim non-negotiable rides the caveat). No score."""
    from src.analytics.supply_chain_ripple import find_supply_chain_ripples

    key = f"supply-chain-ripple|wd={window_days}|r={r_min}|q={fdr_q}"
    return guarded_read(
        db,
        key,
        lambda: find_supply_chain_ripples(db, window_days=window_days, r_min=r_min, fdr_q=fdr_q),
    )


@router.get("/weather-signals")
def signals_weather_signals() -> dict:
    """Read-only view of the derived weather SIGNAL keywords (kind='signal').

    These are (date,place)-anchored signal rows derived from the corroboration clusters,
    kept in their OWN local store so they are NEVER mixed with text keywords. The anomaly is
    UNCHECKED against a baseline until the consented Open-Meteo fetch runs (never fabricated)."""
    from src.analytics.weather_signals import load_signals

    return load_signals()


@router.post("/weather-signals/refresh")
def signals_weather_signals_refresh(
    min_articles: int = Query(3, ge=1, le=100, description="Cluster-size threshold rule"),
    lookback_days: int = Query(90, ge=1, le=3650),
    db: Session = Depends(get_db),
) -> dict:
    """Derive AND persist the weather signal-keywords from the LOCAL corroboration data.

    No network: the derivation scans the corpus only (keyword × place × window clusters that
    clear the explicit article-count threshold) and writes kind='signal' rows to the store
    this router owns — never the keyword tables, never a schema. Each row carries a
    (date,place) anchor by construction and an anomaly-vs-stated-baseline note."""
    from src.analytics.weather_signals import refresh_weather_signals

    payload = refresh_weather_signals(db, min_articles=min_articles, lookback_days=lookback_days)
    return {"derived": len(payload.get("signals", [])), "derived_at": payload.get("derived_at"),
            "signals": payload.get("signals", []), "caveat": payload.get("caveat")}
