#!/usr/bin/env python3
"""
Report the freshness of every registered external artifact (network-free).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Reads configs/external_artifacts.yml via src/maintenance/registry.py and prints a status
line per artifact. Exits NON-ZERO when anything is ``stale`` (past its freshness window
or a version coupling broke), so it can gate CI or drive the (separate, consented)
upstream-watch cron. It does NOT touch the network — the "is upstream newer than our pin?"
check is the cron's job; this answers "are our pins within policy + mutually consistent?".

Usage:
  python scripts/check_external_freshness.py            # report; exit 1 if anything stale
  python scripts/check_external_freshness.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.maintenance import registry as R  # noqa: E402

_SYMBOL = {"ok": "✓", "stale": "✗", "unknown": "?", "info": "·"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="emit the machine-readable summary")
    args = ap.parse_args()

    summ = R.summary()
    if args.json:
        print(json.dumps(summ, indent=2))
    else:
        print("External-artifact freshness (network-free; couplings checked):\n")
        for r in summ["artifacts"]:
            age = r.get("age_months")
            age_s = f"{age}mo" if isinstance(age, int) else "—"
            print(f"  {_SYMBOL.get(r['status'], '?')} {r['status']:8} {r['id']:26} {age_s:>5}  {r['detail']}")
        print(f"\n  counts: {summ['counts']}")
        if summ["stale"]:
            print(f"  STALE (refresh these): {', '.join(summ['stale'])}")
        else:
            print("  all pins within policy + couplings consistent.")
        print(
            "\n  NOTE: this checks OUR pins, not upstream. The 'is upstream newer?' watch "
            "is the separate consented scheduled job."
        )
    return 1 if summ["stale"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
