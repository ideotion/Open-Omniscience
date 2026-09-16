#!/usr/bin/env python3
"""
Build the offline CONTESTED-areas asset (src/static/world_disputed.json).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Run ONCE, on a machine WITH network. Downloads the public-domain Natural Earth
admin-0 breakaway/disputed areas AND the admin-0 countries of the same scale -- the
second is what resolves each viewpoint's alpha-3 claim code to a country, so the two
must come from one release or the codes drift apart.

WHY IT EXISTS (maintainer rulings Q826 and Q803, 2026-09-15): every disputed area is
rendered CONTESTED showing BOTH claims, never a silent pick, and the user can see the
difference between conventions with a toggle. Natural Earth records an
``ADM0_A3_<POV>`` per point of view on each feature, so both halves are read out of
the data rather than curated by hand here.

Until you run this, the map simply has no contested layer -- it never invents one.

Examples:
  python scripts/build_disputed_areas.py
  python scripts/build_disputed_areas.py --precision 2 --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.timemap.disputed_geo import claim_index, coarsen_disputed  # noqa: E402

# Served from the upstream project's own git mirror; see build_country_polygons.py.
_BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson"
SCALES = ("50m", "10m")
DEFAULT_SCALE = "50m"          # matches the admin-0 asset's scale (Q802)
_OUT = Path(__file__).resolve().parents[1] / "src" / "static" / "world_disputed.json"
_UA = (
    "OpenOmniscienceBot/0.4 (+https://github.com/ideotion/Open-Omniscience; "
    "disputed-areas builder; contact open-omniscience@ideotion.com)"
)


def _url(scale: str, layer: str) -> str:
    return f"{_BASE}/ne_{scale}_admin_0_{layer}.geojson"


def fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 (fixed public-domain URL)
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scale", choices=SCALES, default=DEFAULT_SCALE)
    ap.add_argument("--precision", type=int, default=2, help="decimal places kept (2 ~ 1.1 km)")
    ap.add_argument("--dry-run", action="store_true", help="report size, do not write")
    args = ap.parse_args()

    # 50m has no disputed layer of its own; the breakaway_disputed layer is the one
    # Natural Earth publishes at that scale.
    dis_url = _url(args.scale, "breakaway_disputed_areas")
    adm_url = _url(args.scale, "countries")
    print(f"Fetching {dis_url} …", file=sys.stderr)
    disputed = fetch(dis_url)
    print(f"Fetching {adm_url} …", file=sys.stderr)
    admin0 = fetch(adm_url)

    disputed.setdefault("source", f"natural-earth-{args.scale}-breakaway-disputed")
    index = claim_index(admin0, disputed)
    asset = coarsen_disputed(disputed, index=index, precision=args.precision)

    areas = asset["areas"]
    no_claim = [a["name"] for a in areas if not a["claims"]]
    blob = json.dumps(asset, separators=(",", ":"), ensure_ascii=False)
    print(
        f"{len(areas)} contested areas, "
        f"{sum(len(a['rings']) for a in areas)} rings, "
        f"{sum(len(r) for a in areas for r in a['rings'])} coordinate pairs, "
        f"{len(blob) / 1024:.0f} KB (scale={args.scale}, precision={args.precision})",
        file=sys.stderr,
    )
    # An area whose claimants cannot be resolved would render as contested with an
    # empty claim list -- honest, but worth seeing, because it usually means the
    # admin-0 release and the disputed release disagree about a code.
    if no_claim:
        print(f"NOTE: {len(no_claim)} area(s) resolved no claimant: {', '.join(no_claim)}", file=sys.stderr)
    if args.dry_run:
        return 0
    _OUT.write_text(blob, encoding="utf-8")
    print(f"Wrote {_OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
