#!/usr/bin/env python3
"""
The KPI differ (R2, V1_PATHWAY §2.4) — two KPI snapshots -> a cycle report.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Reads two ``oo-kpi-1`` snapshots (from ``GET /api/diagnostics/kpi``, saved across
an improvement cycle) and reports, PER METRIC, whether it improved / regressed /
unchanged / not-measurable / not-comparable — computed from the metric's declared
``direction`` (up / down / exact), never a blended verdict and NO overall score.

Stdlib-only (runs without the app installed — the ``analyze_keyword_log.py``
pattern). A regression is a FINDING for the PLAN stage, not a CI failure, so the
exit code is 0 for any well-formed comparison. Only a malformed / schema-mismatched
input fails LOUD (exit 2) — two snapshots that are not both ``oo-kpi-1`` cannot be
compared honestly.

Usage:
    python3 scripts/kpi_diff.py OLD.json NEW.json          # human-readable table
    python3 scripts/kpi_diff.py OLD.json NEW.json --json    # machine JSON
"""

from __future__ import annotations

import argparse
import json
import sys

_SCHEMA = "oo-kpi-1"
# The verdict for one metric across the two snapshots.
IMPROVED, REGRESSED, UNCHANGED = "improved", "regressed", "unchanged"
NOT_MEASURABLE, NOT_COMPARABLE, CHANGED = "not-measurable", "not-comparable", "changed"


class KpiDiffError(Exception):
    """A malformed / incompatible snapshot — comparison cannot be honest."""


def load_snapshot(path: str) -> dict:
    """Load + validate one KPI snapshot. Fails LOUD on a bad file / wrong schema."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise KpiDiffError(f"{path}: cannot read a KPI snapshot ({exc})") from exc
    if not isinstance(data, dict) or data.get("schema") != _SCHEMA:
        raise KpiDiffError(
            f"{path}: not an {_SCHEMA} snapshot (schema={data.get('schema') if isinstance(data, dict) else '?'})"
        )
    if not isinstance(data.get("metrics"), list):
        raise KpiDiffError(f"{path}: snapshot has no 'metrics' list")
    return data


def _numeric(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def classify(old: dict | None, new: dict | None) -> str:
    """Classify one metric across the two snapshots from its direction-of-goodness.

    A metric missing from either side is not-comparable; a not-measurable value on
    either side is not-measurable (no delta can be computed); otherwise up/down
    metrics compare values numerically and exact metrics compare their green verdict.
    """
    if old is None or new is None:
        return NOT_COMPARABLE
    ov, nv = old.get("value"), new.get("value")
    if ov is None or nv is None:
        return NOT_MEASURABLE
    direction = new.get("direction") or old.get("direction")
    if direction in ("up", "down"):
        if not (_numeric(ov) and _numeric(nv)):
            return NOT_COMPARABLE
        if ov == nv:
            return UNCHANGED
        better = (nv > ov) if direction == "up" else (nv < ov)
        return IMPROVED if better else REGRESSED
    # exact: value has no monotone goodness — the GREEN verdict is the goal.
    og, ng = old.get("verdict") == "green", new.get("verdict") == "green"
    if og != ng:
        return IMPROVED if ng else REGRESSED
    return UNCHANGED if ov == nv else CHANGED


def diff_snapshots(old: dict, new: dict) -> dict:
    """Per-metric cycle report (machine JSON). No overall score — per-category counts only."""
    old_by = {m.get("id"): m for m in old.get("metrics", []) if isinstance(m, dict)}
    new_by = {m.get("id"): m for m in new.get("metrics", []) if isinstance(m, dict)}
    rows: list[dict] = []
    for mid in sorted(set(old_by) | set(new_by), key=lambda x: (len(str(x)), str(x))):
        o, n = old_by.get(mid), new_by.get(mid)
        ref = n or o or {}
        rows.append({
            "id": mid,
            "name": ref.get("name"),
            "direction": ref.get("direction"),
            "classification": classify(o, n),
            "old_value": (o or {}).get("value"),
            "new_value": (n or {}).get("value"),
            "old_verdict": (o or {}).get("verdict"),
            "new_verdict": (n or {}).get("verdict"),
        })
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["classification"]] = counts.get(r["classification"], 0) + 1
    return {
        "schema": "oo-kpi-diff-1",
        "old_generated_at": old.get("generated_at"),
        "new_generated_at": new.get("generated_at"),
        "metrics": rows,
        "counts": counts,  # per-category counts (a listing, not a blended score)
        "method": "per-metric improved/regressed/unchanged/not-measurable/not-comparable "
                  "from the declared direction-of-goodness; no blended verdict, no score.",
    }


def format_report(report: dict) -> str:
    lines = [
        f"KPI cycle diff  ({report.get('old_generated_at')}  ->  {report.get('new_generated_at')})",
        "-" * 72,
    ]
    for r in report["metrics"]:
        lines.append(
            f"  {str(r['id']):4} {str(r['classification']):15} "
            f"{str(r['old_value']):>10} -> {str(r['new_value']):<10}  "
            f"({r['direction']})  {r['name'] or ''}"
        )
    lines.append("-" * 72)
    lines.append("  " + " · ".join(f"{k}: {v}" for k, v in sorted(report["counts"].items())))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Diff two oo-kpi-1 snapshots into a cycle report.")
    ap.add_argument("old", help="the earlier KPI snapshot (oo-kpi-1 JSON)")
    ap.add_argument("new", help="the later KPI snapshot (oo-kpi-1 JSON)")
    ap.add_argument("--json", action="store_true", help="emit the machine-readable JSON report")
    args = ap.parse_args(argv)
    try:
        old, new = load_snapshot(args.old), load_snapshot(args.new)
    except KpiDiffError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2  # a malformed/incompatible input fails loud; a regression does NOT
    report = diff_snapshots(old, new)
    print(json.dumps(report, indent=2) if args.json else format_report(report))
    return 0  # reporting never gates — a regression is a PLAN-stage finding


if __name__ == "__main__":
    raise SystemExit(main())
