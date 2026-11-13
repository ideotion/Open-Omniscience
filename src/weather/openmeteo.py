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
  * the place is rounded to 0.1 degree before it is sent or kept (R675, R683);
  * a fetched slice is kept in the encrypted store, never a loose file, so
    re-viewing it is offline; the hit is disclosed (``cached: true`` + the
    original ``fetched_at``).
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date

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


#: Decimal places a place keeps before it is sent or stored (R675, R683). 0.1 degree is the spacing
#: of ERA5-Land, the finest grid behind the archive's values, so the rounded point sits on a grid
#: node of the cell the archive answers for. Coarser rounding would move the answer to another
#: cell; finer would only send more of where the place is.
PLACE_DECIMALS = 1


def _round1(x: float) -> float:
    # floor(x*10 + 0.5)/10, NOT round(): Python's round() sends a tie such as 0.25 to the even
    # neighbour (0.2) where the page's Math.floor(x*10 + 0.5)/10 says 0.3, and the page names the
    # place it asks consent for. The same IEEE operations on both sides give the same number.
    return math.floor(float(x) * 10 + 0.5) / 10 + 0.0


def round_place(lat: float, lon: float) -> tuple[float, float]:
    """The rounded place that is actually sent and stored. ``-0.0`` reads as ``0.0``.

    Mirrors ``ooRoundPlace`` in src/static/app-home.js exactly (ties go up)."""
    return (_round1(lat), _round1(lon))


def build_archive_url(lat: float, lon: float, start: date, end: date,
                      variables: list[str]) -> str:
    """The exact upstream URL (deterministic: it doubles as the key of the held slice).

    The place is rounded here (:func:`round_place`), so no caller can send or key a finer one."""
    lat, lon = round_place(lat, lon)
    daily = ",".join(sorted(variables))
    return (
        f"{ARCHIVE_BASE}?latitude={lat:.4f}&longitude={lon:.4f}"
        f"&start_date={start.isoformat()}&end_date={end.isoformat()}"
        f"&daily={daily}&timezone=UTC"
    )


#: The folder the loose JSON cache used to live in, before R683 moved every slice into the
#: encrypted store. Its file names hashed URLs carrying unrounded coordinates, in plaintext.
LEGACY_CACHE_DIR = "weather_context"


def purge_plaintext_cache() -> int:
    """Delete the pre-R683 plaintext slice folder, if any; returns how many files it held.

    Deleting rather than migrating is deliberate: the files were keyed by unrounded places, and
    every slice can be fetched again behind the consent. Run once at startup; a no-op after."""
    import shutil

    folder = data_dir() / LEGACY_CACHE_DIR
    if not folder.exists():
        return 0
    n = sum(1 for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else 1
    if folder.is_dir() and not folder.is_symlink():
        shutil.rmtree(folder)
    else:
        folder.unlink()
    return n


def held_store(store):
    if store is not None:
        return store
    from src.weather.held import HeldSlices

    return HeldSlices()


def read_cached_slice(url: str, *, store=None) -> dict | None:
    """The held slice for ``url``, or None when none is held or the store cannot be read.
    Local only: this never fetches. Slices live in the encrypted store (R683), never a file."""
    try:
        return held_store(store).get(url)
    except Exception:  # noqa: BLE001 - a locked or unreadable store is "not held", never a crash
        return None


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
    keep: bool = True,
    store=None,
) -> dict:
    """Fetch (or serve from the held copy) one bounded daily slice. Never raises for
    transport problems: failures come back as honest transport verdicts (the T4 taxonomy),
    exactly like the markets feeds.

    The place is rounded to :data:`PLACE_DECIMALS` before anything is sent or kept. With
    ``keep`` (the default) a held slice is served without a fetch and a fetched one is kept in
    the encrypted store (:mod:`src.weather.held`); ``keep=False`` neither reads nor writes it,
    for a caller that keeps the slice itself (the anomaly view). Nothing here logs the URL."""
    url = build_archive_url(lat, lon, start, end, variables)
    if keep and not force:
        held = read_cached_slice(url, store=store)
        if held is not None:
            return {**held, "cached": True, "label": label}

    try:
        if fetcher is None:
            from src.safety.fetcher import make_fetcher

            # Inside the try: a transport that cannot be built (protected mode, no proxy) is a verdict too.
            fetcher = make_fetcher()
        fetched = fetcher.fetch(url, require_html=False)
    except Exception as exc:  # noqa: BLE001 - every refusal becomes a verdict, never a crash
        from src.markets.csv_feeds import classify_failed_check

        verdict, note, retryable = classify_failed_check(exc)
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
    if not keep:
        return payload
    try:
        held_store(store).put(url, {k: v for k, v in payload.items() if k not in ("label", "cached")})
        payload["kept"] = True
    except Exception as exc:  # noqa: BLE001 - the slice is still shown; that it was not kept is said
        payload["kept"] = False
        # The type only: a store error can quote what it was handed, and the slice names the place (R683).
        _LOG.warning("could not keep a weather slice in the database (%s)", type(exc).__name__)
    return payload
