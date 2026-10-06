#!/usr/bin/env python3
"""Run row D's measured OSM ingest as ONE command and write ONE JSON report (0.5 row D, S05-04).

Open Omniscience - Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The gate closes row D with one country ingested on the 2-core, 3.5 GB reference VM and its sizes,
times, peak memory and peak disk recorded. This runs the app's own ingest scripts as measured
children, in a THROWAWAY encrypted store it makes for the run (your own store is never opened),
and writes the report. It makes NO network request and has no download flag: download the
continent extract (and, for the history step, the full-history planet) in the app first, under its
consent, and pass the files in.

    python scripts/osm_reference_run.py --extract europe-latest.osm.pbf --country FR --report run.json
    python scripts/osm_reference_run.py --extract E.osm.pbf --country FR --history H.osm.pbf --gazetteer osm-only
    python scripts/osm_reference_run.py --extract E.osm.pbf --country FR --plan       # the disk it needs; runs nothing

Run it with the APP STOPPED (the store it makes is its own, but the machine's memory and disk are
the thing being measured). It refuses before reading a byte if the disk cannot plausibly hold the run
(the floor is a GUESS until a report exists: pass ``--prior-report`` to use a measured one), and it
stops a phase cleanly, recording why, if free disk falls below the reserve (``--reserve-gb``, default
2) or available memory below ``--min-available-mb`` (default 256) during the run. The throwaway store
is deleted at the end and the report records the deletion; ``--keep-store`` (with your own ``--passphrase-file``) leaves it so the
gazetteer build can read it separately (``--gazetteer osm-only`` runs the OSM-only build inside the run), and
``--cleanup RUN_DIR`` deletes a kept one.

THE REPORT holds no secret and no path outside the run's own directory (inputs appear by file
name); the passphrase exists only in the children's environment. Exit: 0 done, 1 a phase failed,
2 refused (preflight, mid-run guard, or a phase's own refusal),
3 interrupted (SIGHUP, SIGTERM or Ctrl-C: the child was stopped, the store deleted, the report written).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv: list[str] | None = None) -> int:
    from src.osm import reference_run as R

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--extract", type=Path, help="the continent extract (.osm.pbf), already downloaded in the app")
    ap.add_argument("--country", help="ISO 3166-1 alpha-2 or alpha-3")
    ap.add_argument("--history", type=Path, help="the full-history planet (.osm.pbf); adds the history phase")
    ap.add_argument("--reader", choices=("pyosmium", "python"), default=None)
    ap.add_argument("--gazetteer", choices=R.GAZETTEER_MODES, default="off",
                    help="also build the OSM-only place gazetteer from the throwaway store. The Wikidata join is NOT "
                         "offered here: use --keep-store, then scripts/build_place_gazetteer.py --online with your own "
                         "transport setting (the throwaway store has none)")
    ap.add_argument("--gazetteer-out", type=Path, help="where the gazetteer artifact is written (outside the throwaway store)")
    ap.add_argument("--workdir", type=Path, help="where the throwaway store is made (default: beside the extract)")
    ap.add_argument("--report", type=Path, help="the JSON report (default: ./osm-reference-run-<time>.json)")
    ap.add_argument("--keep-store", action="store_true",
                    help="leave the throwaway store for a separate gazetteer build (needs --passphrase-file)")
    ap.add_argument("--passphrase-file", type=Path,
                    help="a file YOU made holding the store's passphrase; the runner only reads it and writes no secret "
                         "to disk (required with --keep-store, so the gazetteer build can open the kept store)")
    ap.add_argument("--cleanup", type=Path, metavar="RUN_DIR", help="delete a kept store this runner made; nothing else")
    ap.add_argument("--plan", action="store_true", help="print the disk the run needs and what it would do; run nothing")
    ap.add_argument("--prior-report", type=Path, help="a previous report: its measured disk per input byte replaces the guess")
    ap.add_argument("--reserve-gb", type=float, default=R.DEFAULT_RESERVE_BYTES / R.GIB)
    ap.add_argument("--min-available-mb", type=float, default=R.DEFAULT_MIN_AVAILABLE_BYTES / R.MIB)
    ap.add_argument("--floor-factor", type=float, default=R.DEFAULT_FLOOR_FACTOR)
    ap.add_argument("--min-free-gb", type=float, help="override the preflight floor")
    ap.add_argument("--sample-seconds", type=float, default=1.0,
                    help=f"how often the disk and memory guards look ({R.SAMPLE_SECONDS_MIN:g} to {R.SAMPLE_SECONDS_MAX:g})")
    args = ap.parse_args(argv)

    if args.cleanup is not None:
        out = R.cleanup(args.cleanup)
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0 if out.get("deleted") else 2
    if args.extract is None or not args.country:
        ap.error("--extract and --country are required")

    from src.osm.ingest import country_codes

    try:
        country_codes(args.country)
    except ValueError as exc:
        print(f"refused: {exc}")
        return 2
    prior = None
    if args.prior_report is not None:
        try:
            prior = json.loads(args.prior_report.read_text("utf-8"))
        except (OSError, ValueError):
            print("refused: the prior report cannot be read as JSON")
            return 2
    target = args.report or Path(f"osm-reference-run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json")
    try:
        report, kept = R.run(
            extract=args.extract, country=args.country, history=args.history, workdir=args.workdir, reader=args.reader,
            gazetteer=args.gazetteer, gazetteer_out=args.gazetteer_out, keep_store=args.keep_store, passphrase_file=args.passphrase_file,
            reserve_bytes=int(args.reserve_gb * R.GIB), min_available_bytes=int(args.min_available_mb * R.MIB),
            floor_factor=args.floor_factor,
            min_free_override=int(args.min_free_gb * R.GIB) if args.min_free_gb is not None else None,
            prior_report=prior, sample_seconds=args.sample_seconds, plan_only=args.plan,
            on_start=lambda d: print(f"store: {d} (if this run is killed, delete it with --cleanup)", flush=True),
            report_path=None if args.plan else target,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"refused: {exc}")
        return 2

    if args.plan:
        print(json.dumps({"preflight": report["preflight"], "inputs": report["inputs"], "host": report["host"],
                          "guards": report["guards"]}, indent=2, sort_keys=True))
        return 0 if report["preflight"]["ok"] else 2
    # The exit code is settled BEFORE anything is printed: a closed terminal (a dropped session) makes print
    # raise OSError, and that must not turn "interrupted" (3) into a traceback and a 1.
    code = {"ok": 0, "failed": 1, "interrupted": 3}.get(report["status"], 2)
    with contextlib.suppress(OSError):
        phases = ", ".join(f"{p['name']}={p['status']} {p['wall_seconds']}s" for p in report["phases"]) or "none started"
        print(f"status: {report['status']}  ({phases})")
        if report.get("reason"):
            print(f"reason: {report['reason']}")
        if report.get("interrupted_by"):
            print(f"note: the run finished on its own; a {report['interrupted_by']} reached the runner as it ended")
        print(f"store: {'kept at ' + str(kept) + ' (delete with --cleanup)' if kept else 'deleted' if report['store'].get('deleted') else 'none made'}")
        if report.get("report_write_error"):
            print(f"the report could not be written ({report['report_write_error']}); it follows:")
            print(json.dumps(report, indent=2, sort_keys=True, default=str))
        else:
            print(f"report: {target.name}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
