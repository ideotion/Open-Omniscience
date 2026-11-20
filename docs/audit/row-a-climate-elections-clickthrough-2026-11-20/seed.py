"""Seed a plaintext data folder for the 0.6 row A walk (S06-04 §4): climate, the place baseline,
a population-weighted group figure.

Nothing here opens a socket. Each store is written by its OWN code path, with only the transport
replaced: the six climate units go through ``src.stats.climate.fetch_and_store`` with the real
fetchers, whose ``get`` is handed a stand-in that answers with a publisher-shaped body generated
below; the place baseline goes through ``src.weather.anomaly.fetch_anomalies`` with a stand-in
fetcher; the group figure's inputs are stored World Bank rows. So the parsers, the diagnostics,
the vintage bookkeeping and the held store all run for real.

EVERY NUMBER HERE IS INVENTED, in the published SHAPE only (smooth curves, a seasonal sine, a
fixed pseudo-random stream). The screenshots show the app's rendering of invented data, never a
measurement. Run with OO_DATA_DIR pointing at an empty folder and OO_DB_PLAINTEXT=1.
"""
from __future__ import annotations

import json
import math
import random
import types
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from src.database.models import StatFigure
from src.database.session import SessionLocal, init_db
from src.stats import climate
from src.stats import fetch as real_fetch

RNG = random.Random(20261120)
TODAY = date(2026, 11, 20)


class _Resp:
    def __init__(self, text: str, status: int = 200):
        self.text = text
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


# --------------------------------------------------------------------------- publisher shapes
def gistemp_text() -> str:
    head = "Year,Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec,J-D,D-N,DJF,MAM,JJA,SON"
    out = ["Land-Ocean: Global Means", "", head]
    for y in range(1880, 2027):
        base = -0.28 + 0.0000085 * (y - 1880) ** 2.6 / 3.2
        months = []
        for m in range(12):
            if y == 2026 and m >= 10:
                months.append(None)
            else:
                months.append(round(base + 0.12 * math.sin(y * 1.7 + m) + RNG.uniform(-0.05, 0.05), 2))
        jd = round(sum(months) / 12, 2) if None not in months else None
        f = lambda v: "***" if v is None else (f"{v:.2f}".replace("0.", ".", 1) if abs(v) < 1 else f"{v:.2f}")  # noqa: E731
        out.append(",".join([str(y)] + [f(v) for v in months] + [f(jd)] + ["***"] * 5))
    return "\n".join(out) + "\n"


def nsidc_text() -> str:
    out = ["Year, Month, Day,     Extent,    Missing, Source Data",
           "YYYY,    MM,  DD, 10^6 sq km, 10^6 sq km, Source data product web site: http://nsidc.org/data/nsidc-0081.html"]
    d = date(2024, 1, 1)
    while d <= TODAY - timedelta(days=2):
        doy = d.timetuple().tm_yday
        ext = 10.8 + 3.9 * math.cos((doy - 70) / 365.25 * 2 * math.pi) - 0.05 * (d.year - 2024)
        missing = 0.0
        if d in (date(2025, 2, 11), date(2025, 2, 12)):
            missing = 0.420  # part of the pole not observed: a coverage-gap day
        val = "-9999" if d == date(2025, 7, 4) else f"{ext:.3f}"  # one published gap
        out.append(f"{d.year:4d},  {d.month:2d},  {d.day:2d},    {val},      {missing:.3f}, ['ftp://example.invalid/{d:%Y%m%d}.bin']")
        d += timedelta(days=1)
    return "\n".join(out) + "\n"


def oni_text() -> str:
    seasons = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"]
    out = ["SEAS YR   TOTAL ANOM"]
    for y in range(1950, 2027):
        for i, s in enumerate(seasons):
            if y == 2026 and i >= 9:
                break
            anom = round(1.1 * math.sin((y * 12 + i) / 19.0) + RNG.uniform(-0.2, 0.2), 2)
            out.append(f"{s}  {y} {26.5 + anom:5.2f} {anom:5.2f}")
    return "\n".join(out) + "\n"


