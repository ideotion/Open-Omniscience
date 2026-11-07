"""The OSM lane's HTTP face: what the lane holds and analytic 1, per country and region (S05-04).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

EVERY ROUTE HERE READS A LOCAL FILE AND MAKES NO REQUEST, EXCEPT ONE: ``POST /countries/{code}/update`` queues a fetch of the
mirror's daily change files and refuses without ``consent: true`` and under the kill switch (``src/osm/update_job.py``; UI invariants
#14 and #14f). The extract is downloaded by ``/api/geo/downloads`` under the one online consent; the lane reads what is already on disk.

Nothing here returns a file, an export or a bundle: the answers are JSON read by this machine's
own UI over loopback, which is the machine. Q823 = a (2026-09-29) lets OSM data leave the machine
with OSM's credit and the ODbL line; the carriers (backup, bulletin, claim bundle) add that line
through ``src/backup/attribution.py``, which row K owns, so this module states it and holds nothing.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database.session import get_db
from src.monitoring.secret_scrub import http_detail

router = APIRouter(prefix="/api/osm", tags=["osm"])


@router.get("/lane")
def lane_status() -> dict:
    """Is the ``[geo]`` extra installed, what can be read without it, and what the lane holds.

    ``lane_bytes`` is ``None`` when ``osm.db`` does not exist -- absent, never zero.
    """
    from src.osm import completeness
    from src.osm.reader import (
        DICT_BYTES_PER_NODE,
        MEMORY_SHARE,
        available_memory_bytes,
        pyosmium_version,
    )
    from src.osm.tags import NOT_KEPT
    from src.versioned.store import lane_file_bytes

    version = pyosmium_version()
    return {
        "extra": {"installed": version is not None, "pyosmium": version},
        # R77: no file-size cap on either reader. Without the extra, node locations stay in
        # memory up to a share of what is available now, then move to a work file.
        "python_reader": {
            "file_size_cap": None,
            "memory_available_bytes": available_memory_bytes(),
            "memory_share": MEMORY_SHARE,
            "bytes_per_node_in_memory": DICT_BYTES_PER_NODE,
        },
        "lane_bytes": lane_file_bytes("osm"),
        "countries": completeness.countries(),
        "kept": NOT_KEPT,
        # Q823 = a: OSM-derived rows may leave the machine, credited (the carriers add the line).
        "exports": "allowed with OpenStreetMap's credit and the ODbL 1.0 line (Q823)",
        "credit": "© OpenStreetMap contributors (https://www.openstreetmap.org/copyright), ODbL 1.0",
    }


@router.get("/countries/{code}/completeness")
def country_completeness(code: str) -> dict:
    """Analytic 1 for one ingested country (alpha-2 or alpha-3)."""
    from src.osm.completeness import tag_completeness
    from src.osm.ingest import country_codes

    try:
        _a2, a3 = country_codes(code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=http_detail(exc)) from None
    return tag_completeness(a3)


@router.get("/countries/{code}/trends")
def country_trends(code: str) -> dict:
    """Trend surfaces 2 and 3 for one cut country (alpha-2 or alpha-3): adoption over time, openings and closures.

    Read-only, local, no request. The tracked window and the planet's prior are separate keys and are never summed.
    """
    from src.osm.ingest import country_codes
    from src.osm.trends import trends

    try:
        _a2, a3 = country_codes(code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=http_detail(exc)) from None
    return trends(a3)


@router.get("/countries/{code}/profile/{surface}")
def country_profile(code: str, surface: str, limit: int = 100) -> dict:
    """Trend surfaces 4 to 6 for one cut country (alpha-2 or alpha-3): ``brands``, ``channels`` or ``freshness``.

    Read-only, local, no request. The snapshot, the tracked window and the planet's prior are separate keys and are never summed.
    ``limit`` is how many ranked brands to return (the answer states how many exist).
    """
    from src.osm.ingest import country_codes
    from src.osm.profile import SURFACES, profile

    if surface not in SURFACES:
        raise HTTPException(status_code=400, detail=f"surface must be one of {', '.join(SURFACES)}")
    try:
        _a2, a3 = country_codes(code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=http_detail(exc)) from None
    return profile(a3, surface, limit)


@router.get("/geography")
def geography() -> dict:
    """The geography axis at country level: every cut country with its counts for each measure and its own vintage.

    Read-only, local, no request. Admin-1 values travel with each country's completeness (``/countries/{code}/completeness``).
    """
    from src.osm.geography import countries_view

    return countries_view()


@router.post("/countries/{code}/admin1")
def count_admin1(code: str) -> dict:
    """Count analytic 1 per admin-1 region, on a thread of its own (local work, no request).

    A refusal is answered at once, by name: no outline file, no region of this country in it.
    """
    from src.osm.completeness import Admin1Error, start_count
    from src.osm.ingest import country_codes

    try:
        _a2, a3 = country_codes(code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=http_detail(exc)) from None
    try:
        return start_count(a3)
    except Admin1Error as exc:
        raise HTTPException(status_code=409, detail=http_detail(exc)) from None


@router.get("/countries/{code}/prior-summary")
def prior_summary_state(code: str) -> dict:
    """Is the monthly summary of the planet's past current, being built, or absent? Headers only: read-only, local, no request."""
    from src.osm.ingest import country_codes
    from src.osm.prior_summary import summary_state

    try:
        _a2, a3 = country_codes(code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=http_detail(exc)) from None
    return summary_state(a3)


