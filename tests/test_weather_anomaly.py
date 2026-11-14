"""Anomalies against the 1991-2020 baseline — positives and their refusal twins.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Fixtures are HAND-BUILT in the ``fetch_daily_slice`` payload shape; they are not real Open-Meteo
data, and the live shape is unverified from this sandbox (the host is unreachable here).
"""

from __future__ import annotations

from datetime import date, timedelta

from src.weather import anomaly
from src.weather.anomaly import compute_anomalies, fetch_anomalies

UNITS = {"temperature_2m_max": "°C", "temperature_2m_min": "°C", "precipitation_sum": "mm"}


def _slice(start, end, fn, variables=("temperature_2m_max", "precipitation_sum"), units=UNITS):
    days, d = [], start
    while d <= end:
        days.append(d)
        d += timedelta(days=1)
    daily = {"time": [x.isoformat() for x in days]}
    for v in variables:
        daily[v] = [fn(v, x) for x in days]
    return {"ok": True, "daily": daily, "units": dict(units)}


def _base(fn=lambda v, d: 10.0 if v.startswith("temp") else 2.0):
    return _slice(anomaly.BASELINE_START, anomaly.BASELINE_END, fn)


class _Mem:
    """An in-memory stand-in for the encrypted held-slice store."""

    def __init__(self):
        self.d = {}

    def get(self, url):
        return self.d.get(url)

    def put(self, url, payload):
        self.d[url] = payload


def _res(out, var):
    return next(r for r in out["results"] if r["variable"] == var)


def test_temperature_anomaly_is_window_mean_minus_baseline_mean():
    win = _slice(date(2023, 5, 12), date(2023, 5, 14), lambda v, d: 13.0 if v.startswith("temp") else 0.0)
    out = compute_anomalies(_base(), win)
    r = _res(out, "temperature_2m_max")
    assert r["value"] == 3.0 and r["years_used"] == 30 and r["years_excluded"] == 0
    assert r["reason"] is None and out["baseline"]["start"] == "1991-01-01"


def test_precipitation_is_percent_of_baseline_total():
    win = _slice(date(2023, 5, 1), date(2023, 5, 10), lambda v, d: 0.6 if v == "precipitation_sum" else 1.0)
    r = _res(compute_anomalies(_base(), win), "precipitation_sum")
    assert abs(r["baseline_value"] - 20.0) < 1e-9 and abs(r["value"] - 30.0) < 1e-9


def test_zero_baseline_has_no_percentage():
    win = _slice(date(2023, 5, 1), date(2023, 5, 3), lambda v, d: 5.0)
    r = _res(compute_anomalies(_base(lambda v, d: 0.0), win), "precipitation_sum")
    assert r["value"] is None and "0 mm" in r["reason"]


def test_gap_in_window_is_null_with_reason_not_a_short_sum():
    win = _slice(date(2023, 5, 1), date(2023, 5, 3), lambda v, d: None if d.day == 2 else 1.0)
    r = _res(compute_anomalies(_base(), win), "precipitation_sum")
    assert r["value"] is None and r["window_missing_days"] == 1


def test_baseline_year_with_a_gap_is_excluded_and_counted():
    def fn(v, d):
        return None if (d.year == 2000 and d.month == 5 and d.day == 2) else 10.0
    win = _slice(date(2023, 5, 1), date(2023, 5, 3), lambda v, d: 10.0)
    r = _res(compute_anomalies(_base(fn), win), "temperature_2m_max")
    assert r["years_used"] == 29 and r["years_excluded"] == 1 and r["value"] == 0.0


def test_leap_day_window_excludes_non_leap_baseline_years():
    win = _slice(date(2024, 2, 28), date(2024, 3, 1), lambda v, d: 10.0)
    r = _res(compute_anomalies(_base(), win), "temperature_2m_max")
    assert r["years_used"] == 8 and r["years_excluded"] == 22  # 1992..2020 step 4


def test_window_crossing_new_year_keeps_year_offsets():
    # baseline warm only in January days; a Dec->Jan window must see both halves
    def fn(v, d):
        return 20.0 if d.month == 1 else 10.0
    win = _slice(date(2022, 12, 31), date(2023, 1, 1), lambda v, d: 10.0)
    r = _res(compute_anomalies(_base(fn), win), "temperature_2m_max")
    assert r["baseline_value"] == 15.0 and r["years_used"] == 29  # 2020->2021 unavailable


def test_window_inside_baseline_is_flagged():
    win = _slice(date(2005, 5, 1), date(2005, 5, 3), lambda v, d: 10.0)
    assert _res(compute_anomalies(_base(), win), "temperature_2m_max")["window_in_baseline_period"]
    win2 = _slice(date(2023, 5, 1), date(2023, 5, 3), lambda v, d: 10.0)
    assert not _res(compute_anomalies(_base(), win2), "temperature_2m_max")["window_in_baseline_period"]


def test_wrong_or_missing_units_are_refused():
    win = _slice(date(2023, 5, 1), date(2023, 5, 3), lambda v, d: 1.0, units={"temperature_2m_max": "°F"})
    assert _res(compute_anomalies(_base(), win), "temperature_2m_max")["value"] is None
    win = _slice(date(2023, 5, 1), date(2023, 5, 3), lambda v, d: 1.0, units={})
    assert "unit" in _res(compute_anomalies(_base(), win), "precipitation_sum")["reason"]


