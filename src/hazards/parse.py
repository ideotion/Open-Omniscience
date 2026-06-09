"""Parse open natural-hazard feeds into normalised, space-time-stamped records.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Honest relay only: we parse what the official feed actually published — every record
keeps its source, a real timestamp, real coordinates and a link back. Nothing is
scored or invented; severity comes from the *provider's* own scale (USGS magnitude,
GDACS alert level). Malformed entries are skipped, never guessed.

Supported feeds (open, no key):
  * USGS Earthquakes — GeoJSON (earthquake.usgs.gov/earthquakes/feed/v1.0/…).
  * GDACS — the UN/EC Global Disaster Alert system GeoJSON (cyclones, floods, quakes,
    volcanoes, droughts), alert-level Green/Orange/Red.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime


# USGS magnitude → a coarse, honest band (the number itself is kept too).
def _quake_band(mag: float | None) -> str:
    if mag is None:
        return "unknown"
    if mag >= 7:
        return "major"
    if mag >= 6:
        return "strong"
    if mag >= 4.5:
        return "moderate"
    return "minor"


# GDACS alert level → our info/watch/urgent tiers (provider's own scale).
_GDACS_LEVEL = {"green": "info", "orange": "watch", "red": "urgent"}
_GDACS_TYPE = {
    "EQ": "earthquake",
    "TC": "cyclone",
    "FL": "flood",
    "VO": "volcano",
    "DR": "drought",
    "WF": "wildfire",
    "TS": "tsunami",
}


def _ms_to_iso(ms) -> str | None:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=UTC).isoformat()
    except (ValueError, TypeError, OSError):
        return None


def _coords(geom: dict) -> tuple[float | None, float | None]:
    c = (geom or {}).get("coordinates") or []
    if isinstance(c, list) and len(c) >= 2:
        try:
            return float(c[1]), float(c[0])  # GeoJSON is [lon, lat]
        except (ValueError, TypeError):
            return None, None
    return None, None


def parse_usgs(text: str) -> list[dict]:
    """USGS earthquake GeoJSON → hazard records."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    out = []
    for f in data.get("features", []) or []:
        if not isinstance(f, dict):
            continue
        p = f.get("properties") or {}
        lat, lon = _coords(f.get("geometry") or {})
        if lat is None:
            continue
        mag = p.get("mag")
        try:
            mag = float(mag) if mag is not None else None
        except (ValueError, TypeError):
            mag = None
        out.append(
            {
                "source": "usgs",
                "id": str(f.get("id") or p.get("code") or ""),
                "type": "earthquake",
                "title": p.get("title") or p.get("place") or "Earthquake",
                "severity": _quake_band(mag),
                "magnitude": mag,
                "lat": lat,
                "lon": lon,
                "place": p.get("place"),
                "time": _ms_to_iso(p.get("time")),
                "url": p.get("url") or "https://earthquake.usgs.gov/",
            }
        )
    return out


def parse_gdacs(text: str) -> list[dict]:
    """GDACS disaster-alert GeoJSON → hazard records (alert level = severity tier)."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    out = []
    for f in data.get("features", []) or []:
        if not isinstance(f, dict):
            continue
        p = f.get("properties") or {}
        lat, lon = _coords(f.get("geometry") or {})
        if lat is None:
            continue
        level = str(p.get("alertlevel") or "").strip().lower()
        etype = str(p.get("eventtype") or "").strip().upper()
        url = p.get("url")
        if isinstance(url, dict):  # GDACS sometimes nests {report: ...}
            url = url.get("report") or url.get("details") or next(iter(url.values()), None)
        out.append(
            {
                "source": "gdacs",
                "id": str(p.get("eventid") or f.get("id") or ""),
                "type": _GDACS_TYPE.get(etype, etype.lower() or "hazard"),
                "title": p.get("name")
                or p.get("eventname")
                or p.get("htmldescription")
                or "Disaster alert",
                "severity": _GDACS_LEVEL.get(level, "info"),
                "magnitude": None,
                "lat": lat,
                "lon": lon,
                "place": p.get("country"),
                "time": p.get("fromdate") or p.get("datemodified"),
                "url": url or "https://www.gdacs.org/",
            }
        )
    return out


PARSERS = {"usgs": parse_usgs, "gdacs": parse_gdacs}
