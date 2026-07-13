"""
Leads 2.0 — ordering / floor / clustering / lifecycle cores (planning §2).

Pure tests over hand-built Cards. The binding §2 honesty property: importance is a DISCLOSED
ordering over real facts, never a composite score — so order_key is a tuple, explain_order names
the facts, is_major is a threshold FACT, and nothing emits a score-like key.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.briefing.card import Card
from src.briefing.leads import (
    card_deltas,
    cluster_by_article_ids,
    explain_order,
    is_major,
    newest_evidence_age,
    order_key,
    run_leads_selftest,
    sort_leads,
)

NOW = datetime(2026, 7, 13)


def _card(key, *, n=None, sources=0, ages=(), article_ids=(), bucket="rising"):
    ev = [{"source": f"src{i}", "published_at": None} for i in range(sources)]
    for i, a in enumerate(ages):
        if i < len(ev):
            ev[i]["published_at"] = (NOW - timedelta(days=a)).isoformat()
    return Card(
        type="rising", title=key, summary="s", bucket=bucket, method="m", caveat="c",
        key=key, n=n, evidence=ev, article_ids=list(article_ids),
    )


def test_newest_evidence_age_uses_the_freshest_and_degrades_to_none():
    c = _card("c", sources=2, ages=(10, 3))
    assert abs(newest_evidence_age(c, now=NOW) - 3.0) < 0.01
    assert newest_evidence_age(_card("nodate", sources=2), now=NOW) is None  # no dated evidence


def test_future_dated_evidence_is_clamped_to_zero_age():
    c = _card("future", sources=1, ages=(-5,))  # 5 days in the future
    assert newest_evidence_age(c, now=NOW) == 0.0


def test_order_is_by_sources_then_magnitude_then_recency():
    a = _card("a", n=500, sources=2)   # big n but few sources
    b = _card("b", n=10, sources=6)    # more independent sources wins
    assert sort_leads([a, b], now=NOW)[0].key == "b"
    # tie on sources+magnitude → recency decides
    fresh = _card("fresh", n=60, sources=3, ages=(1,))
    stale = _card("stale", n=60, sources=3, ages=(40,))
    assert sort_leads([stale, fresh], now=NOW)[0].key == "fresh"


def test_order_key_is_a_tuple_not_a_scalar_score():
    k = order_key(_card("x", n=5, sources=1), now=NOW)
    assert isinstance(k, tuple) and len(k) == 3


def test_explain_order_names_the_disclosed_facts():
    s = explain_order(_card("x", n=60, sources=4, ages=(2,)), now=NOW)
    assert "independent source" in s and "magnitude tier" in s and "never a score" in s


def test_is_major_is_a_threshold_fact():
    maj = is_major(_card("m", n=120, sources=6))
    assert maj["major"] is True and "≥" in maj["fact"]
    # short on sources → not major, and the fact shows why
    short = is_major(_card("s", n=120, sources=2))
    assert short["major"] is False and "<" in short["fact"]
    # custom floors
    assert is_major(_card("t", n=5, sources=1), floors={"min_n": 1, "min_sources": 1})["major"] is True


def test_cluster_stacks_overlapping_leads_only():
    c1 = _card("c1", article_ids=[1, 2, 3, 4])
    c2 = _card("c2", article_ids=[2, 3, 4, 5])   # Jaccard 3/5 = 0.6
    c3 = _card("c3", article_ids=[90, 91])        # disjoint
    cl = cluster_by_article_ids([c1, c2, c3], threshold=0.5)
    assert cl["n_clusters"] == 1
    assert {m["key"] for m in cl["clusters"][0]} == {"c1", "c2"}


def test_cluster_ignores_leads_without_article_ids():
    a = _card("a")  # no article_ids
    b = _card("b")  # no article_ids
    assert cluster_by_article_ids([a, b], threshold=0.1)["n_clusters"] == 0


def test_cluster_threshold_must_be_a_fraction():
    with pytest.raises(ValueError):
        cluster_by_article_ids([_card("a", article_ids=[1])], threshold=1.5)


def test_card_deltas_new_strengthened_weakened_mixed_gone():
    prev = [_card("keep", n=10, sources=3), _card("weaken", n=10, sources=4), _card("drop", n=5, sources=2)]
    new = [
        _card("keep", n=20, sources=5),      # both up -> strengthened
        _card("weaken", n=5, sources=2),      # both down -> weakened
        _card("fresh", n=3, sources=1),       # not in prev -> new
        # "drop" absent from new -> gone
    ]
    by_status = {d["status"] for d in card_deltas(prev, new)["deltas"]}
    assert {"strengthened", "weakened", "new", "gone"} <= by_status


def test_card_deltas_mixed_when_n_and_sources_move_apart():
    prev = [_card("x", n=10, sources=4)]
    new = [_card("x", n=50, sources=1)]  # n up, sources down
    d = card_deltas(prev, new)["deltas"][0]
    assert d["status"] == "mixed" and d["n_delta"] == 40 and d["sources_delta"] == -3


def test_selftest_all_green():
    log = run_leads_selftest()
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

    c1 = _card("c1", n=60, sources=4, article_ids=[1, 2, 3])
    walk(is_major(c1))
    walk(cluster_by_article_ids([c1], threshold=0.5))
    walk(card_deltas([c1], [c1]))
    walk(run_leads_selftest())