@router.post("/countries/{code}/prior-summary")
def build_prior_summary(code: str) -> dict:
    """Build the monthly summary of the planet's past for a history cut that already exists, on a thread of its own (local work, no request).

    The page asks for this once when it finds a cut without a current summary: a GET never writes, so the build is a POST. Idempotent: a
    country already being built answers ``building``, and one whose summary is current is skipped by the thread.
    """
    from src.osm.ingest import country_codes
    from src.osm.prior_summary import start_build

    try:
        _a2, a3 = country_codes(code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=http_detail(exc)) from None
    return start_build(a3)


class UpdateConsent(BaseModel):
    """``consent`` is true only after the page's one online consent ran (``ensureOnline``); a caller that never went through it is refused."""

    consent: bool = False


@router.post("/countries/{code}/update")
def update_country_route(code: str, req: UpdateConsent) -> dict:
    """Queue the daily change files for one cut country. The ONE route here that reaches the network (on a thread of its own).

    Refused at once, by name: no consent (400), the kill switch (409). A country that cannot be updated as it stands (no finished cut, no
    replication position) is queued all the same and ENDS with that reason, which the task manager shows: the checks that need the lane run
    in the job, once, so this route never opens the lane on the request thread.
    """
    from src.osm.update_job import ConsentRefused, KillSwitchRefused, request_update

    try:
        return request_update(code, consent=req.consent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=http_detail(exc)) from None
    except ConsentRefused as exc:
        raise HTTPException(status_code=400, detail=http_detail(exc)) from None
    except KillSwitchRefused as exc:
        raise HTTPException(status_code=409, detail=http_detail(exc)) from None


@router.get("/updates")
def update_jobs() -> dict:
    """The daily-update jobs this run has queued or ended (read-only, nothing persisted)."""
    from src.osm.update_job import jobs

    return {"jobs": jobs()}


@router.get("/search")
def search(q: str = Query(..., min_length=2, max_length=200)) -> dict:
    """The "Places" facet (Q817): named places in the countries read, from the name index."""
    from src.osm.places import search_names

    return search_names(" ".join(q.split()))


@router.get("/geocode")
def geocode(q: str = Query(..., min_length=1, max_length=300)) -> dict:
    """The local geocoder (Q820): an address in the countries read, or «not located». No request."""
    from src.osm.places import geocode as _geocode

    return _geocode(" ".join(q.split()))