def test_garbage_and_unsupported_input_never_raises_and_is_never_a_number():
    for bad in ({}, {"daily": {}}, {"daily": {"time": ["x"], "temperature_2m_max": [1]}},
                {"daily": {"time": ["2023-01-01", "2023-01-01"], "temperature_2m_max": [1, 2]}},
                {"daily": {"time": ["2023-01-01"], "temperature_2m_max": []}}):
        out = compute_anomalies(bad, bad, ["temperature_2m_max", "wind_speed_10m_max"])
        assert all(r["value"] is None and r["reason"] for r in out["results"])
    nan = _slice(date(2023, 5, 1), date(2023, 5, 1), lambda v, d: float("nan"))
    assert _res(compute_anomalies(_base(), nan), "temperature_2m_max")["value"] is None


def test_no_baseline_year_complete_is_null():
    win = _slice(date(2023, 5, 1), date(2023, 5, 2), lambda v, d: 1.0)
    r = _res(compute_anomalies(_base(lambda v, d: None), win), "temperature_2m_max")
    assert r["value"] is None and r["years_used"] == 0


def test_fetch_stops_on_a_failed_baseline_and_reports_the_stage(monkeypatch):
    calls = []

    def fake(lat, lon, s, e, vs, **kw):
        calls.append((s, e))
        return {"ok": False, "verdict": "network-refused"}
    monkeypatch.setattr(anomaly, "fetch_daily_slice", fake)
    out = fetch_anomalies(1, 2, date(2023, 5, 1), date(2023, 5, 3), store=_Mem())
    assert out["ok"] is False and out["stage"] == "baseline" and len(calls) == 1


def test_fetch_composes_baseline_and_window(monkeypatch):
    def fake(lat, lon, s, e, vs, **kw):
        p = _slice(s, e, lambda v, d: 13.0 if v.startswith("temp") else 1.0)
        p["provenance"] = {"requested_url": "u"}
        return p
    monkeypatch.setattr(anomaly, "fetch_daily_slice", fake)
    out = fetch_anomalies(1, 2, date(2023, 5, 1), date(2023, 5, 3), ["temperature_2m_max"], store=_Mem())
    assert out["ok"] and _res(out, "temperature_2m_max")["value"] == 0.0 and "provenance" in out


def test_route_rejects_variables_without_an_anomaly_definition():
    import pytest
    from pydantic import ValidationError

    from src.api.weather import WeatherAnomalyRequest
    with pytest.raises(ValidationError):
        WeatherAnomalyRequest(lat=1, lon=2, start_date=date(2023, 1, 1), end_date=date(2023, 1, 2),
                              variables=["wind_gusts_10m_max"])


def test_non_dict_units_and_huge_integers_do_not_raise():
    win = _slice(date(2023, 5, 1), date(2023, 5, 2), lambda v, d: 1.0)
    win["units"] = "mm"
    out = compute_anomalies(_base(), win)
    assert all(r["value"] is None and r["reason"] for r in out["results"])
    huge = _slice(date(2023, 5, 1), date(2023, 5, 2), lambda v, d: 10**400)
    assert _res(compute_anomalies(_base(), huge), "temperature_2m_max")["value"] is None


def test_a_window_with_a_skipped_date_is_refused():
    win = {"daily": {"time": ["2023-01-01", "2023-01-10"], "precipitation_sum": [1.0, 1.0]},
           "units": UNITS}
    r = _res(compute_anomalies(_base(), win, ["precipitation_sum"]), "precipitation_sum")
    assert r["value"] is None and "consecutive" in r["reason"]


def test_window_not_covering_the_requested_range_is_refused():
    win = _slice(date(2023, 5, 1), date(2023, 5, 3), lambda v, d: 1.0)
    out = compute_anomalies(_base(), win, expect=(date(2023, 5, 1), date(2023, 5, 9)))
    assert all(r["value"] is None and "not the requested" in r["reason"] for r in out["results"])


def test_integer_dates_are_not_dates():
    win = {"daily": {"time": [20230101], "precipitation_sum": [1.0]}, "units": UNITS}
    assert _res(compute_anomalies(_base(), win, ["precipitation_sum"]), "precipitation_sum")["value"] is None


def test_new_year_window_at_the_baseline_end_counts_the_lost_year():
    win = _slice(date(2020, 12, 31), date(2021, 1, 1), lambda v, d: 10.0)
    r = _res(compute_anomalies(_base(), win), "temperature_2m_max")
    assert r["years_used"] == 29 and r["years_excluded"] == 1


def test_baseline_is_fetched_once_for_all_variables_and_window_checked(monkeypatch):
    seen = []

    def fake(lat, lon, s, e, vs, **kw):
        seen.append((s, tuple(vs)))
        return _slice(s, e, lambda v, d: 1.0, variables=vs)
    monkeypatch.setattr(anomaly, "fetch_daily_slice", fake)
    fetch_anomalies(1, 2, date(2023, 5, 1), date(2023, 5, 3), ["precipitation_sum"], store=_Mem())
    assert seen[0] == (anomaly.BASELINE_START, tuple(sorted(anomaly.SUPPORTED)))


def test_duplicate_variables_collapse():
    win = _slice(date(2023, 5, 1), date(2023, 5, 2), lambda v, d: 1.0)
    out = compute_anomalies(_base(), win, ["precipitation_sum", "precipitation_sum"])
    assert len(out["results"]) == 1
