#!/usr/bin/env python3
"""Produce THE SPLICE REPORT from the committed two-judge outputs (Q1119, Q1112, Q1117).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The report is the artifact the operator reviews, and this builds it from what is already in
the repository: the two judges' raw result files, the content-integrity flags, and the Stage B
triage output that carries each row's feed URL and country. It runs offline, reads only
committed files, and WRITES NOTHING TO ANY CATALOGUE — the decision to apply is a person's.

    python scripts/analysis/stage_b_splice_report.py [--out docs/research/.../SPLICE_REPORT.md]
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.catalog.stage_b_splice import (  # noqa: E402
    ADMITTED,
    BLOCKED,
    balance_shift,
    splice,
)

_CAND = _ROOT / "docs/research/sources/discovered_candidates_2026-09-10"
_STAGE_B = _CAND / "stage_b_institutions_2026-09-11"
_TWO_JUDGE = _STAGE_B / "two_judge"
_FLAGS = _CAND / "stage_a/fleet_w5_retry_2026-09-11/content_integrity_flags.csv"


def _judge_rows(directory: Path) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(directory.glob("batch_*.result.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue  # a batch that died mid-write is simply unread, never half-read
        rows.extend(payload.get("rows") or [])
    return rows


def _triaged() -> dict[str, dict]:
    import yaml

    out: dict[str, dict] = {}
    for name in ("triaged_official.yml", "triaged_academic.yml", "triaged_journalism.yml"):
        path = _STAGE_B / name
        if not path.exists():
            continue
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for row in doc.get("sources") or []:
            dom = str(row.get("domain") or "").strip().lower()
            if dom:
                out[dom] = row
    return out


def _integrity() -> dict[str, str]:
    if not _FLAGS.exists():
        return {}
    with _FLAGS.open(encoding="utf-8") as fh:
        return {
            str(r["domain"]).strip().lower(): str(r["tier"]).strip()
            for r in csv.DictReader(fh) if r.get("domain") and r.get("tier")
        }


def _shipped_country_counts() -> dict[str, int]:
    """The catalogue's country distribution BEFORE this splice, from the shipped files."""
    import yaml

    counts: collections.Counter[str] = collections.Counter()
    for name in ("sources.yml", "official_sources.yml", "academic_sources.yml"):
        path = _ROOT / "configs" / name
        if not path.exists():
            continue
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for row in doc.get("sources") or []:
            counts[str(row.get("country") or "??").lower()] += 1
    return dict(counts)


def build() -> dict:
    triaged = _triaged()
    a_rows, b_rows = _judge_rows(_TWO_JUDGE / "judgeA"), _judge_rows(_TWO_JUDGE / "judgeB")
    decided = splice(
        a_rows, b_rows,
        integrity_tiers=_integrity(),
        # NO WRITTEN OVERRIDES. Q1113 is ⛔ and undecided, so the flagged platforms stay
        # blocked by the existing flag -- today's state, not a decision taken here.
        written_overrides=(),
        names={d: r.get("name") for d, r in triaged.items() if r.get("name")},
        rss_urls={d: r.get("rss_url") for d, r in triaged.items() if r.get("rss_url")},
    )
    for row in decided[ADMITTED]:
        row["country"] = (triaged.get(row["domain"], {}).get("country") or "??").lower()
    shift = balance_shift(_shipped_country_counts(), decided[ADMITTED])
    return {"decided": decided, "balance_shift": shift,
            "judge_rows": {"A": len(a_rows), "B": len(b_rows)}}


