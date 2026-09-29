"""Pure transform for the OSM-derived admin-0 / admin-1 boundary artifacts (0.5 row E).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``scripts/build_admin_boundaries.py`` reads an OpenStreetMap extract (or the planet
file) on the maintainer's machine, assembles the boundary relations into rings and
hands them here as :class:`BoundaryRecord` s. This module turns them into the two
shipped artifacts every ooMap surface reads:

* ``osm_admin0.json`` -- countries (``admin_level=2``) keyed ISO 3166-1 ALPHA-3, read
  from the relation's own ``ISO3166-1:alpha2`` tag through :func:`to_iso3` (the external
  contract stays alpha-2 behind the converter, Q304), plus every ``boundary=disputed`` /
  ``boundary=claim`` area with ALL of its claims (Q826);
* ``osm_admin1.json`` -- ``admin_level=4`` regions keyed ISO 3166-2 (``FR-IDF``) where
  OSM carries the ``ISO3166-2`` tag, the relation id (``r8649``) as the fallback
  identity (Q314, Q804).

THE RULES THIS MODULE KEEPS, and the tests pin:

* NOTHING IS KEYED SILENTLY. Every region says how it was keyed (``key``), and the
  counts of each kind travel in the artifact, so the gap between tagged and
  fallback-keyed relations is a number anyone can read (brief S05-05 §2). A second
  relation carrying a code already taken is keyed by its own id and counted, never
  allowed to overwrite the first.
* NO CLAIM IS PICKED. A contested area carries every party its tags name
  (``claimed_by`` and ``disputed_by``); one naming fewer than two parties is kept and
  marked ``complete: false`` -- dropping it, or completing it from memory, would be
  the silent pick Q826 forbids.
* EVERY POLYGON FITS ITS PUBLISHED VERTEX CAP. Douglas-Peucker at a growing tolerance,
  then the smallest rings dropped, until the feature fits -- the largest outer ring is
  always kept, so no country or region vanishes from the map.
* THE VINTAGE IS REQUIRED. An artifact without the date of the data it was cut from
  would be a border with no "as of" -- the build refuses it.

Pure: no I/O, no network, no osmium import (the reader lives in the script).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from src.catalog.countries import to_iso2, to_iso3

SCHEMA = 1

# The PUBLISHED vertex caps (Q822: "published level-of-detail caps"). They are the
# defaults the build runs with; the maintainer's first run measures what they cost
# in bytes and the PR that ships the artifacts states that number (brief §6: "the
# LOD caps' numbers ... are measured first, then published").
ADMIN0_VERTEX_CAP = 1500      # per country, all rings together
ADMIN1_VERTEX_CAP = 300       # per region, all rings together
CONTESTED_VERTEX_CAP = 600    # per contested area
DEFAULT_PRECISION = 2         # decimal places of a degree kept (2 ~= 1.1 km)

ATTRIBUTION = "© OpenStreetMap contributors, ODbL 1.0"

# The twelve interface locales: a region's name travels in each the data carries.
UI_LANGS = ("en", "fr", "es", "de", "pt", "ru", "zh", "ja", "ar", "hi", "bn", "id")

_ISO3166_2 = re.compile(r"^[A-Z]{2}-[A-Z0-9]{1,3}$")
_VINTAGE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

Ring = list[list[float]]


@dataclass
class BoundaryRecord:
    """One assembled OSM boundary relation, as the build's reader hands it over."""

    osm_id: int
    tags: dict[str, str]
    outers: list[Ring]
    inners: list[Ring] = field(default_factory=list)


# ------------------------------------------------------------------ classification


def kind_of(tags: dict[str, str]) -> str | None:
    """``"admin0"`` | ``"admin1"`` | ``"contested"`` | None for a relation we do not use."""
    b = (tags.get("boundary") or "").strip()
    if b in ("disputed", "claim"):
        return "contested"
    if b != "administrative":
        return None
    lvl = (tags.get("admin_level") or "").strip()
    if lvl == "2":
        return "admin0"
    if lvl == "4":
        return "admin1"
    return None


def admin0_code(tags: dict[str, str]) -> str | None:
    """The country's ALPHA-3, from its own ``ISO3166-1:alpha2`` tag through ``to_iso3``.

    ``ISO3166-1`` (the older spelling of the same tag) is read when the first is absent.
    OSM publishes the alpha-2 code, so no other tag is asked for; a code this app does not
    recognise stays unkeyed (and counted) rather than trusted.
    """
    for key in ("ISO3166-1:alpha2", "ISO3166-1"):
        a3 = to_iso3(tags.get(key))
        if a3:
            return a3
    return None


