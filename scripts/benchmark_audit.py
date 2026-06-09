#!/usr/bin/env python3
"""
Open Omniscience - audit benchmark harness (Phase 4, findings PERF-01/PERF-02).
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Measured, reproducible micro-benchmarks on synthetic local data -- NEVER live
scraping. Run:  python scripts/benchmark_audit.py [--rows N]

Reports:
  1. Near-duplicate clustering (MinHash + LSH) time vs corpus size -> is it
     near-linear, or O(n^2)?  (PERF-01)
  2. /api/articles query latency on a seeded DB: recency-browse and FTS search,
     p50/p95, plus EXPLAIN QUERY PLAN to show which index is used.  (PERF-02)

Everything runs against a throwaway SQLite DB in a temp dir (OO_DATA_DIR), so it
never touches a real corpus.
"""

from __future__ import annotations

import argparse
import os
import random
import statistics
import tempfile
import time
from pathlib import Path

# Bind all on-disk artifacts to a throwaway dir BEFORE importing src.* (the
# engine is computed from OO_DATA_DIR at import time).
_TMP = tempfile.mkdtemp(prefix="oo-bench-")
os.environ.setdefault("OO_DATA_DIR", _TMP)
os.environ.setdefault("OO_NO_SCHEDULER", "1")

WORDS = ("market crisis election protest court ruling climate energy bank merger "
         "drought flood treaty sanction summit verdict inflation strike vote reform "
         "border refugee scandal probe leak audit budget tariff oil metal harvest").split()


def _make_text(rng: random.Random, n_words: int = 120) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(n_words))


def bench_near_dup(sizes: list[int]) -> list[tuple[int, float, int]]:
    from src.signals.near_dup import near_duplicate_clusters

    rng = random.Random(42)
    out = []
    for n in sizes:
        # ~10% are near-duplicates of an earlier doc (realistic dedup workload).
        docs: dict[str, str] = {}
        base = [_make_text(rng) for _ in range(max(1, n // 10))]
        for i in range(n):
            if base and rng.random() < 0.1:
                t = rng.choice(base) + " " + rng.choice(WORDS)
            else:
                t = _make_text(rng)
            docs[str(i)] = t
        t0 = time.perf_counter()
        result = near_duplicate_clusters(docs)
        dt = time.perf_counter() - t0
        n_clusters = len(result.clusters)
        out.append((n, dt, n_clusters))
        print(f"  near_dup  n={n:>6}  time={dt*1000:8.1f} ms  clusters={n_clusters}")
    return out


def _seed_db(session, n: int) -> None:
    from datetime import datetime, timedelta, timezone

    from src.database.models import Article, Source

    rng = random.Random(7)
    src = Source(name="Bench", domain="bench.example", language="en")
    session.add(src)
    session.flush()
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)
    batch = []
    for i in range(n):
        body = _make_text(rng, 200)
        batch.append(Article(
            url=f"https://bench.example/a/{i}",
            canonical_url=f"https://bench.example/a/{i}",
            source_id=src.id,
            title=f"Article {i} {rng.choice(WORDS)}",
            content=body,
            published_at=base + timedelta(minutes=i),
            language="en",
            hash=f"{i:064x}",
            word_count=200,
        ))
        if len(batch) >= 2000:
            session.bulk_save_objects(batch)
            session.commit()
            batch = []
    if batch:
        session.bulk_save_objects(batch)
        session.commit()


def _percentiles(samples: list[float]) -> tuple[float, float]:
    s = sorted(samples)
    p50 = statistics.median(s)
    p95 = s[min(len(s) - 1, int(0.95 * len(s)))]
    return p50, p95


def bench_db(n: int) -> None:
    from sqlalchemy import text

    from src.database.fts import ensure_fts, search_ids
    from src.database.models import Article
    from src.database.session import SessionLocal, engine, init_db

    init_db()
    ensure_fts(engine)
    session = SessionLocal()
    print(f"  seeding {n} articles ...", flush=True)
    t0 = time.perf_counter()
    _seed_db(session, n)
    # rebuild FTS over the seeded rows
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO article_fts(article_fts) VALUES ('rebuild')"))
    print(f"  seeded in {time.perf_counter()-t0:.1f}s")

    # --- recency browse (no query): the default /api/articles path ---
    def browse():
        q = (session.query(Article)
             .order_by(Article.published_at.desc(), Article.id.desc())
             .limit(100))
        return q.all()

    browse()  # warm
    samples = [(_t := time.perf_counter(), browse(), time.perf_counter() - _t)[2] for _ in range(30)]
    p50, p95 = _percentiles(samples)
    print(f"  recency-browse (limit 100): p50={p50*1000:.2f} ms  p95={p95*1000:.2f} ms")

    # --- FTS search ---
    def fts():
        ids = search_ids(session, "market AND court")
        return (session.query(Article).filter(Article.id.in_(ids[:100])).all()
                if ids else [])

    fts()  # warm
    samples = [(_t := time.perf_counter(), fts(), time.perf_counter() - _t)[2] for _ in range(30)]
    p50, p95 = _percentiles(samples)
    print(f"  FTS 'market AND court':     p50={p50*1000:.2f} ms  p95={p95*1000:.2f} ms")

    # --- EXPLAIN QUERY PLAN for the recency browse ---
    with engine.connect() as conn:
        plan = conn.execute(text(
            "EXPLAIN QUERY PLAN SELECT * FROM articles "
            "ORDER BY published_at DESC, id DESC LIMIT 100"
        )).fetchall()
        print("  EXPLAIN (recency browse):")
        for row in plan:
            print("    ", row[-1])

    # --- index footprint: list indexes on articles + sizes ---
    with engine.connect() as conn:
        idxs = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='articles' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )).fetchall()
        print(f"  indexes on articles ({len(idxs)}):", ", ".join(r[0] for r in idxs))
    session.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=50000)
    ap.add_argument("--near-dup-sizes", type=str, default="1000,5000,10000")
    args = ap.parse_args()

    print("== PERF-01: near-duplicate clustering scaling ==")
    sizes = [int(x) for x in args.near_dup_sizes.split(",")]
    bench_near_dup(sizes)

    print(f"\n== PERF-02: DB query latency on {args.rows} rows ==")
    bench_db(args.rows)


if __name__ == "__main__":
    main()