def usgs_events() -> list[str]:
    rows = []
    for k in range(260):
        y = 1973 + (k * 53) // 260
        m = 1 + (k * 7) % 12
        mag = 6.0 + round(RNG.random() * 1.9, 1)
        status = "automatic" if (y, m) >= (2026, 10) else "reviewed"
        rows.append(f"{y:04d}-{m:02d}-{1 + k % 27:02d}T03:04:05.000Z,1.0,2.0,10,{mag},mww,walk{k},\"Walk, Nowhere\",earthquake,{status}")
    rows.append('2001-05-05T00:00:00.000Z,1.0,2.0,0,6.1,ml,walkblast,"Walk, Quarry",quarry blast,reviewed')
    return rows


def owid_text() -> str:
    cols = "country,year,iso_code,population,co2,co2_per_capita,cumulative_co2"
    out = [cols]
    for name, iso, pop, co2 in (("France", "FRA", 58e6, 390.0), ("Germany", "DEU", 80e6, 1050.0),
                                ("India", "IND", 870e6, 600.0), ("Brazil", "BRA", 150e6, 210.0)):
        cum = 0.0
        for y in range(1990, 2024):
            v = co2 * (1 + 0.012 * (y - 1990)) if iso in ("IND", "BRA") else co2 * (1 - 0.009 * (y - 1990))
            cum += v
            p = pop * (1 + 0.006 * (y - 1990))
            gap = iso == "BRA" and y == 1995
            out.append(f"{name},{y},{iso},{p:.0f},{'' if gap else f'{v:.1f}'},{v * 1e6 / p:.2f},{cum:.1f}")
    out.append("World,2023,,8000000000,37000.0,4.6,")
    return "\n".join(out) + "\n"


def ghcnd_text(station: str) -> str:
    lines = []
    for y in (2024, 2025, 2026):
        for m in range(1, 13):
            if (y, m) > (2026, 10):
                break
            for el in ("TMAX", "TMIN", "PRCP"):
                s = f"{station}{y:04d}{m:02d}{el}"
                for d in range(1, 32):
                    try:
                        dt = date(y, m, d)
                    except ValueError:
                        s += "-9999   "
                        continue
                    doy = dt.timetuple().tm_yday
                    if el == "PRCP":
                        v = max(0, int(RNG.gauss(20, 40)))
                    else:
                        t = 125 + 110 * math.sin((doy - 110) / 365.25 * 2 * math.pi) + (50 if el == "TMAX" else -40)
                        v = int(t + RNG.uniform(-25, 25))
                    q = "I" if (y, m, d) == (2025, 3, 3) and el == "TMAX" else " "  # one quality-flagged day
                    s += f"{v:5d} {q}W"
                lines.append(s)
    return "\n".join(lines) + "\n"


def getter(url: str) -> _Resp:
    host = urlparse(url).netloc
    if "giss" in host or "gistemp" in url:
        return _Resp(gistemp_text())
    if "nsidc" in host or "colorado" in host:
        return _Resp(nsidc_text())
    if "cpc" in host or "oni" in url.lower():
        return _Resp(oni_text())
    if "usgs" in host:
        ev = usgs_events()
        if "/count" in url:
            return _Resp(str(len(ev) - 1))  # the service counts earthquakes; the blast is excluded by the parser
        return _Resp("\n".join(["time,latitude,longitude,depth,mag,magType,id,place,type,status"] + ev) + "\n")
    if "owid" in host or "github" in host:
        return _Resp(owid_text())
    if "ncei" in host or "noaa" in host:
        return _Resp(ghcnd_text(url.rsplit("/", 1)[-1].split(".")[0]))
    raise RuntimeError(f"walk seed has no body for {host}")


