"""The climate vertical's catalogue, store and read layer (0.6 gate row A, rulings R661 / R662).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Six keyless datasets already have a guarded fetcher in ``src.stats.fetch`` and a pure parser
beside it (GISTEMP, NSIDC, ONI, USGS earthquakes, OWID CO2 + energy, GHCN-Daily). This module is
what makes them REACHABLE: it names each fetch unit, runs one through its fetcher, stores the
result and reads it back for the Climate tab. It never touches a socket itself; the fetchers do,
and each refuses up front while airplane mode is engaged.

STORAGE (R662). A climate re-fetch stores only the observations that are NEW or REVISED against
the latest stored vintage of the same (series, area, period). A revision is a new row at its new
vintage, so the earlier value stays readable; nothing is ever overwritten or deleted. A full copy
per click would be 100,000 to 400,000 rows for one OWID table or one long GHCN station. Every
fetch is still recorded, with its timestamp and the parser's diagnostics, in ``app_state`` under
``climate.fetch.<dataset>.<param>`` (written in the SAME transaction as the figures), and the
periods a publisher stopped serving are counted rather than silently kept as current.

Honesty carried through unchanged: a published gap is ``value=None`` and stays a gap; no score,
no ranking, no "climate risk" number anywhere.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from src.database.models import AppState
from src.database.models import StatFigure as StatFigureRow
from src.stats import ghcnd, gistemp, nsidc, oni, owid_climate, usgs_quakes
from src.stats.sdmx import StatFigure

#: The earthquake window the Climate tab fetches (accepted defaults, R662's note): magnitude 6.0
#: and above from January 1973 to the current month. About 7,500 events, under the service's
#: 20,000-per-request cap; the caveat names detection improvements over the decades.
USGS_START_MONTH = "1973-01"
USGS_MIN_MAGNITUDE = 6.0

#: Key prefix of the per-fetch record in ``app_state``.
RECORD_PREFIX = "climate.fetch."

#: How many withdrawn periods / coverage gaps a record keeps verbatim (the counts are exact).
SAMPLE_KEPT = 50

_INSERT_CHUNK = 2000


@dataclass(frozen=True)
class Series:
    """One drawable line: a stored ``series_id`` and what to call it."""

    series_id: str
    label: str
    unit: str


@dataclass(frozen=True)
class Dataset:
    id: str
    agency: str
    #: Allowed params; ``None`` = no param; ``()`` = free-form, checked by ``valid_param``.
    params: tuple[str, ...] | None
    default_param: str | None
    #: The upstream page a reader can visit (shown as a full-URL link, never fetched by the app).
    source_page: str
    #: The dated "documented as of" constant of the parser (NOT a live verification).
    documented_as_of: str
    licence: str
    #: The one host the fetcher reaches (shown in the button's hover and the consent popup).
    host: str
    #: Charts: lists of series drawn together (one unit per chart).
    charts: tuple[tuple[Series, ...], ...]


def _usgs_series() -> tuple[tuple[Series, ...], ...]:
    count_id, max_id = usgs_quakes.series_ids(USGS_MIN_MAGNITUDE)
    return (
        (Series(count_id, "Earthquakes per month, magnitude 6.0 and above", usgs_quakes.UNIT_COUNT),),
        (Series(max_id, "Largest magnitude in the month", usgs_quakes.UNIT_MAG),),
    )


DATASETS: dict[str, Dataset] = {
    "gistemp": Dataset(
        id="gistemp",
        host="data.giss.nasa.gov",
        agency=gistemp.AGENCY,
        params=gistemp.REGIONS,
        default_param="GLB",
        source_page="https://data.giss.nasa.gov/gistemp/",
        documented_as_of=gistemp.GISTEMP_AS_OF,
        licence="NASA GISS, public domain (US government work); cite GISTEMP Team and Lenssen et al.",
        charts=(
            (
                Series(gistemp.SERIES_MONTHLY, "Monthly anomaly", gistemp.UNIT),
                Series(gistemp.SERIES_ANNUAL_JD, "Annual mean (January to December)", gistemp.UNIT),
            ),
        ),
    ),
    "nsidc": Dataset(
        id="nsidc",
        host="noaadata.apps.nsidc.org",
        agency=nsidc.AGENCY,
        params=nsidc.REGIONS,
        default_param="N",
        source_page="https://nsidc.org/data/g02135",
        documented_as_of=nsidc.NSIDC_AS_OF,
        licence="NSIDC Sea Ice Index G02135 v3; cite Fetterer et al., NSIDC.",
        charts=((Series(nsidc.SERIES_DAILY_EXTENT, "Daily sea ice extent", nsidc.UNIT),),),
    ),
    "oni": Dataset(
        id="oni",
        host="www.cpc.ncep.noaa.gov",
        agency=oni.AGENCY,
        params=None,
        default_param=None,
        source_page="https://origin.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/ONI_v5.php",
        documented_as_of=oni.ONI_AS_OF,
        licence="NOAA Climate Prediction Center, public domain (US government work).",
        charts=((Series(oni.SERIES_ANOM, "Oceanic Niño Index (three-month anomaly)", "degC"),),),
    ),
    "usgs": Dataset(
        id="usgs",
        host="earthquake.usgs.gov",
        agency=usgs_quakes.AGENCY,
        params=None,
        default_param=None,
        source_page="https://earthquake.usgs.gov/earthquakes/search/",
        documented_as_of=usgs_quakes.USGS_QUAKES_AS_OF,
        licence="USGS ComCat, public domain (US government work).",
        charts=_usgs_series(),
    ),
    "owid": Dataset(
        id="owid",
        host="raw.githubusercontent.com",
        agency=owid_climate.AGENCY,
        params=tuple(owid_climate.CATALOG),
        default_param="co2",
        source_page="https://github.com/owid",
        documented_as_of=owid_climate.OWID_CLIMATE_AS_OF,
        licence="Our World in Data, CC BY 4.0; each column keeps its original producer's terms.",
        charts=(),  # one column at a time, picked on the tab (see owid_series)
    ),
    "ghcnd": Dataset(
        id="ghcnd",
        host="www.ncei.noaa.gov",
        agency=ghcnd.AGENCY,
        params=(),
        default_param=None,
        source_page="https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily",
        documented_as_of=ghcnd.GHCND_AS_OF,
        licence="NOAA NCEI GHCN-Daily, public domain (US government work); cite Menne et al.",
        charts=(
            (
                Series(ghcnd.SERIES_PREFIX + "TMAX", "Daily maximum temperature", "degC"),
                Series(ghcnd.SERIES_PREFIX + "TMIN", "Daily minimum temperature", "degC"),
            ),
            (Series(ghcnd.SERIES_PREFIX + "PRCP", "Daily precipitation", "mm"),),
            (
                Series(ghcnd.SERIES_PREFIX + "SNOW", "Daily snowfall", "mm"),
                Series(ghcnd.SERIES_PREFIX + "SNWD", "Snow depth", "mm"),
            ),
        ),
    ),
}


def owid_series(param: str) -> tuple[tuple[Series, ...], ...]:
    columns: dict[str, str] = owid_climate.CATALOG[param]["columns"]  # type: ignore[assignment]
    return tuple((Series(f"{param}.{col}", col, unit),) for col, unit in columns.items())


def charts_for(dataset: str, param: str | None) -> tuple[tuple[Series, ...], ...]:
    if dataset == "owid" and param:
        return owid_series(param)
    return DATASETS[dataset].charts


def series_ids_for(dataset: str, param: str | None) -> list[str]:
    return [s.series_id for chart in charts_for(dataset, param) for s in chart]


def valid_param(dataset: str, param: str | None) -> str | None:
    """The normalised param, or ValueError. A GHCN station id is checked BEFORE any request."""
    if dataset not in DATASETS:
        raise ValueError(f"unknown climate dataset: {dataset!r}")
    ds = DATASETS[dataset]
    if ds.params is None:
        return None
    p = (param or ds.default_param or "").strip()
    if dataset == "ghcnd":
        p = p.upper()
        if not ghcnd.valid_station_id(p):
            raise ValueError("a GHCN station id is 11 characters: two letters, then nine letters or digits (e.g. USW00094728)")
        return p
    if p not in ds.params:
        raise ValueError(f"{dataset}: param must be one of {list(ds.params)}")
    return p


def area_for(dataset: str, param: str | None) -> str | None:
    """The ``ref_area`` a unit's figures are stored under, or None when it varies (OWID)."""
    if dataset in ("gistemp", "nsidc", "ghcnd"):
        return param
    if dataset == "oni":
        return oni.REF_AREA
    if dataset == "usgs":
        return usgs_quakes.REF_AREA
    return None


