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

from src.weather.openmeteo import LICENSE_NOTE, fetch_daily_slice

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
        dates = [date.fromisoformat(str(t)) for t in daily["time"]]
    except ValueError:
        return [], {}, "daily.time holds a value that is not an ISO date"
    if len(set(dates)) != len(dates):
        return [], {}, "daily.time repeats a date"
    cols = {k: v for k, v in daily.items() if k != "time" and isinstance(v, list)}
    for k, v in cols.items():
        if len(v) != len(dates):
            return [], {}, f"{k} has {len(v)} values for {len(dates)} dates"
    return dates, cols, None


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def _shift(d: date, years: int) -> date | None:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February into a non-leap year
        return None


def _unit_refusal(payload: dict, var: str) -> str | None:
    want = SUPPORTED[var][1]
    got = (payload.get("units") or {}).get(var)
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
    span = max(offsets.values())

    per_year: list[float] = []
    excluded = 0
    for y in range(BASELINE_START.year, BASELINE_END.year - span + 1):
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


def compute_anomalies(baseline: dict, window: dict, variables: list[str] | None = None) -> dict:
    """Anomalies of ``window`` against ``baseline`` for the supported variables.

    Both arguments are ``fetch_daily_slice`` payloads. Never raises for bad data: every
    problem is a ``value: None`` with a ``reason``.
    """
    variables = list(variables) if variables else list(SUPPORTED)
    base = _days(baseline)
    win = _days(window)
    bad = base[2] or win[2]
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


def fetch_anomalies(lat: float, lon: float, start: date, end: date,
                    variables: list[str] | None = None, *, force: bool = False,
                    fetcher=None) -> dict:
    """Fetch (cache-aware) the 1991-2020 baseline and the window, then compute anomalies.

    Two consented fetches through the single ethical path (the baseline is cached on disk after
    the first, so re-viewing is offline). A failed fetch returns that slice's honest transport
    verdict instead of numbers.
    """
    variables = list(variables) if variables else list(SUPPORTED)
    unknown = sorted(set(variables) - set(SUPPORTED))
    if unknown:
        raise ValueError(f"no anomaly definition for {unknown}; supported: {sorted(SUPPORTED)}")
    base = fetch_daily_slice(lat, lon, BASELINE_START, BASELINE_END, variables,
                             force=force, fetcher=fetcher)
    if not base.get("ok"):
        return {**base, "stage": "baseline"}
    win = fetch_daily_slice(lat, lon, start, end, variables, force=force, fetcher=fetcher)
    if not win.get("ok"):
        return {**win, "stage": "window"}
    out = compute_anomalies(base, win, variables)
    out["provenance"] = {"baseline": base.get("provenance"), "window": win.get("provenance"),
                         "baseline_cached": base.get("cached"), "window_cached": win.get("cached")}
    return out


__all__ = ["BASELINE_END", "BASELINE_START", "SUPPORTED", "compute_anomalies", "fetch_anomalies"]
