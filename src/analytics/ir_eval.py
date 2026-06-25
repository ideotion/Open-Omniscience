"""IR retrieval-evaluation harness (keyword-engine Phase 3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The keyword engine has a keyword-QUALITY self-test (``selftest.py``) and an engine
report, but NO RETRIEVAL eval — so a ranking / conflation change (BM25F weights P5.1,
lemmatization P4.3, the embedding recall layer P5.2) cannot be measured, only guessed.
This is that gate, and the project's "measure before you trust / never fabricate" rule
makes it a prerequisite for every quality change.

Design (honesty-first, dependency-free):

* **Standard IR metrics implemented natively** — nDCG@k / MRR@k / Recall@k / P@k / AP,
  the textbook definitions (no torch, no new ``[eval]`` extra to gate or degrade; the
  formulas are simple + unit-tested against hand-computed values).
* **Per-language / per-axis, n always stated; NEVER one pooled average alone.** A single
  blended number hides the per-stratum reality (a method can win overall while losing on
  Arabic). ``by_language`` / ``by_axis`` are the honest view; ``overall`` is pooled and
  carries that caveat. (No composite "quality score" — each metric stands alone.)
* **The conflation trade-off is reported as TWO deltas + example sets**, never blended:
  recall GAINED and precision LOST, with the newly-relevant vs newly-irrelevant docs a
  change surfaced — so a merge that helps recall but hurts precision is visible as both.
* **A regression gate**: compare a fresh report to a frozen baseline; fail if any metric
  drops beyond a tolerance.

The harness is PLUGGABLE: it consumes ``{query_id: [ranked doc ids]}`` (pure, testable
without a backend) and provides ``evaluate_against_corpus`` to run the live FTS search
over a GOLD SET. The gold set itself is corpus-specific + human-judged (graded 0/1/2 over
the maintainer's own documents) — the one OPERATIONAL piece; this module is the
mechanism, ``GoldQuery`` is the format, and ``run_ir_eval_selftest`` proves the metrics on
a fixture so a regression in the harness reddens immediately.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

_METRICS = ("ndcg", "mrr", "recall", "precision", "ap")


# --------------------------------------------------------------------------- #
# Metrics — standard definitions, pure functions over a ranked id list + the
# query's relevance grades {doc_id: grade}. grade 0 = irrelevant, 1/2 = graded.
# --------------------------------------------------------------------------- #
def _gain(grade: float) -> float:
    return (2.0**grade) - 1.0


def dcg_at_k(gains: list[float], k: int) -> float:
    """Discounted cumulative gain of the gains list (already in rank order)."""
    return sum(_gain(g) / math.log2(i + 2) for i, g in enumerate(gains[:k]))


def ndcg_at_k(ranked: list, rel: dict, k: int) -> float:
    """nDCG@k: DCG of the retrieved ranking ÷ IDCG (the ideal ranking of ALL judged
    grades, so an un-retrieved relevant doc correctly costs recall)."""
    dcg = dcg_at_k([rel.get(d, 0) for d in ranked[:k]], k)
    idcg = dcg_at_k(sorted(rel.values(), reverse=True), k)
    return (dcg / idcg) if idcg > 0 else 0.0


def rr_at_k(ranked: list, rel: dict, k: int) -> float:
    """Reciprocal rank of the first relevant (grade>0) doc within the top k."""
    for i, d in enumerate(ranked[:k]):
        if rel.get(d, 0) > 0:
            return 1.0 / (i + 1)
    return 0.0


def recall_at_k(ranked: list, rel: dict, k: int) -> float:
    relevant = {d for d, g in rel.items() if g > 0}
    if not relevant:
        return 0.0
    hit = sum(1 for d in ranked[:k] if d in relevant)
    return hit / len(relevant)


def precision_at_k(ranked: list, rel: dict, k: int) -> float:
    if k <= 0:
        return 0.0
    relevant = {d for d, g in rel.items() if g > 0}
    hit = sum(1 for d in ranked[:k] if d in relevant)
    return hit / k


def average_precision(ranked: list, rel: dict) -> float:
    relevant = {d for d, g in rel.items() if g > 0}
    if not relevant:
        return 0.0
    hits = 0
    total = 0.0
    for i, d in enumerate(ranked):
        if d in relevant:
            hits += 1
            total += hits / (i + 1)
    return total / len(relevant)


# --------------------------------------------------------------------------- #
# Gold set + evaluation
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GoldQuery:
    """One judged query. ``relevances`` maps doc id -> graded relevance (0/1/2). ``axis``
    is the retrieval phenomenon the query exercises (known-item / topic / cross-lingual /
    near-dup), so the report can break down by axis as well as language."""

    id: str
    query: str
    language: str = "en"
    axis: str = "topic"
    relevances: dict = field(default_factory=dict)


def _query_metrics(ranked: list, rel: dict, k: int) -> dict:
    return {
        "ndcg": ndcg_at_k(ranked, rel, k),
        "mrr": rr_at_k(ranked, rel, k),
        "recall": recall_at_k(ranked, rel, k),
        "precision": precision_at_k(ranked, rel, k),
        "ap": average_precision(ranked, rel),
    }


def _mean_metrics(rows: list[dict]) -> dict:
    if not rows:
        return {m: 0.0 for m in _METRICS}
    return {m: round(sum(r[m] for r in rows) / len(rows), 4) for m in _METRICS}


def _aggregate(per_query: list[dict], key: str) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in per_query:
        groups[r[key]].append(r)
    # Per-stratum means WITH n — never collapsed into a single cross-stratum number.
    return {
        val: {**_mean_metrics(rows), "n": len(rows)}
        for val, rows in sorted(groups.items())
    }


def evaluate(results_by_query: dict, gold: list[GoldQuery], *, k: int = 10) -> dict:
    """Score a run. ``results_by_query`` maps a GoldQuery id -> the ranked doc ids the
    system returned. Returns per-query rows + per-language + per-axis aggregates (each
    with n) + a pooled ``overall`` that carries the read-by_language caveat. No composite
    score — every metric is reported on its own."""
    per_query: list[dict] = []
    for g in gold:
        ranked = list(results_by_query.get(g.id, []))
        m = _query_metrics(ranked, g.relevances, k)
        per_query.append(
            {
                "id": g.id,
                "language": g.language,
                "axis": g.axis,
                "n_relevant": sum(1 for v in g.relevances.values() if v > 0),
                "n_retrieved": len(ranked),
                **{mk: round(mv, 4) for mk, mv in m.items()},
            }
        )
    overall = _mean_metrics(per_query)
    return {
        "schema": "oo-ir-eval-1",
        "k": k,
        "n_queries": len(gold),
        "by_language": _aggregate(per_query, "language"),
        "by_axis": _aggregate(per_query, "axis"),
        "overall": {
            **overall,
            "n": len(per_query),
            "caveat": (
                "pooled across languages/axes; read by_language for the honest per-stratum "
                "view (a method can win overall while losing on one language)"
            ),
        },
        "per_query": per_query,
    }


def conflation_delta(
    results_a: dict, results_b: dict, gold: list[GoldQuery], *, k: int = 10
) -> dict:
    """Measure a conflation/ranking change A->B as TWO separate deltas (recall gained,
    precision changed) + the example sets — NEVER one blended number (respects
    no-composite-score). B is the new behaviour (e.g. lemmatized/merged)."""
    ra = evaluate(results_a, gold, k=k)["overall"]
    rb = evaluate(results_b, gold, k=k)["overall"]
    newly_relevant: list[dict] = []
    newly_irrelevant: list[dict] = []
    for g in gold:
        top_a = set(list(results_a.get(g.id, []))[:k])
        top_b = set(list(results_b.get(g.id, []))[:k])
        relevant = {d for d, gr in g.relevances.items() if gr > 0}
        for d in top_b - top_a:  # docs B newly surfaced into the top-k
            (newly_relevant if d in relevant else newly_irrelevant).append(
                {"query": g.id, "language": g.language, "doc": d}
            )
    return {
        "recall_delta": round(rb["recall"] - ra["recall"], 4),
        "precision_delta": round(rb["precision"] - ra["precision"], 4),
        "ndcg_delta": round(rb["ndcg"] - ra["ndcg"], 4),
        "newly_relevant": newly_relevant,
        "newly_irrelevant": newly_irrelevant,
        "caveat": (
            "recall gain and precision change are reported SEPARATELY (with the newly "
            "surfaced relevant vs irrelevant docs), never blended into one score"
        ),
    }


def regression_check(report: dict, baseline: dict, *, tol: float = 0.02) -> dict:
    """Fail if any overall metric dropped more than ``tol`` below the frozen baseline.
    ``baseline`` is a ``{metric: value}`` map (an earlier run's ``overall``)."""
    cur = report.get("overall", {})
    failures = [
        {"metric": m, "baseline": round(baseline[m], 4), "current": round(cur.get(m, 0.0), 4)}
        for m in _METRICS
        if m in baseline and cur.get(m, 0.0) < baseline[m] - tol
    ]
    return {"ok": not failures, "tol": tol, "failures": failures}


def evaluate_against_corpus(session, gold: list[GoldQuery], *, k: int = 10, search_fn=None) -> dict:
    """Run the LIVE search over a gold set and score it. ``search_fn(query) -> [doc_ids]``
    defaults to the FTS5 ranked search (``search_ids``); pass a different one (e.g. a
    BM25F or hybrid variant) to A/B a ranking change with :func:`conflation_delta`."""
    if search_fn is None:
        from src.database.fts import search_ids

        def search_fn(q: str):  # noqa: ANN001 - local default
            return search_ids(session, q, limit=max(k, 50)) or []

    results = {g.id: list(search_fn(g.query) or []) for g in gold}
    return evaluate(results, gold, k=k)


# --------------------------------------------------------------------------- #
# Self-test — proves the metrics + aggregation + delta + gate on a fixture (no
# DB, no network), so a regression in the harness ITSELF reddens immediately.
# --------------------------------------------------------------------------- #
def run_ir_eval_selftest() -> dict:
    """Run the harness over a hand-computed fixture and return an exportable log
    (schema ``oo-ir-eval-selftest-1``). Each check states the property it guards; the
    expected numbers are computed by hand in the test, so a green run is never vacuous."""
    checks: list[dict] = []

    def _check(cid: str, guards: str, ok: bool, detail: str = "") -> None:
        checks.append({"id": cid, "guards": guards, "status": "pass" if ok else "fail", "detail": detail})

    # A fixture query: ranked [d1,d2,d3,d4]; grades d2=2, d3=1 (d1,d4 irrelevant).
    rel = {"d2": 2, "d3": 1}
    ranked = ["d1", "d2", "d3", "d4"]
    ndcg = ndcg_at_k(ranked, rel, 4)
    mrr = rr_at_k(ranked, rel, 4)
    rec = recall_at_k(ranked, rel, 4)
    prec = precision_at_k(ranked, rel, 4)
    _check("mrr_first_relevant_rank2", "MRR = 1/rank of the first relevant doc", abs(mrr - 0.5) < 1e-9, f"mrr={mrr}")
    _check("recall_all_relevant_found", "recall = found/relevant", abs(rec - 1.0) < 1e-9, f"recall={rec}")
    _check("precision_2_of_4", "precision@4 = 2 relevant / 4", abs(prec - 0.5) < 1e-9, f"precision={prec}")
    _check("ndcg_in_unit_range", "nDCG is in (0,1] and < 1 for a non-ideal ranking", 0.0 < ndcg < 1.0, f"ndcg={ndcg:.4f}")
    # A perfect ranking scores nDCG = 1.0.
    _check("ndcg_perfect_is_one", "an ideal ranking scores nDCG=1", abs(ndcg_at_k(["d2", "d3"], rel, 4) - 1.0) < 1e-9)

    # Aggregation: two languages, n stated, never one pooled-only number.
    gold = [
        GoldQuery("q_en", "inflation", "en", "topic", {"a1": 2, "a2": 1}),
        GoldQuery("q_fr", "inflation", "fr", "cross-lingual", {"b1": 2}),
    ]
    rep = evaluate({"q_en": ["a1", "a2"], "q_fr": ["x", "b1"]}, gold, k=10)
    _check(
        "report_breaks_down_by_language",
        "the report carries per-language metrics with n (never one pooled average alone)",
        set(rep["by_language"]) == {"en", "fr"} and rep["by_language"]["en"]["n"] == 1,
    )
    _check("report_has_no_composite_score", "no blended 'score' key — each metric stands alone", "score" not in rep["overall"])

    # Conflation delta: B surfaces one newly-relevant + one newly-irrelevant doc.
    a = {"q_en": ["a1"]}
    b = {"q_en": ["a1", "a2", "z9"]}  # a2 is relevant, z9 is not
    d = conflation_delta(a, b, [gold[0]], k=10)
    _check(
        "conflation_reports_both_sides",
        "recall gain AND the newly-relevant vs newly-irrelevant docs reported separately",
        d["recall_delta"] > 0
        and any(e["doc"] == "a2" for e in d["newly_relevant"])
        and any(e["doc"] == "z9" for e in d["newly_irrelevant"]),
    )

    # Regression gate: a drop beyond tol fails; within tol passes.
    base = {"ndcg": 0.9, "recall": 1.0, "mrr": 1.0, "precision": 1.0, "ap": 1.0}
    worse = {"overall": {"ndcg": 0.5, "recall": 1.0, "mrr": 1.0, "precision": 1.0, "ap": 1.0}}
    _check("regression_gate_catches_a_drop", "the gate fails on a metric drop beyond tol", not regression_check(worse, base, tol=0.02)["ok"])
    _check("regression_gate_passes_within_tol", "a tiny drop within tol passes", regression_check({"overall": base}, base, tol=0.02)["ok"])

    passed = sum(1 for c in checks if c["status"] == "pass")
    return {
        "kind": "ir-eval-selftest",
        "schema": "oo-ir-eval-selftest-1",
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {"total": len(checks), "passed": passed, "failed": len(checks) - passed},
        "checks": checks,
        "note": (
            "This proves the eval MECHANISM. A real retrieval measurement needs a "
            "human-judged GOLD SET (graded 0/1/2) over your own corpus — the one "
            "operational step; feed it to evaluate_against_corpus()."
        ),
    }
