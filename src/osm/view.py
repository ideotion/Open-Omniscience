"""What the map draws of the OSM lane in one view, under published caps (S05-04 S6, Q822 = a).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q822 = a: «Canvas 2D with published level-of-detail caps (points per view, polygon vertices per
zoom), degrading to clusters, never to a frozen tab.» The caps are this module's constants and
travel with every answer, so the legend hover states the numbers the drawing obeyed:

* :data:`POINTS_PER_VIEW` -- above this many objects in the view, NO object is sent: the view
  is cut into a :data:`CLUSTER_GRID` x :data:`CLUSTER_GRID` lattice and each occupied cell comes
  back as one cluster with its exact count. Every object is counted in some cluster; none is
  dropped to make the picture lighter.
* :data:`VERTICES_PER_VIEW` -- the shapes (roads, buildings, water, land use, power lines) are
  first thinned to the view: a vertex closer than one :data:`SIMPLIFY_PX`-th of the view's width
  to the last one kept is skipped (the first and last always stay), and a shape smaller than
  that is sent as its point. If the thinned shapes still exceed the budget, every shape is sent
  as its point instead, and the answer says so (``shapes: "points"``).

THE PYRAMID. Counting a country's tens of millions of objects on every pan would take seconds
(measured: 1.8 s for two million synthetic objects over a France-sized box, the live R*Tree
grouping in :func:`view`'s last branch). So the clusters of a wide view come from
``osm_view_cells``, one row per occupied cell at each of :data:`PYRAMID_LEVELS`, built once per
ingest: the finest level from the R*Tree, each coarser one from the level below. A view picks the
finest level whose cells are at least its width over :data:`CLUSTER_GRID`.

THE INDEX. An R*Tree (``osm_rtree``, SQLite's own module, present in SQLCipher too) holds each
object's bounding box, built from ``osm.db`` after every complete ingest, beside the search
indexes. ``osm_view_indexes`` records which ingest each country's rows were built from, so a
re-ingest is noticed and rebuilt, never served stale.

The time each answer took is measured here and returned (``seconds``); the page adds its own
drawing time. Both are shown in the legend hover, so the caps are read beside what they cost
on the machine in front of the reader. The reference-VM figures are the operator's run.

NOTHING HERE TOUCHES THE NETWORK: it reads ``osm.db`` and nothing else.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

#: Objects in one view above which the view is drawn as clusters (Q822's points per view).
#: 8,000 objects with their shapes is about 1.2 MiB of JSON over loopback and 0.14 s to read
#: (measured on a synthetic two-million-object country in the sandbox, 2026-09-29).
POINTS_PER_VIEW = 8000
#: Shape vertices in one view above which every shape is drawn as its point.
VERTICES_PER_VIEW = 60000
#: Cells per side of the cluster lattice.
CLUSTER_GRID = 40
#: The thinning tolerance is the view's width divided by this (about one screen pixel).
SIMPLIFY_PX = 1600
#: The cluster pyramid's levels: level L cuts the globe into cells 360 / 2**L degrees a side.
#: The finest (17) is about 0.0027 degrees, some 300 m; a view narrower than
#: CLUSTER_GRID of those cells is clustered live from the R*Tree instead.
PYRAMID_LEVELS = range(2, 18)
BATCH = 5000

CLUSTER_EDGE = (
    "A cluster counts every object in its grid cell, so a cell on the edge of the view also "
    "counts the objects just beyond it."
)
CAPS_METHOD = (
    "Up to {points} objects in a view are drawn one by one; more are drawn as clusters on a "
    "{grid} by {grid} grid, each with its exact count. Shapes are thinned to about one screen "
    "pixel; above {vertices} vertices in a view every shape is drawn as its point."
)

_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS osm_rtree USING rtree("
    "id, min_lon, max_lon, min_lat, max_lat)",
)


class ViewError(ValueError):
    """A view box that is not four ordered coordinates on the globe."""


def _ensure(session) -> None:
    from sqlalchemy import text

    for ddl in _DDL:
        session.execute(text(ddl))


# --------------------------------------------------------------------------- #
#  The index                                                                   #
# --------------------------------------------------------------------------- #


def _box(lat, lon, geom) -> tuple[float, float, float, float] | None:
    """``(min_lon, max_lon, min_lat, max_lat)`` from a way's shape, else its point."""
    from src.osm.geometry import decode_coords

    if geom:
        pts = decode_coords(geom)
        if pts:
            lats = [p[0] for p in pts]
            lons = [p[1] for p in pts]
            return (min(lons), max(lons), min(lats), max(lats))
    if lat is None or lon is None:
        return None
    return (lon, lon, lat, lat)


