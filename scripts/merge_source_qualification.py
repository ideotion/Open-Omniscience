#!/usr/bin/env python3
"""
Accumulate source-qualification verdicts from several instances into the shipped overlay.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer runs many instances; each exports what it measured
(``GET /api/diagnostics/source-qualification-export``). This merges those exports into
``configs/source_qualification.yml``, which ships and is adopted by every fresh install.

WHAT IT REFUSES TO DO, and why each refusal matters more than the convenience it costs:

  * IT NEVER RESOLVES A DISAGREEMENT. If one instance qualified a domain and another
    disqualified it, that is a finding -- possibly a site that changed, possibly a criteria
    difference, possibly a cohort that firmed up. It is REPORTED and the domain is left at
    whatever the existing overlay said (or omitted entirely if it said nothing), because
    picking a winner automatically would ship a verdict no human ever looked at, to every
    install, silently. ``--accept-newest`` exists for when the maintainer HAS looked and
    wants the newest verdict to win; it is never the default.

  * IT NEVER COUNTS AN ECHO AS CORROBORATION. A verdict an instance INHERITED (from a backup
    or an earlier overlay) is one measurement seen twice, not two -- so agreement is counted
    over ``basis: measured`` rows only. Without that, importing one backup into eight
    instances would manufacture eightfold "agreement" out of a single trial.

  * IT NEVER RE-STAMPS A DATE. ``qualified_at`` stays the date the verdict was REACHED.
    Refreshing it on merge would restart the six-month re-verification clock on every
    accumulation run, so a shipped verdict could never grow old enough to be re-checked --
    an expiry that never fires.

  * IT NEVER REWRITES A ROW IT WAS NOT GIVEN. Existing overlay entries the exports do not
    mention are carried through untouched, so merging one instance's export cannot silently
    drop what the others contributed.

USAGE
    python scripts/merge_source_qualification.py export1.json [export2.json ...] \\
        [-o configs/source_qualification.yml] [--dry-run] [--accept-newest]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = _ROOT / "configs" / "source_qualification.yml"

SHIPPABLE = ("qualified", "disqualified")


def _load_export(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("verdicts")
    if not isinstance(rows, list):
        raise SystemExit(f"{path}: no 'verdicts' list -- is this a source-qualification export?")
    return rows


def _load_existing(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        str(r["domain"]): r
        for r in (raw.get("verdicts") or [])
        if isinstance(r, dict) and r.get("domain")
    }


def _stamp(row: dict) -> str:
    """Sort key for 'newest verdict'. A row with no date sorts oldest, so a dateless verdict
    can never win a disagreement by default -- being undated is not being recent."""
    return str(row.get("qualified_at") or "")


def merge(exports: list[list[dict]], existing: dict[str, dict], *, accept_newest: bool) -> dict:
    """Pure core: existing overlay + N exports -> merged overlay + a report."""
    proposed: dict[str, list[dict]] = defaultdict(list)
    skipped = 0
    for rows in exports:
        for row in rows:
            domain = str(row.get("domain") or "").strip().lower()
            if not domain or row.get("status") not in SHIPPABLE:
                skipped += 1
                continue
            proposed[domain].append(row)

    merged = dict(existing)
    added: list[str] = []
    updated: list[str] = []
    unchanged = 0
    conflicts: list[dict] = []

    for domain, rows in sorted(proposed.items()):
        # Agreement is counted over MEASURED rows only -- an inherited row is an echo.
        measured = [r for r in rows if r.get("basis", "measured") == "measured"]
        verdicts = {r["status"] for r in (measured or rows)}
        if len(verdicts) > 1:
            conflicts.append({
                "domain": domain,
                "verdicts": sorted(verdicts),
                "measured_by": len(measured),
                "resolution": "newest" if accept_newest else "left as-is (needs review)",
            })
            if not accept_newest:
                continue
        winner = max(measured or rows, key=_stamp)
        entry = {
            "domain": domain,
            "status": winner["status"],
            # NEVER re-stamped -- see the module docstring.
            "qualified_at": winner.get("qualified_at"),
            "criteria_version": winner.get("criteria_version"),
        }
        prior = existing.get(domain)
        if prior is None:
            added.append(domain)
        elif {k: prior.get(k) for k in entry} != entry:
            updated.append(domain)
        else:
            unchanged += 1
            continue
        merged[domain] = entry

    return {
        "merged": merged,
        "report": {
            "exports": len(exports),
            "domains_proposed": len(proposed),
            "added": len(added),
            "updated": len(updated),
            "unchanged": unchanged,
            "carried_through_untouched": len(set(existing) - set(proposed)),
            "conflicts": conflicts,
            "skipped_rows": skipped,
        },
    }


def render(merged: dict[str, dict]) -> str:
    doc = {
        "generated_at": datetime.now(UTC).date().isoformat(),
        "verdicts": [merged[d] for d in sorted(merged)],
    }
    header = (
        "# Source qualification verdicts, EARNED BY MEASUREMENT on real instances.\n"
        "# Merged by scripts/merge_source_qualification.py from per-instance exports\n"
        "# (GET /api/diagnostics/source-qualification-export). Do not hand-edit.\n"
        "# A domain absent from this file ships unqualified and is judged by the install's\n"
        "# own first qualification pass, exactly as before this file existed.\n"
    )
    return header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exports", nargs="+", type=Path, help="per-instance export JSON files")
    ap.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    ap.add_argument(
        "--accept-newest", action="store_true",
        help="resolve disagreements in favour of the newest verdict (never the default: a "
             "disagreement is a finding, and an auto-resolved one ships unreviewed)",
    )
    args = ap.parse_args(argv)

    out = merge(
        [_load_export(p) for p in args.exports],
        _load_existing(args.out),
        accept_newest=args.accept_newest,
    )
    report = out["report"]
    print(json.dumps(report, indent=2))
    if report["conflicts"] and not args.accept_newest:
        print(
            f"\n{len(report['conflicts'])} domain(s) disagree across instances and were left "
            "unchanged. Review them, then re-run with --accept-newest if the newest verdict "
            "should win.",
            file=sys.stderr,
        )
    if args.dry_run:
        print("\n(dry run -- nothing written)", file=sys.stderr)
        return 0
    args.out.write_text(render(out["merged"]), encoding="utf-8")
    print(f"\nwrote {len(out['merged'])} verdict(s) to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
