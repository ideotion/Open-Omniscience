#!/usr/bin/env python3
"""Row J (S05-10) S1: what a source is keyed on, measured on the catalogue an install really seeds.

Read-only: it captures what ``seed_default_sources`` hands the seeder (the production function, never
a rebuild of its inputs -- the 494-vs-475 lesson) and counts what each key would do. Prints numbers.

    python scripts/measure_feed_key.py
"""

from __future__ import annotations

import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.ingest.seed_sources as ss  # noqa: E402
from src.ingest.feed_key import feed_key  # noqa: E402


def capture() -> list[dict]:
    got: list[dict] = []
    real = ss.seed_sources
    ss.seed_sources = lambda _s, srcs: got.extend(srcs) or {  # type: ignore[assignment]
        "created": 0, "skipped": 0, "total": 0, "skipped_existing": 0,
        "shadowed": 0, "shadowed_examples": [],
    }
    try:
        ss.seed_default_sources(session=None)  # type: ignore[arg-type]
    finally:
        ss.seed_sources = real  # type: ignore[assignment]
    return got


def main() -> int:
    cap = [s for s in capture() if s.get("domain")]
    first: dict[str, dict] = {}
    shadowed: list[dict] = []
    for s in cap:
        if s["domain"] in first:
            shadowed.append(s)
        else:
            first[s["domain"]] = s
    feed_domains = {s["domain"] for s in cap if feed_key(s.get("rss_url"))}

    seen: set[tuple[str, str]] = set()
    rows = merged = residue = 0
    shadow_ids = {id(s) for s in shadowed}
    fate: collections.Counter[str] = collections.Counter()
    for s in cap:
        k = feed_key(s.get("rss_url"))
        if not k and s["domain"] in feed_domains:
            merged += 1
            fate["merged" if id(s) in shadow_ids else "other-merged"] += 1
            continue
        key = (s["domain"], k)
        if key in seen:
            residue += 1
            fate["residue" if id(s) in shadow_ids else "other-residue"] += 1
            continue
        seen.add(key)
        rows += 1
        if id(s) in shadow_ids:
            fate["new-row"] += 1

    cross = collections.defaultdict(set)
    for s in cap:
        if feed_key(s.get("rss_url")):
            cross[feed_key(s["rss_url"])].add(s["domain"])
    print(f"entries {len(cap)}  domains {len(first)}  shadowed today {len(shadowed)}")
    print(f"shadowed with a feed {sum(1 for s in shadowed if feed_key(s.get('rss_url')))}"
          f"  without {sum(1 for s in shadowed if not feed_key(s.get('rss_url')))}")
    print(f"feeds carried by more than one DOMAIN (separate rows today): "
          f"{sum(1 for v in cross.values() if len(v) > 1)}")
    print(f"under UNIQUE(domain, feed_key): rows {rows}  feed-less merged as tags {merged}"
          f"  unregistered {residue}")
    print(f"of the {len(shadowed)} shadowed: " + "  ".join(f"{k} {v}" for k, v in sorted(fate.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