@router.get("/view")
def osm_view(
    w: float = Query(...), s: float = Query(...), e: float = Query(...), n: float = Query(...)
) -> dict:
    """What the map draws of the lane in one view box, under the published caps (S6, Q822)."""
    from src.osm.view import ViewError, view

    try:
        return view(w, s, e, n)
    except ViewError as exc:
        raise HTTPException(status_code=400, detail=http_detail(exc)) from None


@router.get("/objects/{osm_type}/{osm_id}")
def object_card(osm_type: str, osm_id: int) -> dict:
    """One stored object with every tag, as the object card shows it."""
    from src.osm.places import object_card as _card

    try:
        out = _card(f"{osm_type}/{osm_id}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=http_detail(exc)) from None
    if out is None:
        raise HTTPException(status_code=404, detail="the OpenStreetMap lane holds no such object")
    return out


class CountrySelection(BaseModel):
    countries: list[str]


@router.get("/picker")
def picker(lang: str = "en", db: Session = Depends(get_db)) -> dict:
    """The Settings picker: the choice, the suggestions for ``lang``, each country's costs.

    ``lang`` is the interface language the page reports; the suggestions come from it and from
    nothing else (Q807: never from the IP address).
    """
    from src.osm.picker import law_countries, picker_state

    try:
        law = law_countries(db)
    except Exception:  # noqa: BLE001 - said on the page ("law_unavailable"), never a silent empty row
        law = None
    return picker_state(lang, law)


@router.put("/countries")
def set_countries(payload: CountrySelection) -> dict:
    """Replace the chosen countries. One local setting; no download starts here."""
    from src.osm.picker import PickerError, save_selection

    try:
        chosen = save_selection(payload.countries)
    except PickerError as exc:
        raise HTTPException(status_code=400, detail=http_detail(exc)) from None
    return {"countries": chosen, "enabled": bool(chosen)}


@router.get("/history")
def history() -> dict:
    """The full-history planet (Q814 = b): its download's catalogue line and every country's cut.

    Reads the catalogue and ``osm.db``; the exact size is ``/api/geo/downloads/size``, behind
    the online consent. ``cuts`` is ``None`` when the lane could not be read (a locked store),
    said on the page, never an empty list that would read as "no country cut yet".
    """
    from src.geo.osm_regions import HISTORY_REGION, OSM_HISTORY_SIZE_AS_OF
    from src.osm.history import GAP, METHOD, history_state

    try:
        cuts: list[dict] | None = history_state()
    except Exception:  # noqa: BLE001 - said on the page ("cuts": null), never a silent []
        cuts = None
    return {
        "download": {**HISTORY_REGION.to_dict(), "size_as_of": OSM_HISTORY_SIZE_AS_OF},
        "cuts": cuts,
        "method": METHOD,
        "gap": GAP,
    }


@router.get("/countries/{code}/places-summary")
def places_summary_state(code: str) -> dict:
    """Is the stored summary of this country's current places current, being built, or absent? Header only: read-only, local, no request."""
    from src.osm.ingest import country_codes
    from src.osm.places_summary import summary_state

    try:
        _a2, a3 = country_codes(code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=http_detail(exc)) from None
    return summary_state(a3)


@router.post("/countries/{code}/places-summary")
def build_places_summary(code: str) -> dict:
    """Build the stored summary of a country's current places, on a thread of its own (local work, no request).

    The page asks for this once per country per session when it finds a country without a current summary: a GET never writes, so the build
    is a POST. Idempotent: a country already being built answers ``building``, one whose summary is current is skipped by the thread, and
    builds of several countries run one at a time.
    """
    from src.osm.ingest import country_codes
    from src.osm.places_summary import start_build

    try:
        _a2, a3 = country_codes(code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=http_detail(exc)) from None
    return start_build(a3)
