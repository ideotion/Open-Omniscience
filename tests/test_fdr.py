"""Benjamini-Hochberg FDR control (the multiple-testing spine for the screening analytics).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Validated two ways: against hand-computed BH cutoffs on textbook datasets, and against
scipy's independent implementation (scipy.stats.false_discovery_control) where available.
"""

from __future__ import annotations

import math

import pytest

from src.stats.fdr import FdrError, benjamini_hochberg, bh_adjusted


def test_hand_computed_cutoff_small():
    # p(1..8), m=8, q=0.05. BH critical value at k is (k/8)*0.05.
    # p(1)=0.005 <= 0.00625 OK; p(2)=0.011 <= 0.0125 OK; p(3)=0.02 > 0.01875 NOT.
    # Largest k with p(k) <= (k/m)q is k=2 -> reject the two smallest.
    p = [0.005, 0.011, 0.02, 0.04, 0.13, 0.20, 0.30, 0.35]
    r = benjamini_hochberg(p, q=0.05)
    assert r.rejected == (0, 1)
    assert r.n_rejected == 2
    assert r.threshold == 0.011
    assert r.m == 8


def test_hand_computed_cutoff_wikipedia_dataset():
    # The classic 15-hypothesis BH example: hypotheses 1..4 survive at q=0.05.
    p = [0.0001, 0.0004, 0.0019, 0.0095, 0.0201, 0.0278, 0.0298, 0.0344,
         0.0459, 0.3240, 0.4262, 0.5719, 0.6528, 0.7590, 1.000]
    r = benjamini_hochberg(p, q=0.05)
    assert r.rejected == (0, 1, 2, 3)
    assert r.threshold == 0.0095


def test_rejection_set_equals_adjusted_le_q():
    # The two BH characterisations must agree: rejected iff adjusted p-value <= q.
    p = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.6]
    for q in (0.01, 0.05, 0.1, 0.2):
        r = benjamini_hochberg(p, q=q)
        by_adjusted = tuple(i for i in range(len(p)) if r.adjusted[i] <= q)
        assert r.rejected == by_adjusted


def test_adjusted_is_monotone_in_sorted_order():
    p = [0.9, 0.001, 0.5, 0.02, 0.2, 0.008]
    adj = bh_adjusted(p)
    # In ascending-p order the adjusted (q-values) must be non-decreasing (the step-up).
    order = sorted(range(len(p)), key=lambda i: p[i])
    seq = [adj[i] for i in order]
    assert all(seq[i] <= seq[i + 1] + 1e-12 for i in range(len(seq) - 1))
    assert all(0.0 <= a <= 1.0 for a in adj)


def test_none_and_all_rejected():
    # Nothing survives -> empty, honest, no fabricated threshold.
    none = benjamini_hochberg([0.9, 0.8, 0.95], q=0.05)
    assert none.rejected == () and none.threshold is None and none.n_rejected == 0
    # Everything tiny -> all survive.
    allr = benjamini_hochberg([0.0001, 0.0002, 0.0003], q=0.05)
    assert allr.rejected == (0, 1, 2)


def test_empty_input_is_honest():
    r = benjamini_hochberg([], q=0.05)
    assert r.m == 0 and r.rejected == () and r.threshold is None and r.adjusted == ()
    assert bh_adjusted([]) == []


def test_yekutieli_is_more_conservative():
    p = [0.001, 0.008, 0.02, 0.03, 0.05, 0.2, 0.4, 0.6]
    indep = benjamini_hochberg(p, q=0.05, dependency="independent")
    arb = benjamini_hochberg(p, q=0.05, dependency="arbitrary")
    # BH-Yekutieli (arbitrary dependence) never rejects MORE than standard BH.
    assert set(arb.rejected).issubset(set(indep.rejected))
    assert arb.n_rejected <= indep.n_rejected


def test_validation_raises_on_bad_input():
    with pytest.raises(FdrError):
        benjamini_hochberg([0.5, 1.5], q=0.05)  # p > 1
    with pytest.raises(FdrError):
        benjamini_hochberg([-0.1, 0.5], q=0.05)  # p < 0
    with pytest.raises(FdrError):
        benjamini_hochberg([0.5, float("nan")], q=0.05)  # NaN
    with pytest.raises(FdrError):
        benjamini_hochberg([0.5], q=0.0)  # q out of (0, 1]
    with pytest.raises(FdrError):
        benjamini_hochberg([0.5], q=1.5)


def test_matches_scipy_false_discovery_control():
    sp = pytest.importorskip("scipy.stats")
    import random

    rng = random.Random(42)
    for _ in range(20):
        m = rng.randint(1, 40)
        # A mix: some genuinely small (signal) + uniform noise, with ties.
        p = [round(rng.random(), 3) for _ in range(m)]
        mine = bh_adjusted(p)
        theirs = list(sp.false_discovery_control(p, method="bh"))
        assert len(mine) == len(theirs)
        for a, b in zip(mine, theirs, strict=True):
            assert math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9), (p, mine, theirs)
