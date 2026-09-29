"""Analytic 1: tag completeness per country (Q815 = a, «1-3 first»; 1 in 0.5).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The share of a country's places with metadata (``kind = 'poi'``) that carry ``opening_hours``,
``website``, ``email`` and ``phone``. COUNTS, n, a method and a caveat -- never a score, never a
blend of the four into one figure (the honesty non-negotiable; the four are shown side by side).

WHAT COUNTS AS PRESENT, stated in :data:`METHOD` and returned with every answer:

* the tag itself, OR its ``contact:*`` twin (``contact:website``, ``contact:email``,
  ``contact:phone``) -- both are documented OSM spellings of one fact; ``opening_hours`` has no
  twin;
* an EMPTY value (``opening_hours=``) is ABSENT: a key with nothing in it says nothing.

WHAT IS REFUSED. A country the lane does not hold, or whose ingest did not finish, returns a
``status`` saying so and no figures: a half-cut country's share is a number about a file, not
about the country. A country with ``n = 0`` places returns every share as ``None`` ("no places"),
never ``0 %``.

PER ADMIN-1 REGION (S05-04 S5). Q815 asks for the view per country / admin-1, with S05-05's
admin-1 keys: the regions of row E's published outline file (``src/static/osm_admin1.json``),
the same file the map draws, so a region's figures and its shape on the map cannot disagree
about where it is. A place is counted in the region whose outline holds its point. Three
populations are counted and never dropped: places in no region's outline (the outlines are
simplified to about a kilometre, so a place near a border can fall between two), places with no
point of their own (a relation), and the regions with no place at all (``n = 0``, no share).

The split is COUNTED ONCE and kept (``osm_admin1_splits``), because a country holds millions of
places and a point-in-outline test for each is minutes of work, never a page load. It records
what it was counted from -- the country's ingest and the outline file's vintage -- and reads as
``stale`` when either has changed, rather than as the current figures. Without the outline file
the answer says so (``no-admin1-file``) and carries no guessed split.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.osm.tags import column_name

_LOG = logging.getLogger("osm.completeness")

#: Row E's published admin-1 outlines, the file the map draws (operator-built, often absent).
ADMIN1_FILE = Path(__file__).resolve().parents[1] / "static" / "osm_admin1.json"

ADMIN1_METHOD = (
    "Each place with metadata is counted in the admin-1 region whose OpenStreetMap outline holds its "
    "point: the outlines of the map's region layer, simplified to about a kilometre. The four keys are "
    "counted as for the whole country, region by region."
)
ADMIN1_CAVEAT = (
    "A place close to a regional border can be counted in the neighbouring region, or in none, because "
    "the outlines are simplified. Places in no region and places with no point are counted, not placed."
)

#: ``(key, contact:* twin or None)`` in Q815's order.
KEYS: tuple[tuple[str, str | None], ...] = (
    ("opening_hours", None),
    ("website", "website"),
    ("email", "email"),
    ("phone", "phone"),
)

METHOD = (
    "Among this country's places with metadata (objects kept as 'poi' by the OSM lane), the count "
    "carrying each tag. A tag counts when it, or its contact:* twin (contact:website, contact:email, "
    "contact:phone), has a non-empty value. The four keys are counted separately and never combined."
)
CAVEAT = (
    "A missing tag means OpenStreetMap does not record it, not that the place lacks it. Completeness "
    "varies with how actively a region is mapped. The figures describe the extract at its vintage."
)


def _has(key: str, twin: str | None):
    """``1`` when the key -- or its contact twin -- has a non-empty value, else ``0``: THE rule,
    read by the country's sums and by the per-region count alike."""
    from sqlalchemy import and_, case, func, or_

    from src.osm.lane_models import osm_objects_table

    col = osm_objects_table.c[column_name(key)]
    cond = and_(col.is_not(None), col != "")
    if twin:
        twin_val = func.json_extract(osm_objects_table.c.contact, f'$."{twin}"')
        cond = or_(cond, and_(twin_val.is_not(None), twin_val != ""))
    return case((cond, 1), else_=0)


