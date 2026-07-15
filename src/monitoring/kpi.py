"""
The V1 KPI snapshot (R1, V1_PATHWAY §2.3) — each metric stands alone, no composite.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A read-only, versioned snapshot of the K1–K14 board — the V1 definition made mechanical
so the KPI differ (R2) can classify improved / regressed / unchanged between two cycles.
Every metric carries ``{id, name, value, method, n, as_of, source_endpoint, direction,
target, verdict}``:

  * ``direction`` (``up`` / ``down`` / ``exact``) is ALWAYS present — R2 cannot classify a
    delta without a declared direction-of-goodness;
  * ``target`` may be ``"pending-ruling-V1-6"`` (the numeric bar is a ruling, not the
    direction);
  * ``verdict`` is ``green`` / ``red`` / ``not-measurable-here`` — NEVER a fabricated pass
    (the S1 lesson: a pass on a proxy over-reads). A metric whose instrument lacks data on
    THIS machine (no live corpus, no graded gold set, no P0 report, no CI facts in-process)
    reports ``not-measurable-here`` — that is the honest answer, not a gap to paper over.

HONESTY BY CONSTRUCTION: no composite (no overall score / percentage / count-of-greens);
this GET NEVER triggers a heavy crunch (an expensive instrument reports its last persisted
value with an ``as_of``, or ``not-measurable-here`` — it is not re-run here). Only the cheap,
in-process instruments (the latency reservoir K2, the locale files K11) are read live.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA = "oo-kpi-1"
_NM = "not-measurable-here"
_LOCALES = Path(__file__).resolve().parent.parent / "static" / "locales"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# The K1–K14 board (V1_PATHWAY §2.3). ``nm`` is the honest reason a metric is not measurable
# in-process on a dev machine (most are: live-corpus / graded-gold-set / operator-run / CI /
# expensive-crunch gated). K2 + K11 have live resolvers below.
_SPECS: tuple[dict, ...] = (
    {"id": "K1", "name": "Warm unlock at 100 GB+", "direction": "down", "target": "< 2 s",
     "source_endpoint": "/api/system/startup-status",
     "nm": "needs a live 100 GB+ corpus warm-unlock timing (operator run); not on a dev boot"},
    {"id": "K2", "name": "Interactive endpoint p95", "direction": "down", "target": "< 500 ms",
     "source_endpoint": "/api/diagnostics/request-latency"},
    {"id": "K3", "name": "Backup at corpus scale", "direction": "exact",
     "target": "pass bounded-RAM + verify + staged-restore",
     "source_endpoint": "/api/diagnostics/p0-validation/last",
     "nm": "needs a P0-validation report from the operator's live corpus run"},
    {"id": "K4", "name": "Crash-free long run", "direction": "up", "target": "≥ 14-day continuous",
     "source_endpoint": "/api/diagnostics/session-forensics",
     "nm": "a duration metric — needs a multi-day live run + memory-guard-clean forensics"},
    {"id": "K5", "name": "Keyword noise (generic-term-candidate share of top terms)",
     "direction": "down", "target": "pending-ruling-V1-6",
     "source_endpoint": "/api/diagnostics/keyword-engine",
     "nm": "engine_report is an expensive corpus scan — not run on this GET (run the "
           "keyword-engine diagnostic on the live corpus); no persisted value here"},
    {"id": "K6", "name": "Cross-language translation coverage", "direction": "up",
     "target": "pending-ruling-V1-6", "source_endpoint": "/api/diagnostics/keyword-engine",
     "nm": "engine_report.translation_coverage is an expensive scan — not run on this GET"},
    {"id": "K7", "name": "Date-extraction recall", "direction": "up",
     "target": "pending-ruling-V1-6", "source_endpoint": "/api/diagnostics/datediag",
     "nm": "datediag coverage is an expensive article scan — not run on this GET"},
    {"id": "K8", "name": "Source health + diversity", "direction": "up",
     "target": "pending-ruling-V1-6 (per-region flag distribution inspected, not scored)",
     "source_endpoint": "/api/diagnostics/source-audit",
     "nm": "source-audit reads per-source extraction validity (expensive) — not run on this GET"},
    {"id": "K9", "name": "Retrieval quality (nDCG/MRR/Recall per language)", "direction": "up",
     "target": "no regression vs frozen baseline (floors at first grading)",
     "source_endpoint": "/api/diagnostics/ir-eval",
     "nm": "needs a graded IR gold set (R6); not-measurable until it is graded"},
    {"id": "K10", "name": "Perception quality (precision/recall/hallucination per stratum)",
     "direction": "up", "target": "clear the harness before extraction ships (floors pending)",
     "source_endpoint": "/api/diagnostics/perception-eval-selftest",
     "nm": "needs a graded who/where/when gold set (R6); not-measurable today"},
    {"id": "K11", "name": "i18n completeness", "direction": "exact",
     "target": "min 100% ×12 (+ audit-chrome 0, CI-verified)",
     "source_endpoint": "scripts/i18n_report.py"},
    {"id": "K12", "name": "Browser verification (share of flagged surfaces ≥ Gecko-verified)",
     "direction": "up", "target": "100% at 1.0 + human UX pass",
     "source_endpoint": "R3 (AppVM ui_walk)",
     "nm": "awaits R3 — the flagged-surface inventory does not exist in-process yet"},
    {"id": "K13", "name": "Vertical coverage", "direction": "exact",
     "target": "first slice ingested + freshness green, per §4 vertical",
     "source_endpoint": "/api/diagnostics/freshness",
     "nm": "per-vertical coverage diagnostics await the §4 vertical builds"},
    {"id": "K14", "name": "Development health (suite · mypy ratchet · open P0s)",
     "direction": "exact", "target": "suite green · mypy ≤ baseline · open data-loss P0s = 0",
     "source_endpoint": "CI",
     "nm": "suite/mypy/CI are out-of-process facts (subprocess forbidden here) — read from CI"},
)


def _entry(spec: dict, *, value=None, n=None, as_of=None, verdict=_NM, method: str = "") -> dict:
    return {
        "id": spec["id"],
        "name": spec["name"],
        "value": value,
        "method": method or spec.get("nm", ""),
        "n": n,
        "as_of": as_of,
        "source_endpoint": spec.get("source_endpoint"),
        "direction": spec["direction"],  # always present (R2 needs it)
        "target": spec["target"],
        "verdict": verdict,
    }


def _k2_latency(spec: dict) -> dict:
    """K2: worst interactive-route p95 vs the 500 ms bar, from the in-memory latency reservoir."""
    from src.monitoring import latency

    summ = latency.summary()
    bar = float(summ.get("snappy_bar") or 500.0)
    # Only routes with a real pass/fail verdict are interactive reads (exempt/low-n excluded).
    interactive = [r for r in (summ.get("routes") or []) if r.get("snappy") in ("pass", "fail")]
    if not interactive:
        return _entry(spec, method=(
            "no interactive-route latency samples on this process yet — make a few reads first "
            "(the reservoir is in-memory, per-process; empty is honest, not a gap)"))
    worst = max(interactive, key=lambda r: float(r.get("p95_ms") or 0.0))
    n = sum(int(r.get("window_n") or 0) for r in interactive)
    any_fail = any(r.get("snappy") == "fail" for r in interactive)
    return _entry(
        spec,
        value=round(float(worst.get("p95_ms") or 0.0), 1),
        n=n,
        as_of=_now(),
        verdict="red" if any_fail else "green",
        method=(f"worst interactive-route p95 over the recent window vs the {bar:.0f} ms bar "
                f"({worst.get('route')}); measured, per-process reservoir, counts only, no score"),
    )


def _k11_i18n(spec: dict) -> dict:
    """K11: minimum locale key-coverage across the 12 locales (cheap in-process file read).

    Mirrors i18n_report's coverage definition (keys present vs en.json). The audit-chrome=0
    half (no un-keyed chrome strings) is a heavier scan verified in CI — noted, not re-run."""
    en_path = _LOCALES / "en.json"
    if not en_path.exists():
        return _entry(spec, method="locale files not found in-process")
    source_keys = set(json.loads(en_path.read_text(encoding="utf-8")).keys())
    total = len(source_keys)
    worst_pct = 100.0
    worst_code = None
    n_locales = 0
    for path in sorted(_LOCALES.glob("*.json")):
        if path.stem == "en":
            continue
        n_locales += 1
        keys = set(json.loads(path.read_text(encoding="utf-8")).keys()) & source_keys
        pct = round(100 * len(keys) / total, 1) if total else 100.0
        if pct < worst_pct:
            worst_pct, worst_code = pct, path.stem
    return _entry(
        spec,
        value=worst_pct,
        n=n_locales,
        as_of=_now(),
        verdict="green" if worst_pct >= 100.0 else "red",
        method=(f"minimum locale key-coverage across {n_locales} locales vs en.json "
                f"(lowest: {worst_code or '—'}); the audit-chrome=0 half is CI-verified"),
    )


_RESOLVERS = {"K2": _k2_latency, "K11": _k11_i18n}


def kpi_snapshot(session=None) -> dict:  # noqa: ARG001 - session accepted for the endpoint contract
    """The read-only K1–K14 KPI snapshot. Deterministic, no heavy crunch, no composite."""
    metrics: list[dict] = []
    for spec in _SPECS:
        resolver = _RESOLVERS.get(spec["id"])
        if resolver is None:
            metrics.append(_entry(spec))  # not-measurable-here with the spec's honest reason
            continue
        try:
            metrics.append(resolver(spec))
        except Exception as exc:  # noqa: BLE001 - a resolver fault degrades to not-measurable
            metrics.append(_entry(spec, method=f"resolver error (not-measurable): {type(exc).__name__}"))
    return {
        "schema": _SCHEMA,
        "generated_at": _now(),
        "metrics": metrics,
        "method": (
            "One entry per K1–K14 metric with a declared direction-of-goodness and target; "
            "only the cheap in-process instruments (latency reservoir, locale files) are read "
            "live, the rest report not-measurable-here honestly. Each metric stands alone."
        ),
        "caveat": (
            "NO composite — there is no overall score or count-of-greens by design. "
            "not-measurable-here is the honest verdict for a metric whose instrument needs the "
            "live corpus, a graded gold set, an operator P0 run, CI facts, or an expensive scan "
            "not run on this GET. Feed two snapshots to scripts/kpi_diff.py for the cycle report."
        ),
    }


def run_kpi_selftest() -> dict:
    """Mechanism proof (no DB, no network): every metric declares a direction and an honest
    verdict, the payload carries no composite/score key, and not-measurable is used honestly."""
    checks: list[dict] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(ok), "detail": detail})

    snap = kpi_snapshot()
    metrics = snap.get("metrics", [])
    _check("schema", snap.get("schema") == _SCHEMA, str(snap.get("schema")))
    _check("all_14_present", len(metrics) == 14, str(len(metrics)))
    _check("direction_always_present",
           all(m.get("direction") in ("up", "down", "exact") for m in metrics))
    _check("verdict_in_domain",
           all(m.get("verdict") in ("green", "red", _NM) for m in metrics))
    _check("target_always_present", all(m.get("target") for m in metrics))
    # not-measurable honesty: a NM metric carries no fabricated value/verdict.
    nm = [m for m in metrics if m["verdict"] == _NM]
    _check("not_measurable_is_honest", all(m.get("value") is None for m in nm),
           f"{len(nm)} not-measurable metrics")

    # no composite: walk keys for the banned score substrings (the key-walker convention).
    def _no_score(o) -> bool:
        if isinstance(o, dict):
            for k, v in o.items():
                if any(b in str(k).lower() for b in ("score", "ranking", "rating", "grade")):
                    return False
                if not _no_score(v):
                    return False
        elif isinstance(o, list):
            return all(_no_score(v) for v in o)
        return True

    _check("no_composite_score_key", _no_score(snap))

    failed = sum(1 for c in checks if not c["passed"])
    return {
        "schema": "oo-kpi-selftest-1",
        "passed": failed == 0,
        "checks": checks,
        "summary": {"total": len(checks), "failed": failed},
        "method": "runs kpi_snapshot() on a dev process and asserts the honesty invariants "
                  "(direction present, verdict in domain, not-measurable honest, no composite).",
    }
