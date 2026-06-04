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
    print(f"Seeded sources: {result['created']} created, {result['skipped']} already present "
          f"(of {result['total']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