def record_key(dataset: str, param: str | None) -> str:
    return f"{RECORD_PREFIX}{dataset}.{param or '-'}"


# --------------------------------------------------------------------------- #
# Fetch (the fetchers egress; this only dispatches)
# --------------------------------------------------------------------------- #
def _current_month(now: datetime | None = None) -> str:
    n = now or datetime.now(UTC)
    return f"{n.year:04d}-{n.month:02d}"


#: CPC's ONI header, token by token (``src.stats.oni`` documents the published shape).
_ONI_HEADER = ("SEAS", "YR", "TOTAL", "ANOM")


def _oni_header(refusal: dict) -> bool:
    """Is this refusal CPC's documented header line, and nothing else?"""
    return tuple(str(refusal.get("text") or "").upper().split()) == _ONI_HEADER


def run_fetch(dataset: str, param: str | None, *, fetchers: Any = None) -> tuple[list[StatFigure], dict, list[str]]:
    """Fetch one unit through its guarded fetcher. Returns (figures, diagnostics, requested URLs).

    ``fetchers`` defaults to ``src.stats.fetch``; tests pass a stand-in. Every fetcher refuses
    under airplane mode before any request (``RuntimeError(NETWORK_REFUSED)``).
    """
    if fetchers is None:
        from src.stats import fetch as fetchers
    p = valid_param(dataset, param)
    if dataset == "gistemp":
        parsed = fetchers.fetch_gistemp(p)
        return parsed.figures, parsed.summary(), [fetchers.gistemp_url(p)]
    if dataset == "nsidc":
        parsed = fetchers.fetch_nsidc(p)
        diag = parsed.summary()
        gaps = diag.pop("coverage_gaps", {}) or {}
        diag["coverage_gap_days"] = len(gaps)
        diag["coverage_gap_sample"] = dict(sorted(gaps.items())[-SAMPLE_KEPT:])
        return parsed.figures, diag, [fetchers.nsidc_url(p)]
    if dataset == "oni":
        parsed = fetchers.fetch_oni()
        # The parser refuses CPC's own header line on purpose (it is not a data row, and
        # ``tests/test_oni_parser.py`` pins that). It is the documented layout, though, so the
        # Climate tab must not report it as "a line not matching the documented layout": every
        # real fetch would then claim one refusal that never happened (found by the 0.6 row A walk).
        refused = [r for r in parsed.refused if not _oni_header(r)]
        diag = {
            "rows_read": parsed.rows_read,
            "figures": len(parsed.figures),
            "refused_total": len(refused),
            "refused_sample": refused[:SAMPLE_KEPT],
            "header_lines": len(parsed.refused) - len(refused),
        }
        return parsed.figures, diag, [fetchers.ONI_URL]
    if dataset == "usgs":
        end = _current_month()
        parsed = fetchers.fetch_usgs_quakes(USGS_START_MONTH, end, USGS_MIN_MAGNITUDE)
        urls = [
            fetchers.usgs_quakes_count_url(USGS_START_MONTH, end, USGS_MIN_MAGNITUDE),
            fetchers.usgs_quakes_query_url(USGS_START_MONTH, end, USGS_MIN_MAGNITUDE),
        ]
        return parsed.figures, parsed.summary(), urls
    if dataset == "owid":
        parsed = fetchers.fetch_owid_dataset(p)
        return parsed.figures, parsed.summary(), [fetchers.owid_dataset_url(p)]
    if dataset == "ghcnd":
        parsed = fetchers.fetch_ghcnd_station(p)
        return parsed.figures, parsed.summary(), [fetchers.ghcnd_url(p)]
    raise ValueError(f"unknown climate dataset: {dataset!r}")  # pragma: no cover - valid_param refused it


