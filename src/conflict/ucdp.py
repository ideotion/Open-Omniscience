"""UCDP's georeferenced event data (GED and the monthly Candidate release), parsed in pure Python
(brief S08-01, slice S1; R747).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

ONE ROW SHAPE, BOTH TRANSPORTS. The Uppsala Conflict Data Program publishes GED and Candidate as
versioned download files (CSV), and its API answers with pages whose ``Result`` rows carry the same
field names. R747 builds on the keyless versioned files; the API is used only if a probe on a
networked machine shows it needs no token. So :func:`parse_ged_rows` reads rows whatever carried
them, :func:`parse_ged_csv` reads a download file and :func:`parse_ged_page` an API page. Nothing
here touches a socket, a file path or a database: what is kept, and where, is the store's business.

THE CALLER NAMES THE DATASET AND ITS VERSION, the parser never guesses them from the rows. Each
version is a vintage (a published, numbered release), and the dataset decides the class: GED events
are UCDP's ``final`` coding, Candidate events are ``preliminary`` (UCDP's own words: candidate events
are released before full review and may change or be removed). The two are classes, never blended.

FATALITIES ARE A RANGE, NEVER ONE NUMBER (V1 §4.4, binding). UCDP publishes a ``low``, a ``best``
and a ``high`` estimate; :class:`Fatalities` carries the three and nothing that collapses them. A
missing or unreadable bound stays ``None``, a gap, never a zero (a zero is a claim: "nobody died").
A range whose bounds are out of order (``low > best`` or ``best > high``) is kept as published and
FLAGGED, never re-ordered or repaired: the producer's numbers are the record.

WHAT ELSE IT REFUSES TO INVENT. An event without coordinates is still an event: it has no map point
and is counted. A coordinate outside the globe is dropped and counted, never clamped. A date that is
not a real calendar date has no ISO date and keeps its raw text. A type of violence other than UCDP's
three keeps its raw code and has no kind. A row with no readable event id cannot be identified, so it
is SKIPPED AND COUNTED in the tally, never given a made-up id; a second row with an id already read
in the same parse is skipped and counted too.

AN EVENT IS A REPORT CODED BY A PROJECT WITH STATED RULES, not ground truth: UCDP is itself a
source with a method and a stance, and the coverage of a conflict depends on what was reported.
:data:`METHOD` and :data:`CAVEAT` say so, for whichever surface shows these rows.
"""

from __future__ import annotations

import calendar
import csv
import io
import json
import math
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import IO, Any

#: The two datasets, and the class each one's events carry.
DATASETS = {"ged": "final", "candidate": "preliminary"}

#: UCDP's three types of organised violence, by their published code.
VIOLENCE_KINDS = {1: "state_based", 2: "non_state", 3: "one_sided"}

#: The death counts by side that UCDP publishes beside the range.
DEATH_FIELDS = (("a", "deaths_a"), ("b", "deaths_b"), ("civilians", "deaths_civilians"), ("unknown", "deaths_unknown"))

#: Longest text kept from one field. UCDP's longest fields (source headlines) are far shorter.
MAX_TEXT = 10_000

METHOD = (
    "Events from the Uppsala Conflict Data Program's georeferenced event dataset: each is an "
    "incident of organised violence that UCDP coded from news and other reports, under its "
    "published rules, with a low, best and high estimate of deaths. GED is UCDP's final coding; "
    "Candidate events are preliminary and may change or be removed in a later release."
)

CAVEAT = (
    "These are reports coded by one project, not a full count: a conflict that is little reported "
    "has fewer events here. Deaths are a range, low to high, never one number."
)

_ASCII_INT = re.compile(r"[0-9]+")
_ISO_DAY = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})(?:$|[ T])")


class UcdpFormatError(ValueError):
    """The input is not a UCDP GED or Candidate file or page."""


@dataclass(frozen=True)
class Fatalities:
    """UCDP's low, best and high estimates of deaths, each ``None`` when the row gave none.

    There is deliberately no single-number accessor: the range is the figure."""

    low: int | None
    best: int | None
    high: int | None

    @property
    def complete(self) -> bool:
        """All three bounds were given."""
        return self.low is not None and self.best is not None and self.high is not None

    @property
    def inverted(self) -> bool:
        """The bounds that were given are out of order (kept as published, flagged here)."""
        given = [v for v in (self.low, self.best, self.high) if v is not None]
        return any(a > b for a, b in zip(given, given[1:], strict=False))


