"""The elections calendar at the coverage floor — per-country tier report and snapshot layering.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

S06-04 slice S1 / v0.6 plan row A2. ``elections.py`` owns the three date-confidence tiers and
``coverage_floor.py`` owns the aggregate "N of the floor are covered"; this module adds the two
things the acceptance line asks for ("each country's tier stated"):

* ``snapshot_to_events`` turns rows shaped like the Wikidata national-election snapshot
  (election QID · country · office · P585 date / P580-P582 range · official URL) into catalog
  entries. It is a PURE converter over rows it is handed: it fetches nothing, and the real
  roster waits on the operator's networked build. Every conversion is a refusal-first one:
  a day is carried only when the row states a day-precision date AND names an official
  source; a coarser or unsourced date is DEGRADED to a window and says why; a row with no
  usable date carries ``null`` and a reason, never a guess.
* ``country_tier_report`` states, for EVERY floor country, one of six states with the reason
  an absent value is absent. It is a list of facts, never a score.

Layering with the hand-curated ``world_events.yml`` entries is by SHADOWING, and every
shadowed snapshot row is returned with its reason rather than dropped silently.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from src.catalog.countries import config_country
from src.civic.elections import (
    PROJECTED,
    SCHEDULED,
    WINDOW,
    _iso_date,
    date_confidence,
    has_passed,
    is_election,
    missing_projection_fields,
    projection,
)

# Per-country states, most- to least-certain. `projected_passed` is a lead, not coverage.
STATE_SCHEDULED = "scheduled"
STATE_WINDOW = "window"
STATE_PROJECTED = "projected_upcoming"
STATE_PROJECTED_PASSED = "projected_passed"
STATE_PASSED = "passed"
STATE_DATELESS = "dateless"
STATE_MISSING = "missing"
STATES: tuple[str, ...] = (
    STATE_SCHEDULED,
    STATE_WINDOW,
    STATE_PROJECTED,
    STATE_PASSED,
    STATE_PROJECTED_PASSED,
    STATE_DATELESS,
    STATE_MISSING,
)

_PRECISIONS = ("day", "month", "year")

#: A Wikidata time value: an optional sign, the date, and an optional time part (``+2027-04-10T00:00:00Z``).
_WIKIDATA_TIME = re.compile(r"^\+?(\d{4}-\d{2}-\d{2})(?:T[0-9:.]+(?:Z|[+-]\d{2}:?\d{2})?)?$")


def _snapshot_date(value: object, precision: str = "") -> date | None:
    """A snapshot date, read the way Wikidata writes it, then through the shared ``_iso_date``.

    The sign and the time part are stripped (a Wikidata time is midnight UTC with a precision, so the
    time says nothing). Below day precision Wikidata writes the unknown parts as ``00``; those become
    the 1st of the period ONLY when the row's precision says so, which is how a coarser date is
    already stored here. A ``00`` under a day precision stays unreadable, never a guessed day.
    """
    if not isinstance(value, str):
        return _iso_date(value)
    m = _WIKIDATA_TIME.match(value.strip())
    if not m:
        return _iso_date(value)
    text = m.group(1)
    if precision == "year":
        text = text[:4] + "-01-01"  # only the year is read at this precision
    elif precision == "month" and text.endswith("-00"):
        text = text[:8] + "01"
    return _iso_date(text)


def _cc(value: object) -> str:
    """One comparable country form: lowercase alpha-2 through the config conversion layer, so the
    curated catalogue's alpha-3 (``FRA``) and a snapshot's alpha-2 (``fr``) meet; a value it cannot
    place is compared as written, lower-cased."""
    return str(config_country(value) or "").strip().lower()


def _inferred(event: dict[str, Any], why: str) -> dict[str, Any]:
    event["inferred"] = True
    event["inferred_reason"] = why
    return event


def snapshot_to_event(
    row: dict[str, Any], today: date | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    """One snapshot row -> ``(event, None)`` or ``(None, reason it was refused)``.

    Row keys: ``country`` (ISO alpha-2), ``office``, ``qid``, ``point_in_time`` (ISO date),
    ``precision`` (day|month|year), ``start``/``end`` (ISO range), ``official_url``.
    """
    today = today or date.today()
    cc = str(row.get("country") or "").strip().upper()
    if len(cc) != 2 or not cc.isalpha():
        return None, "no ISO alpha-2 country"
    office = str(row.get("office") or "").strip()
    qid = str(row.get("qid") or "").strip()
    if not office or not qid:
        return None, "row names no office or election id"
    url = str(row.get("official_url") or "").strip()

    precision = str(row.get("precision") or "").strip().lower()
    point = _snapshot_date(row.get("point_in_time"), precision)
    start, end = _snapshot_date(row.get("start")), _snapshot_date(row.get("end"))

    event: dict[str, Any] = {
        "title": f"{cc} — {office}",
        "calendar": "elections",
        "category": "civic",
        "country": cc,
        "office": office,
        "source_qid": qid,
        "official_url": url or None,
        "confirmed": False,
        "month": None,
        "day": None,
        "tags": ["elections", "snapshot"],
    }

    if point is None and start is not None and end is not None and start <= end:
        if end < today:
            return None, "past election (the agenda is forward-looking)"
        # A range is a window, never a schedule; a month is stated only when both ends agree.
        if (start.year, start.month) == (end.year, end.month):
            event["month"], event["window_year"] = start.month, start.year
        else:
            event["window_year"] = start.year if start.year == end.year else None
            if event["window_year"] is None:
                return _undated(event, "range spans years; no single window stated")
        event["date_basis"] = f"range {start.isoformat()}..{end.isoformat()}"
        return _inferred(event, "window read from a P580-P582 range"), None

    if point is None:
        return _undated(event, "row states no usable date")
    # A month- or year-precision date is stored as the 1st of the period, so compare the
    # period, not the day: the current month/year has not passed.
    if precision == "year":
        is_past = point.year < today.year
    elif precision == "month":
        is_past = (point.year, point.month) < (today.year, today.month)
    else:
        is_past = point < today
    if is_past:
        return None, "past election (the agenda is forward-looking)"

    if precision == "day" and url:
        event.update(month=point.month, day=point.day, confirmed=True, window_year=point.year)
        event["date_basis"] = f"P585 {point.isoformat()} (day precision), source {url}"
        return event, None
    if precision == "day":
        # A day with no authority behind it is not a schedule: degrade, and say so.
        event.update(month=point.month, window_year=point.year)
        event["date_basis"] = (
            f"P585 {point.year}-{point.month:02d} (day dropped: NO official source)"
        )
        return _inferred(event, "day degraded to a window: no official source named"), None
    if precision == "month":
        event.update(month=point.month, window_year=point.year)
        event["date_basis"] = f"P585 month {point.year}-{point.month:02d}"
        return event, None
    if precision == "year":
        event["window_year"] = point.year
        event["date_basis"] = f"P585 year {point.year}"
        return event, None
    return _undated(event, f"unknown date precision {precision!r}")


def _undated(event: dict[str, Any], reason: str) -> tuple[dict[str, Any], None]:
    event["date_reason"] = reason  # null date + the reason it is null
    return event, None


def snapshot_to_events(
    rows: list[dict[str, Any]], today: date | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """All rows -> ``(events, refused)``; ``refused`` carries ``{qid, reason}`` for each."""
    events, refused = [], []
    for row in rows:
        ev, why = snapshot_to_event(row, today)
        if ev is None:
            refused.append({"qid": str(row.get("qid") or ""), "reason": why or "refused"})
        else:
            events.append(ev)
    return events, refused


def _curated_year(entry: dict[str, Any], today: date) -> int | None:
    """The year a curated entry STATES (``window_year``) or projects from a sourced rule; never a
    year read off its title (``elections.py`` refuses that: "due by 2029" is not "in 2029")."""
    stated = entry.get("window_year")
    if isinstance(stated, int) and not isinstance(stated, bool):
        return stated
    if date_confidence(entry) == PROJECTED:
        proj = projection(entry, today)
        return proj["year"] if proj else None
    return None


def _same_election(curated: dict[str, Any], ev: dict[str, Any], today: date) -> str | None:
    """Why ``curated`` covers snapshot entry ``ev``, or None when nothing shows it is the same election.

    Same country is never enough on its own. The curated entry must carry a date tier, the offices
    must agree when the curated entry names one, and the dates must overlap: the same year when both
    years are known (and the same month when both state one), or, for a curated entry with no year,
    the same stated month. Anything less keeps both entries visible rather than hiding one.
    """
    if date_confidence(curated) is None:
        return None
    office = str(curated.get("office") or "").strip()
    if office and office.casefold() != str(ev.get("office") or "").strip().casefold():
        return None
    ey, em = ev.get("window_year"), ev.get("month")
    if ey is None:
        return None  # an undated snapshot row is kept with its own reason
    cy, cm = _curated_year(curated, today), curated.get("month")
    if cy is not None:
        if cy != ey or (cm is not None and em is not None and cm != em):
            return None
        basis = f"year {ey}" + (f", month {em}" if cm is not None and em is not None else "")
    elif cm is not None and em is not None and cm == em:
        basis = f"month {em}"
    else:
        return None
    return f"same country, {'office ' + office if office else 'no office named'}, {basis}"


def layer(
    curated: list[dict[str, Any]], snapshot_events: list[dict[str, Any]], today: date | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Curated entries win; a snapshot entry a curated one demonstrably covers is SHADOWED.

    "Covers" is :func:`_same_election`: same country (alpha-2 or alpha-3 on either side), a dated
    curated entry, agreeing offices and overlapping dates. A curated entry with no office no longer
    shadows every row of its country. Returns ``(entries, shadowed)``; each shadowed row carries the
    reason, so nothing is dropped without a record.
    """
    today = today or date.today()
    cur = [e for e in curated if is_election(e)]
    shadowed: list[dict[str, str]] = []
    kept = []
    for ev in snapshot_events:
        cc = _cc(ev.get("country"))
        hit, why = None, None
        for c in cur:
            if _cc(c.get("country")) != cc:
                continue
            why = _same_election(c, ev, today)
            if why:
                hit = c
                break
        if hit is None:
            kept.append(ev)
        else:
            shadowed.append(
                {
                    "qid": str(ev.get("source_qid") or ""),
                    "country": cc.upper(),
                    "shadowed_by": str(hit.get("title") or ""),
                    "reason": str(why),
                }
            )
    return list(curated) + kept, shadowed