# --------------------------------------------------------------------------- #
# Store (R662: new or revised observations only)
# --------------------------------------------------------------------------- #
_Key = tuple[str, str, str]


def _latest_stored(session: Session, agency: str, series: set[str], areas: set[str] | None) -> dict[_Key, tuple]:
    """The latest stored vintage per (series, area, period) for these series and areas (``None``: every area)."""
    latest: dict[_Key, tuple] = {}
    if not series or (areas is not None and not areas):
        return latest
    cols = (
        StatFigureRow.series_id, StatFigureRow.ref_area, StatFigureRow.time_period, StatFigureRow.value,
        StatFigureRow.unit, StatFigureRow.adjustment, StatFigureRow.base_year, StatFigureRow.extracted_at,
    )
    q = select(*cols).where(
        StatFigureRow.agency == agency,
        StatFigureRow.series_id.in_(sorted(series)),
    )
    if areas is not None:
        q = q.where(StatFigureRow.ref_area.in_(sorted(areas)))
    for row in session.execute(q):
        key = (row[0], row[1], row[2])
        prev = latest.get(key)
        if prev is None or row[7] > prev[4]:
            latest[key] = (row[3], row[4], row[5], row[6], row[7])
    return latest


def store_new_or_revised(session: Session, figures: Iterable[StatFigure], *, all_areas: bool = False) -> dict:
    """Store only figures that are new, or differ from the latest stored vintage (R662).

    Returns ``{new, revised, unchanged, gaps, withdrawn, withdrawn_sample}``: ``withdrawn``
    counts stored (series, area, period) keys of the SAME series that this fetch no longer
    carries; they are kept (never deleted) and named so the surface can say so. With
    ``all_areas`` (the fetched file is the whole series, every area in it) an area the source
    dropped entirely counts too; without it only the areas this fetch carries are compared (a
    file that covers one area, such as one GHCN station). The caller owns the transaction.
    """
    figs = list(figures)
    by_agency: dict[str, list[StatFigure]] = {}
    for f in figs:
        by_agency.setdefault(f.agency, []).append(f)
    new = revised = unchanged = gaps = repeated = 0
    withdrawn: list[str] = []
    rows: list[dict] = []
    for agency, group in by_agency.items():
        latest = _latest_stored(session, agency, {f.series_id for f in group},
                                None if all_areas else {f.ref_area for f in group})
        seen: set[_Key] = set()
        for f in group:
            key = (f.series_id, f.ref_area, f.time_period)
            if key in seen:
                # The same period twice in ONE file: the first is kept, the repeat is counted.
                # Storing both would break the vintage key and roll the whole fetch back.
                repeated += 1
                continue
            seen.add(key)
            if f.value is None:
                gaps += 1
            prev = latest.get(key)
            if prev is not None and (prev[0], prev[1], prev[2], prev[3]) == (f.value, f.unit, f.adjustment, f.base_year):
                unchanged += 1
                continue
            if prev is None:
                new += 1
            else:
                revised += 1
            rows.append(
                {
                    "agency": f.agency, "series_id": f.series_id, "ref_area": f.ref_area,
                    "time_period": f.time_period, "value": f.value, "unit": f.unit,
                    "methodology_ref": f.methodology_ref, "adjustment": f.adjustment,
                    "base_year": f.base_year, "extracted_at": f.extracted_at,
                }
            )
        withdrawn.extend(f"{k[0]} {k[1]} {k[2]}" for k in latest if k not in seen)
    for i in range(0, len(rows), _INSERT_CHUNK):
        session.execute(insert(StatFigureRow), rows[i : i + _INSERT_CHUNK])
    withdrawn.sort()
    return {
        "new": new,
        "revised": revised,
        "unchanged": unchanged,
        "gaps": gaps,
        "repeated": repeated,
        "withdrawn": len(withdrawn),
        "withdrawn_sample": withdrawn[:SAMPLE_KEPT],
    }


