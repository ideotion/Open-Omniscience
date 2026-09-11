#!/usr/bin/env python3
"""Build a RETRY worklist from finished Stage A run directories.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. A Stage A row that was DEFERRED was never judged: nothing was learned
about the outlet, only that we could not reach its robots.txt or its homepage on that
attempt. The 2026-09-11 ruling is that such a row is never dropped, so it has to come
back -- and coming back means a worklist, because Stage A reads worklists.

It is a worklist in the KIT'S OWN FORMAT (``build_candidate_kit.WORKLIST_FIELDS``), written
to ``worklists/worklist_5_retry.csv``, so every piece of machinery the kit already has works
on it unchanged: ``--shard i/N`` across a fleet, the per-run outputs, the packaging, the
RESULTS roll-up. A second kit format would have been a second thing to keep correct.

WHAT IT CARRIES FORWARD, and what it deliberately does not. The identity fields
(name/domain/country/language/tags/source_type) come from the earlier run, because they came
from the export and re-deriving them would be a second implementation of the same ladder.
The earlier REASON travels in ``flags`` as ``retry:<reason>``, so the operator and the triage
can see what is being re-asked -- but nothing in the retry path reads it as a verdict: the
row is judged fresh, by the same code, against a fresh fetch.

Usage:
    python scripts/analysis/build_retry_worklist.py \\
        --run RUNS/shards/1/runs/w3 [--run ...] --out worklists/worklist_5_retry.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.analysis.build_candidate_kit import WORKLIST_FIELDS  # noqa: E402

# The deferral set, kept in ONE place and imported by the verifier that owns it, so this and
# Stage A can never disagree about which rows are owed another look.
try:
    from scripts.analysis.verify_candidate_feeds import DEFERRED_REASONS
except ImportError:  # pragma: no cover - the verifier is part of the kit, not of every tree
    DEFERRED_REASONS = frozenset({
        "robots_refused", "robots_server_error", "robots_unreachable", "robots_unavailable",
        "homepage_unreachable", "crawl_delay_too_long", "host_timeout",
    })


def _rows_of(run_dir: Path) -> list[dict]:
    """Every judged row a run recorded. ``verified.jsonl`` holds them ALL -- one object per
    candidate carrying its ``status`` -- not only the passes, whatever its name suggests."""
    path = run_dir / "verified.jsonl"
    if not path.exists():
        raise SystemExit(f"no verified.jsonl in {run_dir}")
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def build(runs: list[Path], out: Path) -> dict:
    seen: set[str] = set()
    rows: list[dict] = []
    reasons: Counter = Counter()
    judged = deferred = 0
    for run_dir in runs:
        for r in _rows_of(run_dir):
            judged += 1
            reason = str(r.get("reason") or "").strip()
            if reason not in DEFERRED_REASONS:
                continue
            domain = str(r.get("domain") or "").strip().lower()
            # A fleet run shards by host, so a domain cannot legitimately appear twice --
            # but two runs of the SAME shard would, and silently doubling a publisher's
            # request count is the one thing the politeness design must not do.
            if not domain or domain in seen:
                continue
            seen.add(domain)
            deferred += 1
            reasons[reason] += 1
            tags = r.get("tags")
            rows.append({
                "tier": r.get("source_type") or "news",
                "name": r.get("name") or domain,
                "domain": domain,
                "source_type": r.get("source_type") or "news",
                "country": r.get("country") or "",
                "language": r.get("language_detected") or r.get("language_export") or "",
                "language_basis": r.get("language_basis") or "",
                "tags": ",".join(tags) if isinstance(tags, list) else (tags or ""),
                "catalogue_sources_in_country": "",
                "catalogue_sources_in_language": "",
                "flags": f"retry:{reason}",
            })
    rows.sort(key=lambda r: (r["country"], r["name"].lower()))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(WORKLIST_FIELDS), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return {"runs": len(runs), "judged": judged, "deferred": deferred,
            "written": len(rows), "by_reason": dict(reasons.most_common())}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", action="append", required=True, type=Path,
                    help="a finished run directory (the one holding verified.jsonl); repeatable")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    stats = build(args.run, args.out)
    print(json.dumps(stats, indent=1))
    print(f"\n{stats['written']:,} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
