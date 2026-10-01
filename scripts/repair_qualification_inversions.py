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

WHICH ROWS THE BOOT REPAIR TOUCHES: only a source whose live verdict is the shipped catalogue's
own stamp (or nothing). A verdict measured on this install is never changed by an imported
history on its own (rule 12 = b); this script, run by a person, repairs both kinds.

WHY THE RESTORE-TO-QUALIFIED DIRECTION IS OPERATOR-RUN, while restore-to-disqualified is not.
Restoring a recorded 'disqualified' only ever WITHDRAWS a source from collection, so it cannot
spend bandwidth or politeness nobody expected: the app does that one itself at boot
(auto_repair_inversions), with a revert record. Restoring a recorded 'qualified' RE-ADMITS a
potentially large population of sources into live collection at once -- bandwidth, per-host
politeness, the operator's own expectations of what is being collected -- and that is the
maintainer's call, never something code should decide the moment it notices a discrepancy. (The
older note "never call automatically" was a docstring from PR #1117, not a ruling; it was
narrowed on 2026-09-30.) So this defaults to a DRY RUN: it computes and prints the exact tally, in
both directions, and writes NOTHING unless you pass --apply.

--revert-repairs is the maintainer tool that undoes the AUTOMATIC repair: it puts every source the
boot repair restored to disqualified back exactly as it was (status and stamp, only while the row
still reads the state the repair gave it) and keeps it out of any later automatic repair. Dry run
by default too. Nothing in the app asks a user to run either. A source reverted that way is HELD
out of this script as well (the revert says "leave it as it was"), unless --ignore-hold is given.

Run it against the LIVE encrypted corpus (so the maintainer runs it; the sandbox/CI has
no DB, same as scripts/derive_source_topics.py).

USAGE
    python scripts/repair_qualification_inversions.py             # dry run, report only
    python scripts/repair_qualification_inversions.py --apply      # write the reconciliation
    python scripts/repair_qualification_inversions.py --revert-repairs          # dry run
    python scripts/repair_qualification_inversions.py --revert-repairs --apply  # undo the boot repair
    python scripts/repair_qualification_inversions.py --apply --ignore-hold    # also the reverted ones
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
    ap.add_argument(
        "--ignore-hold", action="store_true",
        help="also touch sources a maintainer reverted with --revert-repairs (by default they "
             "are held out, exactly as the boot repair holds them)",
    )
    ap.add_argument(
        "--revert-repairs", action="store_true",
        help="undo the automatic boot repair (dry run unless --apply)",
    )
    args = ap.parse_args(argv)

    from src.catalog.qualification_integrity import repair_inversions, revert_repairs
    from src.database.session import session_scope

    if args.revert_repairs:
        if args.ignore_hold:
            print("--ignore-hold has no effect with --revert-repairs", file=sys.stderr)
        try:
            result = revert_repairs(dry_run=not args.apply)
        except Exception as exc:  # noqa: BLE001 - say why, never a traceback; nothing was changed
            print(f"cannot read the revert record ({exc}); nothing was changed.", file=sys.stderr)
            return 2
        print(json.dumps(result, indent=2))
        print(
            f"\n({'reverted' if args.apply else 'dry run -- would revert'} "
            f"{result['reverted']} source(s); {result['moved_on_since_repair']} moved on since "
            "the repair and were left alone)",
            file=sys.stderr,
        )
        return 0

    held: set[str] = set()
    if not args.ignore_hold:
        from src.catalog.qualification_integrity import held_domains

        try:
            held = held_domains(strict=True)
        except Exception as exc:  # noqa: BLE001 - say why, never a traceback, and change nothing
            print(
                f"cannot read the revert record ({exc}); nothing was changed. "
                "Retry, or use --ignore-hold to proceed without it.",
                file=sys.stderr,
            )
            return 2
    with session_scope() as session:
        report = repair_inversions(session, dry_run=not args.apply, skip_domains=held)

    print(json.dumps(report, indent=2))
    if held:
        print(
            f"\n{report['held_by_operator_revert']} source(s) held out because a maintainer "
            "reverted their repair (--ignore-hold touches them too)",
            file=sys.stderr,
        )
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
