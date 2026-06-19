#!/usr/bin/env python3
"""
Build the offline IP-to-country table (src/geo/data/dbip_country_lite.csv).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Run ONCE, on a machine WITH network. Downloads **DB-IP IP-to-Country Lite
(CC BY 4.0)** for a given month and writes the compact ``start_ip,end_ip,country_code``
CSV the offline geolocator (src/geo/ip_geo.py) reads. Until you run this, the geolocator
has NO country DB and honestly returns ``level="unavailable"`` (it never fabricates a
location). The download is network-blocked in the CI/dev sandbox (403), which is exactly
why this is an explicit, networked-machine step — like the Wikidata / OSM generators.

After running, set ``IP_GEO_AS_OF`` in src/geo/ip_geo.py to the month you fetched
(YYYY-MM) so the freshness test activates and the map/vintage are honest.

LICENSE: DB-IP IP-to-Country Lite is CC BY 4.0 — attribution to DB-IP.com is MANDATORY
and is carried in src/geo/ip_geo.ATTRIBUTION + shown by the map layer. Verify the exact
current license + size on https://db-ip.com/db/download/ip-to-country-lite before bundling.

Examples:
  python scripts/build_ip_geo.py --month 2026-06
  python scripts/build_ip_geo.py --from path/to/dbip-country-lite-2026-06.csv.gz
"""

from __future__ import annotations

import argparse
import gzip
import io
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_OUT = Path(__file__).resolve().parents[1] / "src" / "geo" / "data" / "dbip_country_lite.csv"
_URL = "https://download.db-ip.com/free/dbip-country-lite-{month}.csv.gz"


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "open-omniscience-ipgeo/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - documented DB-IP URL
        return r.read()


def _validate_csv(text: str) -> int:
    """Sanity-check the rows look like start,end,cc; return the row count or raise."""
    import csv

    n = 0
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 3 or len(row[2].strip()) != 2:
            raise SystemExit(f"unexpected row shape (not DB-IP country CSV): {row!r}")
        n += 1
        if n >= 5:
            break
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--month", help="YYYY-MM of the DB-IP lite release to download")
    ap.add_argument("--from", dest="src", help="use a local .csv/.csv.gz instead of downloading")
    ap.add_argument("--out", default=str(_OUT), help="output CSV path")
    args = ap.parse_args()

    if args.src:
        raw = Path(args.src).read_bytes()
    elif args.month:
        url = _URL.format(month=args.month)
        print(f"downloading {url}")
        raw = _fetch(url)
    else:
        ap.error("pass --month YYYY-MM or --from <file>")
        return 2

    text = gzip.decompress(raw).decode("utf-8") if raw[:2] == b"\x1f\x8b" else raw.decode("utf-8")
    _validate_csv(text)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    rows = text.count("\n")
    print(f"wrote {out} ({rows} rows, {out.stat().st_size} bytes)")
    print("NOW: set IP_GEO_AS_OF in src/geo/ip_geo.py to the release month (YYYY-MM).")
    print("LICENSE: DB-IP IP-to-Country Lite is CC BY 4.0 — keep the attribution.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
