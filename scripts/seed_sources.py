#!/usr/bin/env python3
"""
Seed the curated default sources into the database.

Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Usage:
    python scripts/seed_sources.py [path/to/sources.yaml]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.database.session import init_db, session_scope  # noqa: E402
from src.ingest.seed_sources import load_sources_from_yaml, seed_sources  # noqa: E402


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else None
    init_db()
    sources = load_sources_from_yaml(path)
    with session_scope() as session:
        result = seed_sources(session, sources)
    # `skipped` sums three different facts, and calling all of them "already present"
    # was wrong for two: an entry shadowed by an earlier sibling of the same catalogue
    # can never be registered on any install, and a malformed one never could either.
    print(
        f"Seeded sources: {result['created']} created, "
        f"{result['skipped_existing']} already present (of {result['total']})."
    )
    if result["shadowed"]:
        print(
            f"  {result['shadowed']} catalogue entries were SHADOWED -- an earlier entry "
            "claims the same domain, so these can never be registered. They are not "
            "duplicates: see catalog_domain_collisions() for what is lost."
        )
        for ex in result["shadowed_examples"]:
            print(f"    - {ex['name']} ({ex['domain']})")
    if result["skipped_malformed"]:
        print(f"  {result['skipped_malformed']} entries carried no usable domain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