def build_view_index(alpha3: str) -> dict:
    """(Re)build one complete country's rows in the R*Tree. Reads ``osm.db``; opens nothing else."""
    from sqlalchemy import select, text

    from src.osm.lane_models import OsmCountry, OsmViewIndex, osm_objects_table
    from src.versioned import store

    t0 = time.monotonic()
    t = osm_objects_table
    rows = no_box = 0
    with store.lane_session("osm") as s:
        country = s.query(OsmCountry).filter_by(alpha3=alpha3).one_or_none()
        if country is None or country.status != "complete":
            raise ValueError("not-ingested")
        basis = country.finished_at.isoformat() if country.finished_at else None
        _ensure(s)
        # A re-ingest writes new row ids, so the old ones are cleared by absence as well as
        # by country: an id no object holds any more is never drawn.
        s.execute(text("DELETE FROM osm_rtree WHERE id NOT IN (SELECT id FROM osm_objects)"))
        s.execute(
            text("DELETE FROM osm_rtree WHERE id IN (SELECT id FROM osm_objects WHERE country_alpha3 = :a)"),
            {"a": alpha3},
        )
        buf: list[dict] = []
        for oid, lat, lon, geom in s.execute(
            select(t.c.id, t.c.lat, t.c.lon, t.c.geom).where(t.c.country_alpha3 == alpha3)
        ):
            box = _box(lat, lon, geom)
            if box is None:
                no_box += 1
                continue
            buf.append({"i": oid, "a": box[0], "b": box[1], "c": box[2], "d": box[3]})
            rows += 1
            if len(buf) >= BATCH:
                s.execute(text("INSERT INTO osm_rtree VALUES (:i, :a, :b, :c, :d)"), buf)
                buf.clear()
        if buf:
            s.execute(text("INSERT INTO osm_rtree VALUES (:i, :a, :b, :c, :d)"), buf)
        _build_pyramid(s, alpha3)
        row = s.query(OsmViewIndex).filter_by(alpha3=alpha3).one_or_none() or OsmViewIndex(alpha3=alpha3)
        row.basis_ingest, row.rows, row.no_box = basis, rows, no_box
        row.built_at = datetime.now(UTC)
        row.seconds = round(time.monotonic() - t0, 3)
        s.add(row)
    return {"alpha3": alpha3, "rows": rows, "no_box": no_box}


def cell_size(level: int) -> float:
    return 360.0 / (2**level)


def _build_pyramid(s, alpha3: str) -> None:
    """The finest level from the R*Tree centres, then each coarser level from the one below."""
    from sqlalchemy import text

    s.execute(text("DELETE FROM osm_view_cells WHERE alpha3 = :a"), {"a": alpha3})
    top = PYRAMID_LEVELS[-1]
    s.execute(
        text(
            "INSERT INTO osm_view_cells (alpha3, level, cx, cy, n, slat, slon) "
            "SELECT :a, :lv, CAST(((min_lon + max_lon) / 2 + 180) / :sz AS INTEGER) AS gx, "
            "CAST(((min_lat + max_lat) / 2 + 90) / :sz AS INTEGER) AS gy, count(*), "
            "sum((min_lat + max_lat) / 2), sum((min_lon + max_lon) / 2) FROM osm_rtree "
            "WHERE id IN (SELECT id FROM osm_objects WHERE country_alpha3 = :a) GROUP BY gx, gy"
        ),
        {"a": alpha3, "lv": top, "sz": cell_size(top)},
    )
    for lv in reversed(PYRAMID_LEVELS[:-1]):
        s.execute(
            text(
                "INSERT INTO osm_view_cells (alpha3, level, cx, cy, n, slat, slon) "
                "SELECT :a, :lv, cx / 2 AS gx, cy / 2 AS gy, sum(n), sum(slat), sum(slon) "
                "FROM osm_view_cells WHERE alpha3 = :a AND level = :fine GROUP BY gx, gy"
            ),
            {"a": alpha3, "lv": lv, "fine": lv + 1},
        )


