"""Hazards API: relay open natural-hazard feeds as space-time-stamped records.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Honest live relay: we fetch official open feeds (USGS earthquakes, GDACS disaster
alerts) through the same ethical path, parse them, and return what the source actually
published — with provenance and a link back. Severity comes from the provider's own
scale; nothing is scored or invented. Best-effort: a feed that fails is reported, never
a 500. This is the first slice of the climate/hazard space-time channel (see
docs/FUTURE_DEVELOPMENTS.md).
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from src.safety.fetcher import make_fetcher

router = APIRouter(prefix="/api/hazards", tags=["hazards"])

_fetcher = make_fetcher()

# Open, no-key feeds. USGS is rock-solid; a bad/renamed URL fails loudly (best-effort),
# never fabricates — same stance as the market/law catalogs.
_FEEDS = {
    "usgs": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson",
    "gdacs": "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP",
}

_CAVEAT = (
    "Live relay of official open hazard feeds (USGS, GDACS) — space-time-stamped, "
    "severity from the provider's own scale. It shows what a watched source "
    "reported, not everything that is happening; silence is not safety."
)


def fetch_hazards(
    source: str = "all", min_magnitude: float | None = None, *, fetcher=None
) -> tuple[list[dict], list[str]]:
    """Fetch + parse the open hazard feeds. Returns ``(records, failures)``.

    The reusable core of the relay — the route below wraps it, and the temporal map
    (``/api/timemap?hazards=true``) layers its records onto the space-time axis.
    Best-effort: one bad feed lands in ``failures``, never raises. ``fetcher`` lets a
    caller (e.g. the scheduler's background snapshot pass) inject the shared per-pass
    EthicalFetcher; unset it uses this module's own guarded fetcher. Either way the
    kill switch / robots / proxy are honoured by the fetcher (airplane mode refuses).
    """
    from src.hazards.parse import PARSERS

    f = fetcher or _fetcher
    want = list(_FEEDS) if source == "all" else [s for s in (source,) if s in _FEEDS]
    items: list[dict] = []
    failures: list[str] = []
    for key in want:
        try:
            fetched = f.fetch(_FEEDS[key], require_html=False)
            rows = PARSERS[key](fetched.content)
            if key == "usgs" and min_magnitude is not None:
                rows = [r for r in rows if (r.get("magnitude") or 0) >= min_magnitude]
            items.extend(rows)
        except Exception as exc:  # noqa: BLE001 - one bad feed must not 500 the relay
            failures.append(f"{key}: {type(exc).__name__}: {exc}")
    items.sort(key=lambda h: h.get("time") or "", reverse=True)
    return items, failures


@router.get("")
def list_hazards(
    source: str = Query("all", description="usgs | gdacs | all"),
    min_magnitude: float | None = Query(None, description="USGS: drop quakes below this magnitude"),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    """Recent hazards from the open feeds, newest first. Best-effort per source."""
    items, failures = fetch_hazards(source=source, min_magnitude=min_magnitude)
    return {
        "count": len(items[:limit]),
        "caveat": _CAVEAT,
        "failures": failures,
        "hazards": items[:limit],
    }