def admin1_key(tags: dict[str, str], osm_id: int) -> tuple[str, str]:
    """``(key, how)``: the ISO 3166-2 code where OSM carries it, else ``r<relation id>``."""
    code = (tags.get("ISO3166-2") or "").strip().upper()
    if _ISO3166_2.match(code):
        return code, "iso3166-2"
    return f"r{osm_id}", "osm-relation"


def parties(tags: dict[str, str]) -> list[dict[str, str | None]]:
    """Every party a contested relation names, in the order its tags give them.

    ``claimed_by`` first, then ``disputed_by``; both are OSM's semicolon lists of
    alpha-2 codes. A code the converter does not know is KEPT with ``a3: None`` --
    it is still a claim the data makes, and hiding it would be a pick.
    """
    out: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for key in ("claimed_by", "disputed_by"):
        for raw in (tags.get(key) or "").split(";"):
            c = raw.strip().upper()
            if not c or c in seen:
                continue
            seen.add(c)
            out.append({"code": c, "a2": to_iso2(c), "a3": to_iso3(c)})
    return out


def names_of(tags: dict[str, str]) -> dict[str, str]:
    """The ``name:<lang>`` values the data carries for the twelve interface locales."""
    return {lg: tags[f"name:{lg}"] for lg in UI_LANGS if tags.get(f"name:{lg}")}


# ---------------------------------------------------------------------- geometry


def _round_ring(ring: Ring, precision: int) -> Ring:
    out: Ring = []
    for pt in ring:
        try:
            lon, lat = round(float(pt[0]), precision), round(float(pt[1]), precision)
        except (TypeError, ValueError, IndexError):
            continue
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            continue
        if out and out[-1] == [lon, lat]:
            continue
        out.append([lon, lat])
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()                                   # stored open; the renderer closes it
    return out


def _seg_dist(p: list[float], a: list[float], b: list[float]) -> float:
    ax, ay, bx, by, px, py = a[0], a[1], b[0], b[1], p[0], p[1]
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    qx, qy = ax + t * dx, ay + t * dy
    return ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5


def _dp(points: Ring, tol: float) -> Ring:
    """Douglas-Peucker on an open polyline (iterative: no recursion limit on a coast)."""
    n = len(points)
    if n < 3:
        return list(points)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        best, idx = -1.0, -1
        for k in range(i + 1, j):
            d = _seg_dist(points[k], points[i], points[j])
            if d > best:
                best, idx = d, k
        if idx >= 0 and best > tol:
            keep[idx] = True
            stack.append((i, idx))
            stack.append((idx, j))
    return [p for p, k in zip(points, keep, strict=True) if k]


def simplify_ring(ring: Ring, tol: float) -> Ring:
    """Simplify a CLOSED ring: split at the vertex farthest from the first, DP each half."""
    if len(ring) < 5 or tol <= 0:
        return list(ring)
    first = ring[0]
    far = max(range(len(ring)), key=lambda k: (ring[k][0] - first[0]) ** 2 + (ring[k][1] - first[1]) ** 2)
    a = _dp(ring[: far + 1], tol)
    b = _dp(ring[far:] + [first], tol)
    out = a[:-1] + b[:-1]
    return out if len(out) >= 3 else list(ring)


def _span(ring: Ring) -> float:
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return max(max(lons) - min(lons), max(lats) - min(lats)) if ring else 0.0


