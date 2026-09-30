#!/usr/bin/env python3
"""
Split the OSM boundary artifacts into a small world file and per-country detail files.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Reads ``src/static/osm_admin0.json`` and ``src/static/osm_admin1.json`` (the whole-detail
artifacts ``scripts/build_admin_boundaries.py`` writes) and writes, next to them, the files the
MAP loads (``src/timemap/admin_split.py`` says why and what the rules are)::

  src/static/osm_borders/admin0.world.json
  src/static/osm_borders/admin1.world.json
  src/static/osm_borders/detail/<ALPHA3>.json   (one per country whose outlines were simplified)

``build_admin_boundaries.py`` runs this itself after writing the two whole files; run it alone
to split a pair that was built before the split existed. It opens no network connection and
replaces the whole ``osm_borders/`` directory in one rename, so a rebuild never leaves a country's
old outline behind and a browser never reads half of one build and half of another.

  python scripts/split_admin_boundaries.py --dry-run
  python scripts/split_admin_boundaries.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.timemap.admin_split import (  # noqa: E402
    DETAIL_DIR,
    MIN_FEATURE_VERTICES,
    WORLD_FILES,
    WORLD_PRECISION,
    WORLD_VERTEX_BUDGET,
    split_artifacts,
)

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"


def _blob(doc: dict) -> str:
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def write_split(admin0: dict, admin1: dict, out_dir: Path, *, budget: int, precision: int, dry_run: bool = False) -> dict:
    """Split and (unless ``dry_run``) write; returns the report. Pure enough to test on a tmp dir."""
    res = split_artifacts(admin0, admin1, budget=budget, precision=precision)
    blobs = {WORLD_FILES["admin0"]: _blob(res["admin0"]), WORLD_FILES["admin1"]: _blob(res["admin1"])}
    for a3, doc in sorted(res["details"].items()):
        blobs[f"{DETAIL_DIR}/detail/{a3}.json"] = _blob(doc)
    sizes = {name: len(b.encode("utf-8")) for name, b in blobs.items()}
    report = {
        **res["stats"],
        "world_bytes": sizes[WORLD_FILES["admin0"]] + sizes[WORLD_FILES["admin1"]],
        "detail_bytes": sum(v for k, v in sizes.items() if "/detail/" in k),
        "largest_detail": max((v for k, v in sizes.items() if "/detail/" in k), default=0),
    }
    if dry_run:
        return report
    # Written beside the live directory and swapped in, so a run that dies half way (or a browser
    # that loads while it runs) never sees a world file from one build and details from another.
    root = out_dir / DETAIL_DIR
    tmp = out_dir / f".{DETAIL_DIR}.new"
    old = out_dir / f".{DETAIL_DIR}.old"
    for leftover in (tmp, old):
        shutil.rmtree(leftover, ignore_errors=True)
    (tmp / "detail").mkdir(parents=True)
    try:
        for name, blob in blobs.items():
            (tmp / Path(name).relative_to(DETAIL_DIR)).write_text(blob, encoding="utf-8")
        if root.exists():
            root.rename(old)
        tmp.rename(root)
    except BaseException:
        if old.exists() and not root.exists():
            old.rename(root)
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    shutil.rmtree(old, ignore_errors=True)
    report["sha256"] = {name: hashlib.sha256(b.encode("utf-8")).hexdigest() for name, b in blobs.items() if "/detail/" not in name}
    return report


def remove_split(out_dir: Path) -> bool:
    """Delete ``osm_borders/``: the world files a build no longer backs must not outlive it."""
    root = out_dir / DETAIL_DIR
    existed = root.exists()
    shutil.rmtree(root, ignore_errors=True)
    return existed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in-dir", default=str(_STATIC), help="where osm_admin0.json and osm_admin1.json are")
    ap.add_argument("--out-dir", default=str(_STATIC), help="where osm_borders/ goes")
    ap.add_argument("--world-budget", type=int, default=WORLD_VERTEX_BUDGET,
                    help="vertices one layer draws in a world view (paint time, not storage)")
    ap.add_argument("--world-precision", type=int, default=WORLD_PRECISION, help="decimal places the world file keeps")
    ap.add_argument("--dry-run", action="store_true", help="report sizes, write nothing")
    args = ap.parse_args()
    if args.world_budget < MIN_FEATURE_VERTICES:
        print(f"REFUSED: a world budget below {MIN_FEATURE_VERTICES} vertices cannot draw a country.", file=sys.stderr)
        return 2
    src = Path(args.in_dir)
    try:
        admin0 = json.loads((src / "osm_admin0.json").read_text(encoding="utf-8"))
        admin1 = json.loads((src / "osm_admin1.json").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        print(f"REFUSED: {exc.filename} is not there; build it first (scripts/build_admin_boundaries.py).", file=sys.stderr)
        return 2
    try:
        report = write_split(admin0, admin1, Path(args.out_dir), budget=args.world_budget,
                             precision=args.world_precision, dry_run=args.dry_run)
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    if not args.dry_run:
        print(f"Wrote {Path(args.out_dir) / DETAIL_DIR}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
