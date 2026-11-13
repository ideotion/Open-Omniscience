#!/usr/bin/env python3
"""Write the elections coverage report: every floor country with its tier stated (0.6 gate Row A).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The Row A acceptance line asks for "the elections calendar covers the floor with each country's
tier stated (a coverage report as the artifact)". The app already serves the same facts live
(``GET /api/diagnostics/elections-floor``, drawn in Agenda -> Elections coverage); this script writes
them as ONE dated Markdown file for the release record. Offline and read-only: it reads the shipped
catalogue, the country floor and, when the operator's networked run has written it, the Wikidata
snapshot; it fetches nothing and decides nothing (the tiers are ``src.civic``'s). Counts and
reasons only: no score, no ranking, and a country with no entry is listed as missing, never left
out.

    python scripts/elections_coverage_report.py -o docs/product/elections_coverage_2026-11-13.md
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_STATE_WORDS = {
    "scheduled": "scheduled (an official date)",
    "window": "window (a stated month or year)",
    "projected_upcoming": "projected (a sourced rule, not yet passed)",
    "passed": "passed (every stated date has gone by; the next election is not listed)",
    "projected_passed": "projected, passed (status unknown; check the official source)",
    "dateless": "dateless (an entry with no date)",
    "missing": "missing (no entry)",
}


def _cell(text: Any) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def build_report(today: date) -> str:
    from src.civic.calendar_report import country_tier_report, with_snapshot
    from src.civic.coverage_floor import floor_coverage, load_floor
    from src.events.catalog import load_curated_events

    events, snap = with_snapshot(load_curated_events(), today)
    floor = load_floor()
    cov = floor_coverage(today)
    rep = country_tier_report(events, set(floor["countries"]), today)

    out = [f"# Elections coverage of the language floor, {today.isoformat()}", ""]
    out.append("Generated offline by `scripts/elections_coverage_report.py` from the shipped catalogue. "
               "Counts and reasons only; no score.")
    out.append("")
    out.append(f"- Floor: {rep['floor_countries']} countries, country list as of {cov.get('as_of') or floor.get('as_of') or 'unknown'}.")
    if cov.get("caveat"):
        out.append(f"- Floor caveat: {_cell(cov['caveat'])}")
    if snap.get("state") == "present":
        out.append(f"- Wikidata snapshot as of {snap['as_of']}: {snap['added']} entries added, {snap['shadowed']} already "
                   f"in the hand-curated list, {snap['refused'] + snap['generator_refused']} refused.")
    elif snap.get("state") == "unreadable":
        out.append("- Wikidata snapshot: present but unreadable; only the hand-curated list is counted.")
    else:
        out.append("- Wikidata snapshot: not generated yet (it needs a networked run of "
                   "`scripts/generate_wikidata_elections.py`); only the hand-curated list is counted.")
    out.append(f"- Method: {_cell(rep.get('method'))}")
    if rep.get("caveat"):
        out.append(f"- Caveat: {_cell(rep['caveat'])}")
    out.append("")
    out.append("| State | Countries |")
    out.append("| --- | ---: |")
    for state, n in rep["counts"].items():
        out.append(f"| {_STATE_WORDS.get(state, state)} | {n} |")
    out.append("")
    out.append("| Country | State | Entries | Why no date |")
    out.append("| --- | --- | --- | --- |")
    for r in rep["countries"]:
        entries = "<br>".join(_cell(e["title"]) for e in r["entries"]) or "none"
        why = r.get("reason") or ""
        needs = sorted({f for e in r["entries"] for f in (e.get("missing_fields") or [])})
        if needs and r["state"] in ("dateless", "missing"):
            why = (why + "; " if why else "") + "fields needed: " + ", ".join(needs)
        out.append(f"| {r['cc'].upper()} | {_STATE_WORDS.get(r['state'], r['state'])} | {entries} | {_cell(why)} |")
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-o", "--out", type=Path, required=True, help="the Markdown file to write")
    ap.add_argument("--today", type=date.fromisoformat, default=None, help="the date to report as of (default: today)")
    args = ap.parse_args(argv)
    args.out.write_text(build_report(args.today or date.today()) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
