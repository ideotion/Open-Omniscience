"""Split the OSM boundary artifacts into a small WORLD file and per-country DETAIL files.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``osm_admin0.json`` / ``osm_admin1.json`` (``src/timemap/admin_geo.py``) carry every country and
region at the detail the build published, about 0.1 km. A world view draws a few tens of
thousands of vertices of them and throws the rest away, yet the browser had to fetch and parse
all of it first (walked 2026-09-30: about 20 s to read both files, 26 to 36 s to the first
paint, at the size a full build reaches). This module cuts the same data in two:

* ``osm_borders/admin0.world.json`` and ``osm_borders/admin1.world.json`` -- the SAME documents,
  key for key, with every feature's rings simplified (Douglas-Peucker) so a layer totals about
  :data:`WORLD_VERTEX_BUDGET` vertices. Every country and region is present. Each feature adds
  ``full_vertices``, the size of its unsimplified rings, and the document adds ``split``, which
  says where the detail lives;
* ``osm_borders/detail/<ALPHA3>.json`` -- the unsimplified rings of ONE country and its regions,
  fetched by the map only when the view narrows to where they can be drawn.

THE RULES THIS MODULE KEEPS, and the tests pin:

* NOTHING IS LOST OR INVENTED. A detail file holds the input's own rings, byte for byte; the
  world file is the input simplified, never redrawn. The canonical files stay whole, because
  the server reads them too (region completeness).
* NO FEATURE VANISHES. Every feature keeps at least its largest ring at every scale.
* THE BUDGET NAMES WHAT IT PROTECTS. :data:`WORLD_VERTEX_BUDGET` is what ONE map draws per
  layer in a world view (``OOMAP_ADMIN1_VERTEX_CAP`` in ``app-map.js``, held equal by a test):
  paint time, not storage. A build whose layer already fits it is not split.
* A REGION THAT NO COUNTRY CLAIMS stays whole in the world file: it has no detail file to
  come from, and there are few of them (the build counts them as ``unplaced``).

Pure: no I/O and no network. ``scripts/split_admin_boundaries.py`` reads and writes the files.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from src.timemap.admin_geo import fit_to_cap

#: Vertices ONE layer draws in a world view. Equal to ``OOMAP_ADMIN1_VERTEX_CAP`` in
#: ``src/static/app-map.js`` (tests/test_admin_split.py pins the two), because the world file
#: is exactly what a world view draws: this is a paint-time bound, not a size on disk.
WORLD_VERTEX_BUDGET = 120_000

#: Decimal places of a degree the WORLD file keeps (2 ~= 1 km; the detail keeps the input's).
WORLD_PRECISION = 2

#: A feature is never simplified below this many vertices (a triangle plus room to be a coast).
MIN_FEATURE_VERTICES = 12

DETAIL_DIR = "osm_borders"
DETAIL_TEMPLATE = DETAIL_DIR + "/detail/{a3}.json"
WORLD_FILES = {"admin0": DETAIL_DIR + "/admin0.world.json", "admin1": DETAIL_DIR + "/admin1.world.json"}

_A3 = re.compile(r"^[A-Z]{3}$")

Ring = list[list[float]]


def vertices(rings: list[Ring] | None) -> int:
    return sum(len(r) for r in rings or [])


def _features(doc: dict[str, Any], layer: str) -> dict[str, dict]:
    return doc["countries"] if layer == "admin0" else doc["regions"]


def _a3_of(layer: str, key: str, feature: dict) -> str | None:
    """The alpha-3 a feature's detail file is named by, or None (no file)."""
    a3 = key if layer == "admin0" else feature.get("country")
    return a3 if isinstance(a3, str) and _A3.match(a3) else None


#: The share of the budget the allocation aims at. Douglas-Peucker lands a little off any cap
#: (a ring keeps its endpoints, precision rounding merges neighbours), so aiming at the budget
#: exactly would leave a layer just over it, and one vertex over is a stride of 2 that halves
#: every outline in a world view. 96% leaves room for that; the test asserts the total stays under.
BUDGET_AIM = 0.96


def bbox(rings: list[Ring] | None) -> list[float] | None:
    """[west, south, east, north] of ``rings``, or None when there is no vertex."""
    xs = [p[0] for r in rings or [] for p in r]
    ys = [p[1] for r in rings or [] for p in r]
    return [min(xs), min(ys), max(xs), max(ys)] if xs else None


