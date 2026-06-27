#!/usr/bin/env python3
"""
Merge parallel-session enrichment results back into configs/sources.yml — ADDITIVELY.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Takes the YAML the classification sessions produced (see PROMPT_TEMPLATE.md) and
folds it into the catalog by ``domain``. The merge is conservative by design so it
can never undo curated work or fabricate:

  - tags are UNIONED, never replaced. ``topics`` + ``ownership`` + ``lean`` all
    become tags (the existing convention: configs/sources_spectrum.yml already
    encodes lean/ownership as tags), so no schema change is needed.
  - ``source_type`` is set only when the existing value is missing or the bare
    default ``news`` (a curated non-default type is never overwritten).
  - ``country`` / ``language`` are filled only when currently absent (never
    overwritten — the catalog's own values and the by-hand demonym pass win).
  - rows below --min-confidence are skipped; unmatched domains are reported, not
    invented as new sources (use the catalog builder for net-new entries).

Default is a DRY RUN (prints a diff summary). Pass --write to apply.

Examples:
  python scripts/merge_enrichment_results.py results/*.yaml
  python scripts/merge_enrichment_results.py results/ --min-confidence medium --write
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_SOURCES = _ROOT / "configs" / "sources.yml"

_CONF_RANK = {"low": 0, "medium": 1, "high": 2}
# Controlled tag namespaces we accept from results (defence against typo'd junk).
_OWNERSHIP = {
    "independent", "state-owned", "public-broadcaster", "state-media",
    "corporate", "party-affiliated", "nonprofit", "cooperative", "wire-agency",
}
_LEAN = {
    "lean-left", "lean-center-left", "center", "lean-center-right", "lean-right",
}


def _load_results(paths: list[Path]) -> list[dict]:
    rows: list[dict] = []
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(p.glob("*.yaml")) + sorted(p.glob("*.yml")))
        else:
            files.append(p)
    for f in files:
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and "sources" in doc:
            doc = doc["sources"]
        if isinstance(doc, list):
            rows.extend(r for r in doc if isinstance(r, dict) and r.get("domain"))
        else:
            print(f"WARN: {f} is not a list of rows; skipped", file=sys.stderr)
    return rows


def _clean_tags(row: dict) -> list[str]:
    """topics + a valid ownership + a valid lean, lowercased, deduped, order-stable."""
    out: list[str] = []
    for t in row.get("topics") or []:
        t = str(t).strip().lower()
        if t:
            out.append(t)
    own = str(row.get("ownership") or "").strip().lower()
    if own in _OWNERSHIP:
        out.append(own)
    lean = str(row.get("lean") or "").strip().lower()
    if lean in _LEAN:
        out.append(lean)
    seen: set[str] = set()
    deduped = []
    for t in out:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


def merge(
    sources: list[dict], results: list[dict], *, min_conf: str
) -> dict:
    by_domain = {s.get("domain"): s for s in sources if s.get("domain")}
    floor = _CONF_RANK.get(min_conf, 1)
    stats = {
        "matched": 0, "unmatched": 0, "skipped_conf": 0,
        "tags_added": 0, "type_set": 0, "country_set": 0, "language_set": 0,
    }
    unmatched: list[str] = []
    for r in results:
        dom = str(r.get("domain") or "").strip().lower()
        if _CONF_RANK.get(str(r.get("confidence") or "low").lower(), 0) < floor:
            stats["skipped_conf"] += 1
            continue
        src = by_domain.get(dom)
        if not src:
            stats["unmatched"] += 1
            unmatched.append(dom)
            continue
        stats["matched"] += 1
        # tags: union
        existing = list(src.get("tags") or [])
        before = set(existing)
        for t in _clean_tags(r):
            if t not in before:
                existing.append(t)
                before.add(t)
                stats["tags_added"] += 1
        src["tags"] = existing
        # source_type: set only if missing/default
        new_type = str(r.get("source_type") or "").strip().lower()
        if new_type and (not src.get("source_type") or src.get("source_type") == "news"):
            if src.get("source_type") != new_type:
                src["source_type"] = new_type
                stats["type_set"] += 1
        # country / language: fill only when absent
        cc = str(r.get("country") or "").strip().lower()
        if cc and len(cc) == 2 and not src.get("country"):
            src["country"] = cc
            stats["country_set"] += 1
        lang = str(r.get("language") or "").strip().lower()
        if lang and not src.get("language"):
            src["language"] = lang
            stats["language_set"] += 1
    return {"stats": stats, "unmatched": unmatched}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("results", nargs="+", type=Path, help="result .yaml files or dirs")
    ap.add_argument("--sources", type=Path, default=_SOURCES)
    ap.add_argument("--min-confidence", choices=["low", "medium", "high"], default="medium")
    ap.add_argument("--write", action="store_true", help="apply (default: dry run)")
    args = ap.parse_args(argv)

    data = yaml.safe_load(args.sources.read_text(encoding="utf-8"))
    sources = data.get("sources") or []
    results = _load_results(args.results)
    print(f"Loaded {len(results)} result rows; catalog has {len(sources)} sources.")

    report = merge(sources, results, min_conf=args.min_confidence)
    s = report["stats"]
    print(
        f"matched={s['matched']} unmatched={s['unmatched']} "
        f"skipped(low-conf)={s['skipped_conf']}\n"
        f"would set: +{s['tags_added']} tags, {s['type_set']} source_type, "
        f"{s['country_set']} country, {s['language_set']} language"
    )
    if report["unmatched"]:
        print(f"\nUnmatched domains ({len(report['unmatched'])}, first 20):")
        for d in report["unmatched"][:20]:
            print(f"  {d}")

    if args.write:
        args.sources.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000),
            encoding="utf-8",
        )
        print(f"\nWROTE {args.sources}")
    else:
        print("\n(dry run — pass --write to apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