def save_record(session: Session, dataset: str, param: str | None, record: dict) -> None:
    """Write the fetch record in the caller's transaction (atomic with the figures)."""
    key = record_key(dataset, param)
    row = session.get(AppState, key)
    blob = json.dumps(record, sort_keys=True, default=str)
    if row is None:
        session.add(AppState(key=key, value=blob, updated_at=datetime.now(UTC)))
    else:
        row.value = blob
        row.updated_at = datetime.now(UTC)


def load_record(session: Session, dataset: str, param: str | None) -> dict | None:
    row = session.get(AppState, record_key(dataset, param))
    if row is None:
        return None
    try:
        out = json.loads(row.value)
    except ValueError:
        return None
    return out if isinstance(out, dict) else None


#: Why a climate fetch did not store anything (row 265, 0.6 gate row A): a fixed token each, so the record of the operator's
#: real-host run can say which datasets failed and how, and never holds the exception's own text (an address, a host path,
#: a station or a server's words: R734/R736). ``kill_switch`` is the person's own airplane mode, named as such (#14e).
FAILURE_REASONS = (
    "kill_switch",        # airplane mode / the kill switch refused before or during the request
    "robots",             # the host's robots.txt disallows the address
    "robots_unreadable",  # the host's robots.txt could not be read, so the fetch was refused (fail closed)
    "redirect_refused",   # the fetcher refused the address or a redirect hop (off the dataset's site, or not public)
    "transport_stopped",  # the network mode (protected mode, proxy) changed during the fetch, so it stopped (R772)
    "too_large",          # the answer was larger than the table's own shape allows
    "http_403", "http_404", "http_429", "http_4xx", "http_5xx",
    "timeout",            # the host did not answer in time
    "connect",            # the connection could not be made (DNS, refused, reset)
    "unreadable_answer",  # an answer came, but not the documented table
    "other",              # anything not recognised above (the total stays honest)
)