@dataclass(frozen=True)
class ConflictEvent:
    event_id: int
    dataset: str
    version: str
    status: str
    relid: str | None
    code_status: str | None
    violence_code: str | None
    violence_kind: str | None
    conflict_id: int | None
    conflict_name: str | None
    dyad_id: int | None
    dyad_name: str | None
    side_a: str | None
    side_b: str | None
    country: str | None
    country_gw: int | None
    region: str | None
    adm_1: str | None
    adm_2: str | None
    where_description: str | None
    where_prec: int | None
    event_clarity: int | None
    date_start: str | None
    date_end: str | None
    date_start_raw: str | None
    date_end_raw: str | None
    date_prec: int | None
    latitude: float | None
    longitude: float | None
    fatalities: Fatalities
    deaths_by_side: dict[str, int | None]
    number_of_sources: int | None
    source_original: str | None
    source_date: str | None


@dataclass
class ParseTally:
    """What one parse read, and what it could not read. Counts, never values."""

    rows: int = 0
    events: int = 0
    skipped_no_id: int = 0
    skipped_duplicate_id: int = 0
    no_coordinates: int = 0
    bad_coordinates: int = 0
    incomplete_ranges: int = 0
    inverted_ranges: int = 0
    unknown_violence_type: int = 0
    bad_dates: int = 0
    bad_numbers: int = 0
    seen_ids: set[int] = field(default_factory=set, repr=False)

    def as_dict(self) -> dict[str, int]:
        return {k: v for k, v in self.__dict__.items() if k != "seen_ids"}


@dataclass(frozen=True)
class PageInfo:
    """An API page's own paging facts, kept as given and never followed here."""

    total_count: int | None
    total_pages: int | None
    next_page_url: str | None


def _text(row: Mapping[str, Any], key: str) -> str | None:
    raw = row.get(key)
    if raw is None:
        return None
    out = str(raw).strip()
    if not out or out.upper() == "NULL":
        return None
    return out[:MAX_TEXT]


def _int(row: Mapping[str, Any], key: str, tally: ParseTally) -> int | None:
    """A whole number >= 0, or ``None`` for a gap. Text that is not one is counted."""
    raw = row.get(key)
    if isinstance(raw, bool):
        tally.bad_numbers += 1
        return None
    if isinstance(raw, int):
        if raw >= 0:
            return raw
        tally.bad_numbers += 1
        return None
    if isinstance(raw, float):
        if math.isfinite(raw) and raw >= 0 and raw.is_integer():
            return int(raw)
        tally.bad_numbers += 1
        return None
    s = _text(row, key)
    if s is None:
        return None
    if s.endswith(".0"):
        s = s[:-2]
    if _ASCII_INT.fullmatch(s) and len(s) <= 12:
        return int(s)
    tally.bad_numbers += 1
    return None