def _present(key: str, twin: str | None):
    """``SUM(1 when the key -- or its contact twin -- has a non-empty value)``, as an expression."""
    from sqlalchemy import func

    return func.sum(_has(key, twin))


def _keys(n: int, present: list[int]) -> list[dict]:
    """The four keys side by side; a share only where ``n`` is not zero (never ``0 %``)."""
    return [
        {
            "key": key,
            "twin": f"contact:{twin}" if twin else None,
            "present": int(p or 0),
            "share": (int(p or 0) / n) if n else None,
        }
        for (key, twin), p in zip(KEYS, present, strict=True)
    ]


def tag_completeness(alpha3: str) -> dict:
    """The analytic for one ingested country. Reads ``osm.db``; opens nothing else."""
    from sqlalchemy import func, select

    from src.osm.lane_models import OsmCountry, osm_objects_table
    from src.versioned import store

    base: dict[str, Any] = {"country": alpha3, "method": METHOD, "caveat": CAVEAT, "keys": [], "n": None}
    base["admin1"] = None
    if not store.lane_exists("osm"):
        return {**base, "status": "lane-absent"}
    with store.lane_session("osm") as s:
        row = s.query(OsmCountry).filter_by(alpha3=alpha3).one_or_none()
        if row is None:
            return {**base, "status": "not-ingested"}
        facts = {
            "name": row.name,
            "vintage": row.extract_vintage.isoformat() if row.extract_vintage else None,
            "extract": row.extract_name,
        }
        if row.status != "complete":
            return {**base, **facts, "status": row.status}
        t = osm_objects_table
        n, *present = s.execute(
            select(func.count(), *(_present(k, tw) for k, tw in KEYS)).where(
                t.c.country_alpha3 == alpha3, t.c.kind == "poi"
            )
        ).one()
    out = {**base, **facts, "status": "complete", "n": int(n), "keys": _keys(int(n), present)}
    try:
        out["admin1"] = admin1_state(alpha3)
    except Exception as exc:  # noqa: BLE001 - said on the page, never a silent "no regions"
        _LOG.warning("osm: could not read the admin-1 split for %s", alpha3, exc_info=True)
        out["admin1"] = {"status": "unreadable", "error": f"{type(exc).__name__}: {exc}"}
    return out


# --------------------------------------------------------------------------- #
#  Per admin-1 region                                                          #
# --------------------------------------------------------------------------- #


class Admin1Error(ValueError):
    """Why a split cannot be counted, as a token the page names (``no-admin1-file`` ...)."""


def load_outlines(path: Path | None = None) -> dict | None:
    """Row E's admin-1 file, or None when it is absent or unreadable (the map's own degrade)."""
    p = path or ADMIN1_FILE
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and isinstance(doc.get("regions"), dict) else None


def _country_regions(doc: dict, alpha3: str) -> dict[str, dict]:
    return {k: r for k, r in sorted(doc["regions"].items()) if r.get("country") == alpha3}


def _border(rings: list) -> Any:
    """A region's outline as the lane's own inside test. The file's rings are ``[lon, lat]``."""
    from src.osm.geometry import Border

    closed = []
    for ring in rings:
        pts = [(float(p[1]), float(p[0])) for p in ring]
        if len(pts) >= 3:
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            closed.append(pts)
    return Border(closed, grid=128) if closed else None


_RUNNING: set[str] = set()
_RUN_LOCK = threading.Lock()


