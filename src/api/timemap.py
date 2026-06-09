"""Temporal-map API: space-time signals on one zoomable map + time axis.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Read-only and offline by default. Returns normalised signals — curated anchors,
the recurring-events agenda, geocoded corpus — each with a coordinate and a
fractional-year ``t`` so the front-end slider can sweep from antiquity to the near
future. Live geophysical hazards are layered in best-effort *only when asked*
(``hazards=true``), and any fetch failure is reported, never hidden.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from src.timemap.collect import KNOWN_KINDS, collect, time_range

router = APIRouter(prefix="/api/timemap", tags=["timemap"])

_CAVEAT = (
    "Each pin needs BOTH a place and a date. Signals without a coordinate are absent, "
    "not plotted at (0,0); a missing pin means 'not located', never 'did not happen'. "
    "Country-level pins (geocode=country) are approximate stand-in points, not the exact "
    "spot. Future entries are scheduled/astronomical dates and can still change."
)


def _kinds_param(kinds: str | None) -> set[str] | None:
    if not kinds:
        return None
    want = {k.strip() for k in kinds.split(",") if k.strip()}
    return want or None


def _hazard_signals() -> tuple[list[dict], list[str]]:
    """Best-effort live hazards as signals. Returns (signals, failures)."""
    try:
        from datetime import datetime

        from src.api.hazards import fetch_hazards  # type: ignore
        from src.timemap import year_float
    except Exception:
        return [], ["hazards module not installed"]
    sigs: list[dict] = []
    failures: list[str] = []
    try:
        raw, failures = fetch_hazards(source="all")
    except Exception as exc:  # pragma: no cover - network/runtime guard
        return [], [f"hazard fetch error: {exc}"]
    for h in raw or []:
        if h.get("lat") is None or h.get("lon") is None or not h.get("time"):
            continue
        try:
            d = datetime.fromisoformat(str(h["time"]).replace("Z", "+00:00")).date()
        except (TypeError, ValueError):
            continue
        sigs.append({
            "id": "hazard:" + str(h.get("id") or h.get("url") or h.get("place")),
            "title": h.get("place") or h.get("type") or "Hazard",
            "kind": "hazard",
            "lat": float(h["lat"]), "lon": float(h["lon"]),
            "t": round(year_float(d), 3),
            "date": d.isoformat(), "year": d.year,
            "date_precision": "day", "confirmed": True,
            "place": h.get("place"), "country": None,
            "url": h.get("url"), "note": h.get("severity"),
            "source": "hazards", "geocode": "exact",
            "severity": h.get("severity"), "magnitude": h.get("magnitude"),
        })
    return sigs, failures


@router.get("")
def list_signals(
    kinds: str | None = Query(None, description="comma-separated kinds to keep"),
    start: float | None = Query(None, description="earliest fractional year, e.g. 1900"),
    end: float | None = Query(None, description="latest fractional year, e.g. 2030"),
    hazards: bool = Query(False, description="layer in live geophysical hazards (network)"),
    limit: int = Query(2000, ge=1, le=10000),
) -> dict:
    """Space-time signals within an optional time window and kind filter."""
    extra: list[dict] = []
    failures: list[str] = []
    if hazards:
        extra, failures = _hazard_signals()
    sig = collect(kinds=_kinds_param(kinds), start=start, end=end, extra=extra)
    if len(sig) > limit:
        sig = sig[:limit]
    return {
        "signals": sig,
        "count": len(sig),
        "range": time_range(sig),
        "kinds": list(KNOWN_KINDS),
        "failures": failures,
        "caveat": _CAVEAT,
    }


@router.get("/range")
def full_range(hazards: bool = Query(False)) -> dict:
    """The full time extent + per-kind counts across all sources (sets the slider)."""
    extra: list[dict] = []
    if hazards:
        extra, _ = _hazard_signals()
    return time_range(collect(extra=extra))
