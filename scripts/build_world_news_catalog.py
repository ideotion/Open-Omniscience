#!/usr/bin/env python3
"""
Build the worldwide news + institutions source catalog from Wikidata.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Run this on a machine WITH network access (the app sandbox/CI may be egress
restricted). It queries Wikidata (CC0) per country for the source types defined
in configs/catalog_query.yml, normalises + dedups (excluding social networks and
domains already shipped in configs/sources.yml / configs/markets_sources.yml),
writes configs/world_news_sources.yml, and prints a country-coverage summary.

Examples:
  python scripts/build_world_news_catalog.py                      # full run
  python scripts/build_world_news_catalog.py --countries fr,jp,ke # a subset
  python scripts/build_world_news_catalog.py --merge-csv gdelt.csv --dry-run
  python scripts/build_world_news_catalog.py --source-types news  # news only

The optional --merge-csv folds in an external export (e.g. GDELT / Media Cloud):
a CSV with a url-or-domain column plus optional name/country/language columns.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

# Make `src` importable when run as a script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.catalog.build import (  # noqa: E402
    generate_catalog,
    load_query_config,
    write_catalog_yaml,
)
from src.catalog.countries import ISO_3166_1_ALPHA2  # noqa: E402
from src.catalog.coverage import coverage_report  # noqa: E402
from src.catalog.normalize import to_entry  # noqa: E402
from src.catalog.wikidata import WDQS_ENDPOINT, build_query  # noqa: E402

_OUT = Path(__file__).resolve().parents[1] / "configs" / "world_news_sources.yml"
_EXISTING = [
    Path(__file__).resolve().parents[1] / "configs" / "sources.yml",
    Path(__file__).resolve().parents[1] / "configs" / "markets_sources.yml",
]
_UA = (
    "OpenOmniscienceBot/0.4 (+https://github.com/ideotion/Open-Omniscience; "
    "catalog builder; contact open-omniscience@ideotion.com)"
)


def _existing_domains() -> set[str]:
    from src.ingest.seed_sources import load_sources_from_yaml

    domains: set[str] = set()
    for p in _EXISTING:
        if p.exists():
            domains.update(
                s["domain"].lower() for s in load_sources_from_yaml(p) if s.get("domain")
            )
    return domains


def _merge_csv_entries(path: Path, source_type: str) -> list[dict]:
    entries: list[dict] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols = {c.lower(): c for c in (reader.fieldnames or [])}
        url_c = cols.get("url") or cols.get("domain") or cols.get("website")
        name_c = cols.get("name") or cols.get("title") or url_c
        cc_c = cols.get("country") or cols.get("countrycode") or cols.get("country_code")
        lang_c = cols.get("language") or cols.get("lang")
        if not url_c:
            print(f"  ! {path}: no url/domain/website column found; skipping", file=sys.stderr)
            return entries
        for row in reader:
            e = to_entry(
                name=row.get(name_c) if name_c else row.get(url_c),
                url=row.get(url_c),
                country=row.get(cc_c) if cc_c else None,
                language=row.get(lang_c) if lang_c else None,
                source_type=source_type,
                tags=[source_type, "world-catalog", "imported"],
            )
            if e:
                entries.append(e)
    return entries


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--countries", help="comma-separated ISO alpha-2 subset (default: all)")
    ap.add_argument("--source-types", help="comma-separated subset of spec source_types to run")
    ap.add_argument("--config", type=Path, default=None, help="path to catalog_query.yml")
    ap.add_argument("--out", type=Path, default=_OUT, help="output catalog path")
    ap.add_argument(
        "--merge-csv",
        type=Path,
        action="append",
        default=[],
        help="external CSV (GDELT/Media Cloud) to fold in; repeatable",
    )
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between queries (be polite)")
    ap.add_argument("--dry-run", action="store_true", help="print stats, do not write the file")
    args = ap.parse_args()

    try:
        import requests
    except ImportError:
        print("This script needs `requests` (it is in core deps).", file=sys.stderr)
        return 2

    cfg = load_query_config(args.config)
    specs = cfg["specs"]
    if args.source_types:
        wanted = {s.strip() for s in args.source_types.split(",")}
        specs = [s for s in specs if s["source_type"] in wanted]
    if not specs:
        print("No specs to run (check --source-types / config).", file=sys.stderr)
        return 2

    codes = (
        [c.strip().lower() for c in args.countries.split(",")]
        if args.countries
        else sorted(ISO_3166_1_ALPHA2)
    )

    session = requests.Session()
    session.headers.update({"User-Agent": _UA, "Accept": "application/sparql-results+json"})

    def run_query(cc: str, type_qids: list[str]) -> dict:
        q = build_query(cc, type_qids, label_lang=cfg["label_lang"], limit=cfg["limit"])
        r = session.get(WDQS_ENDPOINT, params={"query": q, "format": "json"}, timeout=90)
        r.raise_for_status()
        return r.json()

    print(f"Querying Wikidata for {len(codes)} countries × {len(specs)} spec(s)…", file=sys.stderr)
    result = generate_catalog(
        run_query,
        codes,
        specs,
        existing_domains=_existing_domains(),
        sleep=(lambda: time.sleep(args.delay)) if args.delay else None,
        on_progress=lambda cc, n: print(f"  {cc}: {n}", file=sys.stderr),
    )
    sources = result["sources"]

    for csv_path in args.merge_csv:
        merged = _merge_csv_entries(Path(csv_path), source_type="news")
        print(f"  merged {len(merged)} from {csv_path}", file=sys.stderr)
        sources.extend(merged)
    # Final dedup pass (CSV merges can re-introduce dupes).
    from src.catalog.normalize import dedup_entries

    sources = dedup_entries(sources, _existing_domains())["kept"]

    counts: dict[str, int] = {}
    for s in sources:
        cc = s.get("country")
        if cc:
            counts[cc] = counts.get(cc, 0) + 1
    cov = coverage_report(counts)

    st = result["stats"]
    print(
        f"\nGenerated {len(sources)} sources; raw={st['raw_entries']} "
        f"dupes={st['skipped_dupes']} already-shipped={st['skipped_existing']} "
        f"errors={len(st['errors'])}",
        file=sys.stderr,
    )
    print(
        f"Country coverage: {cov['covered']}/{cov['total_countries']} "
        f"({cov['coverage_pct']}%); {cov['missing_count']} missing.",
        file=sys.stderr,
    )

    if args.dry_run:
        print("(dry-run: not writing)", file=sys.stderr)
        return 0
    write_catalog_yaml(args.out, sources)
    print(f"Wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