def _float(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        v = float(raw)
    else:
        s = str(raw).strip()
        if not s or s.upper() == "NULL":
            return None
        try:
            v = float(s)
        except ValueError:
            return math.nan
    return v if math.isfinite(v) else math.nan


def _coords(row: Mapping[str, Any], tally: ParseTally) -> tuple[float | None, float | None]:
    lat, lon = _float(row.get("latitude")), _float(row.get("longitude"))
    if lat is None and lon is None:
        tally.no_coordinates += 1
        return None, None
    if (
        lat is None or lon is None or math.isnan(lat) or math.isnan(lon)
        or not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0
    ):
        tally.bad_coordinates += 1
        return None, None
    return lat, lon


def _day(raw: str | None) -> str | None:
    if raw is None:
        return None
    m = _ISO_DAY.match(raw)
    if not m:
        return None
    y, mo, d = (int(g) for g in m.groups())
    if not 1 <= mo <= 12 or not 1 <= d <= calendar.monthrange(y, mo)[1] or y < 1:
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _event(row: Mapping[str, Any], dataset: str, version: str, tally: ParseTally) -> ConflictEvent | None:
    tally.rows += 1
    eid = _int(row, "id", tally)
    if eid is None or eid == 0:
        tally.skipped_no_id += 1
        return None
    if eid in tally.seen_ids:
        tally.skipped_duplicate_id += 1
        return None
    tally.seen_ids.add(eid)

    code = _text(row, "type_of_violence")
    kind = VIOLENCE_KINDS.get(int(code)) if code is not None and _ASCII_INT.fullmatch(code) else None
    if kind is None:
        tally.unknown_violence_type += 1

    start_raw, end_raw = _text(row, "date_start"), _text(row, "date_end")
    start, end = _day(start_raw), _day(end_raw)
    if (start_raw is not None and start is None) or (end_raw is not None and end is None):
        tally.bad_dates += 1

    lat, lon = _coords(row, tally)
    fat = Fatalities(_int(row, "low", tally), _int(row, "best", tally), _int(row, "high", tally))
    if not fat.complete:
        tally.incomplete_ranges += 1
    if fat.inverted:
        tally.inverted_ranges += 1

    tally.events += 1
    return ConflictEvent(
        event_id=eid,
        dataset=dataset,
        version=version,
        status=DATASETS[dataset],
        relid=_text(row, "relid"),
        code_status=_text(row, "code_status"),
        violence_code=code,
        violence_kind=kind,
        conflict_id=_int(row, "conflict_new_id", tally),
        conflict_name=_text(row, "conflict_name"),
        dyad_id=_int(row, "dyad_new_id", tally),
        dyad_name=_text(row, "dyad_name"),
        side_a=_text(row, "side_a"),
        side_b=_text(row, "side_b"),
        country=_text(row, "country"),
        country_gw=_int(row, "country_id", tally),
        region=_text(row, "region"),
        adm_1=_text(row, "adm_1"),
        adm_2=_text(row, "adm_2"),
        where_description=_text(row, "where_description"),
        where_prec=_int(row, "where_prec", tally),
        event_clarity=_int(row, "event_clarity", tally),
        date_start=start,
        date_end=end,
        date_start_raw=start_raw,
        date_end_raw=end_raw,
        date_prec=_int(row, "date_prec", tally),
        latitude=lat,
        longitude=lon,
        fatalities=fat,
        deaths_by_side={side: _int(row, key, tally) for side, key in DEATH_FIELDS},
        number_of_sources=_int(row, "number_of_sources", tally),
        source_original=_text(row, "source_original"),
        source_date=_text(row, "source_date"),
    )


def _check(dataset: str, version: str) -> tuple[str, str]:
    if dataset not in DATASETS:
        raise ValueError(f"unknown UCDP dataset {dataset!r}: expected one of {sorted(DATASETS)}")
    v = (version or "").strip()
    if not v:
        raise ValueError("a UCDP dataset version is required: each version is its own vintage")
    return dataset, v


def parse_ged_rows(
    rows: Iterable[Mapping[str, Any]], *, dataset: str, version: str, tally: ParseTally | None = None
) -> Iterator[ConflictEvent]:
    """The events in ``rows`` (mappings with UCDP's field names), in order."""
    dataset, version = _check(dataset, version)
    tally = tally if tally is not None else ParseTally()
    for row in rows:
        if not isinstance(row, Mapping):
            tally.rows += 1
            tally.skipped_no_id += 1
            continue
        ev = _event(row, dataset, version, tally)
        if ev is not None:
            yield ev


def parse_ged_csv(
    stream: IO[bytes], *, dataset: str, version: str, tally: ParseTally | None = None
) -> Iterator[ConflictEvent]:
    """The events in a GED or Candidate download file (UTF-8 CSV with a header row)."""
    dataset, version = _check(dataset, version)
    reader = csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig", newline=""))
    fields = reader.fieldnames or []
    if "id" not in fields:
        raise UcdpFormatError("not a UCDP GED or Candidate file: the header has no 'id' column")
    yield from parse_ged_rows(reader, dataset=dataset, version=version, tally=tally)


def parse_ged_page(
    data: bytes | str | Mapping[str, Any], *, dataset: str, version: str, tally: ParseTally | None = None
) -> tuple[list[ConflictEvent], PageInfo]:
    """The events in one API page, and the page's own paging facts (never followed here)."""
    dataset, version = _check(dataset, version)
    page = json.loads(data) if isinstance(data, (bytes, str)) else data
    if not isinstance(page, Mapping) or not isinstance(page.get("Result"), list):
        raise UcdpFormatError("not a UCDP API page: no 'Result' list")
    info = PageInfo(
        total_count=page.get("TotalCount") if isinstance(page.get("TotalCount"), int) else None,
        total_pages=page.get("TotalPages") if isinstance(page.get("TotalPages"), int) else None,
        next_page_url=page.get("NextPageUrl") if isinstance(page.get("NextPageUrl"), str) and page.get("NextPageUrl") else None,
    )
    return list(parse_ged_rows(page["Result"], dataset=dataset, version=version, tally=tally)), info
