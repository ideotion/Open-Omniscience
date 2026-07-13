"""
Conjunction Lens — N-keyword set algebra + derived lenses (planning §1).

Proves the promoted set-algebra core over an in-memory corpus (intersection / union / difference),
the per-article intensity GROUP BY, the conditional trend, and — pure — the vocabulary contrast +
FTS5 NEAR emission. Honesty guards: no score, honest bounding disclosure, unknown op fails loud.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.analytics.conjunction import (
    conditional_trend,
    corpus_algebra,
    near_match_expression,
    per_article_intensity,
    run_conjunction_selftest,
    vocabulary_contrast,
)
from src.database.models import Base, Keyword, KeywordMention


def _corpus() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    # election -> articles 1,2,3 ; france -> 2,3,4 ; protest -> 3,4,5
    kws = {}
    for term in ("election", "france", "protest"):
        k = Keyword(term=term, normalized_term=term)
        s.add(k)
        s.flush()
        kws[term] = k
    spread = {"election": [1, 2, 3], "france": [2, 3, 4], "protest": [3, 4, 5]}
    for term, arts in spread.items():
        for i, aid in enumerate(arts):
            s.add(
                KeywordMention(
                    keyword_id=kws[term].id,
                    article_id=aid,
                    count=1 + i,
                    observed_on=date(2026, 1, 1 + aid),
                )
            )
    s.commit()
    return s


def test_intersection_is_articles_mentioning_all_terms():
    s = _corpus()
    r = corpus_algebra(s, ["election", "france"], op="intersection")
    assert r["article_ids"] == [2, 3]
    assert r["n_combined"] == 2
    r3 = corpus_algebra(s, ["election", "france", "protest"], op="intersection")
    assert r3["article_ids"] == [3]  # only article 3 has all three


def test_union_and_difference():
    s = _corpus()
    u = corpus_algebra(s, ["election", "france"], op="union")
    assert u["article_ids"] == [1, 2, 3, 4]
    # difference: election articles NOT in france -> {1,2,3} - {2,3,4} = {1}
    d = corpus_algebra(s, ["election", "france"], op="difference")
    assert d["article_ids"] == [1]


def test_per_term_n_is_reported():
    s = _corpus()
    r = corpus_algebra(s, ["election", "france"], op="intersection")
    by = {t["normalized"]: t["n"] for t in r["terms"]}
    assert by == {"election": 3, "france": 3}


def test_unknown_op_fails_loud():
    s = _corpus()
    with pytest.raises(ValueError):
        corpus_algebra(s, ["election"], op="nand")


def test_bounded_disclosed_when_the_scan_hits_the_cap():
    s = _corpus()
    r = corpus_algebra(s, ["election"], op="union", cap=2)  # election has 3 -> scan capped at 2
    assert r["bounded"] is True
    assert "Bounded" in r["caveat"]
    r2 = corpus_algebra(s, ["election"], op="union", cap=100)
    assert r2["bounded"] is False


def test_intersection_under_cap_is_a_subset_never_a_false_member():
    # Skeptic regression: election={1,2,3}, protest={3,4,5}, true intersection={3}. Under a
    # truncating cap the result must be a SUBSET of the truth (never a fabricated member), and
    # the incompleteness must be disclosed via result_bounded — not a benign per-term cap note.
    s = _corpus()
    true_inter = {3}
    r2 = corpus_algebra(s, ["election", "protest"], op="intersection", cap=2)
    assert set(r2["article_ids"]) <= true_inter  # subset — never a false member
    assert r2["result_bounded"] is True
    r100 = corpus_algebra(s, ["election", "protest"], op="intersection", cap=100)
    assert set(r100["article_ids"]) == true_inter  # exact when the scan isn't truncated
    assert r100["result_bounded"] is False


def test_difference_under_cap_never_includes_a_false_member():
    # The dangerous case the naive independent-cap approach got wrong: the SHARED article (3)
    # must NEVER be falsely included in "election minus protest".
    s = _corpus()
    true_diff = {1, 2}
    r2 = corpus_algebra(s, ["election", "protest"], op="difference", cap=2)
    assert set(r2["article_ids"]) <= true_diff
    assert 3 not in r2["article_ids"]  # the shared article is never wrongly in the difference
    assert r2["result_bounded"] is True
    r100 = corpus_algebra(s, ["election", "protest"], op="difference", cap=100)
    assert set(r100["article_ids"]) == true_diff


def test_per_term_n_is_exact_and_uncapped():
    # LOW regression: per-term n is the exact corpus-wide count, not a cap-truncated upper bound.
    s = _corpus()
    r = corpus_algebra(s, ["election"], op="union", cap=1)  # scan truncated to 1 article...
    assert r["terms"][0]["n"] == 3  # ...but election's article count is exact (3), not the cap
    assert r["bounded"] is True


def test_empty_or_unresolvable_terms_are_honest():
    s = _corpus()
    r = corpus_algebra(s, ["   ", ""], op="intersection")
    assert r["article_ids"] == [] and r["n_terms"] == 0


def test_per_article_intensity_ranks_densest_first():
    s = _corpus()
    inter = corpus_algebra(s, ["election", "france", "protest"], op="union")["article_ids"]
    r = per_article_intensity(s, inter, ["election", "france", "protest"])
    # article 3 mentions all three -> distinct_terms == 3, ranked first
    assert r["articles"][0]["article_id"] == 3
    assert r["articles"][0]["distinct_terms"] == 3


def test_conditional_trend_buckets_the_conjunction_set():
    s = _corpus()
    ids = corpus_algebra(s, ["election", "france"], op="intersection")["article_ids"]  # {2,3}
    tr = conditional_trend(s, ids, bucket="month")
    assert tr["total"] > 0
    assert all(set(p) == {"date", "count"} for p in tr["points"])


def test_vocabulary_contrast_is_a_pure_delta_with_both_ns():
    a = [{"normalized": "election", "term": "election", "articles": 10}]
    b = [{"normalized": "election", "term": "election", "articles": 3}]
    vc = vocabulary_contrast(a, b, n_a=10, n_b=10)
    row = vc["contrasts"][0]
    assert row["a_articles"] == 10 and row["b_articles"] == 3 and row["delta"] == 7


def test_near_emission_is_pure_and_escapes():
    assert near_match_expression(["oil", "gas"], distance=5) == 'NEAR("oil" "gas", 5)'
    assert near_match_expression(["oil"]) is None
    with pytest.raises(ValueError):
        near_match_expression(["a", "b"], distance=-1)


def test_selftest_all_green():
    log = run_conjunction_selftest()
    assert log["passed"] is True, [c for c in log["checks"] if not c["passed"]]


def test_no_score_field_anywhere():
    s = _corpus()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert not any(b in str(k).lower() for b in ("score", "ranking", "rating", "grade"))
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(corpus_algebra(s, ["election", "france"], op="intersection"))
    walk(per_article_intensity(s, [2, 3], ["election", "france"]))
    walk(run_conjunction_selftest())


def test_corpus_algebra_endpoint_is_wired():
    # WIRING CONTRACT (source-inspected, no app import): the N-keyword backend seam exists.
    from pathlib import Path

    src = Path("src/api/insights.py").read_text(encoding="utf-8")
    assert '@router.get("/corpus-algebra")' in src
    assert "from src.analytics.conjunction import corpus_algebra" in src
