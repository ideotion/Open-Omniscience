#!/usr/bin/env python3
"""Check the bundled El Niño episode table against NOAA CPC's own ONI series.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE OPERATOR STEP this closes. ``configs/climate_events.yml`` has carried
``verification_status: "drafted-from-training-knowledge; clearnet check pending"`` since
2026-06-12. The CPC convention is pure arithmetic over one small public-domain file, so
the check needs no judgement — only the file, which no agent session can fetch (the CPC
host answers CONNECT 403 through the sandbox proxy).

    curl -o oni.ascii.txt https://origin.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/detrend.nino34.ascii.txt
    python scripts/verify_oni_episodes.py oni.ascii.txt

Stdlib + PyYAML only; makes NO network call itself — it takes a path you already have, so
running it can never be an egress surprise. It REPORTS and never edits: flipping
``verification_status`` is a human's decision after reading the diff, because a script that
marked its own input verified would make the flag meaningless.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.stats.oni import episodes_from_oni, parse_oni, season_months  # noqa: E402


def _bundled(path: Path) -> list[dict]:
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(raw.get("el_nino_episodes") or [])


def _start_month(period: str) -> str:
    """A derived episode's first season as ``YYYY-MM``, for comparison with the table.

    The bundled table is keyed by month, so a comparison has to cross the season/month
    boundary somewhere. It happens HERE, in the reporting layer, and never in the parser —
    and it uses the season's TRUE first month via ``season_months`` rather than assuming the
    label's own year, which is wrong for DJF by a whole year.
    """
    year_s, _, season = period.partition("-")
    y, m = season_months(season, int(year_s))[0]
    return f"{y:04d}-{m:02d}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("oni_file", type=Path, help="a locally downloaded CPC ONI ASCII table")
    ap.add_argument("--config", type=Path,
                    default=Path(__file__).resolve().parents[1] / "configs" / "climate_events.yml")
    args = ap.parse_args(argv)

    text = args.oni_file.read_text(encoding="utf-8", errors="replace")
    parsed = parse_oni(text, extracted_at=datetime.now(UTC).isoformat(timespec="seconds"))

    if parsed.looks_unrecognised:
        print("REFUSED: that file does not parse as a CPC ONI table.")
        print(f"  {len(parsed.refused)} unreadable lines, 0 data rows. First few:")
        for r in parsed.refused[:3]:
            print(f"    line {r['line']}: {r['reason']} -- {r['text']!r}")
        print("  Nothing is compared, because a wrong file must never read as a clean table.")
        return 2

    derived = episodes_from_oni(parsed.figures, warm=True)
    bundled = _bundled(args.config)

    print(f"ONI file      : {args.oni_file}")
    print(f"data rows     : {parsed.rows_read}   unreadable lines: {len(parsed.refused)}")
    print(f"derived El Niño episodes: {len(derived)}   bundled: {len(bundled)}")
    print()

    d_by_start = {_start_month(e["start"]): e for e in derived}
    b_by_start = {str(e.get("start")): e for e in bundled}

    matched = sorted(set(d_by_start) & set(b_by_start))
    only_derived = sorted(set(d_by_start) - set(b_by_start))
    only_bundled = sorted(set(b_by_start) - set(d_by_start))

    print(f"start months agreeing : {len(matched)}")
    for k in matched:
        d, b = d_by_start[k], b_by_start[k]
        dp, bp = d["peak_oni"], b.get("peak_oni")
        flag = "" if bp is not None and abs(float(dp) - float(bp)) < 0.05 else "   <-- peak differs"
        print(f"  {k}  derived peak {dp:+.2f} / bundled {bp}{flag}")
    if only_derived:
        print(f"\nin CPC but NOT in the bundled table ({len(only_derived)}):")
        for k in only_derived:
            e = d_by_start[k]
            print(f"  {k} .. {e['end']}  peak {e['peak_oni']:+.2f}  ({e['intensity']}, {e['seasons']} seasons)")
    if only_bundled:
        print(f"\nin the bundled table but NOT in CPC ({len(only_bundled)}):")
        for k in only_bundled:
            print(f"  {k}  {b_by_start[k]}")

    print()
    if only_derived or only_bundled:
        print("The table and the CPC series DISAGREE. Read the rows above before editing")
        print("anything; this script reports and never edits.")
    else:
        print("Every episode start agrees. A human may now flip verification_status in")
        print(f"{args.config} -- deliberately not done here.")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
