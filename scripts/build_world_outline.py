#!/usr/bin/env python3
"""
Build the offline world-outline asset (src/static/world_outline.json).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Run ONCE, on a machine WITH network. Downloads the public-domain Natural Earth
1:110m land polygons (GeoJSON) and coarsens them into the compact
``{"rings": [...]}`` shape the temporal map renders as coastlines. Until you run
this, the temporal map falls back to a lat/lon graticule (it never fabricates
coastlines). Pure transform + tests live in src/timemap/outline.py.

Examples:
  python scripts/build_world_outline.py
  python scripts/build_world_outline.py --precision 1 --min-span 1.5 --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.timemap.outline import coarsen_geojson  # noqa: E402

# Natural Earth is public domain (no permission needed, no attribution required).
SOURCE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_110m_land.geojson"
)
_OUT = Path(__file__).resolve().parents[1] / "src" / "static" / "world_outline.json"
_UA = (
    "OpenOmniscienceBot/0.4 (+https://github.com/ideotion/Open-Omniscience; "
    "world outline builder; contact open-omniscience@ideotion.com)"
)


def fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (fixed public-domain URL)
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the offline world outline asset.")
    ap.add_argument("--url", default=SOURCE_URL, help="GeoJSON land source (public domain)")
    ap.add_argument("--precision", type=int, default=1, help="decimal places kept (1 ≈ 11 km)")
    ap.add_argument(
        "--min-span", type=float, default=1.0, help="drop islands smaller than N degrees"
    )
    ap.add_argument("--out", type=Path, default=_OUT)
    ap.add_argument("--dry-run", action="store_true", help="print stats, do not write")
    args = ap.parse_args()

    print(f"Fetching {args.url} …", file=sys.stderr)
    try:
        raw = fetch(args.url)
    except Exception as exc:  # noqa: BLE001
        print(f"  download failed: {exc}", file=sys.stderr)
        return 1

    out = coarsen_geojson(raw, precision=args.precision, min_span=args.min_span)
    out["source"] = args.url
    n_pts = sum(len(r) for r in out["rings"])
    payload = json.dumps(out, separators=(",", ":"))
    print(
        f"  {len(out['rings'])} rings · {n_pts} points · {len(payload) / 1024:.0f} KB",
        file=sys.stderr,
    )

    if args.dry_run:
        print("  (dry run — not written)", file=sys.stderr)
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(payload, encoding="utf-8")
    print(f"  wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