def _chain(exc: BaseException):
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        yield cur
        cur = cur.__cause__ or cur.__context__


def _class_names(exc: BaseException) -> set[str]:
    """Every class ``exc`` is an instance of, by module and name: requests' exceptions are recognised without importing an HTTP
    client into this module (the socket-importer ratchet, test_network_consent.py)."""
    return {f"{c.__module__}.{c.__qualname__}" for c in type(exc).__mro__}


def failure_reason(exc: BaseException) -> str:
    """The :data:`FAILURE_REASONS` token for a failed climate fetch. Reads the exception's TYPE and status code, and its text only to
    recognise our own kill-switch sentences (never a phrase a server wrote): nothing of the text is kept."""
    from src.ingest import BlockedTarget, RobotsDisallowed, RobotsUnavailable
    from src.ingest.airplane import AirplaneModeError
    from src.ingest.fetch_verdict import NETWORK_REFUSED, is_kill_switch_refusal
    from src.safety.fetcher import ConnectTargetRefused, RedirectRefused
    from src.safety.transport_watch import TransportStopped
    from src.stats.fetch import BodyTooLarge

    for e in _chain(exc):
        text = str(e)
        if isinstance(e, AirplaneModeError) or text.startswith(NETWORK_REFUSED) or is_kill_switch_refusal(text):
            return "kill_switch"
    for e in _chain(exc):
        if isinstance(e, RobotsDisallowed):
            return "robots"
        if isinstance(e, RobotsUnavailable):
            return "robots_unreadable"
        if isinstance(e, (RedirectRefused, BlockedTarget, ConnectTargetRefused)):
            return "redirect_refused"
        if isinstance(e, TransportStopped):
            return "transport_stopped"
        if isinstance(e, BodyTooLarge):
            return "too_large"
        names = _class_names(e)
        if "requests.exceptions.HTTPError" in names:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (403, 404, 429):
                return f"http_{code}"
            if isinstance(code, int) and 400 <= code < 500:
                return "http_4xx"
            if isinstance(code, int) and 500 <= code < 600:
                return "http_5xx"
            return "other"
        if "requests.exceptions.Timeout" in names:
            return "timeout"
        if "requests.exceptions.ConnectionError" in names or isinstance(e, ConnectionError):
            return "connect"
    if isinstance(exc, ValueError):
        return "unreadable_answer"
    return "other"


def record_failure(session: Session, dataset: str, param: str | None, reason: str) -> None:
    """Write down that a fetch of one unit failed, in that unit's own fetch record (row 265, 0.6 gate row A).

    The record is the one :func:`fetch_and_store` keeps per unit in the encrypted library (:func:`save_record`), so nothing
    new is stored beside it: the failure is one more field, ``last_failure`` = its time and one :data:`FAILURE_REASONS`
    token, never the exception's text. The unit's last successful fetch stays as it was (the tab still shows it); the next
    successful fetch writes a fresh record without the field, so ``last_failure`` present means the latest outcome failed."""
    if dataset not in DATASETS:
        return
    rec = load_record(session, dataset, param) or {}
    rec["last_failure"] = {"failed_at": datetime.now(UTC).isoformat(), "reason": reason if reason in FAILURE_REASONS else "other"}
    save_record(session, dataset, param, rec)


def _sum(values: Iterable[Any]) -> int | None:
    """The sum of the counts given, or None when not one of them is a count (never a 0 for 'not recorded')."""
    ints = [v for v in values if isinstance(v, int) and not isinstance(v, bool) and v >= 0]
    return sum(ints) if ints else None