#: Where the networked run of ``scripts/generate_wikidata_elections.py`` writes its snapshot for
#: the app to read (``-o configs/elections_snapshot.json``). ABSENT until the operator runs it, and
#: the app says so rather than reading the absence as "no elections".
SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "configs" / "elections_snapshot.json"

_CATALOG_DEFAULTS: dict[str, Any] = {
    "region": None, "cadence": "once", "weekday": None, "week": None, "end_month": None, "end_day": None,
}


def load_snapshot(path: Path | None = None) -> tuple[dict[str, Any] | None, str]:
    """``(snapshot, state)``: state is ``absent``, ``unreadable`` (with nothing read) or ``present``.

    Local only. A file that is not the generator's shape (an object with a ``rows`` list and an
    ``as_of`` date) is ``unreadable``: never half-read, never guessed at."""
    p = path or SNAPSHOT_PATH
    if not p.is_file():
        return None, "absent"
    try:
        snap = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "unreadable"
    if (not isinstance(snap, dict) or not isinstance(snap.get("rows"), list)
            or _iso_date(str(snap.get("as_of") or "")) is None):
        return None, "unreadable"
    return snap, "present"


def _catalog_shape(ev: dict[str, Any]) -> dict[str, Any]:
    """A snapshot event in the curated catalogue's shape, so the agenda reads both alike.

    A snapshot election is ONE election, never an annual recurrence: a stated year bounds it
    (``origin_year`` = ``until_year``). The date's basis, or the reason it has none, is its note."""
    out = {**_CATALOG_DEFAULTS, **ev}
    out["country"] = config_country(ev.get("country"), upper=True) or str(ev.get("country") or "").upper()
    year = ev.get("window_year")
    out["origin_year"] = out["until_year"] = year if isinstance(year, int) else None
    out["note"] = ev.get("date_basis") or ev.get("date_reason")
    return out