def fit_to_cap(outers: list[Ring], inners: list[Ring], cap: int, precision: int) -> tuple[list[Ring], bool]:
    """Rings (outers first, then holes) that fit ``cap`` vertices in total.

    Returns ``(rings, simplified)``. The tolerance starts at one unit of the kept
    precision and doubles; once it stops helping, the smallest rings (holes first,
    then islands) are dropped. The largest outer ring is never dropped.
    """
    outs = [r for r in (_round_ring(r, precision) for r in outers) if len(r) >= 3]
    ins = [r for r in (_round_ring(r, precision) for r in inners) if len(r) >= 3]
    if not outs:
        return [], False
    outs.sort(key=_span, reverse=True)
    ins.sort(key=_span, reverse=True)

    def total(rs: list[Ring]) -> int:
        return sum(len(r) for r in rs)

    if total(outs) + total(ins) <= cap:
        return outs + ins, False
    tol = 10.0 ** -precision
    cur_o, cur_i = outs, ins
    for _ in range(24):
        cur_o = [s for s in (simplify_ring(r, tol) for r in outs) if len(s) >= 3]
        cur_i = [s for s in (simplify_ring(r, tol) for r in ins) if len(s) >= 3]
        if not cur_o:                                # never lose the feature itself
            cur_o = [simplify_ring(outs[0], tol)]
        if total(cur_o) + total(cur_i) <= cap:
            return cur_o + cur_i, True
        tol *= 2
    # Still over: drop holes smallest-first, then islands smallest-first.
    while cur_i and total(cur_o) + total(cur_i) > cap:
        cur_i.pop()
    while len(cur_o) > 1 and total(cur_o) + total(cur_i) > cap:
        cur_o.pop()
    if total(cur_o) + total(cur_i) > cap:            # one ring, still too long: stride it
        r = cur_o[0]
        step = -(-len(r) // max(3, cap))
        cur_o = [r[::step]]
    return cur_o + cur_i, True


def _interior_point(ring: Ring) -> tuple[float, float] | None:
    """A point strictly inside a ring: the middle of the first span a scanline crosses."""
    if len(ring) < 3:
        return None
    lats = sorted({p[1] for p in ring})
    y = (lats[0] + lats[-1]) / 2
    if y in lats:                                     # avoid running along a vertex
        y += (lats[-1] - lats[0]) * 1e-6 or 1e-9
    xs = []
    n = len(ring)
    for k in range(n):
        (x1, y1), (x2, y2) = ring[k], ring[(k + 1) % n]
        if (y1 > y) != (y2 > y):
            xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    xs.sort()
    if len(xs) < 2:
        return None
    return ((xs[0] + xs[1]) / 2, y)


def point_in_rings(pt: tuple[float, float], rings: list[Ring]) -> bool:
    """Even-odd point-in-polygon over all rings (holes subtract by construction)."""
    x, y = pt
    inside = False
    for ring in rings:
        n = len(ring)
        for k in range(n):
            (x1, y1), (x2, y2) = ring[k], ring[(k + 1) % n]
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


# ---------------------------------------------------------------------- the build


def valid_vintage(v: str | None) -> bool:
    if not v or not _VINTAGE.match(v):
        return False
    try:
        date.fromisoformat(v)
    except ValueError:
        return False
    return True


def build_artifacts(
    records: list[BoundaryRecord],
    *,
    vintage: str,
    source: str,
    precision: int = DEFAULT_PRECISION,
    admin0_cap: int = ADMIN0_VERTEX_CAP,
    admin1_cap: int = ADMIN1_VERTEX_CAP,
    contested_cap: int = CONTESTED_VERTEX_CAP,
) -> tuple[dict, dict]:
    """``(admin0_doc, admin1_doc)`` from assembled boundary relations; pure.

    ``vintage`` is the date of the OSM data (``YYYY-MM-DD``); ``source`` names the file
    it was cut from (e.g. ``planet-260921.osm.pbf``). Raises ValueError without a
    valid vintage.
    """
    if not valid_vintage(vintage):
        raise ValueError("a boundary artifact needs the date of its OSM data (YYYY-MM-DD)")
    caps = {"admin0": admin0_cap, "admin1": admin1_cap, "contested": contested_cap, "precision": precision}
    meta = {"schema": SCHEMA, "source": source, "vintage": vintage, "attribution": ATTRIBUTION, "caps": caps}

    countries: dict[str, dict] = {}
    raw_admin0: dict[str, list[Ring]] = {}            # full-resolution rings, for placing regions
    unkeyed0: list[dict] = []
    dup0: list[dict] = []
    contested: list[dict] = []
    admin1_recs: list[BoundaryRecord] = []
    simplified = {"admin0": 0, "admin1": 0, "contested": 0}

    for rec in sorted(records, key=lambda r: r.osm_id):  # deterministic: same input, same bytes
        k = kind_of(rec.tags)
        if k == "admin1":
            admin1_recs.append(rec)
            continue
        if k == "admin0":
            a3 = admin0_code(rec.tags)
            label = {"osm": rec.osm_id, "name": rec.tags.get("name:en") or rec.tags.get("name") or ""}
            if not a3:
                unkeyed0.append(label)
                continue
            if a3 in countries:
                dup0.append({**label, "code": a3})
                continue
            rings, simp = fit_to_cap(rec.outers, rec.inners, admin0_cap, precision)
            if not rings:
                continue
            simplified["admin0"] += int(simp)
            raw_admin0[a3] = list(rec.outers) + list(rec.inners)
            countries[a3] = {
                "a2": to_iso2(a3),
                "name": rec.tags.get("name:en") or rec.tags.get("name") or a3,
                "names": names_of(rec.tags),
                "osm": rec.osm_id,
                "rings": rings,
            }
        elif k == "contested":
            rings, simp = fit_to_cap(rec.outers, rec.inners, contested_cap, precision)
            if not rings:
                continue
            simplified["contested"] += int(simp)
            who = parties(rec.tags)
            contested.append({
                "id": f"r{rec.osm_id}",
                "osm": rec.osm_id,
                "boundary": rec.tags.get("boundary"),
                "name": rec.tags.get("name:en") or rec.tags.get("name") or "",
                "names": names_of(rec.tags),
                "claims": who,
                "complete": len(who) >= 2,
                "rings": rings,
            })

    regions: dict[str, dict] = {}
    n_tagged = n_fallback = n_dup = n_unplaced = 0
    for rec in admin1_recs:
        key, how = admin1_key(rec.tags, rec.osm_id)
        if key in regions:                            # a code already taken: never overwrite
            key, how = f"r{rec.osm_id}", "osm-relation"
            n_dup += 1
        rings, simp = fit_to_cap(rec.outers, rec.inners, admin1_cap, precision)
        if not rings:
            continue
        simplified["admin1"] += int(simp)
        country = None
        placed_by = None
        if how == "iso3166-2":
            country, placed_by = to_iso3(key[:2]), "iso3166-2-prefix"
        if not country:
            country = to_iso3(rec.tags.get("is_in:country_code"))
            placed_by = "is_in:country_code" if country else None
        if not country and rec.outers:
            big = max(rec.outers, key=_span)
            pt = _interior_point(big)
            if pt:
                for a3, rs in raw_admin0.items():
                    if point_in_rings(pt, rs):
                        country, placed_by = a3, "inside-admin0"
                        break
        if not country:
            n_unplaced += 1
        if how == "iso3166-2":
            n_tagged += 1
        else:
            n_fallback += 1
        regions[key] = {
            "country": country,
            "a2": to_iso2(country) if country else None,
            "placed_by": placed_by,
            "name": rec.tags.get("name") or rec.tags.get("name:en") or key,
            "names": names_of(rec.tags),
            "osm": rec.osm_id,
            "key": how,
            "rings": rings,
        }

    def vcount(features) -> int:
        return sum(len(r) for f in features for r in f["rings"])

    admin0_doc = {
        **meta,
        "kind": "admin0",
        "method": (
            "OSM boundary=administrative admin_level=2 relations, keyed ISO 3166-1 alpha-3 from their "
            "own ISO3166-1:alpha2 tag; boundary=disputed and boundary=claim areas with every party their "
            "claimed_by and disputed_by tags name. Douglas-Peucker to the published vertex caps."
        ),
        "counts": {
            "countries": len(countries),
            "unkeyed": len(unkeyed0),
            "duplicate_codes": len(dup0),
            "contested": len(contested),
            "contested_incomplete": sum(1 for c in contested if not c["complete"]),
            "simplified": {"countries": simplified["admin0"], "contested": simplified["contested"]},
            "vertices": vcount(countries.values()) + vcount(contested),
        },
        "unkeyed": unkeyed0,
        "duplicates": dup0,
        "countries": countries,
        "contested": contested,
    }
    admin1_doc = {
        **meta,
        "kind": "admin1",
        "method": (
            "OSM boundary=administrative admin_level=4 relations, keyed ISO 3166-2 where the relation "
            "carries the ISO3166-2 tag and by its relation id (r<id>) otherwise; each region placed in a "
            "country by its code's prefix, its is_in:country_code tag, or a point inside it."
        ),
        "counts": {
            "regions": len(regions),
            "tagged": n_tagged,
            "fallback": n_fallback,
            "duplicate_codes": n_dup,
            "unplaced": n_unplaced,
            "simplified": simplified["admin1"],
            "vertices": vcount(regions.values()),
        },
        "regions": regions,
    }
    return admin0_doc, admin1_doc
