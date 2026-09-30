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
* ``osm_borders/detail/<ALPHA3>.json`` (the country's own unsimplified rings) and
  ``osm_borders/detail/<ALPHA3>.regions.json`` (its regions'), fetched by the map only when the
  view narrows to where they can be drawn. They are separate files because the two layers are
  drawn and budgeted separately: a view that draws countries only (regions switched off) must
  not download every region of every country in sight.

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
import math
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
#: The one path each layer's detail is read from (exact-matched by ``app-map.js``).
DETAIL_TEMPLATES = {"admin0": DETAIL_DIR + "/detail/{a3}.json", "admin1": DETAIL_DIR + "/detail/{a3}.regions.json"}
#: Boxes kept per simplified feature: one per ring, the largest rings first; the rest are merged.
MAX_BOXES = 64
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


def ring_boxes(rings: list[Ring] | None, cap: int = MAX_BOXES) -> list[list[float]]:
    """One box per ring (largest first), the smallest merged past ``cap``; rounded outward.

    One box per FEATURE says a country is in sight whenever any of it is: Russia and the USA cross
    the antimeridian, so their box spans the whole map and every view would fetch their files. A box
    per ring keeps the test as tight as the shape while still covering rings the world outline lost.
    """
    boxes = [b for b in (bbox([r]) for r in rings or []) if b]
    boxes.sort(key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)
    if len(boxes) > cap:
        rest = boxes[cap - 1:]
        boxes = boxes[:cap - 1] + [[min(b[0] for b in rest), min(b[1] for b in rest),
                                    max(b[2] for b in rest), max(b[3] for b in rest)]]
    return [[math.floor(b[0] * 1000) / 1000, math.floor(b[1] * 1000) / 1000,
             math.ceil(b[2] * 1000) / 1000, math.ceil(b[3] * 1000) / 1000] for b in boxes]


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
    size, so a coast keeps more than a square (:func:`_caps`). Each feature that lost anything (a
    vertex or a whole ring) also carries ``full_boxes``, the boxes of its UNSIMPLIFIED rings
    (:func:`ring_boxes`): a simplified outline can lose a far island altogether, and the map
    decides what is in sight from these boxes, so that island is not written off at every zoom.
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
        boxes = ring_boxes(f["rings"])
        lost = vertices(rings) < f["full_vertices"] or len(rings) < len(f["rings"])
        f["rings"] = rings
        if lost and boxes:                             # rounding alone can drop an islet too
            f["full_boxes"] = boxes
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

    ``{"admin0": doc, "admin1": doc, "details": {"admin0": {A3: doc}, "admin1": {A3: doc}},
    "stats": {...}}``. ``details`` is empty when neither layer exceeds ``budget`` (nothing to
    split); the world documents are then the canonical ones, each still carrying
    ``full_vertices`` so the reader has one code path.
    """
    if budget < MIN_FEATURE_VERTICES:
        raise ValueError(f"a world budget below {MIN_FEATURE_VERTICES} vertices cannot draw a country")
    if admin0.get("vintage") != admin1.get("vintage"):
        raise ValueError("the two boundary files come from different data dates; rebuild them together")
    w0, n0 = _simplify_layer(admin0, "admin0", budget, precision)
    w1, n1 = _simplify_layer(admin1, "admin1", budget, precision)

    details: dict[str, dict[str, dict]] = {"admin0": {}, "admin1": {}}
    for layer, canon, world in (("admin0", admin0, w0), ("admin1", admin1, w1)):
        for key, f in _features(canon, layer).items():
            a3 = _a3_of(layer, key, f)
            w = _features(world, layer)[key]
            if a3 is None or vertices(w.get("rings")) >= vertices(f.get("rings")):
                continue                               # the world file already holds all of it
            d = details[layer].setdefault(a3, {
                "schema": canon.get("schema", 1), "vintage": canon.get("vintage"), "a3": a3,
                "attribution": canon.get("attribution"),
                **({"country": None} if layer == "admin0" else {"regions": {}}),
            })
            if layer == "admin0":
                d["country"] = {"rings": f["rings"]}
            else:
                d["regions"][key] = {"rings": f["rings"]}

    for layer, w in (("admin0", w0), ("admin1", w1)):
        w["split"] = {
            "detail": DETAIL_TEMPLATES[layer] if details[layer] else None,
            "world_budget": budget,
            "world_precision": precision,
        }
    stats: dict[str, Any] = {
        "budget": budget,
        "detail_files": len(details["admin0"]) + len(details["admin1"]),
        "admin0": {"full": _sum(admin0, "admin0"), "world": _sum(w0, "admin0"), "simplified": n0},
        "admin1": {"full": _sum(admin1, "admin1"), "world": _sum(w1, "admin1"), "simplified": n1},
    }
    # A layer over the budget is drawn strided by the map (every outline halved): say so.
    stats["warnings"] = [
        f"{layer}: the world file holds {stats[layer]['world']} vertices, over the budget of {budget}; "
        "the map will stride every outline. Unplaced regions and per-feature floors are kept whole."
        for layer in ("admin0", "admin1") if stats[layer]["world"] > budget
    ]
    return {"admin0": w0, "admin1": w1, "details": details, "stats": stats}


def _sum(doc: dict[str, Any], layer: str) -> int:
    return sum(vertices(f.get("rings")) for f in _features(doc, layer).values())
