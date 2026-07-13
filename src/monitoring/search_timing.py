"""
Per-search intra-request timing breakdown (planning §4 — search instrumentation FIRST).

§4's doctrine is *measure before you optimize*: the app already has the S2.7 per-ROUTE p95
reservoir (``latency.py``) and the slow-query EXPLAIN instrument (``slowquery.py``), but not
the intra-request breakdown that says WHERE one search spends its wall-clock — FTS ``MATCH``
ms vs content-fetch ms vs serialization ms. Which phase DOMINATES decides the §4 lever, so it
must be measured on the operator's live encrypted corpus, never guessed.

This is the pure, testable core. It mirrors three shipped foundations:
  * ``src/api/unlock.py:_forensic_timer`` — the per-phase wall-clock timer (injectable clock).
  * ``src/monitoring/latency.py:_pct`` — the reservoir percentile (replicated, 4 lines, to keep
    this module import-light — importing latency pulls in the asyncio watchdog).
  * ``src/monitoring/collect_perf.py:_append_jsonl``/``_trim_jsonl`` — the bounded JSONL log.

Honesty by construction: measurements only, no composite score; the aggregate names the
dominant phase by MEASURED p95 (a fact about where wall-clock goes, not a quality judgement);
degrades to an honest empty report before anything is recorded. The networked call (running a
real search on the live corpus) is the OPERATOR/CI seam — ``instrument_search`` is the one-line
hook a handler calls; the core proves the mechanism on an injected clock.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

_LOG = logging.getLogger(__name__)

SCHEMA = "oo-search-timing-1"
SELFTEST_SCHEMA = "oo-search-timing-selftest-1"

# Recent search records kept in-process for the aggregate (bounded, recent-window — the same
# discipline as latency.py's per-route reservoir; a leak here must never grow unbounded).
_RES_CAP = 512
_CAP_LINES = 5000
_LOCK = threading.Lock()
_recent: list[dict] = []


class SearchPhaseTimer:
    """Times the phases of ONE search request. Mirrors unlock._forensic_timer: ``phase(name)``
    records the wall-clock since the previous mark; ``finish()`` returns the record + the total.

    The clock is injected (default ``time.monotonic``) so the timer is fully deterministic in
    tests — no real waiting. Every method is cheap and best-effort; a timing failure must never
    change what a search returns."""

    def __init__(self, *, monotonic: Callable[[], float] | None = None) -> None:
        self._mono = monotonic or time.monotonic
        self._t0 = self._mono()
        self._last = self._t0
        self._phases: list[dict] = []

    def phase(self, name: str) -> dict:
        """Mark the end of a phase; return its ``{phase, ms}`` record."""
        now = self._mono()
        rec = {"phase": str(name), "ms": round((now - self._last) * 1000, 3)}
        self._phases.append(rec)
        self._last = now
        return rec

    def finish(self) -> dict:
        """Return ``{phases, total_ms, method, caveat}`` — total is the FULL wall from start to
        finish (so unmarked time between phases is visible as total minus the phase sum)."""
        total = round((self._mono() - self._t0) * 1000, 3)
        return {
            "phases": list(self._phases),
            "total_ms": total,
            "method": (
                "Wall-clock over one search request, split by phase (FTS MATCH · content "
                "fetch · serialization); total is the full request wall, so unmarked time is "
                "total minus the phase sum."
            ),
            "caveat": (
                "One request — a single sample, not a distribution; feed many into the "
                "aggregate for percentiles. Deduced from wall-clock, never a quality score."
            ),
        }


def _pct(sorted_vals: list[float], p: float) -> float:
    """Replicates latency._pct — nearest-rank percentile over a pre-sorted list."""
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, int(round((p / 100.0) * (len(sorted_vals) - 1)))))
    return round(sorted_vals[k], 3)


def aggregate_phases(records: list[dict]) -> dict:
    """PURE aggregate over a list of finished search records — per-phase percentiles + the
    MEASURED dominant phase (by p95 ms — where wall-clock actually goes, the §4 lever). Never
    touches module state, so the self-test and the live report share one implementation.

    Honest on an empty list: ``phases={}``, ``dominant_phase=None`` — no fabricated numbers."""
    per: dict[str, list[float]] = {}
    totals: list[float] = []
    for r in records:
        for p in r.get("phases", []) or []:
            try:
                ms = float(p.get("ms", 0.0))
            except (TypeError, ValueError):
                continue  # a malformed ms must not create an empty-list phase (max([]) → 500).
            per.setdefault(str(p.get("phase")), []).append(ms)
        t = r.get("total_ms")
        if t is not None:
            with contextlib.suppress(TypeError, ValueError):
                totals.append(float(t))

    phases: dict[str, dict] = {}
    for name, vals in per.items():
        s = sorted(vals)
        phases[name] = {
            "n": len(vals),
            "p50_ms": _pct(s, 50),
            "p95_ms": _pct(s, 95),
            "p99_ms": _pct(s, 99),
            "max_ms": round(max(vals), 3),
            "mean_ms": round(sum(vals) / len(vals), 3),
        }
    # The dominant phase is the one with the highest p95 wall-clock — a measurement, not a
    # ranking of quality. Ties resolve deterministically by phase name so the answer is stable.
    dominant = (
        max(phases, key=lambda k: (phases[k]["p95_ms"], k)) if phases else None
    )
    ts = sorted(totals)
    return {
        "schema": SCHEMA,
        "searches": len(records),
        "phases": phases,
        "total": {
            "n": len(totals),
            "p50_ms": _pct(ts, 50),
            "p95_ms": _pct(ts, 95),
            "p99_ms": _pct(ts, 99),
            "max_ms": round(max(totals), 3) if totals else 0.0,
        },
        "dominant_phase": dominant,
        "method": (
            "Per-phase percentiles over a bounded recent-window of in-process search records; "
            "the dominant phase is the highest measured p95 wall-clock — the §4 target chosen "
            "by evidence, not theory."
        ),
        "caveat": (
            f"In-process + recent-window only (last {_RES_CAP} searches); a cold cache or the "
            "live encrypted corpus at scale can shift the split, so the deciding run is the "
            "operator's. Measurements only — no composite score."
        ),
    }


def record_search_phases(record: dict) -> None:
    """Feed one finished search record into the in-process aggregate (bounded, thread-safe)."""
    with _LOCK:
        _recent.append(record)
        if len(_recent) > _RES_CAP:
            del _recent[0 : len(_recent) - _RES_CAP]


def _snapshot() -> list[dict]:
    with _LOCK:
        return list(_recent)


def search_timing_report() -> dict:
    """The live aggregate over what this process has recorded so far — read-only, degrades to an
    honest empty report before any search is instrumented."""
    return aggregate_phases(_snapshot())


def _log_path():
    from src.paths import data_dir

    return data_dir() / "search_timing.jsonl"


def _trim_jsonl() -> None:
    try:
        path = _log_path()
        if not path.exists():
            return
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > _CAP_LINES:
            path.write_text("\n".join(lines[-_CAP_LINES:]) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001 - logging must never break a search
        _LOG.debug("search_timing trim failed", exc_info=True)


def append_search_timing(record: dict) -> None:
    """Durably append one search record to the bounded JSONL log AND feed the in-process
    aggregate. Best-effort — a logging failure never touches the search that produced it."""
    record_search_phases(record)
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, separators=(",", ":")) + "\n")
        _trim_jsonl()
    except Exception:  # noqa: BLE001
        _LOG.debug("search_timing append failed", exc_info=True)


def instrument_search(fn: Callable[[SearchPhaseTimer], Any]) -> Any:
    """The OPERATOR/CI seam. A handler runs its search inside ``fn`` (calling ``timer.phase(...)``
    at each stage); this records the finished breakdown and returns the search result unchanged.

    Wiring this into the real (async) search endpoint is the CI/operator step (§4's live per-phase
    ms on the 100-130 GB encrypted corpus decides the lever); the core here is fully proven on an
    injected clock without a browser, Ollama, network, or the live corpus."""
    timer = SearchPhaseTimer()
    try:
        result = fn(timer)
    finally:
        try:
            append_search_timing(timer.finish())
        except Exception:  # noqa: BLE001
            _LOG.debug("instrument_search record failed", exc_info=True)
    return result


def _reset_for_tests() -> None:
    """Drop the in-process record window (test hook)."""
    with _LOCK:
        _recent.clear()


def _walk_no_score(obj: Any) -> None:
    banned = ("score", "ranking", "rating", "grade")
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert not any(b in str(k).lower() for b in banned), f"score-like key: {k}"
            _walk_no_score(v)
    elif isinstance(obj, list):
        for v in obj:
            _walk_no_score(v)


class _FakeClock:
    """Deterministic monotonic clock: returns each tick in order, holds the last forever."""

    def __init__(self, ticks: list[float]) -> None:
        self._ticks = list(ticks)
        self._i = 0

    def __call__(self) -> float:
        v = self._ticks[min(self._i, len(self._ticks) - 1)]
        self._i += 1
        return v


def run_search_timing_selftest() -> dict:
    """Prove the §4 mechanism on a deterministic injected clock — no browser, no network, no DB,
    no live corpus. Hand-computed asserts pin the per-phase ms, the total wall, and — the point
    of the instrument — that the DOMINANT phase is chosen by MEASURED p95, not by insertion order.

    Mirrors run_perception_eval_selftest / run_triage_selftest so a regression reddens both the
    in-app diagnostics endpoint AND CI. Returns a log with a top-level ``passed`` bool."""
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    # Ticks in SECONDS: init, phase1, phase2, phase3, finish. Chosen so the middle phase
    # (content_fetch) dominates — proving "dominant" is not just the first-recorded phase.
    ticks_a = [0.0, 0.010, 0.055, 0.058, 0.060]
    timer_a = SearchPhaseTimer(monotonic=_FakeClock(ticks_a))
    timer_a.phase("fts_match")
    timer_a.phase("content_fetch")
    timer_a.phase("serialize")
    rec_a = timer_a.finish()

    ms_by_phase = {p["phase"]: p["ms"] for p in rec_a["phases"]}
    check(
        "phase_ms_exact",
        ms_by_phase == {"fts_match": 10.0, "content_fetch": 45.0, "serialize": 3.0},
        str(ms_by_phase),
    )
    check("total_ms_exact", rec_a["total_ms"] == 60.0, str(rec_a["total_ms"]))
    # Unmarked time is visible: total (60) > phase sum (58).
    check(
        "unmarked_time_visible",
        rec_a["total_ms"] > sum(p["ms"] for p in rec_a["phases"]),
        f"total={rec_a['total_ms']} sum={sum(p['ms'] for p in rec_a['phases'])}",
    )

    # A second search where content_fetch stays the wall-clock hog.
    ticks_b = [0.0, 0.012, 0.052, 0.056, 0.058]
    timer_b = SearchPhaseTimer(monotonic=_FakeClock(ticks_b))
    timer_b.phase("fts_match")
    timer_b.phase("content_fetch")
    timer_b.phase("serialize")
    rec_b = timer_b.finish()

    agg = aggregate_phases([rec_a, rec_b])
    check(
        "dominant_is_measured_not_first",
        agg["dominant_phase"] == "content_fetch",
        f"dominant={agg['dominant_phase']} (fts_match was recorded first)",
    )
    check(
        "percentiles_and_n_present",
        agg["phases"]["content_fetch"]["n"] == 2
        and set(agg["phases"]["content_fetch"]) >= {"p50_ms", "p95_ms", "p99_ms", "max_ms"},
        str(agg["phases"].get("content_fetch")),
    )
    # Non-vacuous: a DIFFERENT input shifts the dominant phase — the answer tracks the data.
    ticks_c = [0.0, 0.002, 0.006, 0.106, 0.107]  # serialize is now the hog
    timer_c = SearchPhaseTimer(monotonic=_FakeClock(ticks_c))
    timer_c.phase("fts_match")
    timer_c.phase("content_fetch")
    timer_c.phase("serialize")
    agg_c = aggregate_phases([timer_c.finish()])
    check(
        "dominant_tracks_the_data",
        agg_c["dominant_phase"] == "serialize",
        f"dominant={agg_c['dominant_phase']}",
    )

    # Honest empty aggregate.
    empty = aggregate_phases([])
    check(
        "empty_is_honest",
        empty["phases"] == {} and empty["dominant_phase"] is None and empty["searches"] == 0,
        str(empty["dominant_phase"]),
    )

    # The bounded record window never grows past the cap.
    _reset_for_tests()
    for _ in range(_RES_CAP + 50):
        record_search_phases({"phases": [{"phase": "x", "ms": 1.0}], "total_ms": 1.0})
    bounded = len(_snapshot()) <= _RES_CAP
    _reset_for_tests()
    check("record_window_bounded", bounded, f"cap={_RES_CAP}")

    # No composite score anywhere in the surfaced structures.
    no_score = True
    try:
        _walk_no_score(rec_a)
        _walk_no_score(agg)
    except AssertionError as exc:
        no_score = False
        check("no_score_field", False, str(exc))
    if no_score:
        check("no_score_field", True)

    passed = all(c["passed"] for c in checks)
    return {
        "schema": SELFTEST_SCHEMA,
        "passed": passed,
        "checks": checks,
        "total": len(checks),
        "passed_count": sum(1 for c in checks if c["passed"]),
        "failed_count": sum(1 for c in checks if not c["passed"]),
        "method": (
            "Runs the SearchPhaseTimer + aggregate on a deterministic injected clock with "
            "hand-computed expected ms; proves the dominant phase is chosen by measured p95, "
            "not insertion order, and that the aggregate is honest on empty input."
        ),
        "caveat": (
            "Verifies the MECHANISM, not the live corpus. Real per-phase ms come from wiring "
            "instrument_search into the search endpoint on the operator's rig (§4 CI/operator "
            "seam). No score."
        ),
    }
