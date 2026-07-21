"""
Synthetic collect soak (P0.3 acceptance): flat RSS across recycled passes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Drives the REAL collection stack — ``run_scrape_once`` + the real
``EthicalFetcher`` + the real store/indexer — over SYNTHETIC sources served by
an in-process fake HTTP session. ZERO NETWORK BY CONSTRUCTION: no socket is
ever opened (the "session" is a local object generating feeds/articles), and
the network kill switch is honoured exactly as in production because the real
``EthicalFetcher.fetch`` runs (its kill-switch refusal is the first check).

What it measures, per pass (all numbers real, none fabricated):

  * process RSS before/after the pass and after the between-pass hygiene step
    (the E1/E2 acceptance: RSS stays FLAT across recycled passes instead of
    accumulating for a day);
  * writer-gate deltas (grants / contended / total_wait_s) and per stored
    article (the P1.8 acceptance: batching reduces gate windows + wait);
  * articles stored / duplicates / tally, fetcher cache sizes.

Optionally (``--trip-guard-after-pass N``) it feeds the RSS memory guard fake
over-threshold readings after pass N and PROVES pause-not-die: the next pass
winds down (everything deferred, reason "memory"), then the guard is released
and collection continues — the report shows all of it.

SAFETY: refuses to run unless ``OO_DATA_DIR`` is explicitly set (never against
a default/live data dir). Run it in its own process:

    OO_DATA_DIR=$(mktemp -d) OO_DB_PLAINTEXT=1 OO_COLLECT_COMMIT_BATCH=8 \
        python -m src.testing.collect_soak --passes 6 --sources 100 \
        --items 8 --parallelism 8

The report states plaintext-vs-encrypted honestly (a plaintext run omits the
SQLCipher codec cost — fine for MEMORY soak, stated for write-cost numbers).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import uuid

REPORT_SCHEMA = "oo-collect-soak-1"

_RSS_XML = (
    '<?xml version="1.0"?><rss version="2.0"><channel><title>{d}</title>{items}</channel></rss>'
)


class _Resp:
    def __init__(self, text="", ct="text/html", url=None, status=200):
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": ct}
        self.url = url

    def close(self) -> None:
        pass


class SyntheticSession:
    """A requests-Session-shaped object generating deterministic synthetic
    pages IN PROCESS. No socket exists anywhere on this path.

    Per pass, ``fresh_per_pass`` of each source's ``items`` articles carry
    pass-stamped bodies (new content → stored) and the rest repeat (duplicate
    path exercised too). Bodies are padded to ``body_kb`` so extraction works
    on realistic sizes.
    """

    def __init__(self, *, items: int, fresh_per_pass: int, body_kb: int) -> None:
        self.headers: dict = {}
        self.proxies: dict = {}
        self.items = items
        self.fresh = min(fresh_per_pass, items)
        self.body_kb = max(1, body_kb)
        self.pass_no = 0
        self.pages_served = 0
        self._lock = threading.Lock()

    def next_pass(self) -> None:
        self.pass_no += 1

    def _feed(self, domain: str) -> str:
        items = "".join(
            f"<item><title>i{i}-p{self.pass_no if i < self.fresh else 0}</title>"
            f"<link>https://{domain}/news/{i}-p{self.pass_no if i < self.fresh else 0}</link></item>"
            for i in range(self.items)
        )
        return _RSS_XML.format(d=domain, items=items)

    def _article(self, domain: str, slug: str) -> str:
        filler = (f"Synthetic soak sentence about {domain} {slug} with several distinct words. ")
        body = filler * max(1, (self.body_kb * 1024) // len(filler))
        return (
            f"<html><head><title>{slug} at {domain}</title></head>"
            f"<body><article><h1>{slug} at {domain}</h1><p>{body}</p>"
            f'<a href="https://origin.example/{slug}">origin</a></article></body></html>'
        )

    def get(self, url, timeout=None, allow_redirects=True, headers=None, proxies=None,
            stream=None, **kw):
        with self._lock:
            self.pages_served += 1
        if url.endswith("/robots.txt"):
            return _Resp(text="User-agent: *\nAllow: /", ct="text/plain", url=url)
        host = url.split("://", 1)[1].split("/", 1)[0]
        if url.endswith("/feed.xml"):
            return _Resp(text=self._feed(host), ct="application/rss+xml", url=url)
        slug = url.rsplit("/", 1)[-1]
        return _Resp(text=self._article(host, slug), url=url)


def _rss_mb() -> float | None:
    try:
        import psutil

        return round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001
        return None


def _gate_stats() -> dict:
    from src.database.writer import write_gate_stats

    return write_gate_stats()


def _seed_sources(n: int, tag: str) -> None:
    from src.database.models import Source
    from src.database.session import session_scope

    with session_scope() as s:
        for i in range(n):
            s.add(Source(
                name=f"soak-{i}", domain=f"soak-{tag}-{i}.example",
                rss_url=f"https://soak-{tag}-{i}.example/feed.xml",
                enabled=True, status="qualified", language="en", tags="soak",
            ))


def run_soak(args, emit=None) -> dict:
    """The soak loop. Assumes the process env (OO_DATA_DIR etc.) is already
    set — see main(). Returns the full report dict; ``emit`` (the CLI's
    printer) receives each per-pass row + the summary as they land — library
    callers omit it and read the returned report (no print in library code,
    MAINT-04)."""
    emit = emit or (lambda obj: None)
    from src.database.session import init_db, session_scope
    from src.ingest import EthicalFetcher
    from src.scheduler import memguard
    from src.scheduler.hygiene import run_pass_hygiene
    from src.scheduler.runner import deferred_carryover_count, run_scrape_once
    from src.scheduler.settings import SchedulerSettings

    init_db()
    tag = uuid.uuid4().hex[:6]
    _seed_sources(args.sources, tag)
    session_stub = SyntheticSession(
        items=args.items, fresh_per_pass=args.fresh, body_kb=args.body_kb
    )
    settings = SchedulerSettings(
        mode="rss",
        collect_parallelism=args.parallelism,
        collect_rate_mode="maximum",
        select_tags=["soak"],
    )

    passes: list[dict] = []
    guard_proof: dict | None = None
    for pass_no in range(1, args.passes + 1):
        session_stub.next_pass()
        # A fresh fetcher per pass, exactly like the scheduler's run boundary.
        fetcher = EthicalFetcher(
            min_interval_s=0.0,
            retry_backoff_s=0.0,
            # A synthetic requests-shaped double (the fetcher's documented
            # injection seam for tests/soaks) — not a real requests.Session.
            session=session_stub,  # type: ignore[arg-type]
        )
        rss_before = _rss_mb()
        gate_before = _gate_stats()
        t0 = time.monotonic()
        with session_scope() as db:
            result = run_scrape_once(db, fetcher, settings)
        wall_s = round(time.monotonic() - t0, 2)
        rss_after_pass = _rss_mb()
        hygiene = run_pass_hygiene()  # the real between-pass release + checkpoint
        rss_after_hygiene = _rss_mb()
        gate_after = _gate_stats()
        stored = result.get("articles_stored", 0)
        gate_delta = {
            k: round((gate_after.get(k) or 0) - (gate_before.get(k) or 0), 3)
            for k in ("grants", "contended", "total_wait_s")
        }
        row = {
            "pass": pass_no,
            "wall_s": wall_s,
            "sources_processed": result.get("sources_processed"),
            "articles_stored": stored,
            "deferred_next_pass": result.get("deferred_next_pass", 0),
            "recycled": result.get("recycled"),
            "rss_mb_before": rss_before,
            "rss_mb_after_pass": rss_after_pass,
            "rss_mb_after_hygiene": rss_after_hygiene,
            "gate_delta": gate_delta,
            "gate_windows_per_stored": (
                round(gate_delta["grants"] / stored, 2) if stored else None
            ),
            "fetcher_caches": fetcher.cache_stats(),
            "hygiene": hygiene,
        }
        passes.append(row)
        emit({"kind": "pass", **row})

        if args.trip_guard_after_pass and pass_no == args.trip_guard_after_pass:
            guard_proof = _prove_guard_pause(session_stub, settings, memguard)
            emit({"kind": "guard-proof", **guard_proof})

    ends = [p["rss_mb_after_hygiene"] for p in passes if p["rss_mb_after_hygiene"] is not None]
    report = {
        "schema": REPORT_SCHEMA,
        "config": {
            "passes": args.passes, "sources": args.sources, "items": args.items,
            "fresh_per_pass": args.fresh, "body_kb": args.body_kb,
            "parallelism": args.parallelism,
            "collect_commit_batch": os.getenv("OO_COLLECT_COMMIT_BATCH", "(default)"),
            "pass_budget_minutes": os.getenv("OO_PASS_BUDGET_MINUTES", "(default 60)"),
        },
        "corpus_plaintext": os.getenv("OO_DB_PLAINTEXT") == "1",
        "plaintext_caveat": (
            "Plaintext store: write-cost numbers omit the SQLCipher codec cost. "
            "Memory behaviour is representative; gate numbers are comparative only."
            if os.getenv("OO_DB_PLAINTEXT") == "1" else None
        ),
        "network": {
            "sockets_opened": 0,
            "method": (
                "The HTTP session is an in-process synthetic object; the real "
                "EthicalFetcher runs (kill switch honoured by construction) but "
                "no socket API is ever reached."
            ),
            "pages_served": session_stub.pages_served,
        },
        "passes": passes,
        "rss_flatness": {
            "first_pass_end_mb": ends[0] if ends else None,
            "last_pass_end_mb": ends[-1] if ends else None,
            "max_mb": max(ends) if ends else None,
            "growth_mb": round(ends[-1] - ends[0], 1) if len(ends) >= 2 else None,
            "method": (
                "RSS sampled after each pass's hygiene step; growth = last - "
                "first. Judge the curve yourself — the per-pass rows are above."
            ),
        },
        "guard_proof": guard_proof,
        "deferred_carryover_at_end": deferred_carryover_count(),
    }
    emit({"kind": "summary", **report})
    return report


def _prove_guard_pause(session_stub, settings, memguard_mod) -> dict:
    """Inject FAKE over-threshold readings (the acceptance ask: 'inject a fake
    RSS reading'), run a pass, and show it pauses-not-dies: everything defers
    with reason 'memory' and the pass returns promptly; then release."""
    from src.database.session import session_scope
    from src.ingest import EthicalFetcher
    from src.scheduler.memguard import MemoryGuard
    from src.scheduler.runner import _consume_deferred, run_scrape_once

    fake_reading = {"rss_mb": 9990.0, "mem_avail_mb": 64.0, "mem_total_mb": 10000.0}
    guard = MemoryGuard(trip_after=1, resume_after=1, readings_fn=lambda: fake_reading)
    original = memguard_mod.memory_guard
    memguard_mod.memory_guard = guard
    try:
        guard.poll()
        assert guard.engaged
        session_stub.next_pass()
        fetcher = EthicalFetcher(
            min_interval_s=0.0,
            retry_backoff_s=0.0,
            # The synthetic double again (see the pass loop above).
            session=session_stub,  # type: ignore[arg-type]
        )
        t0 = time.monotonic()
        with session_scope() as db:
            result = run_scrape_once(db, fetcher, settings)
        wall_s = round(time.monotonic() - t0, 2)
        deferred = len(_consume_deferred())
        state = guard.state()
        guard.reset(reason="soak proof complete")
        return {
            "engaged_via_fake_reading": True,
            "pass_wall_s": wall_s,
            "sources_processed": result.get("sources_processed"),
            "recycled": result.get("recycled"),
            "deferred": deferred,
            "guard_reason": state.get("reason"),
            "paused_not_died": (
                result.get("recycled") == "memory"
                and result.get("sources_processed") == 0
            ),
        }
    finally:
        memguard_mod.memory_guard = original


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--passes", type=int, default=5)
    ap.add_argument("--sources", type=int, default=60)
    ap.add_argument("--items", type=int, default=8, help="feed items per source")
    ap.add_argument("--fresh", type=int, default=3, help="new articles per source per pass")
    ap.add_argument("--body-kb", type=int, default=8, dest="body_kb")
    ap.add_argument("--parallelism", type=int, default=8)
    ap.add_argument("--trip-guard-after-pass", type=int, default=0,
                    dest="trip_guard_after_pass",
                    help="after pass N, prove the memory guard pauses-not-dies")
    args = ap.parse_args(argv)

    # SAFETY: never run against a default (possibly live) data dir — and never
    # against ANY dir that already holds a corpus (an operator's live install
    # may itself use OO_DATA_DIR): the soak seeds synthetic sources/articles
    # that would permanently pollute a real store.
    data_dir = os.getenv("OO_DATA_DIR")
    if not data_dir:
        print("collect_soak: refusing to run without an explicit OO_DATA_DIR "
              "(never against a live corpus). Example: OO_DATA_DIR=$(mktemp -d) "
              "OO_DB_PLAINTEXT=1 python -m src.testing.collect_soak", file=sys.stderr)
        return 2
    from pathlib import Path

    if any(Path(data_dir).glob("*.db*")):
        print(f"collect_soak: {data_dir} already contains a database - refusing "
              "to seed synthetic soak data into an existing corpus. Point "
              "OO_DATA_DIR at a FRESH directory (e.g. $(mktemp -d)).", file=sys.stderr)
        return 2

    def _emit(obj: dict) -> None:
        print(json.dumps(obj, separators=(",", ":")), flush=True)

    run_soak(args, emit=_emit)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
