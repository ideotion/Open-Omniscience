"""Curated space-time anchors (configs/world_timeline.yml) for the temporal map.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

These seed the time-slider with real, well-documented events that already carry
a coordinate and a date, so the map is meaningful before any corpus exists. The
loader is strict: an anchor without a usable lat/lon/date is skipped (never
guessed), and any scholarly date doubt rides along in ``note``.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

from src.timemap import year_float

CATALOG_PATH = Path(__file__).resolve().parents[2] / "configs" / "world_timeline.yml"


def _parse_date(raw) -> date | None:
    """ISO date string -> date. Handles years < 1000 ('0079-10-24'). None if bad."""
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _normalise(a: dict) -> dict | None:
    """One catalog row -> a signal dict, or None if it lacks coord+date."""
    try:
        lat, lon = float(a["lat"]), float(a["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    d = _parse_date(a.get("date"))
    if d is None:
        return None
    title = str(a.get("title", "")).strip()
    if not title:
        return None
    return {
        "id": str(a.get("id") or title),
        "title": title,
        "kind": str(a.get("kind", "milestone")),
        "lat": lat,
        "lon": lon,
        "t": round(year_float(d), 3),
        "date": d.isoformat(),
        "year": d.year,
        "date_precision": str(a.get("date_precision", "day")),
        "confirmed": bool(a.get("confirmed", False)),
        "place": a.get("place"),
        "country": (str(a["country"]).lower() if a.get("country") else None),
        "url": a.get("url"),
        "note": a.get("note"),
        "source": "anchor",
        "geocode": "exact",  # anchors carry their own real coordinate
    }


@lru_cache(maxsize=1)
def _raw() -> dict:
    if not CATALOG_PATH.exists():
        return {}
    return yaml.safe_load(CATALOG_PATH.read_text("utf-8")) or {}


@lru_cache(maxsize=1)
def load_anchors() -> list[dict]:
    """All valid curated anchors as normalised signals (coordinate + date present)."""
    out = []
    for a in _raw().get("anchors", []):
        if isinstance(a, dict):
            sig = _normalise(a)
            if sig:
                out.append(sig)
    return out
