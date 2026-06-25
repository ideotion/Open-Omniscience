"""IR retrieval-eval harness (keyword-engine Phase 3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pure-Python IR metrics (nDCG/MRR/Recall/P@k/AP) + a pluggable evaluate() with
per-language aggregation, the conflation recall/precision deltas, and a regression gate.
The metrics are asserted against HAND-COMPUTED values so a green run is never vacuous.
"""

from __future__ import annotations

import math

from src.analytics.ir_eval import (
    GoldQuery,
    average_precision,
    conflation_delta,
    evaluate,
    evaluate_against_corpus,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    regression_check,
    rr_at_k,
    run_ir_eval_selftest,
)

# Fixture: ranked [d1,d2,d3,d4]; relevant d2 (grade 2), d3 (grade 1).
_RANKED = ["d1", "d2", "d3", "d4"]
_REL = {"d2": 2, "d3": 1}


def test_metrics_match_hand_computed_values():
    # DCG = 0 + (2^2-1)/log2(3) + (2^1-1)/log2(4) = 3/1.58496 + 0.5 = 2.39279
    # IDCG (grades [2,1]) = 3/1 + 1/log2(3) = 3.63093 ; nDCG = 0.65899
    assert math.isclose(ndcg_at_k(_RANKED, _REL, 4), 0.65899, abs_tol=1e-4)
    assert math.isclose(rr_at_k(_RANKED, _REL, 4), 0.5, abs_tol=1e-9)  # first relevant at rank 2
    assert math.isclose(recall_at_k(_RANKED, _REL, 4), 1.0, abs_tol=1e-9)  # both relevant found
    assert math.isclose(precision_at_k(_RANKED, _REL, 4), 0.5, abs_tol=1e-9)  # 2 of 4
    # AP = (1/2 at rank2 + 2/3 at rank3) / 2 = 0.58333
    assert math.isclose(average_precision(_RANKED, _REL), 0.58333, abs_tol=1e-4)


def test_ndcg_edges():
    assert ndcg_at_k(["d2", "d3"], _REL, 4) == 1.0  # ideal ranking
    assert ndcg_at_k([], _REL, 4) == 0.0  # nothing retrieved
    assert ndcg_at_k(_RANKED, {}, 4) == 0.0  # nothing relevant -> 0 (no idcg)


def test_recall_at_k_respects_cutoff():
    # only d2 is in the top-1 -> recall 1/2
    assert math.isclose(recall_at_k(_RANKED, _REL, 2), 0.5, abs_tol=1e-9)


def test_evaluate_breaks_down_by_language_with_n_and_no_composite_score():
    gold = [
        GoldQuery("q_en", "inflation", "en", "topic", {"a1": 2, "a2": 1}),
        GoldQuery("q_fr", "inflation", "fr", "cross-lingual", {"b1": 2}),
    ]
    rep = evaluate({"q_en": ["a1", "a2"], "q_fr": ["x", "b1"]}, gold, k=10)
    assert set(rep["by_language"]) == {"en", "fr"}
    assert rep["by_language"]["en"]["n"] == 1 and rep["by_language"]["fr"]["n"] == 1
    assert set(rep["by_axis"]) == {"topic", "cross-lingual"}
    # honesty: a pooled overall carries the read-by_language caveat, and there is NO
    # blended composite "score" key — each metric stands alone.
    assert "caveat" in rep["overall"] and "score" not in rep["overall"]
    # q_en perfect (both relevant on top) -> ndcg 1.0; q_fr relevant at rank 2.
    assert math.isclose(rep["by_language"]["en"]["ndcg"], 1.0, abs_tol=1e-9)


def test_conflation_delta_reports_both_sides_separately():
    gold = [GoldQuery("q", "x", "en", "topic", {"a1": 2, "a2": 1})]
    a = {"q": ["a1"]}
    b = {"q": ["a1", "a2", "z9"]}  # a2 newly-relevant, z9 newly-irrelevant
    d = conflation_delta(a, b, gold, k=10)
    assert d["recall_delta"] > 0  # B found another relevant doc
    assert any(e["doc"] == "a2" for e in d["newly_relevant"])
    assert any(e["doc"] == "z9" for e in d["newly_irrelevant"])
    # reported separately, never one blended number
    assert "recall_delta" in d and "precision_delta" in d and "caveat" in d


def test_regression_check_catches_a_drop_and_passes_within_tol():
    base = {"ndcg": 0.9, "recall": 1.0, "mrr": 1.0, "precision": 1.0, "ap": 1.0}
    worse = {"overall": {"ndcg": 0.5, "recall": 1.0, "mrr": 1.0, "precision": 1.0, "ap": 1.0}}
    out = regression_check(worse, base, tol=0.02)
    assert out["ok"] is False and any(f["metric"] == "ndcg" for f in out["failures"])
    assert regression_check({"overall": base}, base, tol=0.02)["ok"] is True


def test_evaluate_against_corpus_uses_the_injected_search_fn():
    # No DB needed: inject a search_fn so the harness is provable end-to-end.
    gold = [GoldQuery("q", "inflation", "en", "known-item", {"d1": 2})]
    rep = evaluate_against_corpus(None, gold, k=10, search_fn=lambda q: ["d1", "d2"])
    assert math.isclose(rep["by_language"]["en"]["recall"], 1.0, abs_tol=1e-9)


def test_ir_eval_selftest_all_pass():
    log = run_ir_eval_selftest()
    assert log["schema"] == "oo-ir-eval-selftest-1"
    assert log["summary"]["failed"] == 0 and log["summary"]["passed"] == log["summary"]["total"]