def with_snapshot(
    curated: list[dict[str, Any]], today: date | None = None, path: Path | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The curated entries LAYERED with the Wikidata snapshot when one is present.

    Returns ``(events, info)``. ``info`` states the snapshot's state and, when present, its
    ``as_of`` and the counts of rows added, shadowed by a curated entry and refused, so a reader
    can tell "no snapshot yet" from "the snapshot found nothing"."""
    snap, state = load_snapshot(path)
    if snap is None:
        return list(curated), {"state": state}
    evs, refused = snapshot_to_events(snap["rows"], today)
    merged, shadowed = layer(curated, [_catalog_shape(e) for e in evs], today)
    added = len(merged) - len(curated)
    return merged, {
        "state": state, "as_of": str(snap.get("as_of")), "rows": len(snap["rows"]),
        "added": added, "shadowed": len(shadowed), "refused": len(refused),
        "generator_refused": len(snap.get("refused") or []),
    }


def country_tier_report(
    events: list[dict[str, Any]], floor: set[str], today: date | None = None
) -> dict[str, Any]:
    """For every floor country: its state, best tier, entries, and why a value is absent."""
    today = today or date.today()
    per: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        if is_election(ev):
            per.setdefault(_cc(ev.get("country")), []).append(ev)

    rows = []
    for cc in sorted({_cc(c) for c in floor}):
        entries = []
        for ev in per.get(cc, []):
            tier = date_confidence(ev)
            proj = projection(ev, today) if tier == PROJECTED else None
            entries.append(
                {
                    "title": str(ev.get("title") or ""),
                    "tier": tier,
                    "passed": tier in (SCHEDULED, WINDOW) and has_passed(ev, today),
                    "projection_status": proj["status"] if proj else None,
                    "inferred": bool(ev.get("inferred")),
                    "reason": ev.get("date_reason") or ev.get("inferred_reason"),
                    "missing_fields": missing_projection_fields(ev) if tier is None else [],
                }
            )
        tiers = {e["tier"] for e in entries if not e["passed"]}
        stated_passed = any(e["passed"] for e in entries)
        live_proj = any(
            e["tier"] == PROJECTED and e["projection_status"] != "passed" for e in entries
        )
        if SCHEDULED in tiers:
            state, reason = STATE_SCHEDULED, None
        elif WINDOW in tiers:
            state, reason = STATE_WINDOW, None
        elif live_proj:
            state, reason = STATE_PROJECTED, None
        elif stated_passed:
            state, reason = STATE_PASSED, "every listed election has passed; the next one is not listed"
        elif PROJECTED in tiers:
            state, reason = STATE_PROJECTED_PASSED, "every projection has passed; status unknown"
        elif entries:
            state, reason = STATE_DATELESS, "entry states no date and no sourced recurrence rule"
        else:
            state, reason = STATE_MISSING, "no election entry for this country"
        rows.append(
            {
                "cc": cc,
                "state": state,
                "tier": next((t for t in (SCHEDULED, WINDOW, PROJECTED) if t in tiers), None),
                "reason": reason,
                "entries": entries,
            }
        )
    counts = {s: sum(1 for r in rows if r["state"] == s) for s in STATES}
    return {
        "floor_countries": len(rows),
        "counts": counts,
        "countries": rows,
        "method": (
            "Each floor country takes ONE state from its election entries in the shipped catalogue, "
            "first match wins: scheduled (an entry states an official date), window (a stated month "
            "or year), projected (a sourced recurrence rule projects a year not yet passed), "
            "passed (every stated date has gone by and the next election is not listed), "
            "projected · passed (every projection has passed), dateless (an entry with no date and "
            "no rule) or missing (no entry). The counts are plain tallies of these states."
        ),
        "caveat": (
            "States describe calendar ENTRIES, never a claim that an election will be held. "
            "A projected date is a prompt to check the official source, not a date. "
            "A stated date that has gone by stays as the source gave it and is never moved to a later year."
        ),
    }
