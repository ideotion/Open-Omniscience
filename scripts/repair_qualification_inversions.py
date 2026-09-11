#!/usr/bin/env python3
"""
Reconcile Source.status for sources whose live status no longer agrees with their own
qualification-attempt history (the "inversion" GET /api/diagnostics/qualification-integrity
finds; see src/catalog/qualification_integrity.py).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT THIS IS. src.catalog.qualification_integrity.repair_inversions re-derives every
inversion from the SAME newest-judging-attempt join the integrity report uses, then --
only if asked -- sets Source.status (and the qualified_at/qualification_criteria_version
stamp) back to what this instance's OWN source_qualification_attempts history already
recorded. It writes NO new attempt row: this reconciles existing history, it does not
judge anything fresh.

WHY THIS IS A SEPARATE, OPERATOR-RUN SCRIPT rather than something that fixes itself at
boot. Re-admitting a potentially large population of sources back into live collection at
once is a real behaviour change -- bandwidth, per-host politeness, and the operator's own
expectations of what is being collected -- and it is the maintainer's call, never
something code should decide on its own the moment it notices a discrepancy. So this
defaults to a DRY RUN: it computes and prints the exact tally, in both directions, and
writes NOTHING unless you pass --apply.

Run it against the LIVE encrypted corpus (so the maintainer runs it; the sandbox/CI has
no DB, same as scripts/derive_source_topics.py).

USAGE
    python scripts/repair_qualification_inversions.py             # dry run, report only
    python scripts/repair_qualification_inversions.py --apply      # write the reconciliation
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--apply", action="store_true",
        help="actually write the reconciliation (default: dry run -- report only, "
             "nothing changed)",
    )
    args = ap.parse_args(argv)

    from src.catalog.qualification_integrity import repair_inversions
    from src.database.session import session_scope

    with session_scope() as session:
        report = repair_inversions(session, dry_run=not args.apply)

    print(json.dumps(report, indent=2))
    if args.apply:
        print(
            f"\nreconciled {report['reconciled_total']} source(s) "
            f"({report['restored_to_disqualified_total']} restored to disqualified, "
            f"{report['restored_to_qualified_total']} restored to qualified)",
            file=sys.stderr,
        )
    else:
        print(
            f"\n(dry run -- nothing written; would reconcile "
            f"{report['reconciled_total']} source(s). Re-run with --apply to write it.)",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
