#!/usr/bin/env python3
"""
Open Omniscience - performance harness for the 0.09 PERFORMANCE BATCH.
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Measure -> fix -> re-measure (maintainer-mandated 2026-06-12): the app got very
slow at 6.4k articles / 228k keywords / 243 MB, and the keyword diagnostics
export initially failed at that scale. This harness builds a DETERMINISTIC
synthetic corpus of exactly that shape in a throwaway OO_DATA_DIR and times the
hot endpoints in-process (FastAPI TestClient -- no sockets, no network, ever).

Run:  python scripts/perf_harness.py [--articles 6400] [--keywords 228000]
                                     [--scale 0.1] [--json out.json]
                                     [--endpoints-only] [--encrypted]

100k SCALE PROFILE (audit-07 B3 / OO-D8-001): a year of continuous collection is
~10-20x the T1-tested shape. Run the named-path profile with
    python scripts/perf_harness.py --articles 100000 --keywords 3600000 \
        --encrypted --json perf_100k.json
It now also times the FTS rebuild and the corpus-window/search/briefing paths the
audit flagged as unmeasured. NOTE: this run is heavy (~GBs on disk, minutes-to-
hours of build + decrypt) and is intended for a maintainer/CI box, not this
sandbox -- measure first, then fix what fails the existing thresholds.

Honesty notes (the numbers' method, printed with them):
  * Synthetic corpus: Zipf-distributed mentions over 16 catalog languages,
    ~35 KB of text per article -- the SHAPE of the maintainer's live corpus,
    not its content. Numbers are comparative (before/after a fix on the same
    machine), never absolute promises for other hardware.
  * Each endpoint is called twice: cold (first touch after connect) and warm
    (page cache populated). Both are reported; neither is an average of the
    other.
  * --encrypted measures through SQLCipher (every page read costs a decrypt),
    the shipped default for fresh installs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Bind all on-disk artifacts to a throwaway dir BEFORE importing src.* (the
# engine binds to OO_DATA_DIR at import time). Same pattern as benchmark_audit.
_TMP = os.environ.get("OO_PERF_DIR") or tempfile.mkdtemp(prefix="oo-perf-")
os.environ["OO_DATA_DIR"] = _TMP
os.environ.setdefault("OO_NO_SCHEDULER", "1")
os.environ.setdefault("OO_FIELD_TEST", "0")

LANGS = ["en", "fr", "de", "es", "it", "pt", "ru", "ar", "zh", "ja", "sv", "nl", "pl", "tr", "fa", "uk"]  # 16 catalog languages
COUNTRIES = ["us", "fr", "de", "es", "it", "br", "ru", "eg", "cn", "jp", "se", "nl", "pl", "tr", "ir", "ua", "gb", "in", "ke", "ng", "za", "mx", "ca", "au", "ar"]

WORDS = ["market", "crisis", "election", "protest", "court", "ruling", "climate", "energy", "bank", "merger", "drought", "flood", "treaty", "sanction", "summit", "verdict", "inflation", "strike", "vote", "reform", "border", "refugee", "scandal", "probe", "leak", "audit", "budget", "tariff", "oil", "metal", "harvest", "minister", "parliament", "senate", "currency", "pipeline", "embargo", "ceasefire", "mandate"]


def log(msg: str) -> None:
    print(f"[perf] {msg}", flush=True)


# --------------------------------------------------------------------------- #
# Corpus generation (raw SQL, batched -- the ORM would take minutes here)
# --------------------------------------------------------------------------- #
def build_corpus(n_articles: int, n_keywords: int, body_kb: int = 35) -> dict:
    from sqlalchemy import text

    from src.database.session import engine, init_db

    t0 = time.perf_counter()
    init_db()
    rng = random.Random(42)

    n_sources = max(40, min(400, n_articles // 16))

    with engine.begin() as conn:
        # Sources spread over countries/languages (coverage endpoints need this).
        src_rows = []
        for i in range(n_sources):
            cc = COUNTRIES[i % len(COUNTRIES)]
            lang = LANGS[i % len(LANGS)]
            src_rows.append(
                {
                    "name": f"Synthetic Outlet {i}",
                    "domain": f"outlet-{i}.example",
                    "rss_url": f"https://outlet-{i}.example/feed",
                    "language": lang,
                    "country": cc,
                    "enabled": True,
                    "tags": "synthetic,perf",
                }
            )
        conn.execute(
            text(
                "INSERT INTO sources (name, domain, rss_url, language, country, enabled, tags) "
                "VALUES (:name, :domain, :rss_url, :language, :country, :enabled, :tags)"
            ),
            src_rows,
        )
        source_ids = [r[0] for r in conn.execute(text("SELECT id FROM sources")).fetchall()]
        src_lang = {
            r[0]: (r[1], r[2])
            for r in conn.execute(text("SELECT id, language, country FROM sources")).fetchall()
        }

        # Articles: ~body_kb KB of plain text each (the 243 MB is mostly content).
        filler_words = [rng.choice(WORDS) for _ in range(4000)]
        base_body = " ".join(filler_words)
        per_article_words = max(1, (body_kb * 1024) // (len(base_body) // len(filler_words) + 1))
        art_rows = []
        for i in range(n_articles):
            sid = source_ids[i % len(source_ids)]
            lang, cc = src_lang[sid]
            published = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(
                minutes=rng.randint(0, 60 * 24 * 520)
            )
            body = f"synthetic article {i} " + " ".join(
                rng.choice(filler_words) for _ in range(per_article_words)
            )
            art_rows.append(
                {
                    "url": f"https://outlet/{i}",
                    "canonical_url": f"https://outlet/{i}",
                    "source_id": sid,
                    "title": f"Synthetic headline {i} {rng.choice(WORDS)}",
                    "content": body,
                    "published_at": published.replace(tzinfo=None),
                    "language": lang,
                    "country": cc,
                    "hash": hashlib.sha256(f"perf-{i}".encode()).hexdigest(),
                    "word_count": per_article_words,
                }
            )
            if len(art_rows) >= 500:
                conn.execute(
                    text(
                        "INSERT INTO articles (url, canonical_url, source_id, title, content, "
                        "published_at, language, country, hash, word_count) VALUES "
                        "(:url, :canonical_url, :source_id, :title, :content, :published_at, "
                        ":language, :country, :hash, :word_count)"
                    ),
                    art_rows,
                )
                art_rows = []
        if art_rows:
            conn.execute(
                text(
                    "INSERT INTO articles (url, canonical_url, source_id, title, content, "
                    "published_at, language, country, hash, word_count) VALUES "
                    "(:url, :canonical_url, :source_id, :title, :content, :published_at, "
                    ":language, :country, :hash, :word_count)"
                ),
                art_rows,
            )
        art_meta = conn.execute(
            text("SELECT id, language, country, date(published_at) FROM articles")
        ).fetchall()

        # Keywords: per-language vocabularies (the per-language cap needs them).
        kw_rows = []
        for i in range(n_keywords):
            lang = LANGS[i % len(LANGS)]
            term = f"{lang}-term-{i // len(LANGS)}"
            kw_rows.append(
                {"term": term, "normalized_term": term, "language": lang, "frequency": 0}
            )
            if len(kw_rows) >= 10000:
                conn.execute(
                    text(
                        "INSERT INTO keywords (term, normalized_term, language, frequency) "
                        "VALUES (:term, :normalized_term, :language, :frequency)"
                    ),
                    kw_rows,
                )
                kw_rows = []
        if kw_rows:
            conn.execute(
                text(
                    "INSERT INTO keywords (term, normalized_term, language, frequency) "
                    "VALUES (:term, :normalized_term, :language, :frequency)"
                ),
                kw_rows,
            )

        # Mentions: Zipf-shaped -- rank-1 keywords reach ~40% of articles, the
        # long tail gets one. Unique (keyword_id, article_id); ~4x keywords.
        kid_lang = conn.execute(text("SELECT id, language FROM keywords")).fetchall()
        arts_by_lang: dict[str, list] = {}
        for aid, lang, cc, pub in art_meta:
            arts_by_lang.setdefault(lang, []).append((aid, cc, pub))
        all_arts = [(aid, cc, pub) for aid, lang, cc, pub in art_meta]

        mention_rows = []
        total_mentions = 0
        for rank, (kid, lang) in enumerate(kid_lang, start=1):
            n = max(1, int(n_articles * 0.4 / (rank**0.85)))
            pool = arts_by_lang.get(lang) or all_arts
            picks = rng.sample(pool, min(n, len(pool)))
            for aid, cc, pub in picks:
                mention_rows.append(
                    {
                        "keyword_id": kid,
                        "article_id": aid,
                        "count": rng.randint(1, 9),
                        "observed_on": pub,
                        "country": cc,
                        "extractor": "synthetic",
                    }
                )
            total_mentions += len(picks)
            if len(mention_rows) >= 50000:
                conn.execute(
                    text(
                        "INSERT INTO keyword_mentions (keyword_id, article_id, count, "
                        "observed_on, country, extractor) VALUES (:keyword_id, :article_id, "
                        ":count, :observed_on, :country, :extractor)"
                    ),
                    mention_rows,
                )
                mention_rows = []
        if mention_rows:
            conn.execute(
                text(
                    "INSERT INTO keyword_mentions (keyword_id, article_id, count, "
                    "observed_on, country, extractor) VALUES (:keyword_id, :article_id, "
                    ":count, :observed_on, :country, :extractor)"
                ),
                mention_rows,
            )

    db_file = Path(_TMP) / "open_omniscience.db"
    shape = {
        "articles": n_articles,
        "sources": n_sources,
        "keywords": n_keywords,
        "mentions": total_mentions,
        "db_bytes": db_file.stat().st_size if db_file.exists() else None,
        "build_s": round(time.perf_counter() - t0, 1),
        "data_dir": _TMP,
    }
    log(f"corpus built: {shape}")
    return shape


# --------------------------------------------------------------------------- #
# Measurement
# --------------------------------------------------------------------------- #
HOT_ENDPOINTS = [
    "/api/diagnostics/keywords",  # the maintainer-reported failure
    "/api/database/stats",  # Library tab, polled
    "/api/database/coverage",
    "/api/database/countries",
    "/api/insights/top?limit=50",
    "/api/insights/trending",
    "/api/insights/associations?term=en-term-1",
    "/api/insights/graph?term=en-term-1",
    "/api/insights/map",
    "/api/timemap/range",
    "/api/briefing",  # Home cards (briefing recompute) -- audit-07 B3
    "/api/articles?limit=50",  # reader list
    "/api/search/omni?q=en-term-1",  # index-backed omnibar (FTS5) -- audit-07 B3
    "/api/insights/corpus-sentiment?days=3650",  # a corpus-window aggregate -- audit-07 B3
]


def measure_fts_rebuild() -> dict:
    """Time a full FTS5 rebuild over the corpus.

    The FTS rebuild is a maintenance path whose cost grows with the article count;
    audit-07 B3 named it (with briefing recompute and corpus windows) as unmeasured
    at ~10-20x the T1-tested scale. Timing it here lets a 100k profile expose any
    regression instead of discovering it in the field.
    """
    from src.database.fts import ensure_fts
    from src.database.session import engine

    t0 = time.perf_counter()
    ensure_fts(engine)  # idempotent DDL + INSERT INTO article_fts(article_fts) VALUES ('rebuild')
    return {
        "endpoint": "FTS rebuild (maintenance)",
        "cold_ms": round((time.perf_counter() - t0) * 1000),
        "warm_ms": None,
        "status": "ok",
        "bytes": "-",
    }


def _rss_mb() -> float | None:
    try:
        import psutil

        return round(psutil.Process(os.getpid()).memory_info().rss / 1048576, 1)
    except Exception:  # noqa: BLE001 - measurement aid only
        return None


def measure(endpoints: list[str]) -> list[dict]:
    from fastapi.testclient import TestClient

    from src.api.main import app

    results: list[dict] = []
    with TestClient(app) as client:
        for ep in endpoints:
            row: dict = {"endpoint": ep}
            for phase in ("cold", "warm"):
                rss_before = _rss_mb()
                t0 = time.perf_counter()
                try:
                    resp = client.get(ep)
                    elapsed = time.perf_counter() - t0
                    row[phase + "_ms"] = round(elapsed * 1000)
                    row["status"] = resp.status_code
                    row["bytes"] = len(resp.content)
                except Exception as exc:  # noqa: BLE001 - report, don't crash the run
                    row[phase + "_ms"] = None
                    row["status"] = f"EXC:{type(exc).__name__}"
                    row["error"] = str(exc)[:160]
                    break
                finally:
                    rss_after = _rss_mb()
                    if rss_before is not None and rss_after is not None:
                        row[phase + "_rss_delta_mb"] = round(rss_after - rss_before, 1)
            results.append(row)
            log(
                f"{ep}: cold={row.get('cold_ms')}ms warm={row.get('warm_ms')}ms "
                f"status={row.get('status')} bytes={row.get('bytes')}"
            )
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--articles", type=int, default=6400)
    ap.add_argument("--keywords", type=int, default=228_000)
    ap.add_argument("--scale", type=float, default=1.0, help="scale both counts (0.1 = quick run)")
    ap.add_argument("--body-kb", type=int, default=35)
    ap.add_argument("--json", type=str, default=None, help="write results JSON here")
    ap.add_argument(
        "--endpoints-only",
        action="store_true",
        help="reuse the corpus already in OO_PERF_DIR (skip generation)",
    )
    ap.add_argument(
        "--encrypted",
        action="store_true",
        help="measure through SQLCipher (the shipped default for fresh installs)",
    )
    args = ap.parse_args()

    # At-rest profile, decided BEFORE the first src import binds the engine.
    if args.encrypted:
        os.environ.setdefault("OO_DB_PASSPHRASE", "perf-harness-throwaway")
        os.environ.pop("OO_DB_PLAINTEXT", None)
    else:
        os.environ["OO_DB_PLAINTEXT"] = "1"

    n_articles = int(args.articles * args.scale)
    n_keywords = int(args.keywords * args.scale)

    shape: dict = {}
    if not args.endpoints_only:
        shape = build_corpus(n_articles, n_keywords, body_kb=args.body_kb)

    # Maintenance path that scales with corpus size (audit-07 B3) before endpoints.
    maintenance = [measure_fts_rebuild()] if not args.endpoints_only else []
    results = maintenance + measure(HOT_ENDPOINTS)

    out = {
        "method": (
            "Synthetic deterministic corpus (shape of the 2026-06-12 live report: "
            "6.4k articles / 228k keywords / 243 MB), in-process TestClient, "
            "cold+warm wall-clock per endpoint. Comparative numbers for this "
            "machine only."
        ),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "corpus": shape,
        "results": results,
    }
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2))
        log(f"wrote {args.json}")

    width = max(len(r["endpoint"]) for r in results)
    print(f"\n{'endpoint':<{width}}  {'cold':>8}  {'warm':>8}  {'status':>6}  {'bytes':>12}")
    for r in results:
        print(
            f"{r['endpoint']:<{width}}  {str(r.get('cold_ms')) + 'ms':>8}  "
            f"{str(r.get('warm_ms')) + 'ms':>8}  {str(r.get('status')):>6}  "
            f"{str(r.get('bytes', '-')):>12}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