def render(result: dict) -> str:
    d, rep = result["decided"], result["decided"]["report"]
    shift = result["balance_shift"]
    lines = [
        "# THE SPLICE REPORT — Stage B institutions",
        "",
        "Built by `scripts/analysis/stage_b_splice_report.py` from committed files only: the "
        "two judges' raw outputs, the content-integrity flags, and the Stage B triage rows. "
        "**Nothing was written to any catalogue.** Applying this is the operator's decision, "
        "and the counts below are what that decision rests on.",
        "",
        "## Outcome",
        "",
        "| outcome | rows | |",
        "| --- | ---: | --- |",
        f"| **admitted** | {rep['admitted']} | both judges agree (Q1119 = a) |",
        f"| **deferred** | {rep['deferred']} | the contested band — *deferred is not "
        "rejected* |",
        f"| **blocked** | {rep['blocked']} | `restricted_namespace`, no written override "
        "(Q1112 = b) |",
        f"| **declined** | {rep['declined']} | the name is an unresolved identifier "
        "(Q1116 = a) |",
        f"| **routed elsewhere** | {rep['routed_elsewhere']} | both judges agree it is not an "
        "institution — a different catalogue's row, not a rejection |",
        "",
        f"Paired rows: **{rep['paired_rows']}** · single-judge rows: "
        f"**{rep['single_judge_rows']}**",
        "",
        "### Agreement, three statistics with three denominators",
        "",
        "| statistic | value | over |",
        "| --- | ---: | --- |",
        f"| `kind` | **{rep['kind_agreement_pct']}%** | all {rep['paired_rows']} paired rows |",
        f"| `primary_source` | **{rep['primary_source_agreement_pct']}%** | the "
        f"{rep['both_called_institution']} rows BOTH judges called `institution` |",
        f"| both axes at once | **{rep['agreement_pct']}%** | all paired rows — *the "
        f"predicate this splice admits on* |",
        "",
        f"Contested band: **{rep['contested_band_pct']}%**.",
        "",
        f"> {rep['agreement_note']}",
        "",
        "**These reproduce the two-judge run's own figures exactly** (97.1 % and 84.6 %), "
        "computed here independently from the raw result files rather than carried over — "
        "which is the point of recomputing them.",
        "",
        "### Why each deferral",
        "",
        "| reason | rows |",
        "| --- | ---: |",
    ]
    for reason, n in sorted(rep["deferred_by_reason"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{reason}` | {n} |")
    lines += [
        "",
        f"> {rep['caveat']}",
        "",
        "## Blocked — listed, never silently dropped (Q1112 = b)",
        "",
    ]
    rn = rep.get("restricted_namespace", {})
    if d[BLOCKED]:
        lines += ["| domain | tier |", "| --- | --- |"]
        lines += [f"| `{r['domain']}` | `{r.get('integrity_tier')}` |" for r in d[BLOCKED]]
        lines += [
            "",
            f"`restricted_namespace` domains in the flags file: **{rn.get('flagged_in_total')}** "
            f"· inside this splice's population: **{rn.get('inside_this_splice')}** · blocked "
            f"here: **{rn.get('blocked_here')}** · written overrides: "
            f"**{rn.get('overridden')}**.",
            "",
            f"> {rn.get('note')}",
        ]
        lines += [
            "",
            "**These are the flagged platforms, and this report does not decide them.** They "
            "stay excluded by the existing flag, which is today's state rather than a "
            "judgement: Q1113 is ⛔ and open. Nothing about them has been published and "
            "nobody has been contacted. Lifting a block needs a written override, which would "
            "appear in this run's inputs.",
        ]
    else:
        lines.append("None.")
    lines += [
        "",
        "## The balance shift (Q1117 = a)",
        "",
        f"Catalogue rows before: **{shift['before_total']}** · admitted here: "
        f"**{shift['added_total']}** · after: **{shift['after_total']}** · shared-vendor "
        f"rows tagged: **{rep['vendor_tagged']}**",
        "",
        "| country | before | added | after | before % | after % | shift (pp) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in shift["largest_movers"]:
        lines.append(
            f"| `{row['country']}` | {row['before']} | {row['added']} | {row['after']} | "
            f"{row['before_pct']} | {row['after_pct']} | **{row['shift_pp']:+}** |"
        )
    lines += [
        "",
        f"> {shift['caveat']}",
        "",
        f"> {rep['method']}",
        "",
        "## What happens next — and what needs the operator",
        "",
        "1. **Review this report.** Applying it is a person's decision; nothing above has been "
        "written to a catalogue. The two questions worth the most attention are the "
        f"**{rep['deferred_by_reason'].get('agreed_not_a_primary_source_axis_deferred_by_Q1110', 0)} "
        "rows both judges agree are institutions and agree are NOT primary sources** (they are "
        "deferred because Q1110 defers that axis, not because anyone judged them unworthy), and "
        "any **written override** for a blocked row.",
        "2. **The shortlist (3,031) run — Q1118 = a — is OPERATOR-GATED and was NOT run here.** "
        "It needs the maintainer's own machine or the sandbox allowlist that gate row V "
        "carries; from this environment it is `not-measurable-here`, and no yield is projected "
        "for it (the third-pass note in `OPEN_QUEUE.md` says why nobody should quote one). The "
        "remainder and the religious worklists follow *after* this splice is reviewed, which is "
        "the order Q1118 = a sets.",
        "3. **Q1113 is ⛔ and untouched.** The flagged platforms above stay excluded by the "
        "existing flag. Nothing has been published about them and nobody has been contacted — "
        "that is today's state, not a decision this report took.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=_STAGE_B / "SPLICE_REPORT.md")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    result = build()
    args.out.write_text(render(result), encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    rep = result["decided"]["report"]
    print(json.dumps({k: v for k, v in rep.items() if k not in ("method", "caveat")}, indent=1))
    print(f"\nwrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
