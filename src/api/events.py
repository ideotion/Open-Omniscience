"""World-events agenda API (P0): read-only, offline, honest.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Serves the curated events catalog. Fixed-date civic observances get a real
``next_occurrence``; movable summits carry ``confirmed: false`` and link to the
official source for the precise date. No fabricated dates. The catalog itself
is offline; the ONLY network here is the operator-initiated feed verify/import
below, which goes through the ethical fetcher (fail-closed, kill-switch aware).
"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query

router = APIRouter(prefix="/api/events", tags=["events"])

_CAVEAT = (
    "A forward-looking agenda of major recurring events. Fixed civic dates are "
    "confirmed; summit/meeting dates move each year — follow the official source "
    "for the exact date. Nothing here is fabricated."
)


@router.get("/calendars")
def list_calendars() -> dict:
    """Subscribable calendars (with event counts) + the available filter facets."""
    from src.events.catalog import facets

    return facets()


@router.get("")
def list_events(
    category: str | None = Query(None, description="civic|political|economic|technology"),
    calendar: str | None = Query(None, description="a calendar key, e.g. un_days"),
    country: str | None = Query(None, description="ISO country code, e.g. FR"),
    tag: str | None = Query(None, description="a single tag, e.g. press-freedom"),
    dedup: bool = Query(True, description="collapse the same event seen in several calendars"),
) -> dict:
    """Curated world events matching the given facets, soonest fixed-date first.

    Facets (calendar / country / category / tag) are AND-combined; omit any for a
    wildcard. With ``dedup`` (default), an event appearing in several calendars is
    collapsed into one row that lists its sources (``sources`` / ``also_in``) and flags
    any date disagreement (``date_variants``) rather than hiding it. Subscription itself
    is a client preference (which calendars to show).
    """
    from src.events.catalog import agenda, load_calendars
    from src.events.dedup import dedup as dedup_events

    items = agenda(category=category, calendar=calendar, country=country, tag=tag)
    if dedup:
        cal_names = {c["key"]: c["name"] for c in load_calendars()}
        items = dedup_events(items, cal_names)
    return {
        "count": len(items),
        "confirmed": sum(1 for e in items if e["confirmed"]),
        "caveat": _CAVEAT,
        "events": items,
    }


# --------------------------------------------------------------------------- #
#  Calendar feed directory (maintainer-supplied aggregation, 2026-06-10):
#  bundled candidates -> explicit verify/import through the ethical fetcher.
#  Families SHOW duplicate providers; nothing is fetched without a click.
# --------------------------------------------------------------------------- #
@router.get("/feeds")
def feed_directory() -> dict:
    """The bundled calendar-feed directory with per-feed verdicts and imports."""
    from src.events.feeds import directory_status

    return directory_status()


@router.post("/feeds/{feed_id}/verify")
def feed_verify(feed_id: str) -> dict:
    """Fetch ONE feed now and record an honest verdict (operator-initiated)."""
    from src.events.feeds import feed_by_id, verify_feed
    from src.safety.fetcher import make_fetcher

    if feed_by_id(feed_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown feed: {feed_id}")
    return {"feed": feed_id, "verdict": verify_feed(make_fetcher(), feed_id)}


@router.post("/feeds/{feed_id}/import")
def feed_import(feed_id: str) -> dict:
    """Fetch ONE feed and import its events under its family (deduplicated
    within the family; every source stays listed)."""
    from src.events.feeds import feed_by_id, import_feed
    from src.safety.fetcher import make_fetcher

    if feed_by_id(feed_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown feed: {feed_id}")
    try:
        return import_feed(make_fetcher(), feed_id)
    except Exception as exc:  # noqa: BLE001 - surface the refusal honestly
        raise HTTPException(status_code=502, detail=str(exc)[:300]) from exc


@router.post("/feeds/import-ics")
def feed_import_ics(payload: dict = Body(...)) -> dict:
    """Import a .ics file the user UPLOADED (NO network). The events join the agenda
    (deduped) as a user-owned, removable, excludable calendar. The raw file is parsed
    and discarded — only event title + date (+ uid) are stored."""
    name = str(payload.get("name") or "").strip()
    ics = str(payload.get("ics") or "")
    if not ics.strip():
        raise HTTPException(status_code=400, detail="No .ics content provided.")
    from src.events.feeds import import_ics_text

    try:
        return import_ics_text(name, ics)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:300]) from exc


@router.get("/feeds/user")
def feed_list_user() -> dict:
    """The user's own uploaded calendars (removable)."""
    from src.events.feeds import list_user_feeds

    return {"feeds": list_user_feeds()}


