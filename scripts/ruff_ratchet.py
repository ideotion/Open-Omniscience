#!/usr/bin/env python3
"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""

"""Non-growth ratchet for the ADVISORY ruff style lane (J-ruff, 2026-09-07).

The style lane is ``continue-on-error`` and has been since the legacy debt was
measured. That verdict is unchanged and deliberate -- see
``docs/maintenance/RUFF_STYLE_LANE.md`` for the composition and why converging it
is not a behaviour-neutral change. What was missing is that "advisory" quietly
became "unwatched": the lane was recorded at **344** findings on 2026-08-20 and
measured **432** on 2026-09-07, an 88-finding drift nobody saw, because a lane
that is allowed to fail says nothing when it fails a little more.

So the count is ratcheted the way this repo ratchets everything else (the two
i18n gates, the slicer budget, the import-cycle ceiling): it may only be LOWERED.
Growth reddens; a drop prints the new floor to set.

WHY THE VERSION IS PRINTED. A count-over-a-tool ratchet is only meaningful while
the tool's rule set is fixed -- the recorded mypy lesson is that at zero slack a
newer release "reddens every PR through no code change, which is why the pin is
load-bearing". ``pyproject.toml`` therefore bounds ruff to one minor series, and
this script names the version it measured with in its own failure message, so a
rule-set change presents as itself rather than as mystery debt.

Usage:
    python scripts/ruff_ratchet.py --max 432
    python scripts/ruff_ratchet.py --max 432 --show-composition
"""

import argparse
import json
import subprocess
import sys
from collections import Counter

#: The paths the advisory lane lints. Kept identical to ci.yml's own step, so the
#: ratchet cannot silently measure a different tree than the lane it guards.
TARGETS = ("src/", "tests/")


def _ruff_version() -> str:
    try:
        out = subprocess.run(
            [sys.executable, "-m", "ruff", "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return out.stdout.strip() or "unknown"


def findings() -> list[dict]:
    """Every advisory finding, as ruff's own JSON. Never a line count of human
    output: the summary lines ("Found N errors", "[*] N fixable") are part of that
    output and would inflate a naive ``wc -l`` by two."""
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", *TARGETS, "--output-format=json"],
        capture_output=True,
        text=True,
    )
    # ruff exits 1 when it has findings, which is the normal case here; only a
    # crash (2) or unparseable output is an error worth refusing on.
    if proc.returncode not in (0, 1):
        raise SystemExit(f"ruff failed (rc={proc.returncode}):\n{proc.stderr.strip()}")
    try:
        return json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"could not parse ruff JSON output: {exc}") from exc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--max",
        type=int,
        required=True,
        help="the recorded ceiling; the run fails if the real count exceeds it",
    )
    ap.add_argument(
        "--show-composition",
        action="store_true",
        help="print the per-rule breakdown (what a burn-down would have to take on)",
    )
    args = ap.parse_args()

    found = findings()
    n = len(found)
    version = _ruff_version()
    print(f"ruff advisory findings: {n} (ceiling {args.max}, {version})")

    if args.show_composition:
        by_rule = Counter(f.get("code") or "?" for f in found)
        for code, count in by_rule.most_common():
            print(f"  {count:5d}  {code}")

    if n > args.max:
        print(
            f"\nFAIL: the advisory ruff lane GREW to {n}, past its recorded ceiling of "
            f"{args.max}.\nThis is a ratchet, not a target: it may only be lowered. Fix "
            f"the new findings, or\nargue the ceiling up deliberately in the same PR. "
            f"(measured with {version} -- if the\nruff version moved, the rule set moved "
            f"with it and that is the thing to look at first.)",
            file=sys.stderr,
        )
        return 1
    if n < args.max:
        print(f"\nThe ratchet can be lowered: set --max {n} in .github/workflows/ci.yml.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