def count_admin1(alpha3: str, *, path: Path | None = None) -> dict:
    """Count analytic 1 per admin-1 region for one ingested country and keep the result.

    Reads ``osm.db`` and the outline file; opens nothing else. Raises :class:`Admin1Error` with
    the page's token when it cannot start; a failure once started is RECORDED (``failed``).
    """
    from sqlalchemy import select

    from src.osm.lane_models import OsmAdmin1Split, OsmCountry, osm_objects_table
    from src.versioned import store

    doc = load_outlines(path)
    if doc is None:
        raise Admin1Error("no-admin1-file")
    regions = _country_regions(doc, alpha3)
    if not regions:
        raise Admin1Error("no-regions")
    if not store.lane_exists("osm"):
        raise Admin1Error("lane-absent")
    with store.lane_session("osm") as s:
        country = s.query(OsmCountry).filter_by(alpha3=alpha3).one_or_none()
        if country is None or country.status != "complete":
            raise Admin1Error("not-ingested")
        basis = country.finished_at.isoformat() if country.finished_at else None
        row = s.query(OsmAdmin1Split).filter_by(alpha3=alpha3).one_or_none()
        if row is None:
            row = OsmAdmin1Split(alpha3=alpha3)
            s.add(row)
        row.status, row.error, row.finished_at, row.seconds = "counting", None, None, None
        row.started_at = datetime.now(UTC)
        row.basis_ingest = basis
        row.outline_vintage, row.outline_source = doc.get("vintage"), doc.get("source")

    t0 = time.monotonic()
    try:
        borders = [(k, b) for k, r in regions.items() if (b := _border(r.get("rings") or [])) is not None]
        # Only a region whose outline could be built is counted: one with no usable outline is
        # absent from the answer ("not counted", drawn as no data), never a counted zero.
        counts: dict[str, dict] = {k: {"n": 0, "present": [0, 0, 0, 0]} for k, _b in borders}
        outside = no_point = 0
        t = osm_objects_table
        query = select(t.c.lat, t.c.lon, *(_has(k, tw) for k, tw in KEYS)).where(
            t.c.country_alpha3 == alpha3, t.c.kind == "poi"
        )
        with store.lane_session("osm") as s:
            for lat, lon, *has in s.execute(query).yield_per(5000):
                if lat is None or lon is None:
                    no_point += 1
                    continue
                hit = next(
                    (k for k, b in borders
                     if b.min_lat <= lat <= b.max_lat and b.min_lon <= lon <= b.max_lon and b.contains(lat, lon)),
                    None,
                )
                if hit is None:
                    outside += 1
                    continue
                c = counts[hit]
                c["n"] += 1
                for i, h in enumerate(has):
                    c["present"][i] += int(h or 0)
        keyed = {k: {"n": c["n"], "present": dict(zip((k2 for k2, _ in KEYS), c["present"], strict=True))}
                 for k, c in counts.items()}
        with store.lane_session("osm") as s:
            row = s.query(OsmAdmin1Split).filter_by(alpha3=alpha3).one()
            row.status = "complete"
            row.regions_json = json.dumps(keyed, sort_keys=True)
            row.outside, row.no_point = outside, no_point
            row.finished_at = datetime.now(UTC)
            row.seconds = round(time.monotonic() - t0, 3)
    except Exception as exc:
        with store.lane_session("osm") as s:
            row = s.query(OsmAdmin1Split).filter_by(alpha3=alpha3).one()
            row.status, row.error = "failed", f"{type(exc).__name__}: {exc}"
            row.finished_at = datetime.now(UTC)
        raise
    return admin1_state(alpha3, path=path)


def start_count(alpha3: str, *, path: Path | None = None) -> dict:
    """Start :func:`count_admin1` on a thread of its own; ``{"started": bool, ...}``.

    The checks that can refuse run HERE, so a refusal is answered by name at once rather than
    discovered later in a thread nobody is watching.
    """
    doc = load_outlines(path)
    if doc is None:
        raise Admin1Error("no-admin1-file")
    if not _country_regions(doc, alpha3):
        raise Admin1Error("no-regions")
    with _RUN_LOCK:
        if alpha3 in _RUNNING:
            return {"started": False, "status": "counting"}
        _RUNNING.add(alpha3)

    def run() -> None:
        try:
            count_admin1(alpha3, path=path)
        except Exception:  # noqa: BLE001 - recorded on the row as "failed"; logged here
            _LOG.warning("osm: the admin-1 count for %s failed", alpha3, exc_info=True)
        finally:
            with _RUN_LOCK:
                _RUNNING.discard(alpha3)

    threading.Thread(target=run, name=f"osm-admin1-{alpha3}", daemon=True).start()
    return {"started": True, "status": "counting"}


