#!/usr/bin/env python3
"""Build the place gazetteer (configs/places_gazetteer.yml) from row D's osm.db (S05-03 S4).

Open Omniscience - Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The operator's half of 0.5 row C: OpenStreetMap ``place=*`` objects of one or more ingested
countries, joined to Wikidata for population, labels in the twelve languages and a coordinate
check, written in the shape ``src/catalog/cities.py`` loads. The loader reads the file BESIDE the
world-city file and merges the two by QID; this never overwrites ``configs/cities.yml``.

It reads the lane (``osm.db``) the app is NOT running on: run it with the app STOPPED, against the
data directory ``scripts/osm_ingest.py`` filled, with ``OO_DB_PASSPHRASE`` set for an encrypted one
(or ``--passphrase-file``). It DELETES NOTHING and never touches the corpus.

HOW WIKIDATA IS JOINED is a choice you must make, because the default makes no request:

    --plan                  count the QIDs and print the request count and minimum run time. Reads
                            osm.db only; writes nothing, asks nothing.
    --no-wikidata           write the OSM-only artifact (no Wikidata-derived value; source: osm).
    --wikidata-fixture F    join from a recorded wbgetentities answer F. Opens no socket.
    --online                join from www.wikidata.org. This flag IS your consent to those requests:
                            wbgetentities, up to 50 QIDs each, ONE request at a time, every 10 seconds
                            (R8: it protects Wikidata's shared servers and this User-Agent's standing),
                            with maxlag and a descriptive User-Agent, Retry-After honoured, through the
                            app's one guarded fetch path and your transport setting. It refuses by name
                            under airplane mode.

    python scripts/build_place_gazetteer.py --country FR --plan
    python scripts/build_place_gazetteer.py --country FR --online

Prints the run as JSON: the counts, the plan, the artifact's sha256 and the registry entry to add in
the artifact's own PR. The same osm.db and the same Wikidata answers give the same bytes
(``--built-date`` pins the one date the file records besides the extract's).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "configs" / "places_gazetteer.yml"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--country", action="append", required=True, help="ISO 3166-1 alpha-2 or alpha-3; repeatable")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    how = ap.add_mutually_exclusive_group(required=True)
    how.add_argument("--plan", action="store_true", help="count QIDs, print requests and minimum time; write nothing")
    how.add_argument("--no-wikidata", action="store_true", help="OSM-only artifact")
    how.add_argument("--wikidata-fixture", type=Path, help="join from a recorded wbgetentities answer")
    how.add_argument("--online", action="store_true", help="join from www.wikidata.org (your consent to those requests)")
    ap.add_argument("--passphrase-file", type=Path, help="a file holding the osm.db passphrase (instead of OO_DB_PASSPHRASE)")
    ap.add_argument("--built-date", help="YYYY-MM-DD recorded as the build date (default: today, UTC)")
    args = ap.parse_args(argv)

    import os
    from datetime import date

    if args.passphrase_file is not None:
        try:
            os.environ["OO_DB_PASSPHRASE"] = args.passphrase_file.read_text("utf-8").strip()
        except OSError as exc:
            print(f"refused: cannot read the passphrase file: {type(exc).__name__}")
            return 2

    from src.entities import gazetteer_build as G
    from src.osm.ingest import country_codes

    try:
        built = date.fromisoformat(args.built_date) if args.built_date else G.today()
    except ValueError:
        print(f"refused: --built-date {args.built_date!r} is not YYYY-MM-DD")
        return 2

    try:
        countries: list[dict] = []
        per_country: dict[str, list[G.OsmPlace]] = {}
        read_counts: dict[str, dict] = {}
        seen: set[str] = set()
        for code in args.country:
            a2, a3 = country_codes(code)
            if a3 in seen:
                continue
            seen.add(a3)
            country, pl, counts = G.read_places(a3)
            countries.append(country)
            per_country[country["alpha2"]] = pl
            read_counts[a3] = counts
    except ValueError as exc:
        print(f"refused: {exc}")
        return 2
    except G.GazetteerBuildError as exc:
        print(f"refused: {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001 - the operator reads the reason; never a passphrase
        print(f"failed: could not read osm.db ({type(exc).__name__}); is the app stopped and the passphrase set?")
        return 1

    qids = sorted({p.qid for pl in per_country.values() for p in pl if p.qid})
    plan = G.plan(len(qids))
    out: dict = {"countries": countries, "read": read_counts, "plan": plan}

    if args.plan:
        print(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False))
        return 0

    items = None
    wikidata: dict = {"joined": False}
    if args.wikidata_fixture is not None:
        items = G.items_from_fixture(args.wikidata_fixture)
        wikidata = {"joined": True, "via": "fixture", "items": len(items)}
    elif args.online:
        try:
            items, fetch = G.fetch_wikidata(qids, getter=G.guarded_getter)
        except G.AirplaneRefusal as exc:
            print(f"refused: {exc}")
            return 2
        out["fetch"] = fetch
        if fetch["stopped_by_airplane_mode"]:
            print("refused: airplane mode was engaged during the join; nothing was written", file=sys.stderr)
            print(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False))
            return 2
        if fetch["not_asked"]:
            print("refused: the join was interrupted; nothing was written", file=sys.stderr)
            print(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False))
            return 2
        wikidata = {"joined": True, "via": "wbgetentities", "requests": fetch["requests_made"], "items": len(items)}

    entries: list = []
    stats_all: list[dict] = []
    for c in countries:
        e, st = G.build_entries(per_country[c["alpha2"]], items, country_alpha2=c["alpha2"])
        entries.extend(e)
        st["country"] = c["alpha3"]
        stats_all.append(st)
    entries.sort(key=lambda x: (x["country"], x["name"].casefold(), x["osm"]))

    text = G.render_yaml(entries, countries=countries, wikidata=wikidata, built=built)
    G.write_atomic(args.out, text)
    sha = G.sha256_hex(text.encode("utf-8"))
    vintages = [c["vintage"] for c in countries]
    vintage = min(vintages) if vintages and all(vintages) else None
    try:
        rel = str(args.out.resolve().relative_to(ROOT))
    except ValueError:
        rel = args.out.name
    out.update(
        {
            "artifact": {"path": rel, "bytes": len(text.encode("utf-8")), "sha256": sha, "entries": len(entries),
                         "vintage": vintage},
            "build": stats_all,
            "registry_entry": G.registry_entry(path=rel, sha256=sha, vintage=vintage, built=built),
        }
    )
    print(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
