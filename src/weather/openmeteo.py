"""
Bounded Open-Meteo archive slices — the corpus drives the weather, never bulk.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

One (place, window) reanalysis slice per call, fetched through THE single
ethical fetch path (:func:`src.safety.fetcher.make_fetcher` — robots
fail-closed, politeness, kill switch, protected-mode proxy all inherited).
Never called at boot, never called by a producer: only the user's explicit,
consented click reaches this module (FUTURE_DEVELOPMENTS, Open-Meteo layer).

Honesty, stated in every payload:
  * license/attribution: Open-Meteo open data, CC BY 4.0;
  * the data is ERA5-family REANALYSIS — a model estimate on a grid cell,
    not a station record; corroboration is never proof;
  * a fetched slice is cached to disk so re-viewing it is offline; the cache
    hit is disclosed (``cached: true`` + the original ``fetched_at``).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date
from pathlib import Path

from src.paths import data_dir

_LOG = logging.getLogger(__name__)

ARCHIVE_BASE = "https://archive-api.open-meteo.com/v1/archive"

# Daily reanalysis variables the corroboration rules may request (allowlist —
# the endpoint never relays arbitrary parameters to the upstream API).
ALLOWED_DAILY = frozenset({
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "rain_sum",
    "snowfall_sum",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
})

# ERA5 coverage floor; the upstream archive starts in 1940.
ARCHIVE_FLOOR = date(1940, 1, 1)
MAX_WINDOW_DAYS = 366

LICENSE_NOTE = (
    "Open-Meteo open data, CC BY 4.0 (https://open-meteo.com/) — "
    "ERA5-family reanalysis: a model estimate for a grid cell, not a station record."
)


def build_archive_url(lat: float, lon: float, start: date, end: date,
                      variables: list[str]) -> str:
    """The exact upstream URL (deterministic — it doubles as the cache key)."""
    daily = ",".join(sorted(variables))
    return (
        f"{ARCHIVE_BASE}?latitude={lat:.4f}&longitude={lon:.4f}"
        f"&start_date={start.isoformat()}&end_date={end.isoformat()}"
        f"&daily={daily}&timezone=UTC"
    )


def cache_path(url: str) -> Path:
    d = data_dir() / "weather_context"
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".json")


def fetch_daily_slice(
    lat: float,
    lon: float,
    start: date,
    end: date,
    variables: list[str],
    *,
    label: str | None = None,
    force: bool = False,
    fetcher=None,
) -> dict:
    """Fetch (or serve from cache) one bounded daily slice. Never raises for
    transport problems — failures come back as honest transport verdicts
    (the T4 taxonomy), exactly like the markets feeds."""
    url = build_archive_url(lat, lon, start, end, variables)
    cpath = cache_path(url)
    if not force and cpath.exists():
        try:
            payload = json.loads(cpath.read_text(encoding="utf-8"))
            payload["cached"] = True
            payload["label"] = label or payload.get("label")
            return payload
        except (OSError, ValueError):
            _LOG.warning("unreadable weather cache %s; refetching", cpath)

    if fetcher is None:
        from src.safety.fetcher import make_fetcher

        fetcher = make_fetcher()
    try:
        fetched = fetcher.fetch(url, require_html=False)
    except Exception as exc:  # noqa: BLE001 - every refusal becomes a verdict, never a crash
        from src.markets.csv_feeds import classify_fetch_failure

        verdict, note, retryable = classify_fetch_failure(exc)
        return {"ok": False, "verdict": verdict, "verdict_note": note,
                "retryable": retryable, "requested_url": url, "label": label}

    try:
        body = json.loads(fetched.content)
        daily = body["daily"]
        if not isinstance(daily.get("time"), list):
            raise ValueError("daily.time missing")
    except (ValueError, KeyError, TypeError):
        return {
            "ok": False, "verdict": "parse-failed",
            "verdict_note": "the upstream response was not a usable daily series",
            "retryable": False, "requested_url": url, "label": label,
        }

    payload = {
        "ok": True,
        "label": label,
        "daily": daily,
        "units": body.get("daily_units") or {},
        "cached": False,
        "provenance": {
            "requested_url": url,
            "final_url": fetched.final_url,
            "status_code": fetched.status_code,
            "fetched_at": fetched.fetched_at.isoformat(),
            "dataset": "archive-api.open-meteo.com (ERA5-family reanalysis)",
            "license": LICENSE_NOTE,
            "grid_note": (
                "values describe the reanalysis grid cell containing the point, "
                "not the exact coordinate"
            ),
        },
    }
    try:
        cpath.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    except OSError:
        _LOG.warning("could not cache weather slice to %s", cpath, exc_info=True)
    return payload
