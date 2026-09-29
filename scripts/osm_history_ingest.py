#!/usr/bin/env python3
"""Cut one country's past out of the full-history planet into ``osm.db`` (S05-04 S4, Q814 = b).

Open Omniscience - Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The operator's half of 0.5 row D's history step: the gate records the full-history file's
measured size and the first country's history ingest time. This runs the same code the app
will, on files already on disk, and prints the recorded row as JSON.

It makes NO network request. Download the full-history planet first (Settings -> OpenStreetMap
-> Full history, under the online consent), and cut the country from its continent extract
first (``scripts/osm_ingest.py``): the history follows that cut's border and objects.

    OO_DATA_DIR=... python scripts/osm_history_ingest.py --history PATH --extract PATH --country FR

The planet-wide file needs the ``[geo]`` extra (pyosmium); the pure-Python reader refuses it
by name. An encrypted install needs ``OO_DB_PASSPHRASE`` set for the run (Q825), and the app
must be STOPPED: the lane is a single-writer database.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--history", required=True, type=Path, help="the full-history .osm.pbf on disk")
    ap.add_argument("--extract", required=True, type=Path, help="the continent extract the country was cut from")
    ap.add_argument("--country", required=True, help="ISO 3166-1 alpha-2 or alpha-3")
    ap.add_argument("--reader", choices=("pyosmium", "python"), default=None)
    args = ap.parse_args()

    from src.database.connect import get_passphrase, is_encrypted_file, plaintext_mode
    from src.osm.history import HistoryError, ingest_history
    from src.osm.reader import GeoExtraMissing
    from src.paths import data_dir
    from src.versioned.store import lane_file_bytes

    corpus = data_dir() / "open_omniscience.db"
    if not get_passphrase() and not plaintext_mode() and is_encrypted_file(corpus) is not False:
        print("refused: the corpus is encrypted (or not created yet); set OO_DB_PASSPHRASE for this run")
        return 2
    before = lane_file_bytes("osm")
    try:
        report = ingest_history(args.history, args.extract, args.country, reader=args.reader)
    except (GeoExtraMissing, HistoryError) as exc:
        print(f"refused: {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001 - the operator reads the reason, the row records it
        print(f"failed: {type(exc).__name__}: {exc}")
        return 1
    out = report.to_dict()
    out["history_bytes"] = args.history.stat().st_size
    out["osm_db_bytes_before"] = before
    out["osm_db_bytes"] = lane_file_bytes("osm")
    print(json.dumps(out, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
