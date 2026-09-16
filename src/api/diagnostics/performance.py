"""
Performance, benchmark and LLM-throughput reports.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Part of the mechanical ``src/api/diagnostics.py`` -> package split (Q1139 = a,
2026-09-16): this file is lines 2494-3008 of the pre-split module, verbatim. The
routes, their paths, their methods and their order are unchanged; ``__init__``
imports the submodules in the original file order so the decorators still
register on one router in that order.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from src.database.models import Article, Keyword, Source
from src.database.session import get_db
from src.utils.export_envelope import envelope

from ._base import router
from .keywords import keyword_log


@router.get("/performance")
def performance_report(
    selftest: bool = True, db: Session = Depends(get_db)
) -> JSONResponse:
    """The PERFORMANCE field report (maintainer-asked 2026-06-12): one local,
    on-click JSON the operator can send back, carrying real evidence from THIS
    machine and THIS corpus — the maintainer↔developer channel pattern.

    Three evidence classes, each with its method stated:
      * passive endpoint latencies — the app's own Prometheus histograms,
        accumulated from REAL interactive use since this boot (no overhead
        added; the middleware was already measuring);
      * environment + store facts — CPUs, RAM, at-rest encryption state, page
        cache/mmap settings, file/page/freelist sizes (real PRAGMA readings);
      * an optional ACTIVE self-test — the hot read handlers timed twice,
        in-process, against the live corpus (labelled in-session: OS and page
        caches reflect real use, so these are warm-path numbers).
    Generated only on click; never transmitted anywhere by the app.
    """
    import os as _os
    import platform
    import sys as _sys
    import time as _time

    from src.api import system as _system
    from src.database.connect import locked_state
    from src.database.session import engine
    from src.paths import data_dir as _data_dir

    db_file = _data_dir() / "open_omniscience.db"

    # -- environment ------------------------------------------------------- #
    vitals = _system._process_vitals()
    try:
        import psutil as _ps

        total_ram = int(_ps.virtual_memory().total)
    except Exception:  # noqa: BLE001 - honest null, never a guess
        total_ram = None
    env = {
        "python": _sys.version.split()[0],
        "platform": platform.platform(),
        "cpu_count": _os.cpu_count(),
        "total_ram_bytes": total_ram,
        "process_rss_bytes": vitals.get("rss_bytes"),
        "at_rest_state": locked_state(db_file),
        "uptime_s": round(_time.time() - _system._BOOT_TS, 1),
    }

    # -- store facts (real PRAGMA readings) --------------------------------- #
    store: dict = {"db_bytes": db_file.stat().st_size if db_file.exists() else None}
    if engine.url.get_backend_name() == "sqlite":
        with engine.connect() as conn:
            for pragma in (
                "page_size",
                "page_count",
                "freelist_count",
                "journal_mode",
                "cache_size",
                "mmap_size",
            ):
                store[pragma] = conn.execute(text(f"PRAGMA {pragma}")).scalar()
    counts = {
        "articles": int(db.query(func.count(Article.id)).scalar() or 0),
        "sources": int(db.query(func.count(Source.id)).scalar() or 0),
        "keywords": int(db.query(func.count(Keyword.id)).scalar() or 0),
        "keyword_mentions": int(
            db.execute(text("SELECT COUNT(*) FROM keyword_mentions")).scalar() or 0
        ),
    }

    # Last collection pass: break its fetch_failed count down by reason, so the
    # number is diagnosable (Tor-403 reality vs a real transport/DB problem) and
    # not a raw mystery. From the scheduler's own last result; empty if no pass ran.
    from src.ingest.fetch_verdict import fetch_failed_reasons as _ff_reasons
    from src.scheduler.runner import get_scheduler as _get_scheduler

    _last = _get_scheduler().status().get("last_result") or {}
    _tally_raw = _last.get("tally")
    _last_tally: dict = _tally_raw if isinstance(_tally_raw, dict) else {}
    collection = {
        "last_pass_fetch_failed": int(_last_tally.get("fetch_failed") or 0),
        "fetch_failed_reasons": _ff_reasons(_last),
        "method": (
            "The last scrape pass's fetch failures bucketed by cause (per-reason "
            "counts sum to fetch_failed). http_403 is typically the Tor-block "
            "reality on premium news, NOT asserted as Tor. Counts only, no score."
        ),
    }
    # Why the collector may be running fewer workers than collect_parallelism allows:
    # the ceiling this machine demonstrated under memory pressure. Null on any box that
    # has never backed off, which is the normal state and is NOT the same as a ceiling
    # of zero. Degrades to an honest absence rather than failing the report.
    try:
        from src.scheduler.capacity import state_report as _capacity_report
        from src.scheduler.settings import load_settings as _load_sched_settings

        collection["learned_concurrency"] = _capacity_report(
            int(getattr(_load_sched_settings(), "collect_parallelism", 1) or 1)
        )
    except Exception as exc:  # noqa: BLE001 - a diagnostic never breaks on a side read
        collection["learned_concurrency"] = {"available": False, "reason": str(exc)[:160]}

    # -- passive latencies: the app's own histograms, real use since boot --- #
    endpoint_latency: list[dict] = []
    try:
        from src.api.main import REQUEST_LATENCY

        for metric in REQUEST_LATENCY.collect():
            series: dict[tuple, dict] = {}
            for s in metric.samples:
                key = (s.labels.get("method", "?"), s.labels.get("endpoint", "?"))
                slot = series.setdefault(key, {"buckets": []})
                if s.name.endswith("_bucket"):
                    slot["buckets"].append((float(s.labels["le"]), s.value))
                elif s.name.endswith("_count"):
                    slot["count"] = s.value
                elif s.name.endswith("_sum"):
                    slot["sum_s"] = s.value
            for (method_, endpoint_), slot in series.items():
                n = slot.get("count", 0)
                if not n:
                    continue
                est = {}
                finite = sorted(b for b in slot["buckets"] if b[0] != float("inf"))
                for q_ in (0.5, 0.95):
                    target = n * q_
                    for le, cum in finite:
                        if cum >= target:
                            est[f"p{int(q_ * 100)}_le_s"] = le
                            break
                    else:
                        # The quantile sits beyond the largest finite bucket —
                        # report that bound honestly instead of a fake number.
                        if finite:
                            est[f"p{int(q_ * 100)}_gt_s"] = finite[-1][0]
                endpoint_latency.append(
                    {
                        "method": method_,
                        "endpoint": endpoint_,
                        "requests": int(n),
                        "total_s": round(slot.get("sum_s", 0.0), 3),
                        "mean_ms": round(slot.get("sum_s", 0.0) / n * 1000, 1),
                        **est,
                    }
                )
        endpoint_latency.sort(key=lambda e: -e["total_s"])
        endpoint_latency = endpoint_latency[:80]
    except Exception:  # noqa: BLE001 - the report must not fail on metrics shape
        endpoint_latency = []

    # -- active self-test: hot read handlers, timed in-process -------------- #
    selftest_rows: list[dict] = []
    if selftest:
        from src.analytics import queries as aq
        from src.api.database import country_coverage, database_stats

        def _timed(name: str, fn) -> None:
            for run in (1, 2):
                t0 = _time.perf_counter()
                try:
                    out = fn()
                    # Streamed responses: consume fully so the cost is real.
                    body_iter = getattr(out, "body_iterator", None)
                    size = None
                    if body_iter is not None and hasattr(body_iter, "__aiter__"):
                        # Starlette wraps sync generators into async iterators;
                        # this sync endpoint runs in a worker thread (no loop),
                        # so a private loop can drain the stream for real.
                        import asyncio

                        async def _drain(it) -> int:
                            total = 0
                            async for c in it:
                                total += len(c.encode("utf-8") if isinstance(c, str) else c)
                            return total

                        size = asyncio.run(_drain(body_iter))
                    elif body_iter is not None:
                        size = sum(len(c.encode("utf-8")) for c in body_iter)
                    selftest_rows.append(
                        {
                            "probe": name,
                            "run": run,
                            "ms": round((_time.perf_counter() - t0) * 1000),
                            **({"bytes": size} if size is not None else {}),
                        }
                    )
                except Exception as exc:  # noqa: BLE001 - report failures honestly
                    selftest_rows.append(
                        {"probe": name, "run": run, "error": str(exc)[:160]}
                    )

        _timed("database_stats", lambda: database_stats(db=db))
        _timed("country_coverage", lambda: country_coverage(db=db))
        _timed("insights_top", lambda: aq.top_terms(db, limit=50))
        _timed("insights_trending", lambda: aq.trending(db))
        _timed("insights_map", lambda: aq.map_data(db))
        _timed("keyword_export_streamed", lambda: keyword_log(db=db))

    payload = {
        "environment": env,
        "store": store,
        "corpus": counts,
        "collection": collection,
        "endpoint_latency_since_boot": {
            "method": (
                "The app's own request-latency histograms (Prometheus middleware), "
                "accumulated from real use since this boot — server-side wall time "
                "per endpoint; p50/p95 are bucket upper bounds (≤), not exact "
                "quantiles. Top 80 by total time."
            ),
            "series": endpoint_latency,
        },
        "selftest": {
            "method": (
                "Hot read handlers timed in-process against the live corpus, two "
                "runs each, streamed bodies fully consumed. In-session numbers: "
                "OS/page caches reflect real use (warm path). No network involved."
            ),
            "ran": bool(selftest),
            "results": selftest_rows,
        },
    }
    body = envelope(
        kind="performance-report", query={"selftest": selftest},
        count=len(selftest_rows) + len(endpoint_latency), payload=payload,
    )
    fname = f"oo-perf-report-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


@router.get("/benchmark")
def benchmark_report(
    repeats: int = Query(3, ge=1, le=10, description="Runs per case (1 = cold only)"),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """The SCALING benchmark (maintainer-asked 2026-06-19): a repeatable, on-click
    timing of the heavy read paths against THIS corpus on THIS machine — so the
    data-architecture scaling work (denormalised keyword counters, de-N+1
    associations/graph) can be LIVE-tested, with a self-describing log to hand back.

    Each case runs ``repeats`` times (run 1 cold, runs 2..N warm) over a bounded
    query-layer function the UI already calls. The log carries the corpus size, the
    keyword-counter freshness, the columnar engine mode and host facts so a number is
    interpretable away from the machine. READ-ONLY (it does not reconcile the
    counters — it reports their current freshness), bounded, airplane-safe; generated
    only on click and never transmitted. See src/monitoring/benchmark.py.
    """
    from src.monitoring.benchmark import run_benchmark

    payload = run_benchmark(db, repeats=repeats)
    body = envelope(
        kind="scaling-benchmark",
        query={"repeats": repeats},
        count=payload.get("summary", {}).get("cases_run", 0),
        payload=payload,
    )
    fname = f"oo-benchmark-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


@router.get("/rollup-benchmark")
def rollup_benchmark(
    repeats: int = Query(3, ge=1, le=10, description="Timing runs per window"),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """The WINDOWED-aggregation rollup benchmark (scaling 5A-bis): builds the
    ``keyword_daily`` rollup in-memory over THIS corpus and times the windowed keyword
    aggregation both ways — the live mention scan (the Insights/trends freeze) vs summing
    the rollup — reporting the speedup + a parity check, so the operator can SEE how much
    the rollup helps on their own data before it is wired to the hot path or the persisted
    store is bundled. READ-ONLY, in-memory (never a plaintext file), airplane-safe;
    generated on click only and never transmitted. See src/monitoring/rollup_benchmark.py.
    """
    from src.monitoring.rollup_benchmark import run_rollup_benchmark

    payload = run_rollup_benchmark(db, repeats=repeats)
    body = envelope(
        kind="rollup-benchmark",
        query={"repeats": repeats},
        count=len(payload.get("windows", [])),
        payload=payload,
    )
    fname = f"oo-rollup-benchmark-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


@router.get("/llm-bench")
def llm_bench(
    repeats: int = Query(3, ge=1, le=10, description="Timed calls per prompt shape"),
) -> JSONResponse:
    """Per-call LLM latency on THIS machine, per prompt SHAPE.

    Any feature that runs the local model over many articles needs an operator setting
    for how much work to do, and the honest form of that setting is a TIME BUDGET, not
    an article count — a count means nothing without knowing what a call costs here.
    Nothing in this repo recorded per-call latency, so a budget could only be guessed.

    Times the shapes the app actually sends (a small fact bundle, one article for
    who/where/when, one article for a summary, and a 24,000-character excerpt set for a
    synthesis), each after an excluded warmup, and translates the result into calls per
    hour. Ollama reports its own durations; vLLM's OpenAI-compatible response carries
    none, so those figures are wall-clock — stated per shape, never mixed.

    LOOPBACK inference only: no egress, so it is airplane-safe and deliberately carries
    no kill-switch refusal of its own. Runs on click only and is never transmitted.
    See src/monitoring/llm_bench.py.
    """
    from src.monitoring.llm_bench import run_llm_bench

    payload = run_llm_bench(repeats=repeats)
    body = envelope(
        kind="llm-bench",
        query={"repeats": repeats},
        count=len(payload.get("shapes", [])),
        payload=payload,
    )
    fname = f"oo-llm-bench-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


@router.get("/llm-throughput")
def llm_throughput(
    levels: str = Query(
        "1,2,4,8,16", description="Comma-separated concurrency levels to sweep"
    ),
    calls_per_level: int = Query(12, ge=1, le=200, description="Calls issued at each level"),
    shape: str = Query("perception", description="Which prompt shape to sweep"),
) -> JSONResponse:
    """Articles per hour ACTUALLY achieved at each concurrency level, on this machine.

    Field report 2026-08-09: "I see my GPU working only 20%". The sibling `/llm-bench`
    measures one call at a time and then multiplies by the configured concurrency to get
    a rate — a multiplication nothing had ever checked, and a 20%-utilised GPU is what an
    unchecked upper bound looks like from the outside. This sweeps the levels instead and
    reports the batch rate measured at each, with GPU utilisation sampled while the work
    is happening, so the curve's bend is a measurement rather than a guess.

    Levels above the RUNNING vLLM server's `--max-num-seqs` measure queueing rather than
    concurrency (raising it takes a restart); those rows say so rather than reporting a
    plateau as though it were a finding.

    LOOPBACK inference only: no egress, so it is airplane-safe and deliberately carries
    no kill-switch refusal of its own. Runs on click only and is never transmitted.
    A plain `def` so the sweep runs in the threadpool and never freezes the one worker.
    See src/monitoring/llm_throughput.py.
    """
    from src.monitoring.llm_throughput import run_throughput_bench

    wanted: list[int] = []
    for part in (levels or "").split(","):
        part = part.strip()
        if part.isdigit() and 0 < int(part) <= 256:
            wanted.append(int(part))
    if not wanted:
        raise HTTPException(
            status_code=400,
            detail="levels must be comma-separated positive integers, each at most 256",
        )
    payload = run_throughput_bench(
        levels=tuple(sorted(set(wanted))),
        calls_per_level=calls_per_level,
        shape=shape,
    )
    body = envelope(
        kind="llm-throughput",
        query={"levels": wanted, "calls_per_level": calls_per_level, "shape": shape},
        count=len(payload.get("levels", [])),
        payload=payload,
    )
    fname = f"oo-llm-throughput-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )


@router.get("/ai-activity")
def ai_activity(
    recent: int = Query(12, ge=1, le=100, description="Latest found items per category"),
    hours: int = Query(24, ge=1, le=720, description="Window for the stored-rows rate"),
    db: Session = Depends(get_db),
) -> dict:
    """What the background AI has actually been doing — the live details feed.

    Maintainer ask 2026-08-09: latest detected keywords and languages, totals per
    category, what is left, and articles processed per hour.

    A READER over records the sweeps already write. Three of the four append a per-batch
    JSONL record — with a start AND a finish time — while the run is in flight, next to
    detail records carrying what they found; nothing had ever parsed them, because
    `last_*_report` reads a header, a footer and a line count. Each log is read from its
    END under a byte ceiling of the reader's own, so a sweep left running for days cannot
    turn this into the whole-file read that once OOM'd the app at boot.

    TWO RATES per sweep, both real: the model's own speed (items over summed batch
    durations) and what the corpus gains (items over the elapsed span, including every
    gap where the sweep waited its turn in the coordinator's round-robin). They diverge
    by the duty cycle, and publishing either alone would mislead.

    LOCAL only: reads files and the corpus, no egress, airplane-safe.
    """
    from src.ai_layer.activity import recent_activity

    return recent_activity(session=db, recent=recent, hours=hours)


@router.get("/ai-activity-selftest")
def ai_activity_selftest() -> dict:
    """Prove the reader is bounded and the two rates really separate, on a fixture."""
    from src.ai_layer.activity import run_activity_selftest

    return run_activity_selftest()


@router.get("/llm-throughput-selftest")
def llm_throughput_selftest() -> dict:
    """Prove the concurrency sweep measures concurrency, with no model and no GPU.

    Cheap and deterministic, so it rides the all-diagnostics bundle: a bench whose own
    mechanism is unverified would report a plausible curve while running everything
    serially."""
    from src.monitoring.llm_throughput import run_throughput_selftest

    return run_throughput_selftest()


@router.get("/bulletin-preview")
def bulletin_preview(
    cadence: str = Query("weekly", description="daily | weekly | monthly | trimester | semester | yearly"),
    download: bool = Query(False),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Layer A of the Bulletin for one closed period — the deterministic record.

    The Bulletin is deterministic first: exact, uncapped counts over a half-open
    period on ``coalesce(published_at, created_at)``, quarantined articles excluded
    AND counted, with the masthead that states the lens (which sources actually
    contributed, how concentrated they were, which languages and countries, how
    many of the period's days had any ingest at all) and the disclosures that name
    what the edition cannot see. No model is involved in any figure here.

    This preview exists so the output can be READ on a real corpus before the
    persistence, narration and review surfaces are built — the sandbox-phase
    instruction that classification should fall out of observed content rather
    than be guessed up front.

    Read-only. The period ENDS at the start of today, so it covers whole days and
    re-rendering it tomorrow answers the same question.

    The hardware gate covers the NARRATION layer only (ruled 2026-09-07, open
    question 4), and this preview is Layer A — deterministic SQL — so it is
    produced on any machine. The verdict still travels in the payload, because a
    reader of the preview should be able to see what this machine could add to it.
    See src/bulletin/.
    """
    from src.bulletin.facts import layer_a
    from src.bulletin.gate import bulletin_available
    from src.bulletin.period import resolve_period

    gate = bulletin_available()
    if not gate["available"]:
        payload: dict = {"available": False, "gate": gate}
    else:
        try:
            period = resolve_period(cadence)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        payload = layer_a(db, period)
        payload["available"] = True
        payload["gate"] = gate

    headers = {}
    if download:
        fname = f"oo-bulletin-{cadence}-{datetime.now().strftime('%Y%m%d')}.json"
        headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    return JSONResponse(payload, headers=headers)


@router.get("/source-coverage-benchmark")
def source_coverage_benchmark(
    repeats: int = Query(3, ge=1, le=10, description="Timing runs per read"),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """The per-country source-coverage rollup benchmark (D4, scaling 5A-bis): builds the
    ``source_coverage`` rollup in-memory over THIS corpus and times the per-country
    choropleth aggregation both ways — the live scan of articles+sources+mentions (the map
    read) vs reading the cached rows — reporting the speedup, a parity check (the counts
    must match exactly), and the rollup wrapped in the honesty envelope. READ-ONLY,
    in-memory (never a plaintext file), airplane-safe; generated on click only and never
    transmitted. See src/monitoring/source_coverage_benchmark.py.
    """
    from src.monitoring.source_coverage_benchmark import run_source_coverage_benchmark

    payload = run_source_coverage_benchmark(db, repeats=repeats)
    body = envelope(
        kind="source-coverage-benchmark",
        query={"repeats": repeats},
        count=len(payload.get("coverage", {}).get("value", []) or []),
        payload=payload,
    )
    fname = f"oo-source-coverage-benchmark-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    return JSONResponse(
        body, headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )
