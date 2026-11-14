"""
Anomalies against a STATED 1991-2020 baseline, from Open-Meteo daily reanalysis slices.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The corroboration layer (FUTURE_DEVELOPMENTS, Open-Meteo section) says "anomalies, not raw
values": 40 mm of rain means nothing without what that place normally gets in those days. This
module is the pure arithmetic for that; :func:`compute_anomalies` takes two already-decoded
slices (the baseline and the window, both in the ``fetch_daily_slice`` payload shape) and never
imports ``requests`` / ``httpx`` / ``socket``. The one networked entry point,
:func:`fetch_anomalies`, goes through ``src.weather.openmeteo.fetch_daily_slice`` — the single
ethical fetch path, the same host (``archive-api.open-meteo.com``) already enumerated in
``docs/SECURITY.md`` and ``src/static/net-hosts.js``; no new host is introduced.

**THE LIVE RESPONSE SHAPE IS NOT VERIFIED HERE.** This session cannot reach the host; the shape
(``daily.time`` ISO dates plus one array per variable, ``daily_units``) is the one
``fetch_daily_slice`` already relies on. Anything the parser does not recognise becomes a null
with a reason; nothing is bent to fit.

HONESTY PROPERTIES (each a refusal, not a caveat):

* **Unknown is null with a reason.** A window with a gap does not get a sum or mean that quietly
  understates it; it gets ``value: null`` and says how many days were missing.
* **Same calendar days, same offsets.** The baseline for 12 May - 20 June 2023 is those same
  calendar days in each of 1991..2020 (a window crossing New Year keeps its year offsets). A
  baseline year that is incomplete for those days, or that lacks a 29 February the window has,
  is EXCLUDED and counted (``years_used`` / ``years_excluded``) rather than imputed.
* **A zero baseline has no percentage.** If the baseline total is 0 mm, "% of baseline" is null
  with that reason, never infinity or 0.
* **The window may sit inside the baseline.** That is allowed but flagged
  (``window_in_baseline_period``): an anomaly against a period containing it is not independent.
* **Units are checked.** A slice whose ``daily_units`` are not the expected ones is refused.
* No score, no threshold verdict: numbers, n and method only. Reanalysis is a model estimate for
  a grid cell, not a station record.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from src.weather.openmeteo import (
    LICENSE_NOTE,
    PLACE_DECIMALS,
    build_archive_url,
    fetch_daily_slice,
    round_place,
)

BASELINE_START = date(1991, 1, 1)
BASELINE_END = date(2020, 12, 31)
BASELINE_LABEL = "1991-2020 (the WMO standard climate normal period)"

# variable -> (kind, expected unit, display unit). "mean" variables are compared as the window
# mean minus the baseline mean of the same days; "sum" variables as the window total against the
# mean of the per-year totals over the same calendar days.
SUPPORTED: dict[str, tuple[str, str, str]] = {
    "temperature_2m_max": ("mean", "°C", "°C"),
    "temperature_2m_min": ("mean", "°C", "°C"),
    "precipitation_sum": ("sum", "mm", "mm"),
}

METHOD = (
    "anomaly = window value minus (mean) or as a percentage of (sum) the same calendar days "
    f"averaged over the baseline {BASELINE_LABEL}; years with any missing day are excluded"
)
CAVEAT = (
    "Open-Meteo ERA5-family reanalysis: a model estimate for the grid cell containing the "
    "point, not a station record. An anomaly is consistency of evidence, never proof."
)


def _days(payload: dict) -> tuple[list[date], dict[str, list], str | None]:
    """Decode a slice's ``daily`` block. Returns (dates, columns, refusal-reason)."""
    daily = payload.get("daily") if isinstance(payload, dict) else None
    if not isinstance(daily, dict) or not isinstance(daily.get("time"), list):
        return [], {}, "the slice has no daily.time series"
    try:
        if not all(isinstance(t, str) for t in daily["time"]):
            raise ValueError
        dates = [date.fromisoformat(t) for t in daily["time"]]
    except ValueError:
        return [], {}, "daily.time holds a value that is not an ISO date"
    if len(set(dates)) != len(dates):
        return [], {}, "daily.time repeats a date"
    if any((b - a).days != 1 for a, b in zip(dates, dates[1:], strict=False)):
        return [], {}, "daily.time is not one consecutive run of days (a skipped date would shrink the window)"
    cols = {k: v for k, v in daily.items() if k != "time" and isinstance(v, list)}
    for k, v in cols.items():
        if len(v) != len(dates):
            return [], {}, f"{k} has {len(v)} values for {len(dates)} dates"
    return dates, cols, None


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    try:
        return float(x) if math.isfinite(x) else None
    except OverflowError:  # an integer too large for a float
        return None


def _shift(d: date, years: int) -> date | None:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February into a non-leap year
        return None


def _unit_refusal(payload: dict, var: str) -> str | None:
    want = SUPPORTED[var][1]
    units = payload.get("units")
    got = units.get(var) if isinstance(units, dict) else None
    if got is None:
        return f"the slice does not state a unit for {var}; expected {want}"
    if got != want:
        return f"{var} is in {got!r}, expected {want!r}"
    return None


def _null(var: str, reason: str, **extra: Any) -> dict:
    return {"variable": var, "value": None, "reason": reason, **extra}


def _one(var: str, base: tuple, win: tuple, base_payload: dict, win_payload: dict) -> dict:
    kind, _, unit = SUPPORTED[var]
    for p in (base_payload, win_payload):
        why = _unit_refusal(p, var)
        if why:
            return _null(var, why)
    bdates, bcols, _ = base
    wdates, wcols, _ = win
    if var not in bcols or var not in wcols:
        return _null(var, f"{var} is absent from the {'baseline' if var not in bcols else 'window'} slice")
    if not wdates:
        return _null(var, "the window slice is empty")

    wvals = [_num(x) for x in wcols[var]]
    w_missing = sum(1 for v in wvals if v is None)
    if w_missing:
        return _null(var, f"{w_missing} of {len(wvals)} window days have no value; a "
                          f"{'mean' if kind == 'mean' else 'total'} over a gap would be wrong",
                     n_window_days=len(wvals), window_missing_days=w_missing)
    wlookup = dict(zip(wdates, wvals, strict=True))
    blookup = {d: _num(x) for d, x in zip(bdates, bcols[var], strict=True)}
    first = min(wdates)
    offsets = {d: d.year - first.year for d in wdates}

    per_year: list[float] = []
    excluded = 0
    for y in range(BASELINE_START.year, BASELINE_END.year + 1):
        vals: list[float] = []
        ok = True
        for d in wdates:
            bd = _shift(d, y + offsets[d] - d.year)
            v = blookup.get(bd) if bd is not None else None
            if v is None:
                ok = False
                break
            vals.append(v)
        if not ok:
            excluded += 1
            continue
        per_year.append(sum(vals) / len(vals) if kind == "mean" else sum(vals))

    n_years = len(per_year)
    common = {
        "variable": var, "unit": unit, "kind": kind,
        "n_window_days": len(wvals), "years_used": n_years, "years_excluded": excluded,
        "window_in_baseline_period": (min(wdates) >= BASELINE_START and max(wdates) <= BASELINE_END),
    }
    if n_years == 0:
        return _null(var, "no baseline year is complete for these calendar days", **common)

    base_val = sum(per_year) / n_years
    win_val = (sum(wlookup[d] for d in wdates) / len(wdates)) if kind == "mean" else sum(wlookup.values())
    out = {**common, "window_value": win_val, "baseline_value": base_val}
    if kind == "mean":
        out["value"] = win_val - base_val
        out["value_unit"] = unit
        out["reason"] = None
    elif base_val == 0:
        out["value"] = None
        out["reason"] = "the baseline total for these days is 0 mm, so a percentage is undefined"
    else:
        out["value"] = 100.0 * win_val / base_val
        out["value_unit"] = "% of baseline"
        out["reason"] = None
    return out


def compute_anomalies(baseline: dict, window: dict, variables: list[str] | None = None,
                      expect: tuple[date, date] | None = None) -> dict:
    """Anomalies of ``window`` against ``baseline`` for the supported variables.

    Both arguments are ``fetch_daily_slice`` payloads. Never raises for bad data: every
    problem is a ``value: None`` with a ``reason``.
    """
    variables = list(dict.fromkeys(variables)) if variables else list(SUPPORTED)
    base = _days(baseline)
    win = _days(window)
    bad = base[2] or win[2]
    if not bad and expect is not None and win[0] and (min(win[0]), max(win[0])) != expect:
        win = ([], {}, f"the slice covers {min(win[0])}..{max(win[0])}, not the requested "
                       f"{expect[0]}..{expect[1]}")
        bad = win[2]
    results = []
    for var in variables:
        if var not in SUPPORTED:
            results.append(_null(var, f"{var} has no anomaly definition; supported: {sorted(SUPPORTED)}"))
        elif bad:
            results.append(_null(var, ("baseline: " + base[2]) if base[2] else ("window: " + str(win[2]))))
        else:
            results.append(_one(var, base, win, baseline, window))
    return {
        "ok": True,
        "baseline": {"label": BASELINE_LABEL, "start": BASELINE_START.isoformat(),
                     "end": BASELINE_END.isoformat()},
        "method": METHOD,
        "caveat": CAVEAT,
        "license": LICENSE_NOTE,
        "results": results,
    }


#: R675: the place is ROUNDED before it leaves the machine (:data:`src.weather.openmeteo.PLACE_DECIMALS`,
#: one decimal of a degree, the ERA5-Land spacing; ``build_archive_url`` applies it for every caller).
PLACE_NOTE = (
    "Coordinates are rounded to 0.1 degree (about 11 km) before they are sent: that is the spacing of "
    "ERA5-Land, the finest grid behind these values. Open-Meteo also adjusts temperature for the terrain "
    "height at the point it receives, so a reading can differ slightly from the exact spot."
)


def place(lat: float, lon: float) -> tuple[float, float]:
    """The rounded place actually sent and stored (R675). ``-0.0`` reads as ``0.0``."""
    return round_place(lat, lon)


def _all_vars() -> list[str]:
    # Both slices always carry every supported variable, so one held slice answers any subset.
    return sorted(SUPPORTED)


def _place_store(store):
    # The person's own place, kept apart from corroboration slices (src/weather/held.py PLACE_KEY_PREFIX).
    if store is not None:
        return store
    from src.weather.held import PLACE_KEY_PREFIX, HeldSlices

    return HeldSlices(PLACE_KEY_PREFIX)


def _place_block(lat: float, lon: float) -> dict:
    return {"lat": lat, "lon": lon, "decimals": PLACE_DECIMALS, "note": PLACE_NOTE}


def held_anomalies(lat: float, lon: float, start: date, end: date,
                   variables: list[str] | None = None, *, store=None) -> dict:
    """The anomalies from slices ALREADY held on this machine. Never fetches: a slice not held is
    named in ``missing`` and no number is computed (R675's re-view, readable in airplane mode)."""
    lat, lon = place(lat, lon)
    st = _place_store(store)
    base = st.get(build_archive_url(lat, lon, BASELINE_START, BASELINE_END, _all_vars()))
    win = st.get(build_archive_url(lat, lon, start, end, _all_vars()))
    missing = [name for name, p in (("baseline", base), ("window", win)) if p is None]
    if missing:
        return {"ok": True, "held": False, "missing": missing, "place": _place_block(lat, lon)}
    out = compute_anomalies(base, win, variables, expect=(start, end))
    out.update(held=True, place=_place_block(lat, lon),
               provenance={"baseline": base.get("provenance"), "window": win.get("provenance")})
    return out


def fetch_anomalies(lat: float, lon: float, start: date, end: date,
                    variables: list[str] | None = None, *, force: bool = False,
                    fetcher=None, store=None) -> dict:
    """Fetch what is not held yet (the 1991-2020 baseline and the window), keep it, compute.

    Two consented fetches at most, through the single ethical path, for the ROUNDED place
    (:func:`place`). The baseline is a ~30-year slice (about 11,000 days, deliberately beyond the
    366-day window bound, which applies to the window only), fetched once per place. Slices are
    kept in the encrypted store (:mod:`src.weather.held`), never in a loose file; ``force``
    re-downloads both. A failed fetch returns that slice's honest transport verdict instead of
    numbers.
    """
    variables = list(dict.fromkeys(variables)) if variables else list(SUPPORTED)
    unknown = sorted(set(variables) - set(SUPPORTED))
    if unknown:
        raise ValueError(f"no anomaly definition for {unknown}; supported: {sorted(SUPPORTED)}")
    lat, lon = place(lat, lon)
    st = _place_store(store)
    got: dict[str, dict] = {}
    held: dict[str, bool] = {}
    kept = True
    for stage, (s, e) in (("baseline", (BASELINE_START, BASELINE_END)), ("window", (start, end))):
        url = build_archive_url(lat, lon, s, e, _all_vars())
        payload = None if force else st.get(url)
        held[stage] = payload is not None
        if payload is None:
            payload = fetch_daily_slice(lat, lon, s, e, _all_vars(), force=True, fetcher=fetcher,
                                        keep=False)
            if not payload.get("ok"):
                return {**payload, "stage": stage, "place": _place_block(lat, lon)}
            payload = {k: v for k, v in payload.items() if k not in ("label", "cached")}
            try:
                st.put(url, payload)
            except Exception:  # noqa: BLE001 - the numbers are still shown; that they were not kept is said
                kept = False
        got[stage] = payload
    out = compute_anomalies(got["baseline"], got["window"], variables, expect=(start, end))
    out["place"] = _place_block(lat, lon)
    out["kept"] = kept
    out["provenance"] = {"baseline": got["baseline"].get("provenance"), "window": got["window"].get("provenance"),
                         "baseline_cached": held["baseline"], "window_cached": held["window"]}
    return out


__all__ = ["BASELINE_END", "BASELINE_START", "PLACE_DECIMALS", "SUPPORTED", "compute_anomalies", "fetch_anomalies",
           "held_anomalies", "place"]
