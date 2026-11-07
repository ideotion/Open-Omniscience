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

from datetime import date
from typing import Any

from src.civic.elections import (
    PROJECTED,
    SCHEDULED,
    WINDOW,
    _iso_date,
    date_confidence,
    is_election,
    missing_projection_fields,
    projection,
)

# Per-country states, most- to least-certain. `projected_passed` is a lead, not coverage.
STATE_SCHEDULED = "scheduled"
STATE_WINDOW = "window"
STATE_PROJECTED = "projected_upcoming"
STATE_PROJECTED_PASSED = "projected_passed"
STATE_DATELESS = "dateless"
STATE_MISSING = "missing"
STATES: tuple[str, ...] = (
    STATE_SCHEDULED,
    STATE_WINDOW,
    STATE_PROJECTED,
    STATE_PROJECTED_PASSED,
    STATE_DATELESS,
    STATE_MISSING,
)

_PRECISIONS = ("day", "month", "year")


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

    point = _iso_date(row.get("point_in_time"))
    start, end = _iso_date(row.get("start")), _iso_date(row.get("end"))
    precision = str(row.get("precision") or "").strip().lower()

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
    if point < today:
        return None, "past election (the agenda is forward-looking)"

    if precision == "day" and url:
        event.update(month=point.month, day=point.day, confirmed=True, window_year=point.year)
        event["date_basis"] = f"P585 {point.isoformat()} (day precision), source {url}"
        return event, None
    if precision == "day":
        # A day with no authority behind it is not a schedule: degrade, and say so.
        event.update(month=point.month, window_year=point.year)
        event["date_basis"] = f"P585 {point.isoformat()} (day precision), NO official source"
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


def layer(
    curated: list[dict[str, Any]], snapshot_events: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Curated entries win; a snapshot entry for a country+office they cover is SHADOWED.

    A curated entry naming no ``office`` shadows every snapshot entry of its country (it cannot
    be told apart). Returns ``(entries, shadowed)`` — nothing is dropped without a record.
    """
    cur = [e for e in curated if is_election(e)]
    shadowed: list[dict[str, str]] = []
    kept = []
    for ev in snapshot_events:
        cc = str(ev.get("country") or "").upper()
        hit = next(
            (
                c
                for c in cur
                if str(c.get("country") or "").upper() == cc
                and (not c.get("office") or c.get("office") == ev.get("office"))
            ),
            None,
        )
        if hit is None:
            kept.append(ev)
        else:
            shadowed.append(
                {
                    "qid": str(ev.get("source_qid") or ""),
                    "country": cc,
                    "shadowed_by": str(hit.get("title") or ""),
                }
            )
    return list(curated) + kept, shadowed


def country_tier_report(
    events: list[dict[str, Any]], floor: set[str], today: date | None = None
) -> dict[str, Any]:
    """For every floor country: its state, best tier, entries, and why a value is absent."""
    today = today or date.today()
    per: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        if is_election(ev):
            per.setdefault(str(ev.get("country") or "").strip().lower(), []).append(ev)

    rows = []
    for cc in sorted(floor):
        entries = []
        for ev in per.get(cc, []):
            tier = date_confidence(ev)
            proj = projection(ev, today) if tier == PROJECTED else None
            entries.append(
                {
                    "title": str(ev.get("title") or ""),
                    "tier": tier,
                    "projection_status": proj["status"] if proj else None,
                    "inferred": bool(ev.get("inferred")),
                    "reason": ev.get("date_reason") or ev.get("inferred_reason"),
                    "missing_fields": missing_projection_fields(ev) if tier is None else [],
                }
            )
        tiers = {e["tier"] for e in entries}
        live_proj = any(
            e["tier"] == PROJECTED and e["projection_status"] != "passed" for e in entries
        )
        if SCHEDULED in tiers:
            state, reason = STATE_SCHEDULED, None
        elif WINDOW in tiers:
            state, reason = STATE_WINDOW, None
        elif live_proj:
            state, reason = STATE_PROJECTED, None
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
        "caveat": (
            "States describe calendar ENTRIES, never a claim that an election will be held. "
            "A projected date is a prompt to check the official source, not a date."
        ),
    }
