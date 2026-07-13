"""
Keyword fingerprints — the same-skeleton echo tier (planning §3).

Pure tests over hand-built keyword skeletons: fingerprint stability + order-independence, MinHash
skeleton clustering (reusing the token-agnostic near_dup machinery), the ORDER-aware comparator,
and the skeleton_echo producer gate (≥3 sources, refuses a text near-dup / single source). Honesty
guards: no score, the innocent explanation on every card, exact article_ids.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.analytics.skeleton import (
    build_skeleton_echo_card,
    ordered_skeleton_similarity,
    run_skeleton_selftest,
    skeleton_clusters,
    skeleton_fingerprint,
    skeleton_signature,
)


def test_fingerprint_is_stable_and_order_independent():
    assert skeleton_fingerprint({3, 1, 2}) == skeleton_fingerprint({1, 2, 3})
    assert len(skeleton_fingerprint({1, 2, 3})) == 16
    assert skeleton_fingerprint({1, 2, 3}) != skeleton_fingerprint({1, 2, 4})
    # empty skeleton has a stable sentinel fingerprint
    assert skeleton_fingerprint(set()) == skeleton_fingerprint(set())


def test_skeleton_signature_feeds_the_id_set_into_minhash():
    sig = skeleton_signature({1, 2, 3, 4}, num_perm=64)
    assert isinstance(sig, list) and len(sig) == 64


def test_near_identical_skeletons_cluster_disjoint_does_not():
    base = set(range(1, 41))
    docs = {
        "a": set(base),
        "b": (set(base) - {40}) | {41},   # 39/41 overlap
        "c": set(range(500, 540)),         # disjoint
    }
    clusters = skeleton_clusters(docs, threshold=0.7)
    assert len(clusters) == 1
    assert clusters[0] == {"a", "b"}


def test_empty_skeletons_never_form_a_phantom_cluster():
    assert skeleton_clusters({"x": set(), "y": set()}, threshold=0.0) == []


def test_skeleton_clusters_threshold_validated():
    with pytest.raises(ValueError):
        skeleton_clusters({"a": {1}}, threshold=2.0)


def test_ordered_comparator_is_order_aware():
    seq = [10, 20, 30, 40, 50]
    assert ordered_skeleton_similarity(seq, seq) == 1.0
    # same members, reversed order -> strictly lower (a template vs a coincidental vocabulary)
    assert ordered_skeleton_similarity(seq, [50, 40, 30, 20, 10]) < 1.0
    assert ordered_skeleton_similarity([], []) == 0.0
    # a shared prefix scores by the longest common subsequence / max length
    assert ordered_skeleton_similarity([1, 2, 3], [1, 2, 9]) == pytest.approx(2 / 3)


def test_producer_fires_on_three_sources_with_innocent_caveat():
    card = build_skeleton_echo_card(
        doc_ids=["d1", "d2", "d3"],
        source_of={"d1": "A", "d2": "B", "d3": "C"},
        article_ids=[3, 1, 2],
        keyword_ids={7, 8, 9},
        is_text_neardup=False,
    )
    assert card is not None
    assert card.signal["value"] == 3
    assert card.article_ids == [1, 2, 3]  # exact, sorted
    assert "never proof of coordination" in card.caveat
    assert card.n == 3


def test_producer_refuses_text_neardup_and_single_source():
    common = {"doc_ids": ["d1", "d2", "d3"], "article_ids": [1, 2, 3], "keyword_ids": {1, 2, 3}}
    # a whole-text near-dup is echo_chamber's job, not a skeleton echo
    assert build_skeleton_echo_card(
        source_of={"d1": "A", "d2": "B", "d3": "C"}, is_text_neardup=True, **common) is None
    # below the distinct-source floor
    assert build_skeleton_echo_card(
        source_of={"d1": "A", "d2": "A", "d3": "A"}, is_text_neardup=False, **common) is None


def test_selftest_all_green():
    log = run_skeleton_selftest()
    assert log["passed"] is True, [c for c in log["checks"] if not c["passed"]]


def test_no_score_field_anywhere():
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert not any(b in str(k).lower() for b in ("score", "ranking", "rating", "grade"))
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    card = build_skeleton_echo_card(
        doc_ids=["d1", "d2", "d3"], source_of={"d1": "A", "d2": "B", "d3": "C"},
        article_ids=[1, 2, 3], keyword_ids={1, 2, 3}, is_text_neardup=False,
    )
    assert card is not None
    walk(card.signal)
    walk(run_skeleton_selftest())