class _Fetchers(types.SimpleNamespace):
    """``src.stats.fetch`` with every ``fetch_*`` handed the stand-in getter; the URL builders are real."""

    def __getattr__(self, name):
        attr = getattr(real_fetch, name)
        if name.startswith("fetch_") and callable(attr):
            return lambda *a, **kw: attr(*a, get=getter, **kw)
        return attr


# --------------------------------------------------------------------------- Open-Meteo stand-in
class _Fetched:
    def __init__(self, url: str, body: dict):
        self.content = json.dumps(body).encode()
        self.final_url = url
        self.status_code = 200
        self.fetched_at = datetime(2026, 11, 20, 9, 30, tzinfo=UTC)


class _MeteoFetcher:
    def fetch(self, url: str, require_html: bool = False) -> _Fetched:
        q = parse_qs(urlparse(url).query)
        s, e = date.fromisoformat(q["start_date"][0]), date.fromisoformat(q["end_date"][0])
        days, d = [], s
        while d <= e:
            days.append(d)
            d += timedelta(days=1)
        daily = {"time": [x.isoformat() for x in days]}
        warm = 1.3 if s.year >= 2026 else 0.0  # the window runs warmer than the baseline (invented)
        for var in q["daily"][0].split(","):
            vals = []
            for x in days:
                doy = x.timetuple().tm_yday
                season = math.sin((doy - 110) / 365.25 * 2 * math.pi)
                if var == "temperature_2m_max":
                    vals.append(round(16 + 9 * season + warm + RNG.uniform(-2, 2), 1))
                elif var == "temperature_2m_min":
                    vals.append(round(8 + 7 * season + warm + RNG.uniform(-2, 2), 1))
                else:
                    vals.append(round(max(0.0, RNG.gauss(1.7, 3.0) * (0.7 if warm else 1.0)), 1))
            daily[var] = vals
        units = {v: ("mm" if v.startswith("precip") else "°C") for v in daily if v != "time"}
        return _Fetched(url, {"daily": daily, "daily_units": {"time": "iso8601", **units}})


def main() -> None:
    init_db()
    f = _Fetchers()
    with SessionLocal() as s:
        for dataset, param in (("gistemp", "GLB"), ("nsidc", "N"), ("oni", None), ("usgs", None),
                               ("owid", "co2"), ("ghcnd", "USW00094728")):
            rec = climate.fetch_and_store(s, dataset, param, fetchers=f)
            s.commit()
            print(dataset, param, rec.get("tally"), sorted((rec.get("diagnostics") or {}).keys()))

        # The group figure's inputs: World Bank-shaped rows, 2023, invented values.
        members = {"FRA": (68.2, 44_400), "DEU": (84.5, 52_700), "ITA": (58.9, 38_400), "ESP": (48.3, 33_500),
                   "POL": (36.7, 22_100), "NLD": (17.9, 62_500), "PRT": (10.5, 27_300), "GRC": (10.4, 23_400),
                   "SWE": (10.5, 56_300), "IRL": (5.3, 104_000)}
        for iso, (pop_m, gdp_pc) in members.items():
            s.add(StatFigure(agency="worldbank", series_id="SP.POP.TOTL", ref_area=iso, time_period="2023",
                             value=pop_m * 1e6, unit="persons", extracted_at="2026-11-20T09:00:00+00:00"))
            s.add(StatFigure(agency="worldbank", series_id="NY.GDP.PCAP.CD", ref_area=iso, time_period="2023",
                             value=float(gdp_pc), unit="current US$", extracted_at="2026-11-20T09:00:00+00:00"))
        s.commit()

    from src.weather.anomaly import fetch_anomalies

    out = fetch_anomalies(48.86, 2.35, date(2026, 6, 1), date(2026, 8, 31), fetcher=_MeteoFetcher())
    print("place", out.get("place"), [(r["variable"], r.get("value")) for r in out.get("results", [])], out.get("kept"))


if __name__ == "__main__":
    main()
