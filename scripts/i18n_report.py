#!/usr/bin/env python3
"""
i18n completeness report — measure how fully each UI locale covers the English source.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

English (``en.json``) is the canonical source: every chrome string the UI shows has a key
there. A locale is "complete" when it translates every English key; any missing key falls
back to English at runtime (so a partial locale never breaks the UI — it just shows some
English). This script makes that coverage visible and is safe to wire into CI as a soft
gate (``--min`` fails the build if a locale claiming ``status: complete`` regresses).

Usage:
    python scripts/i18n_report.py                 # human-readable table
    python scripts/i18n_report.py --json          # machine-readable
    python scripts/i18n_report.py --min 100       # exit 1 if a 'complete' locale < 100%
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_LOCALES = Path(__file__).resolve().parent.parent / "src" / "static" / "locales"


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _keys(data: dict) -> set[str]:
    return {k for k in data if k != "_meta"}


def build_report() -> dict:
    en = _load(_LOCALES / "en.json")
    source_keys = _keys(en)
    n = len(source_keys)
    locales = []
    for path in sorted(_LOCALES.glob("*.json")):
        code = path.stem
        if code == "en":
            continue
        data = _load(path)
        meta = data.get("_meta", {})
        have = _keys(data) & source_keys
        missing = sorted(source_keys - have)
        # Coverage = keys present (an *absent* key is what falls back to English at runtime).
        # A present key whose value equals the English source is counted as covered: in many
        # languages a term is a genuine loanword (Wikipedia, Briefing, Mode), so an identical
        # value is a deliberate translation, not a gap. We surface those separately as a hint.
        covered = len(have)
        identical = sorted(k for k in have if str(data.get(k, "")).strip() and data[k] == k)
        pct = round(100 * covered / n, 1) if n else 100.0
        locales.append({
            "code": code,
            "name": meta.get("name", code),
            "native": meta.get("native", ""),
            "declared_status": meta.get("status", "unknown"),
            "translated": covered,
            "total": n,
            "percent": pct,
            "missing": missing,
            "identical_to_english": identical,
        })
    locales.sort(key=lambda x: (-x["percent"], x["code"]))
    return {"source": "en", "source_keys": n, "locales": locales}


def _print_table(report: dict) -> None:
    print(f"i18n coverage — {report['source_keys']} English chrome keys\n")
    print(f"  {'locale':<8}{'name':<14}{'status':<11}{'coverage':>10}")
    print("  " + "-" * 43)
    for loc in report["locales"]:
        bar = f"{loc['translated']}/{loc['total']} ({loc['percent']}%)"
        print(f"  {loc['code']:<8}{loc['name']:<14}{loc['declared_status']:<11}{bar:>10}")
    stubs = [loc["code"] for loc in report["locales"] if loc["percent"] < 5]
    if stubs:
        print(f"\n  stub locales (≈English fallback): {', '.join(stubs)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="i18n completeness report")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    ap.add_argument("--min", type=float, default=None,
                    help="fail (exit 1) if any locale declaring status:complete is below this %%")
    args = ap.parse_args(argv)

    report = build_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_table(report)

    if args.min is not None:
        regressed = [loc for loc in report["locales"]
                     if loc["declared_status"] == "complete" and loc["percent"] < args.min]
        if regressed:
            names = ", ".join(f"{loc['code']} ({loc['percent']}%)" for loc in regressed)
            print(f"\nFAIL: locales declared 'complete' below {args.min}%: {names}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