def refresh_view_indexes() -> dict:
    """Build the view rows of every complete country whose rows do not match its ingest."""
    from src.osm.lane_models import OsmCountry, OsmViewIndex
    from src.versioned import store

    if not store.lane_exists("osm"):
        return {}
    todo = []
    with store.lane_session("osm") as s:
        built = {r.alpha3: r.basis_ingest for r in s.query(OsmViewIndex)}
        for c in s.query(OsmCountry).filter_by(status="complete"):
            basis = c.finished_at.isoformat() if c.finished_at else None
            if built.get(c.alpha3, "-") != basis:
                todo.append(c.alpha3)
    return {a3: build_view_index(a3) for a3 in todo}


# --------------------------------------------------------------------------- #
#  One view                                                                    #
# --------------------------------------------------------------------------- #


def caps() -> dict[str, Any]:
    return {
        "points_per_view": POINTS_PER_VIEW,
        "vertices_per_view": VERTICES_PER_VIEW,
        "cluster_grid": CLUSTER_GRID,
        "simplify_px": SIMPLIFY_PX,
        "method": CAPS_METHOD,
        "cluster_edge": CLUSTER_EDGE,
    }


def parse_bbox(w: float, s: float, e: float, n: float) -> tuple[float, float, float, float]:
    for v in (w, s, e, n):
        if v != v:  # NaN
            raise ViewError("a coordinate is not a number")
    w, e = max(-180.0, w), min(180.0, e)
    s, n = max(-90.0, s), min(90.0, n)
    if not (w < e and s < n):
        raise ViewError("the view box must run west < east and south < north")
    return w, s, e, n