def admin1_state(alpha3: str, *, path: Path | None = None) -> dict:
    """What the page shows under the country: the split, or why there is none."""
    from src.osm.lane_models import OsmAdmin1Split, OsmCountry
    from src.versioned import store

    base: dict[str, Any] = {"method": ADMIN1_METHOD, "caveat": ADMIN1_CAVEAT}
    doc = load_outlines(path)
    if doc is None:
        return {**base, "status": "no-admin1-file"}
    regions = _country_regions(doc, alpha3)
    outline = {"vintage": doc.get("vintage"), "source": doc.get("source")}
    if not regions:
        return {**base, "status": "no-regions", "outline": outline}
    if not store.lane_exists("osm"):
        return {**base, "status": "not-counted", "outline": outline}
    with store.lane_session("osm") as s:
        row = s.query(OsmAdmin1Split).filter_by(alpha3=alpha3).one_or_none()
        country = s.query(OsmCountry).filter_by(alpha3=alpha3).one_or_none()
        basis = country.finished_at.isoformat() if country and country.finished_at else None
        if row is None:
            return {**base, "status": "not-counted", "outline": outline}
        counted_from = {"ingest": row.basis_ingest, "outline_vintage": row.outline_vintage,
                        "outline_source": row.outline_source}
        facts: dict[str, Any] = {
            "outline": outline,
            "counted_from": counted_from,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "seconds": row.seconds,
        }
        status, error = row.status, row.error
        stored = json.loads(row.regions_json) if row.regions_json else {}
        outside, no_point = row.outside, row.no_point
    if status == "counting" and alpha3 not in _RUNNING:
        status = "interrupted"   # a restart ended the thread: said, never shown as still running
    if status != "complete":
        return {**base, **facts, "status": status, "error": error}
    stale = (counted_from["ingest"] != basis
             or counted_from["outline_vintage"] != outline["vintage"]
             or counted_from["outline_source"] != outline["source"])
    rows: list[dict[str, Any]] = []
    for key, r in regions.items():
        got = stored.get(key)
        if got is None:          # a region the file gained after the count: absent, not zero
            rows.append({"key": key, "name": r.get("name"), "names": r.get("names") or {}, "n": None, "keys": []})
            continue
        n = int(got["n"])
        rows.append({"key": key, "name": r.get("name"), "names": r.get("names") or {}, "n": n,
                     "keys": _keys(n, [got["present"].get(k, 0) for k, _ in KEYS])})
    return {**base, **facts, "status": "stale" if stale else "complete", "regions": rows,
            "outside": outside, "no_point": no_point}


def countries() -> list[dict]:
    """Every country the lane holds, with its recorded measurements. ``[]`` when the lane is absent."""
    from src.osm.lane_models import OsmCountry
    from src.versioned import store

    if not store.lane_exists("osm"):
        return []
    out = []
    with store.lane_session("osm") as s:
        for r in s.query(OsmCountry).order_by(OsmCountry.alpha3):
            out.append(
                {
                    "alpha2": r.alpha2,
                    "alpha3": r.alpha3,
                    "name": r.name,
                    "status": r.status,
                    "extract": r.extract_name,
                    "extract_bytes": r.extract_bytes,
                    "vintage": r.extract_vintage.isoformat() if r.extract_vintage else None,
                    "reader": r.reader,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                    "ingest_seconds": r.ingest_seconds,
                    "counts": json.loads(r.counts_json) if r.counts_json else None,
                    "blob": json.loads(r.blob_json) if r.blob_json else None,
                    "border": json.loads(r.border_json) if r.border_json else None,
                    "error": r.error,
                }
            )
    return out
