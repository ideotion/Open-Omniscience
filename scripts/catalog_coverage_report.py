#!/usr/bin/env python3
"""
Catalog coverage report — the 0.09 de-US-centring acceptance metric.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Measures the SHIPPED catalogs (configs/*.yml — no database, no network) the same
way seeding will see them: explicit country values canonicalised through the one
conversion layer, missing ones backfilled from a reliable ccTLD. Prints global
coverage, the per-region balance against configs/catalog_targets.yml, and the
concentration guards. Every number is a real count; targets are clearly labelled
aspirations.

Usage:  python scripts/catalog_coverage_report.py [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.catalog.cctld import infer_country  # noqa: E402
from src.catalog.countries import country_display_name, normalize_country  # noqa: E402
from src.catalog.coverage import coverage_report, regional_report  # noqa: E402
from src.ingest import seed_sources as seeds  # noqa: E402


def gather_counts() -> tuple[Counter, int]:
    """Country counts over unique shipped-catalog domains (seed-equivalent view)."""
    seen: set[str] = set()
    counts: Counter = Counter()
    total = 0
    for path in (
        seeds.DEFAULT_SOURCES_PATH,
        seeds.MARKETS_SOURCES_PATH,
        seeds.WORLD_SOURCES_PATH,
        seeds.SPECTRUM_SOURCES_PATH,
        seeds.LEGAL_SOURCES_PATH,
    ):
        if not path.exists():
            continue
        for s in seeds.load_sources_from_yaml(path):
            domain = s["domain"]
            if domain in seen:
                continue
            seen.add(domain)
            total += 1
            cc = normalize_country(str(s.get("country") or "")) or infer_country(domain)
            if cc:
                counts[cc] += 1
    return counts, total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    counts, total = gather_counts()
    cov = coverage_report(counts)
    reg = regional_report(counts, total_sources=total)

    if args.json:
        print(json.dumps({"coverage": cov, "regional": reg}, indent=2))
        return 0

    print(f"Shipped catalog: {total} unique domains, "
          f"{reg['located_sources']} with a country "
          f"({reg.get('located_share_pct', 0)}% located; "
          f"floor {reg.get('min_located_share_pct')}%)")
    print(f"Countries covered: {cov['covered']}/{cov['total_countries']} "
          f"({cov['coverage_pct']}%) — {cov['missing_count']} missing, "
          f"{len(cov['thin'])} thin (<{cov['thin_threshold']} sources)")
    tc = reg["top_country"]
    flag = ""
    if tc["max_share_pct"] is not None and tc["share_pct"] > tc["max_share_pct"]:
        flag = f"  [ABOVE the {tc['max_share_pct']}% guard]"
    print(f"Top country: {country_display_name(tc['code'])} — "
          f"{tc['sources']} sources, {tc['share_pct']}% of located{flag}")
    print()
    print(f"{'Region':<15} {'sources':>8} {'floor':>6}   {'countries':>9} {'floor':>6}")
    for row in reg["regions"]:
        s_mark = {True: "ok", False: "SHORT", None: "-"}[row["sources_met"]]
        c_mark = {True: "ok", False: "SHORT", None: "-"}[row["countries_met"]]
        print(f"{row['region']:<15} {row['sources']:>8} "
              f"{str(row['min_sources'] or '-'):>6} {s_mark:<6}"
              f"{row['countries_covered']:>4}/{row['countries_total']:<4} "
              f"{str(row['min_countries'] or '-'):>6} {c_mark}")
    print()
    missing_named = [country_display_name(c) for c in cov["missing"]]
    print(f"Missing ({cov['missing_count']}): {', '.join(missing_named)}")
    if cov["extra_codes"]:
        print(f"Unrecognised values (fix these): {cov['extra_codes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
