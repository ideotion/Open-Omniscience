#!/usr/bin/env python3
"""Cut one country out of an OSM extract into ``osm.db`` and print what was measured (S05-04).

Open Omniscience - Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The operator's half of 0.5 row D: the gate closes when one country is ingested on the reference
VM with its measured sizes and ingest time recorded. This runs the same code the app will, on a
file already on disk, and prints the recorded row as JSON -- the numbers the gate row cites.

It makes NO network request. Download the continent extract first (Settings, the offline-map
downloads, under the online consent); its file sits in the data directory's ``osm_regions``.

    OO_DATA_DIR=... python scripts/osm_ingest.py --extract PATH --country FR [--reader pyosmium|python]

An encrypted install needs ``OO_DB_PASSPHRASE`` set for the run, because ``osm.db`` is encrypted
with the corpus passphrase (Q825); without it the script refuses before opening anything. (It does
not prompt: the app's one passphrase path is the environment or the unlock screen.) Run it with the app STOPPED: the lane is a
single-writer database.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--extract", required=True, type=Path, help="an .osm.pbf already on disk")
    ap.add_argument("--country", required=True, help="ISO 3166-1 alpha-2 or alpha-3")
    ap.add_argument("--reader", choices=("pyosmium", "python"), default=None)
    args = ap.parse_args()

    from src.database.connect import get_passphrase, is_encrypted_file, plaintext_mode
    from src.osm.ingest import ingest_country
    from src.osm.reader import GeoExtraMissing
    from src.paths import data_dir
    from src.versioned.store import lane_file_bytes

    corpus = data_dir() / "open_omniscience.db"
    if not get_passphrase() and not plaintext_mode() and is_encrypted_file(corpus) is not False:
        print("refused: the corpus is encrypted (or not created yet); set OO_DB_PASSPHRASE for this run")
        return 2
    try:
        report = ingest_country(args.extract, args.country, reader=args.reader)
    except GeoExtraMissing as exc:
        print(f"refused: {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001 - the operator reads the reason, the row records it
        print(f"failed: {type(exc).__name__}: {exc}")
        return 1
    out = report.to_dict()
    out["extract_bytes"] = args.extract.stat().st_size
    out["osm_db_bytes"] = lane_file_bytes("osm")
    print(json.dumps(out, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
