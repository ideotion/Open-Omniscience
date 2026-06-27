#!/usr/bin/env python3
"""
Reconcile catalog domains against Wikidata to fill source_type (+ some ownership).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Run on a machine WITH network access — Wikidata is egress-restricted in the
sandbox/CI (same as build_world_news_catalog.py). For each source missing a
source_type, it searches Wikidata by name, then verifies the candidate's official
website (P856) matches the source's domain before reading ``instance of`` (P31) —
so a wrong search hit yields nothing, never a wrong type (anti-fabrication gate in
src/catalog/wikidata_enrich.py).

Writes results in the row format scripts/merge_enrichment_results.py consumes, so
the normal additive merge folds them in (never overwriting curated values).

Examples:
  python scripts/enrich_sources_wikidata.py --limit 50 --out results/wikidata.yaml
  python scripts/enrich_sources_wikidata.py            # full run (slow; be polite)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
from src.catalog.wikidata_enrich import (  # noqa: E402
    parse_search_qids,
    reconcile,
    wbentities_url,
    wbsearch_url,
)

_SOURCES = _ROOT / "configs" / "sources.yml"
_UA = "OpenOmniscience-source-enricher/0.1 (local-first research app)"


def _fetch(url: str, getter=None) -> dict:
    if getter is not None:
        return json.loads(getter(url))
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 - documented Wikidata API
        return json.loads(r.read())


def enrich(sources: list[dict], *, getter=None, sleep: float = 0.2, log=print) -> list[dict]:
    """Reconcile each untyped source; one failure never aborts the run."""
    rows: list[dict] = []
    for s in sources:
        name, domain = s.get("name"), s.get("domain")
        if not name or not domain:
            continue
        try:
            qids = parse_search_qids(_fetch(wbsearch_url(name), getter))
            if not qids:
                continue
            payload = _fetch(wbentities_url(qids), getter)
            row = next(
                (r for r in (reconcile(payload, q, expected_domain=domain) for q in qids) if r),
                None,
            )
            if row:
                rows.append(row)
                log(f"  {domain} -> {row['source_type']} ({row['note']})")
        except Exception as e:  # noqa: BLE001 - one source's failure is not fatal
            log(f"  ! {domain}: {e}")
        if sleep:
            time.sleep(sleep)
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sources", type=Path, default=_SOURCES)
    ap.add_argument("--out", type=Path, default=_ROOT / "results" / "wikidata.yaml")
    ap.add_argument("--limit", type=int, default=0, help="cap sources processed (0 = all)")
    ap.add_argument("--sleep", type=float, default=0.2, help="politeness delay between sources")
    args = ap.parse_args(argv)

    data = yaml.safe_load(args.sources.read_text(encoding="utf-8"))
    todo = [s for s in (data.get("sources") or []) if not s.get("source_type")]
    if args.limit:
        todo = todo[: args.limit]
    print(f"Reconciling {len(todo)} untyped sources against Wikidata...")

    rows = enrich(todo, sleep=args.sleep)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(yaml.safe_dump(rows, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"\nResolved {len(rows)} source_type assignments -> {args.out}")
    print("Next: python scripts/merge_enrichment_results.py", args.out, "--min-confidence medium")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
