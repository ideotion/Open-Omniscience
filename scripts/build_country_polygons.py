#!/usr/bin/env python3
"""
Build the offline country-polygons asset (src/static/world_countries.json).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Run ONCE, on a machine WITH network. Downloads the public-domain Natural Earth
1:110m admin-0 countries (GeoJSON) and coarsens them into the compact
``{"countries": {iso2: {"name", "rings"}}}`` shape the universal map (ooMap) fills
to draw a choropleth. Until you run this, the map has no country fills (it never
fabricates borders). Pure transform + tests live in src/timemap/countries_geo.py.

Examples:
  python scripts/build_country_polygons.py
  python scripts/build_country_polygons.py --precision 1 --min-span 0.8 --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.timemap.countries_geo import coarsen_admin0  # noqa: E402

# Natural Earth is public domain (no permission needed, no attribution required).
SOURCE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_110m_admin_0_countries.geojson"
)
_OUT = Path(__file__).resolve().parents[1] / "src" / "static" / "world_countries.json"
_UA = (
    "OpenOmniscienceBot/0.4 (+https://github.com/ideotion/Open-Omniscience; "
    "country polygons builder; contact open-omniscience@ideotion.com)"
)


def fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (fixed public-domain URL)
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--precision", type=int, default=1, help="decimal places kept (1 ≈ 11 km)")
    ap.add_argument("--min-span", type=float, default=0.8, help="drop islands smaller than N degrees")
    ap.add_argument("--url", default=SOURCE_URL)
    ap.add_argument("--dry-run", action="store_true", help="report size, do not write")
    args = ap.parse_args()

    print(f"Fetching {args.url} …", file=sys.stderr)
    geojson = fetch(args.url)
    geojson.setdefault("source", "natural-earth-110m-admin-0")
    asset = coarsen_admin0(geojson, precision=args.precision, min_span=args.min_span)

    countries = asset["countries"]
    n_rings = sum(len(c["rings"]) for c in countries.values())
    blob = json.dumps(asset, separators=(",", ":"), ensure_ascii=False)
    print(
        f"{len(countries)} countries, {n_rings} rings, {len(blob) / 1024:.0f} KB "
        f"(precision={args.precision}, min_span={args.min_span})",
        file=sys.stderr,
    )
    if args.dry_run:
        return 0
    _OUT.write_text(blob, encoding="utf-8")
    print(f"Wrote {_OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