def _caps(sizes: dict[str, int], reserved: int, budget: int) -> dict[str, int]:
    """Per-feature vertex caps that sum to about ``budget`` less what is ``reserved``.

    Proportional to each feature's own size, but never below :data:`MIN_FEATURE_VERTICES`. A
    feature that floor binds is pinned at the floor and the rest are rescaled (water-filling),
    otherwise the floors would push the layer over the budget; what stays whole (``reserved``)
    is taken off the top for the same reason.
    """
    left = max(0.0, budget * BUDGET_AIM - reserved)
    free = dict(sizes)
    caps: dict[str, int] = {}
    while free:
        total = sum(free.values())
        scale = left / total if total else 1.0
        pinned = [k for k, n in free.items() if n * scale < MIN_FEATURE_VERTICES]
        if not pinned:
            caps.update({k: max(MIN_FEATURE_VERTICES, int(n * scale)) for k, n in free.items()})
            break
        for k in pinned:
            caps[k] = MIN_FEATURE_VERTICES
            left = max(0.0, left - min(free[k], MIN_FEATURE_VERTICES))
            del free[k]
    return caps


def _simplify_layer(doc: dict[str, Any], layer: str, budget: int, precision: int) -> tuple[dict[str, Any], int]:
    """A copy of ``doc`` whose ``layer`` features are simplified to about ``budget`` vertices.

    Returns ``(world_doc, n_simplified)``. The allocation is proportional to each feature's own
    size, so a coast keeps more than a square (:func:`_caps`). Each feature that is simplified
    also carries ``full_bbox``, the box of its UNSIMPLIFIED rings: a simplified outline can lose
    a far island altogether, and the map decides what is in sight from this box, so that island
    is not written off at every zoom.
    """
    world = copy.deepcopy(doc)
    feats = _features(world, layer)
    total = sum(vertices(f.get("rings")) for f in feats.values())
    for f in feats.values():
        f["full_vertices"] = vertices(f.get("rings"))
    n_simplified = 0
    if total <= budget:
        return world, n_simplified
    placeable = {k: f["full_vertices"] for k, f in feats.items() if f.get("rings") and _a3_of(layer, k, f) is not None}
    reserved = total - sum(placeable.values())         # no detail file could carry these: kept whole
    caps = _caps(placeable, reserved, budget)
    for key, cap in caps.items():
        f = feats[key]
        if f["full_vertices"] <= cap:
            continue
        rings, simplified = fit_to_cap(f["rings"], [], cap, precision, refine=True)
        if not rings:                                  # never lose the feature itself
            continue
        box = bbox(f["rings"])
        f["rings"] = rings
        if simplified and box:
            f["full_bbox"] = box
        n_simplified += int(simplified)
    return world, n_simplified


def split_artifacts(
    admin0: dict[str, Any],
    admin1: dict[str, Any],
    *,
    budget: int = WORLD_VERTEX_BUDGET,
    precision: int = WORLD_PRECISION,
) -> dict[str, Any]:
    """The world documents and the detail documents for a pair of canonical artifacts.

    ``{"admin0": doc, "admin1": doc, "details": {A3: doc}, "stats": {...}}``. ``details`` is empty
    when neither layer exceeds ``budget`` (nothing to split); the world documents are then the
    canonical ones, each still carrying ``full_vertices`` so the reader has one code path.
    """
    if budget < MIN_FEATURE_VERTICES:
        raise ValueError(f"a world budget below {MIN_FEATURE_VERTICES} vertices cannot draw a country")
    if admin0.get("vintage") != admin1.get("vintage"):
        raise ValueError("the two boundary files come from different data dates; rebuild them together")
    w0, n0 = _simplify_layer(admin0, "admin0", budget, precision)
    w1, n1 = _simplify_layer(admin1, "admin1", budget, precision)

    details: dict[str, dict] = {}
    for layer, canon, world in (("admin0", admin0, w0), ("admin1", admin1, w1)):
        for key, f in _features(canon, layer).items():
            a3 = _a3_of(layer, key, f)
            w = _features(world, layer)[key]
            if a3 is None or vertices(w.get("rings")) >= vertices(f.get("rings")):
                continue                               # the world file already holds all of it
            d = details.setdefault(a3, {
                "schema": canon.get("schema", 1), "vintage": canon.get("vintage"), "a3": a3,
                "attribution": canon.get("attribution"), "country": None, "regions": {},
            })
            if layer == "admin0":
                d["country"] = {"rings": f["rings"]}
            else:
                d["regions"][key] = {"rings": f["rings"]}

    split = {
        "detail": DETAIL_TEMPLATE if details else None,
        "world_budget": budget,
        "world_precision": precision,
    }
    for w in (w0, w1):
        w["split"] = dict(split)
    stats = {
        "budget": budget,
        "detail_files": len(details),
        "admin0": {"full": _sum(admin0, "admin0"), "world": _sum(w0, "admin0"), "simplified": n0},
        "admin1": {"full": _sum(admin1, "admin1"), "world": _sum(w1, "admin1"), "simplified": n1},
    }
    return {"admin0": w0, "admin1": w1, "details": details, "stats": stats}


def _sum(doc: dict[str, Any], layer: str) -> int:
    return sum(vertices(f.get("rings")) for f in _features(doc, layer).values())
