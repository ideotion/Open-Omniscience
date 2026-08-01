#!/usr/bin/env python3
"""
The card-audit differ — two saved deep card-audit runs -> a cycle report.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The third instrument of the card-system improvement loop (continuous improvement,
maintainer-ruled 2026-07-31). The determinism check and per-run persistence were
already built inside ``src/briefing/card_audit.py``; nothing compared two saved
runs, so "did the fix work, and did anything else regress?" had to be answered by
reading two JSON files side by side.

Reads two ``oo-card-audit-1`` reports (written by
``POST /api/diagnostics/card-audit/run`` into ``<data_dir>/diagnostics/``) and
reports, PER METRIC, improved / regressed / unchanged / not-measurable /
not-comparable — from each metric's declared direction-of-goodness. Counts with no
direction (how many cards surfaced) report changed/unchanged and are never called
an improvement. No blended verdict, no score.

A regression is a FINDING for the next improvement cycle, not a CI failure, so the
exit code is 0 for any well-formed comparison. Only a malformed input fails LOUD
(exit 2) — two reports that cannot be read cannot be compared honestly.

Unlike ``kpi_diff.py`` this imports from ``src`` (the projection needs to know the
audit payload's shape), so run it from the repo root:

    python3 -m scripts.card_audit_diff OLD.json NEW.json
    python3 -m scripts.card_audit_diff OLD.json NEW.json --json
    python3 -m scripts.card_audit_diff --latest      # the two newest saved runs
"""

from __future__ import annotations

import argparse
import json
import sys

from src.briefing.card_audit_diff import (
    CardAuditDiffError,
    diff_card_audit_reports,
    diff_latest_card_audits,
    list_card_audit_reports,
)


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise CardAuditDiffError(f"{path}: cannot read a card-audit report ({exc})") from exc
    if not isinstance(data, dict):
        raise CardAuditDiffError(f"{path}: not a card-audit report object")
    return data


def format_report(report: dict) -> str:
    lines = [
        f"Card-audit cycle diff  ({report.get('old_generated_at')}  ->  "
        f"{report.get('new_generated_at')})",
        "-" * 78,
    ]
    for r in report["metrics"]:
        lines.append(
            f"  {str(r['id']):4} {str(r['classification']):16} "
            f"{str(r['old_value']):>8} -> {str(r['new_value']):<8}  "
            f"({r['direction'] or 'no direction'})  {r['name'] or ''}"
        )
    lines.append("-" * 78)
    lines.append("  " + " · ".join(f"{k}: {v}" for k, v in sorted(report["counts"].items())))
    lines.append("")
    lines.append("  " + report.get("caveat", ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Diff two saved deep card-audit runs into a cycle report."
    )
    ap.add_argument("old", nargs="?", help="the earlier card-audit report (JSON)")
    ap.add_argument("new", nargs="?", help="the later card-audit report (JSON)")
    ap.add_argument("--latest", action="store_true", help="compare the two newest saved runs")
    ap.add_argument("--list", action="store_true", help="list saved runs and exit")
    ap.add_argument("--json", action="store_true", help="emit the machine-readable JSON report")
    args = ap.parse_args(argv)

    if args.list:
        names = list_card_audit_reports()
        print("\n".join(names) if names else "no saved deep card-audit runs")
        return 0

    if args.latest:
        report = diff_latest_card_audits()
        if not report.get("available"):
            print(f"error: {report.get('reason')}", file=sys.stderr)
            return 2
    else:
        if not (args.old and args.new):
            ap.error("give OLD and NEW report paths, or --latest")
        try:
            report = diff_card_audit_reports(_load(args.old), _load(args.new))
        except CardAuditDiffError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2  # a malformed input fails loud; a regression does NOT

    print(json.dumps(report, indent=2) if args.json else format_report(report))
    return 0  # reporting never gates — a regression is a finding for the next cycle


if __name__ == "__main__":
    raise SystemExit(main())