def fetch_outcomes(session: Session) -> dict:
    """What the fetches on this machine came to, per DATASET, read from the per-unit fetch records (row 265).

    Counts, dates, the publisher's host and reason tokens only. No unit is named: a GHCN station says where someone looks,
    so stations are a count and their figures a sum (and the fixed units are counted the same way, the stricter reading of
    "no unit in the record"). A dataset no unit of which was fetched says ``not_fetched_yet``. Never an address or a path."""
    held: dict[str, list[dict]] = {}
    for key, value in session.execute(select(AppState.key, AppState.value).where(AppState.key.startswith(RECORD_PREFIX))):
        name = str(key)[len(RECORD_PREFIX):].partition(".")[0]
        if name not in DATASETS:
            continue
        try:
            rec = json.loads(value)
        except (TypeError, ValueError):
            continue
        if isinstance(rec, dict):
            held.setdefault(name, []).append(rec)
    out: dict[str, dict] = {}
    for name, ds in sorted(DATASETS.items()):
        recs = held.get(name, [])
        fetched = [r for r in recs if isinstance(r.get("fetched_at"), str)]
        failed = [r["last_failure"] for r in recs if isinstance(r.get("last_failure"), dict)]
        reasons: dict[str, int] = {}
        for f in failed:
            tok = f.get("reason") if f.get("reason") in FAILURE_REASONS else "other"
            reasons[tok] = reasons.get(tok, 0) + 1
        offered = None if ds.params == () else (1 if ds.params is None else len(ds.params))
        stored = [stored_summary(session, name, r.get("param") if isinstance(r.get("param"), str) else None)["stored_rows"]
                  for r in fetched]
        tallies: list[dict] = [t if isinstance(t := r.get("tally"), dict) else {} for r in fetched]
        out[name] = {
            "host": ds.host,
            "state": "fetched" if fetched else ("failed" if failed else "not_fetched_yet"),
            "unit_kind": "station" if ds.params == () else "unit",
            "units_offered": offered,
            "units_fetched": len(fetched),
            "units_last_failed": len(failed),
            "units_not_fetched_yet": None if offered is None else max(offered - len(fetched), 0),
            "last_fetched_at": max((r["fetched_at"] for r in fetched), default=None),
            "last_failed_at": max((str(f.get("failed_at")) for f in failed if f.get("failed_at")), default=None),
            "figures": _sum(r.get("figures") for r in fetched),
            "new": _sum(t.get("new") for t in tallies),
            "revised": _sum(t.get("revised") for t in tallies),
            "stored_rows": _sum(stored),
            "reasons": dict(sorted(reasons.items())),
        }
    return out


