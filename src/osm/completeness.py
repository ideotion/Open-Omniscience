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

ADMIN-1 IS NOT HERE YET, AND SAYS WHY. Q815 asks for the view per country / admin-1, with
S05-05's admin-1 keys. Those keys are row E's artifact, which does not exist; the answer carries
``admin1: {"status": "waiting", "reason": "admin1-keys-row-e"}`` rather than a guessed split.
"""

from __future__ import annotations

import json
from typing import Any

from src.osm.tags import column_name

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


def _present(key: str, twin: str | None):
    """``SUM(1 when the key -- or its contact twin -- has a non-empty value)``, as an expression."""
    from sqlalchemy import and_, case, func, or_

    from src.osm.lane_models import osm_objects_table

    col = osm_objects_table.c[column_name(key)]
    cond = and_(col.is_not(None), col != "")
    if twin:
        twin_val = func.json_extract(osm_objects_table.c.contact, f'$."{twin}"')
        cond = or_(cond, and_(twin_val.is_not(None), twin_val != ""))
    return func.sum(case((cond, 1), else_=0))


def tag_completeness(alpha3: str) -> dict:
    """The analytic for one ingested country. Reads ``osm.db``; opens nothing else."""
    from sqlalchemy import func, select

    from src.osm.lane_models import OsmCountry, osm_objects_table
    from src.versioned import store

    base: dict[str, Any] = {"country": alpha3, "method": METHOD, "caveat": CAVEAT, "keys": [], "n": None}
    base["admin1"] = {"status": "waiting", "reason": "admin1-keys-row-e"}
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
    keys = []
    for (key, twin), p in zip(KEYS, present, strict=True):
        keys.append(
            {
                "key": key,
                "twin": f"contact:{twin}" if twin else None,
                "present": int(p or 0),
                "share": (int(p or 0) / n) if n else None,
            }
        )
    return {**base, **facts, "status": "complete", "n": int(n), "keys": keys}


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
