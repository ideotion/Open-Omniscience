#!/usr/bin/env python3
"""
Build the OSM-derived boundary artifacts (0.5 row E, brief S05-05 S1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Writes ``src/static/osm_admin0.json`` (countries keyed ISO 3166-1 alpha-3, plus every
disputed / claimed area with all of its claims) and ``src/static/osm_admin1.json``
(admin_level=4 regions keyed ISO 3166-2, the relation id as the fallback), which every
ooMap surface draws in place of Natural Earth once they exist. The pure transform and
its rules live in ``src/timemap/admin_geo.py``.

RUN ON THE MAINTAINER'S MACHINE, from a file you downloaded yourself. This script opens
no network connection: it reads a local OpenStreetMap ``.osm.pbf`` (the planet file or
an extract) with pyosmium (``pip install osmium``, the ``[geo]`` extra). For the planet,
filter it first so the boundaries fit in memory (osmium-tool):

  osmium tags-filter planet.osm.pbf \\
      r/boundary=administrative r/boundary=disputed r/boundary=claim \\
      -o boundaries.osm.pbf
  python scripts/build_admin_boundaries.py boundaries.osm.pbf --dry-run
  python scripts/build_admin_boundaries.py boundaries.osm.pbf

THE VINTAGE: the date of the OSM data is read from the file's own header
(``osmosis_replication_timestamp``, else ``timestamp``). A file whose header carries
neither needs ``--vintage YYYY-MM-DD``; the build refuses to write a border with no
"as of".

Then record each artifact's sha256 and ``last_verified`` in
``configs/external_artifacts.yml`` (entries ``osm-admin0-boundaries`` and
``osm-admin1-boundaries``); the report printed here gives the counts the PR states.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.timemap.admin_geo import (  # noqa: E402
    ADMIN0_VERTEX_CAP,
    ADMIN1_VERTEX_CAP,
    CONTESTED_VERTEX_CAP,
    DEFAULT_PRECISION,
    BoundaryRecord,
    build_artifacts,
    kind_of,
    valid_vintage,
)

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
OUT_ADMIN0 = "osm_admin0.json"
OUT_ADMIN1 = "osm_admin1.json"


def header_vintage(path: str) -> str | None:
    """The data date from the file header, as ``YYYY-MM-DD``, or None."""
    import osmium  # the [geo] extra; imported here so the pure module never needs it

    reader = osmium.io.Reader(path, osmium.osm.osm_entity_bits.NOTHING)
    try:
        h = reader.header()
        for key in ("osmosis_replication_timestamp", "timestamp"):
            v = (h.get(key) or "").strip()
            if len(v) >= 10 and valid_vintage(v[:10]):
                return v[:10]
    finally:
        reader.close()
    return None


def read_boundaries(path: str) -> list[BoundaryRecord]:
    """Every boundary relation the transform uses, assembled into rings by libosmium."""
    import osmium

    records: list[BoundaryRecord] = []

    class _Areas(osmium.SimpleHandler):
        def area(self, a):  # noqa: ANN001 (pyosmium callback)
            if a.from_way():
                return
            tags = {t.k: t.v for t in a.tags}
            if kind_of(tags) is None:
                return
            outers, inners = [], []
            for outer in a.outer_rings():
                outers.append([[n.lon, n.lat] for n in outer if n.location.valid()])
                for inner in a.inner_rings(outer):
                    inners.append([[n.lon, n.lat] for n in inner if n.location.valid()])
            records.append(BoundaryRecord(osm_id=a.orig_id(), tags=tags, outers=outers, inners=inners))

    _Areas().apply_file(path, locations=True, idx="flex_mem")
    return records


def _write(doc: dict, path: Path) -> str:
    blob = json.dumps(doc, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(blob, encoding="utf-8")
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pbf", help="a local OpenStreetMap .osm.pbf (planet or extract), boundaries filtered")
    ap.add_argument("--vintage", default=None, help="date of the OSM data, YYYY-MM-DD (else the file header)")
    ap.add_argument("--precision", type=int, default=DEFAULT_PRECISION, help="decimal places kept")
    ap.add_argument("--admin0-cap", type=int, default=ADMIN0_VERTEX_CAP, help="vertices per country")
    ap.add_argument("--admin1-cap", type=int, default=ADMIN1_VERTEX_CAP, help="vertices per region")
    ap.add_argument("--contested-cap", type=int, default=CONTESTED_VERTEX_CAP, help="vertices per contested area")
    ap.add_argument("--out-dir", default=str(_STATIC), help="where the two JSON files go")
    ap.add_argument("--dry-run", action="store_true", help="report counts and sizes, write nothing")
    args = ap.parse_args()

    vintage = args.vintage or header_vintage(args.pbf)
    if not valid_vintage(vintage):
        print("REFUSED: the file header carries no data date; pass --vintage YYYY-MM-DD.", file=sys.stderr)
        return 2
    print(f"Reading {args.pbf} (vintage {vintage}) …", file=sys.stderr)
    records = read_boundaries(args.pbf)
    admin0, admin1 = build_artifacts(
        records,
        vintage=str(vintage),
        source=Path(args.pbf).name,
        precision=args.precision,
        admin0_cap=args.admin0_cap,
        admin1_cap=args.admin1_cap,
        contested_cap=args.contested_cap,
    )
    c0, c1 = admin0["counts"], admin1["counts"]
    size0 = len(json.dumps(admin0, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    size1 = len(json.dumps(admin1, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    report = {
        "vintage": vintage,
        "relations_read": len(records),
        "admin0": {**c0, "bytes": size0},
        "admin1": {**c1, "bytes": size1},
        "unkeyed_countries": admin0["unkeyed"],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.dry_run:
        return 0
    out = Path(args.out_dir)
    s0 = _write(admin0, out / OUT_ADMIN0)
    s1 = _write(admin1, out / OUT_ADMIN1)
    print(f"Wrote {out / OUT_ADMIN0}  sha256 {s0}", file=sys.stderr)
    print(f"Wrote {out / OUT_ADMIN1}  sha256 {s1}", file=sys.stderr)
    print("Record both sha256 values and last_verified in configs/external_artifacts.yml.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
