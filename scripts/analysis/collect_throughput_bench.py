#!/usr/bin/env python3
"""Where does a collect pass spend its time? — a reproducible, network-free harness.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. "Article download is slow" has, until now, only ever been answered
from field logs after the fact. The collector's own instrument
(``src/monitoring/collect_perf.py``) samples a LIVE pass and classifies a bottleneck,
which is the right shape for the field and the wrong shape for a question a session
must answer today, offline, against two trees. This harness answers that one: it
serves every fetch from memory with an injectable latency, so the only variable left
is the app's OWN cost per article.

WHAT IT MEASURES, and what a reader may therefore conclude:

  ``stages``  -- per-article CPU of each extraction step, called directly. No DB, no
                 fetcher, no threads. This is the number that scales with nothing but
                 the article, so it is the one to compare ACROSS TREES.
  ``pass``    -- a whole ``run_scrape_once`` against an in-memory HTTP double, with a
                 real DB and the real worker pool, governor and write gate. ``--delay``
                 is the simulated per-fetch latency: 0.02 stands for a fast direct
                 link, 1.5 for the Tor shape the field runs on.
  ``sweep``   -- ``pass`` repeated across worker counts. This is what shows whether
                 ``collect_parallelism`` buys anything at a given latency.
  ``governor``-- the control loop alone, driven with fixed contention flags. No I/O at
                 all; it answers "what would the governor do if this flag were true",
                 which a live pass can only answer by accident.

WHAT IT CANNOT SEE, stated rather than implied:

  * Real network variance, real hosts, real robots, real Tor. ``--delay`` is a
    constant, so this measures the app against an idealised transport and will always
    look BETTER than the field.
  * SQLCipher. The harness runs the plaintext store (``OO_DB_PLAINTEXT``), so every DB
    figure here is a floor -- the encrypted store pays a codec decrypt per page on top.
  * The pass TAIL and the housekeeping lane. ``run_scrape_once`` is the collection
    itself; discovery, enrichment, the briefing refresh and the WAL checkpoint run
    around it and are not in these numbers.
  * Anything about a specific machine. Absolute figures are this box's; the RATIOS
    (stage shares, the parallelism curve, tree-vs-tree) are what travel.

USAGE

    python3 scripts/analysis/collect_throughput_bench.py stages
    python3 scripts/analysis/collect_throughput_bench.py pass --delay 1.5 --workers 8
    python3 scripts/analysis/collect_throughput_bench.py sweep --delay 1.5
    python3 scripts/analysis/collect_throughput_bench.py governor
    python3 scripts/analysis/collect_throughput_bench.py patterns

    # compare two trees (a git worktree of an older commit works unchanged):
    python3 scripts/analysis/collect_throughput_bench.py stages --repo /tmp/oo-old
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import tempfile
import time
import uuid

# Deliberately mundane newswire filler. The extractors this harness measures are
# language- and content-sensitive, so the corpus has to look like prose rather than
# like random characters, and it has to be the SAME prose across trees.
_VOCAB = [
    "government", "report", "analysts", "said", "the", "market", "moved", "sharply",
    "after", "officials", "confirmed", "a", "new", "policy", "on", "energy", "imports",
    "which", "economists", "described", "as", "significant", "for", "the", "region",
    "and", "its", "trading", "partners", "over", "the", "coming", "months",
    "parliament", "committee", "minister", "budget", "inflation", "exports", "tariffs",
    "regulation", "industry", "workers", "union", "agreement", "talks",
]


def _bootstrap(repo: str) -> None:
    """Point the interpreter at ``repo`` and give it a throwaway data dir.

    Set BEFORE any ``src.*`` import: ``src.database.session`` reads ``OO_DATA_DIR`` at
    import time, so a late assignment binds the wrong directory (the same trap
    tests/conftest.py documents).
    """
    os.environ.setdefault("OO_DATA_DIR", tempfile.mkdtemp(prefix="oo-bench-"))
    os.environ.setdefault("OO_DB_PLAINTEXT", "1")
    os.environ.setdefault("OO_NO_SCHEDULER", "1")
    os.environ.setdefault("OO_AUTOSEED", "0")
    os.environ.setdefault("OO_LLM_AUTOSTART", "0")
    os.environ.setdefault("OO_LLM_AUTORELEASE", "0")
    sys.path.insert(0, repo)


def _body(rnd: random.Random, nchars: int) -> str:
    out: list[str] = []
    n = 0
    while n < nchars:
        p = " ".join(rnd.choice(_VOCAB) for _ in range(rnd.randint(30, 70)))
        if rnd.random() < 0.3:
            p += " On 11 September 2001 and again in March 2024 officials in Berlin and Nairobi met."
        out.append("<p>" + p + "</p>")
        n += len(p)
    return "".join(out)


def _page(rnd: random.Random, i: int, j: int, size: int) -> str:
    # Carries the metadata a real news page carries. WITHOUT
    # article:published_time trafilatura falls through htmldate to dateparser's
    # whole-locale search, which is ~430 ms on its own -- a real tail cost, but a
    # different measurement from this one, and it would swamp everything here.
    return (
        f"<html lang='en'><head><title>Story {i}-{j} about the policy</title>"
        f"<meta property='article:published_time' content='2026-03-04T09:15:00Z'>"
        f"<meta name='author' content='A Reporter'></head><body><article>"
        f"<h1>Story {i}-{j} about the policy</h1>{_body(rnd, size)}</article></body></html>"
    )


# --------------------------------------------------------------------------- #
# stages: per-article CPU of each extraction step
# --------------------------------------------------------------------------- #

def cmd_stages(args) -> None:
    from src.analytics.extract import get_extractor
    from src.ingest.extract import extract_article
    from src.timemap.dateextract import extract_dates
    from src.timemap.locextract import extract_locations

    rnd = random.Random(5)
    docs = [_page(rnd, 0, j, args.size) for j in range(args.articles)]
    n = len(docs)

    def timed(label, fn):
        fn()  # warm
        t0 = time.perf_counter()
        fn()
        return (label, (time.perf_counter() - t0) / n * 1000)

    extracted: list = []

    def _ex():
        extracted.clear()
        extracted.extend(extract_article(h, url="https://bench.example/x") for h in docs)

    rows = [timed("extract_article (trafilatura)", _ex)]
    texts = [d.text for d in extracted if d]
    ex = get_extractor("baseline")
    rows.append(timed("keyword extract (baseline)",
                      lambda: [ex.extract(t, title="Story", language="en") for t in texts]))
    rows.append(timed("extract_dates", lambda: [extract_dates(t, language="en") for t in texts]))
    rows.append(timed("extract_locations", lambda: [extract_locations(t) for t in texts]))
    try:
        from src.analytics.sentiment import score_article

        rows.append(timed("score_article (sentiment)",
                          lambda: [score_article(t, language="en") for t in texts]))
    except Exception:  # noqa: BLE001 - an optional extra is absent, not broken
        rows.append(("score_article (sentiment) [absent]", 0.0))
    try:
        from src.ingest.non_article import classify_non_article

        rows.append(timed("classify_non_article",
                          lambda: [classify_non_article("https://x/y", title="Story", text=t,
                                                        word_count=len(t.split()), language="en")
                                   for t in texts]))
    except Exception:  # noqa: BLE001
        pass

    avg = sum(len(t) for t in texts) // max(1, len(texts))
    print(f"per-article extraction CPU  ({n} articles, {avg:,} chars of body text each)")
    print(f"  tree: {args.repo}")
    total = sum(ms for _, ms in rows)
    for label, ms in rows:
        share = ms / total * 100 if total else 0
        print(f"    {label:34s} {ms:8.1f} ms  {share:5.1f}%")
    print(f"    {'TOTAL':34s} {total:8.1f} ms")


# --------------------------------------------------------------------------- #
# pass: a whole run_scrape_once against an in-memory transport
# --------------------------------------------------------------------------- #

class _Resp:
    def __init__(self, text="", ct="text/html", url=None, status=200):
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": ct}
        self.url = url

    def close(self):
        pass


def _run_pass(args, *, workers: int, seed: int = 4) -> tuple[int, float, int]:
    from src.database.models import Source
    from src.database.session import SessionLocal, init_db, session_scope
    from src.ingest import EthicalFetcher
    from src.scheduler.runner import run_scrape_once
    from src.scheduler.settings import SchedulerSettings

    tag = "bench" + uuid.uuid4().hex[:6]
    # A DIFFERENT seed per run, deliberately: the bodies drive the content hash, so
    # re-running the same corpus in one process makes every article a DUPLICATE and
    # the pass reports a throughput that is really the dedup path's. A sweep whose
    # later rows silently measure deduplication is the shape of benchmark that reads
    # as a spectacular speedup.
    rnd = random.Random(seed)
    articles: dict[str, str] = {}
    feeds: dict[str, str] = {}
    for i in range(args.sources):
        host = f"{tag}-{i}.example"
        items = []
        for j in range(args.items):
            u = f"https://{host}/a{j}-{uuid.uuid4().hex[:8]}"
            articles[u] = _page(rnd, i, j, args.size)
            items.append(f"<item><title>S{i}-{j}</title><link>{u}</link></item>")
        feeds[host] = ('<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
                       + "".join(items) + "</channel></rss>")

    class _Serve:
        """robots + feeds + articles from memory, with a fixed per-fetch latency."""

        def __init__(self):
            self.headers: dict = {}
            self.proxies: dict = {}
            self.n = 0

        def get(self, url, timeout=None, allow_redirects=True, headers=None,
                proxies=None, stream=None, **kw):
            if url.endswith("/robots.txt"):
                return _Resp("User-agent: *\nAllow: /", "text/plain", url)
            if args.delay:
                time.sleep(args.delay)
            self.n += 1
            host = url.split("://", 1)[1].split("/", 1)[0]
            if url.endswith("/feed.xml"):
                return _Resp(feeds[host], "application/rss+xml", url)
            return _Resp(articles.get(url, "<html><body>x</body></html>"), "text/html", url)

    init_db()
    with session_scope() as s:
        for i in range(args.sources):
            s.add(Source(name=f"B{i}", domain=f"{tag}-{i}.example",
                         rss_url=f"https://{tag}-{i}.example/feed.xml",
                         enabled=True, status="qualified", language="en", tags=tag,
                         country="fr" if i % 2 else "de"))

    serve = _Serve()
    fetcher = EthicalFetcher(min_interval_s=0.0, retry_backoff_s=0.0, session=serve)
    settings = SchedulerSettings(mode="rss", collect_parallelism=workers,
                                 select_tags=[tag], collect_rate_mode="maximum")
    sel = SessionLocal()
    t0 = time.perf_counter()
    try:
        res = run_scrape_once(sel, fetcher, settings)
    finally:
        sel.close()
    return int(res.get("articles_stored", 0)), time.perf_counter() - t0, serve.n


def cmd_pass(args) -> None:
    stored, dt, fetches = _run_pass(args, workers=args.workers)
    print(f"collect pass  tree={args.repo}")
    print(f"  workers={args.workers}  per-fetch delay={args.delay}s  fetches={fetches}")
    print(f"  stored={stored}  wall={dt:.2f}s  ->  {stored / dt:.2f} articles/s "
          f"({dt / max(1, stored) * 1000:.0f} ms per stored article)")


def cmd_sweep(args) -> None:
    print(f"parallelism sweep  tree={args.repo}  per-fetch delay={args.delay}s")
    print("  workers   wall      articles/s   ms/article")
    for i, w in enumerate([int(x) for x in args.sweep_workers.split(",")]):
        stored, dt, _ = _run_pass(args, workers=w, seed=1000 + i)
        print(f"  {w:>7}  {dt:7.2f}s  {stored / dt:9.2f}   {dt / max(1, stored) * 1000:9.0f}"
              f"   (stored {stored})")


# --------------------------------------------------------------------------- #
# governor: what the control loop does with a given contention flag
# --------------------------------------------------------------------------- #

def cmd_governor(args) -> None:
    from src.scheduler.bandwidth import BandwidthGovernor

    def walk(label, ticks, **flags):
        g = BandwidthGovernor(mode="maximum", w_max=args.workers, min_adjust_interval_s=0.0)
        t = 0.0
        trace = [g.permits]
        why = "seed"
        for _ in range(ticks):
            t += 1.5
            p, why = g.observe(2000.0, now=t, **flags)
            trace.append(p)
        print(f"  {label:36s} {trace[0]:>3} -> {trace[-1]:>3}  after {ticks} ticks "
              f"({ticks * 1.5:.0f}s)  reason={why!r}")
        return trace

    print(f"bandwidth governor, w_max={args.workers}, mode=maximum, 1.5s tick")
    walk("no contention", 80)
    walk("cpu_saturated (sys CPU >= 92%)", 80, cpu_saturated=True)
    walk("writer_saturated", 80, writer_saturated=True)
    t = walk("mem_low (avail < 512 MB)", 80, mem_low=True)
    print(f"    mem_low permit trace: {t[:9]} ...")


# --------------------------------------------------------------------------- #
# patterns: which date regexes carry the cost
# --------------------------------------------------------------------------- #

def cmd_patterns(args) -> None:
    import re

    from src.timemap import dateextract as d

    rnd = random.Random(7)
    paras: list[str] = []
    n = 0
    while n < args.size:
        p = " ".join(rnd.choice(_VOCAB) for _ in range(rnd.randint(30, 70)))
        if rnd.random() < 0.3:
            p += " On 11 September 2001 and again in March 2024 officials met."
        paras.append(p)
        n += len(p)
    text = "\n\n".join(paras)

    alt_len = len(d._MONTH_ALT)
    rows = []
    for name, rx in vars(d).items():
        if not isinstance(rx, re.Pattern):
            continue
        t0 = time.perf_counter()
        for _ in range(3):
            list(rx.finditer(text))
        rows.append(((time.perf_counter() - t0) / 3 * 1000, name, len(rx.pattern)))
    rows.sort(reverse=True)
    total = sum(r[0] for r in rows)
    carriers = [r for r in rows if r[2] > alt_len]

    print(f"date-extractor regex cost  ({len(text):,} chars, one finditer pass each)")
    print(f"  the month alternation is {d._MONTH_ALT.count('|') + 1} names / {alt_len:,} chars")
    for ms, name, plen in rows[:12]:
        mark = "  <- carries the month alternation" if plen > alt_len else ""
        print(f"    {ms:7.2f} ms  {name:22s} pattern={plen:>6,}{mark}")
    print(f"    {total:7.2f} ms  TOTAL over {len(rows)} patterns")
    print(f"\n  {len(carriers)} patterns carry the alternation: {sum(r[0] for r in carriers):.1f} ms "
          f"= {sum(r[0] for r in carriers) / total * 100:.0f}% of all pattern time")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", choices=("stages", "pass", "sweep", "governor", "patterns"))
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), help="tree to measure (a git worktree works)")
    ap.add_argument("--articles", type=int, default=12)
    ap.add_argument("--sources", type=int, default=16)
    ap.add_argument("--items", type=int, default=6)
    ap.add_argument("--size", type=int, default=22000, help="body characters per article")
    ap.add_argument("--delay", type=float, default=0.02,
                    help="simulated per-fetch latency (1.5 ~ the Tor shape)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--sweep-workers", default="1,4,8,16,50")
    args = ap.parse_args()

    _bootstrap(args.repo)
    {"stages": cmd_stages, "pass": cmd_pass, "sweep": cmd_sweep,
     "governor": cmd_governor, "patterns": cmd_patterns}[args.mode](args)


if __name__ == "__main__":
    main()
