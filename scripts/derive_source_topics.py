#!/usr/bin/env python3
"""
Derive deduced topic tags for sources from the live corpus (Strategy 1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Runs against the LIVE encrypted corpus (so the maintainer runs it; the sandbox/CI
has no DB). Aggregates the controlled TOPIC tags of the keywords each source
publishes (src/analytics/source_topics.py) and writes deduced rows in the format
scripts/merge_enrichment_results.py consumes.

Honesty: the topics are DEDUCED from coverage, never asserted -- rows carry
``note: deduced:corpus`` and a confidence (never "high"). Review before merging;
a strict merge can exclude them entirely:
  python scripts/merge_enrichment_results.py results/topics.yaml --min-confidence high   # drops all deduced

Examples:
  python scripts/derive_source_topics.py --min-articles 5 --top-n 4
  python scripts/derive_source_topics.py --out results/topics.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=_ROOT / "results" / "topics.yaml")
    ap.add_argument("--min-articles", type=int, default=5)
    ap.add_argument("--top-n", type=int, default=4)
    args = ap.parse_args(argv)

    from src.analytics.source_topics import derive_source_topics
    from src.database.session import session_scope

    with session_scope() as session:
        rows = derive_source_topics(
            session, min_articles=args.min_articles, top_n=args.top_n
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(yaml.safe_dump(rows, allow_unicode=True, sort_keys=False), encoding="utf-8")
    n_topics = sum(len(r["topics"]) for r in rows)
    print(f"Derived topics for {len(rows)} sources ({n_topics} topic tags) -> {args.out}")
    print("These are DEDUCED from corpus coverage. Review, then:")
    print(f"  python scripts/merge_enrichment_results.py {args.out} --min-confidence medium")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