@router.delete("/feeds/user/{key}")
def feed_remove_user(key: str) -> dict:
    """Remove a user-uploaded calendar (reversible: re-import the .ics)."""
    from src.events.feeds import remove_user_feed

    try:
        return remove_user_feed(key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/imported")
def imported_events(
    family: str | None = Query(None, description="one family key, e.g. holidays-fr"),
    frm: str | None = Query(None, alias="from", description="ISO date lower bound"),
) -> dict:
    """Events imported from verified feeds, soonest first (per-machine data).

    Cross-feed duplicates are collapsed into one row each (the same holiday carried
    by many feeds shows once, listing every source); ``count`` is the collapsed row
    count and ``occurrences`` the raw pre-collapse total, so the merge is transparent.
    """
    from src.events.feeds import imported_agenda

    items = imported_agenda(family=family, frm=frm)
    occurrences = len(imported_agenda(family=family, frm=frm, collapse=False))
    return {"count": len(items), "occurrences": occurrences, "events": items}


@router.post("/feeds/verify-batch")
def feed_verify_batch(limit: int = Query(25, ge=1, le=100)) -> dict:
    """Verify the next ``limit`` UNCHECKED feeds (operator-initiated, bounded).

    Repeating clicks walk the whole directory politely; verdicts accumulate in
    the per-machine store and the shareable network diagnostics log."""
    from src.events.feeds import load_families, load_verdicts, verify_feed
    from src.safety.fetcher import make_fetcher

    verdicts = load_verdicts()
    pending = [
        fd["id"]
        for fam in load_families()
        for fd in fam["feeds"]
        if fd["id"] not in verdicts
    ][:limit]
    fetcher = make_fetcher()
    out = {fid: verify_feed(fetcher, fid) for fid in pending}
    ok = sum(1 for v in out.values() if v.get("status") == "ok")
    return {"checked": len(out), "ok": ok, "remaining_unchecked": max(
        0, sum(len(f["feeds"]) for f in load_families()) - len(load_verdicts())
    ), "verdicts": out}


@router.get("/astronomy")
def astronomy(year: int = Query(..., ge=1900, le=2200)) -> dict:
    """Lunar phases for the agenda year — computed locally (Meeus ch. 49),
    zero network, with method + accuracy carried on the result (the agenda
    renders them via the hover convention)."""
    from src.events.astronomy import phases_for_year, seasons_for_year

    out = phases_for_year(year)
    out["seasons"] = seasons_for_year(year)["seasons"]
    out["seasons_naming"] = seasons_for_year(year)["naming"]
    return out


@router.get("/climate")
def climate_events() -> dict:
    """Historical climate phenomena (El Niño episodes) from the bundled,
    provenance-carrying dataset. HONESTY: the per-file verification_status
    travels with the data — entries drafted from training knowledge stay
    flagged until the clearnet check against the NOAA CPC ONI table; nothing
    is presented as verified before it is."""
    from pathlib import Path

    import yaml

    path = Path(__file__).resolve().parents[2] / "configs" / "climate_events.yml"
    if not path.exists():
        raise HTTPException(status_code=404, detail="climate dataset not bundled")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    episodes = data.get("el_nino_episodes", [])
    for ep in episodes:
        try:
            sy, sm = (int(x) for x in ep["start"].split("-"))
            ey, em = (int(x) for x in ep["end"].split("-"))
            ep["length_months"] = (ey - sy) * 12 + (em - sm) + 1
        except Exception:  # noqa: BLE001 - a malformed row shows without the derived field
            ep["length_months"] = None
    return {
        "as_of": data.get("as_of"),
        "source": data.get("source"),
        "method": data.get("method"),
        "verification_status": data.get("verification_status"),
        "el_nino_episodes": episodes,
        "count": len(episodes),
    }


@router.get("/astronomy/lunar-series")
def lunar_series(start: str, end: str) -> dict:
    """Daily lunar-phase series (age, illuminated fraction, waxing flag) for
    correlation studies — method + the correlation≠causation caveat ride the
    payload. Bounded to 100 years per request."""
    from datetime import date as _date

    from src.events.astronomy import lunar_phase_series

    try:
        d0, d1 = _date.fromisoformat(start), _date.fromisoformat(end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"bad date: {exc}") from exc
    if abs((d1 - d0).days) > 36525:
        raise HTTPException(status_code=400, detail="window exceeds 100 years")
    return lunar_phase_series(start, end)