def thin(coords: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Skip a vertex closer than ``tol`` degrees to the last one kept; first and last stay."""
    if len(coords) <= 2:
        return list(coords)
    out = [coords[0]]
    t2 = tol * tol
    for p in coords[1:-1]:
        q = out[-1]
        if (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 >= t2:
            out.append(p)
    out.append(coords[-1])
    return out


def view(w: float, s: float, e: float, n: float) -> dict[str, Any]:
    """What to draw of the lane in the box ``w, s, e, n`` (degrees). Reads ``osm.db`` only."""
    from sqlalchemy import text

    from src.osm.geometry import decode_coords
    from src.osm.lane_models import OsmViewIndex, osm_objects_table
    from src.osm.tags import column_name
    from src.versioned import store

    w, s, e, n = parse_bbox(w, s, e, n)
    t0 = time.monotonic()
    out: dict[str, Any] = {"bbox": [w, s, e, n], "caps": caps()}
    if not store.lane_exists("osm"):
        return {**out, "status": "no-lane", "total": 0, "seconds": 0.0}
    hit = "max_lon >= :w AND min_lon <= :e AND max_lat >= :s AND min_lat <= :n"
    p = {"w": w, "s": s, "e": e, "n": n}
    with store.lane_session("osm") as ses:
        if not ses.query(OsmViewIndex).count():
            return {**out, "status": "not-indexed", "total": 0, "seconds": 0.0}
        _ensure(ses)
        few: int = ses.execute(
            text(f"SELECT count(*) FROM (SELECT 1 FROM osm_rtree WHERE {hit} LIMIT :cap)"),  # nosec B608 - hit is a constant clause; values are bound
            {**p, "cap": POINTS_PER_VIEW + 1},
        ).scalar_one()
        if few > POINTS_PER_VIEW:
            want = (e - w) / CLUSTER_GRID
            fit = [lv for lv in PYRAMID_LEVELS if cell_size(lv) >= want]
            lv = fit[-1] if fit else PYRAMID_LEVELS[0]
            # Sizes halve level by level, so only a view finer than the finest level fails this.
            if cell_size(lv) <= 2 * want:
                sz = cell_size(lv)
                rows = ses.execute(
                    text(
                        "SELECT sum(n), sum(slat), sum(slon) FROM osm_view_cells WHERE level = :lv "
                        "AND cx BETWEEN :x0 AND :x1 AND cy BETWEEN :y0 AND :y1 GROUP BY cx, cy ORDER BY cy, cx"
                    ),
                    {"lv": lv, "x0": int((w + 180) // sz), "x1": int((e + 180) // sz),
                     "y0": int((s + 90) // sz), "y1": int((n + 90) // sz)},
                ).all()
                clusters = [{"n": int(c), "lat": round(la / c, 6), "lon": round(lo / c, 6)} for c, la, lo in rows]
                out["level"] = lv
            else:
                cw, ch = (e - w) / CLUSTER_GRID, (n - s) / CLUSTER_GRID
                live = ses.execute(
                    text(
                        "SELECT min(:g - 1, max(0, CAST(((min_lon + max_lon) / 2 - :w) / :cw AS INTEGER))) AS cx, "  # nosec B608 - hit is a constant clause; values are bound
                        "min(:g - 1, max(0, CAST(((min_lat + max_lat) / 2 - :s) / :ch AS INTEGER))) AS cy, "
                        "count(*), avg((min_lat + max_lat) / 2), avg((min_lon + max_lon) / 2) "
                        f"FROM osm_rtree WHERE {hit} GROUP BY cx, cy ORDER BY cy, cx"
                    ),
                    {**p, "cw": cw, "ch": ch, "g": CLUSTER_GRID},
                ).all()
                clusters = [{"n": int(c), "lat": round(la, 6), "lon": round(lo, 6)} for _, _, c, la, lo in live]
                out["level"] = None
            out.update(status="clusters", total=sum(c["n"] for c in clusters), clusters=clusters)
        else:
            name = osm_objects_table.c[column_name("name")].name
            rows = ses.execute(
                text(
                    f"SELECT o.osm_type, o.osm_id, o.kind, o.lat, o.lon, o.geom, o.{name} "  # nosec B608 - name is a column name read from the table definition, never input
                    "FROM osm_rtree r JOIN osm_objects o ON o.id = r.id "
                    "WHERE r.max_lon >= :w AND r.min_lon <= :e AND r.max_lat >= :s AND r.min_lat <= :n "
                    "ORDER BY o.id"
                ),
                p,
            ).all()
            tol = (e - w) / SIMPLIFY_PX
            feats: list[dict[str, Any]] = []
            vertices = 0
            for otype, oid, kind, lat, lon, geom, label in rows:
                f: dict[str, Any] = {"o": f"{otype}/{oid}", "k": kind}
                if label:
                    f["name"] = label
                shape = decode_coords(geom) if geom else None
                if shape:
                    lats = [q[0] for q in shape]
                    lons = [q[1] for q in shape]
                    if max(lats) - min(lats) >= tol or max(lons) - min(lons) >= tol:
                        thinned = thin(shape, tol)
                        f["c"] = [[round(a, 6), round(b, 6)] for a, b in thinned]
                        vertices += len(thinned)
                if lat is not None and lon is not None:
                    f["p"] = [round(lat, 6), round(lon, 6)]
                if "c" in f or "p" in f:
                    feats.append(f)
            shapes = "shapes"
            if vertices > VERTICES_PER_VIEW:
                shapes = "points"
                for f in feats:
                    f.pop("c", None)
                feats = [f for f in feats if "p" in f]
            out.update(status="objects", total=len(rows), objects=feats, vertices=vertices, shapes=shapes)
    out["seconds"] = round(time.monotonic() - t0, 3)
    return out
