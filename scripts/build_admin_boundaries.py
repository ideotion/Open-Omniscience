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
an extract) through the OSM lane's reader (``src/osm/reader.py``: pyosmium with the
``[geo]`` extra, pure Python for a small file). For the planet, filter it first so the
boundaries are a small file (osmium-tool):

  osmium tags-filter planet.osm.pbf \\
      r/boundary=administrative r/boundary=disputed r/boundary=claim \\
      -o boundaries.osm.pbf
  python scripts/build_admin_boundaries.py boundaries.osm.pbf --dry-run
  python scripts/build_admin_boundaries.py boundaries.osm.pbf

THE VINTAGE: the date of the OSM data is read from the file's own header
(``osmosis_replication_timestamp``, else ``timestamp``). A file whose header carries
neither needs ``--vintage YYYY-MM-DD``; the build refuses to write a border with no
"as of".

It also writes ``src/static/osm_borders/`` (a small world file plus one detail file per country,
``scripts/split_admin_boundaries.py``), which is what the map loads; ``--no-split`` skips it and removes the previous one, which would
describe an older build.

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

from src.osm.geometry import stitch  # noqa: E402
from src.osm.reader import open_extract  # noqa: E402
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
    """The data date from the file header (its replication timestamp), as ``YYYY-MM-DD``."""
    stamp = open_extract(path).header().replication_timestamp
    v = stamp.date().isoformat() if stamp else None
    return v if valid_vintage(v) else None


def read_boundaries(path: str, *, reader: str | None = None) -> tuple[list[BoundaryRecord], int]:
    """Every boundary relation the transform uses, with its rings, and the unclosed-segment count.

    Read through the OSM lane's ONE reader seam (``src.osm.reader.open_extract``: pyosmium
    with the ``[geo]`` extra, pure Python under its cap), and the rings joined by the lane's
    own ``stitch`` -- so the lane has one reader and one ring builder, not two. A segment
    that closes into no ring is COUNTED and reported, never bridged with a straight line.
    """
    ext = open_extract(path, reader=reader)
    wanted = [r for r in ext.relations() if kind_of(r.tags) is not None]
    way_ids = {m.ref for r in wanted for m in r.members if m.type == "w"}
    ways = {w.id: w.refs for w in ext.ways_by_id(way_ids)}
    node_ids = {n for refs in ways.values() for n in refs}
    locs = {n.id: [n.lon, n.lat] for n in ext.nodes_by_id(node_ids)}
    records: list[BoundaryRecord] = []
    unclosed = 0
    for rel in wanted:
        segs: dict[str, list[tuple[int, ...]]] = {"outer": [], "inner": []}
        for m in rel.members:
            if m.type == "w" and m.ref in ways:
                segs["inner" if m.role == "inner" else "outer"].append(ways[m.ref])
        rings: dict[str, list[list[list[float]]]] = {}
        for role, parts in segs.items():
            id_rings, dropped = stitch(parts)
            unclosed += dropped
            rings[role] = [[locs[n] for n in ring if n in locs] for ring in id_rings]
        records.append(BoundaryRecord(osm_id=rel.id, tags=dict(rel.tags), outers=rings["outer"], inners=rings["inner"]))
    return records, unclosed


def _write(doc: dict, path: Path) -> str:
    blob = json.dumps(doc, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(blob, encoding="utf-8")
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def write_outputs(admin0: dict, admin1: dict, out: Path, *, no_split: bool = False) -> None:
    """Write the two whole artifacts and keep ``osm_borders/`` in step with them (or remove it)."""
    from scripts.split_admin_boundaries import remove_split, write_split
    from src.timemap.admin_split import WORLD_PRECISION, WORLD_VERTEX_BUDGET

    s0 = _write(admin0, out / OUT_ADMIN0)
    s1 = _write(admin1, out / OUT_ADMIN1)
    print(f"Wrote {out / OUT_ADMIN0}  sha256 {s0}", file=sys.stderr)
    print(f"Wrote {out / OUT_ADMIN1}  sha256 {s1}", file=sys.stderr)
    if no_split:
        # A world file from the PREVIOUS build would be read first by the map and would outrank the
        # whole files just written, so skipping the split removes it rather than leaving it stale.
        if remove_split(out):
            print(f"Removed the previous {out / 'osm_borders'} (it described the old build).", file=sys.stderr)
        return
    # The map loads the split (a small world file, then a country's detail as it zooms in); the two
    # whole files stay what the server reads. One run keeps all three in step.
    try:
        rep = write_split(admin0, admin1, out, budget=WORLD_VERTEX_BUDGET, precision=WORLD_PRECISION)
    except BaseException:
        # The whole files above are already the NEW build. A split left from the previous one would be
        # read FIRST by the map and draw the old borders under the new "as of": remove it, so the map
        # falls back to the whole files, and let the failure through.
        remove_split(out)
        print("The split failed; the previous osm_borders/ was removed so the map reads the new whole "
              "files. Run scripts/split_admin_boundaries.py once the cause is fixed.", file=sys.stderr)
        raise
    print(json.dumps({"split": {k: v for k, v in rep.items() if k != "sha256"}}, indent=2))
    for w in rep.get("warnings", []):
        print("WARNING:", w, file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pbf", help="a local OpenStreetMap .osm.pbf (planet or extract), boundaries filtered")
    ap.add_argument("--reader", choices=("pyosmium", "python"), default=None,
                    help="force the lane's reader backend (default: pyosmium when installed)")
    ap.add_argument("--vintage", default=None, help="date of the OSM data, YYYY-MM-DD (else the file header)")
    ap.add_argument("--precision", type=int, default=DEFAULT_PRECISION, help="decimal places kept")
    ap.add_argument("--admin0-cap", type=int, default=ADMIN0_VERTEX_CAP, help="vertices per country")
    ap.add_argument("--admin1-cap", type=int, default=ADMIN1_VERTEX_CAP, help="vertices per region")
    ap.add_argument("--contested-cap", type=int, default=CONTESTED_VERTEX_CAP, help="vertices per contested area")
    ap.add_argument("--out-dir", default=str(_STATIC), help="where the two JSON files go")
    ap.add_argument("--no-split", action="store_true",
                    help="do not write the map's world + per-country detail files (scripts/split_admin_boundaries.py)")
    ap.add_argument("--dry-run", action="store_true", help="report counts and sizes, write nothing")
    args = ap.parse_args()

    vintage = args.vintage or header_vintage(args.pbf)
    if not valid_vintage(vintage):
        print("REFUSED: the file header carries no data date; pass --vintage YYYY-MM-DD.", file=sys.stderr)
        return 2
    print(f"Reading {args.pbf} (vintage {vintage}) …", file=sys.stderr)
    records, unclosed = read_boundaries(args.pbf, reader=args.reader)
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
        "unclosed_segments": unclosed,
        "admin0": {**c0, "bytes": size0},
        "admin1": {**c1, "bytes": size1},
        "unkeyed_countries": admin0["unkeyed"],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.dry_run:
        return 0
    write_outputs(admin0, admin1, Path(args.out_dir), no_split=args.no_split)
    print("Record both sha256 values and last_verified in configs/external_artifacts.yml.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