def fetch_and_store(
    session: Session, dataset: str, param: str | None, *, fetchers: Any = None,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Fetch one unit, store new or revised observations, record the fetch. Returns the record."""
    p = valid_param(dataset, param)
    if progress:
        progress("fetching")
    figures, diagnostics, urls = run_fetch(dataset, p, fetchers=fetchers)
    if progress:
        progress("storing")
    # Only an OWID column is one file holding every area of its series, so only there is an area the file
    # no longer carries withdrawn by the source (R662). GISTEMP and NSIDC fetch one region per file under a
    # shared series id, and a GHCN fetch is one station: each compares the areas it carries (ONI and USGS
    # have a single area either way).
    tally = store_new_or_revised(session, figures, all_areas=dataset == "owid")
    stamps = sorted({f.extracted_at for f in figures})
    record = {
        "dataset": dataset,
        "param": p,
        "fetched_at": stamps[-1] if stamps else datetime.now(UTC).isoformat(),
        "requested_urls": urls,
        "figures": len(figures),
        "tally": tally,
        "diagnostics": diagnostics,
    }
    save_record(session, dataset, p, record)
    return record


# --------------------------------------------------------------------------- #
# Read (local only)
# --------------------------------------------------------------------------- #
def _place(dataset: str, period: str) -> str | None:
    """A period label -> the ISO date the chart puts it at (the MIDDLE of its period), or None."""
    s = period.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    if re.fullmatch(r"\d{4}-\d{2}", s):
        return s + "-15"
    if re.fullmatch(r"\d{4}", s):
        return s + "-07-01"
    m = re.fullmatch(r"(\d{4})-([A-Z]{3})", s)
    if m and dataset == "oni":
        try:
            y, mo = oni.season_months(m.group(2), int(m.group(1)))[1]
        except ValueError:
            return None
        return f"{y:04d}-{mo:02d}-15"
    return None


def read_series(session: Session, dataset: str, series_id: str, area: str) -> dict:
    """The latest stored vintage per period of ONE (series, area), placed for the chart."""
    ds = DATASETS[dataset]
    q = select(
        StatFigureRow.time_period, StatFigureRow.value, StatFigureRow.unit, StatFigureRow.extracted_at,
    ).where(
        StatFigureRow.agency == ds.agency,
        StatFigureRow.series_id == series_id,
        StatFigureRow.ref_area == area,
    )
    latest: dict[str, tuple] = {}
    revised_periods: set[str] = set()
    for period, value, unit, stamp in session.execute(q):
        prev = latest.get(period)
        if prev is not None:
            revised_periods.add(period)
        if prev is None or stamp > prev[2]:
            latest[period] = (value, unit, stamp)
    points: list[dict] = []
    unplaced: list[str] = []
    units: set[str] = set()
    for period, (value, unit, _stamp) in latest.items():
        at = _place(dataset, period)
        if at is None:
            unplaced.append(period)
            continue
        if unit:
            units.add(unit)
        points.append({"t": at, "v": value, "p": period})
    points.sort(key=lambda pt: pt["t"])
    stamps = sorted({v[2] for v in latest.values()})
    return {
        "dataset": dataset,
        "series_id": series_id,
        "area": area,
        "points": points,
        "n": sum(1 for pt in points if pt["v"] is not None),
        "gaps": sum(1 for pt in points if pt["v"] is None),
        "first": points[0]["p"] if points else None,
        "last": points[-1]["p"] if points else None,
        "units": sorted(units),
        "unplaced": sorted(unplaced),
        "periods_with_several_vintages": len(revised_periods),
        "oldest_vintage_shown": stamps[0] if stamps else None,
        "newest_vintage_shown": stamps[-1] if stamps else None,
    }


def stored_summary(session: Session, dataset: str, param: str | None) -> dict:
    """Counts and dates of what this install holds for one unit (no figure values)."""
    ds = DATASETS[dataset]
    q = select(
        func.count(StatFigureRow.id), func.min(StatFigureRow.extracted_at), func.max(StatFigureRow.extracted_at),
        func.count(func.distinct(StatFigureRow.extracted_at)),
    ).where(StatFigureRow.agency == ds.agency)
    area = area_for(dataset, param)
    if area is not None:
        # Every series of the unit, charted or not (ONI's absolute SST, GISTEMP's D-N mean).
        q = q.where(StatFigureRow.ref_area == area)
    else:
        q = q.where(StatFigureRow.series_id.in_(series_ids_for(dataset, param)))
    rows, oldest, newest, vintages = session.execute(q).one()
    return {
        "stored_rows": int(rows or 0),
        "first_vintage": oldest,
        "newest_vintage": newest,
        "vintages": int(vintages or 0),
    }


def areas(session: Session, dataset: str, param: str | None) -> list[dict]:
    """The areas (OWID countries and aggregates) or stations (GHCN) stored for a unit."""
    ds = DATASETS[dataset]
    if dataset == "ghcnd":
        sids = [s.series_id for chart in ds.charts for s in chart]
    else:
        sids = series_ids_for(dataset, param)
    q = (
        select(StatFigureRow.ref_area, func.count(StatFigureRow.id))
        .where(StatFigureRow.agency == ds.agency, StatFigureRow.series_id.in_(sids))
        .group_by(StatFigureRow.ref_area)
        .order_by(StatFigureRow.ref_area)
    )
    out = []
    for code, n in session.execute(q):
        name = None
        if dataset == "owid":
            from src.catalog.countries import country_display_name

            name = country_display_name(code) if len(code) == 3 and code.isupper() else code
        out.append({"code": code, "name": name or code, "stored_rows": int(n)})
    return out


def unit_status(session: Session, dataset: str, param: str | None) -> dict:
    ds = DATASETS[dataset]
    return {
        "dataset": dataset,
        "param": param,
        "agency": ds.agency,
        "area": area_for(dataset, param),
        "source_page": ds.source_page,
        "documented_as_of": ds.documented_as_of,
        "licence": ds.licence,
        "host": ds.host,
        "charts": [
            [{"series_id": s.series_id, "label": s.label, "unit": s.unit} for s in chart]
            for chart in charts_for(dataset, param)
        ],
        "stored": stored_summary(session, dataset, param),
        "last_fetch": load_record(session, dataset, param),
    }
