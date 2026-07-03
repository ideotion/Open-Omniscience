"""The Benjamini-Hochberg FDR mechanism self-test (the multiple-testing spine).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Proves the self-test itself is correct and NON-VACUOUS: every fixture passes against the
real module, a deliberately-wrong expectation is caught, the signals-layer functions are
the SAME objects as the pure src.stats.fdr computation (reused, never re-implemented), and
the exported log carries no score-shaped field.
"""

from __future__ import annotations

import math

from src.signals.fdr import (
    _case_reject,
    benjamini_hochberg,
    bh_adjusted,
    fdr_selftest,
)


def test_every_fixture_passes():
    log = fdr_selftest()
    assert log["all_passed"] is True, [c for c in log["cases"] if not c["ok"]]
    assert log["n_cases"] == 10
    assert log["n_passed"] == 10 and log["n_failed"] == 0
    assert log["schema"] == "oo-fdr-selftest-1"
    assert log["method"] and log["caveat"]


def test_is_non_vacuous_a_wrong_expectation_is_caught():
    # If the harness merely echoed the module, no expectation could ever fail. Feed a
    # deliberately-wrong expected rejected-set and require the case to report FAIL.
    bad = _case_reject(
        "deliberately wrong",
        [0.005, 0.03, 0.5, 0.9], 0.05,
        expect_rejected=(0, 1, 2, 3),  # the truth is (0,) only
        expect_threshold=0.9,
    )
    assert bad["ok"] is False
    assert "rejected" in bad["detail"]


def test_independent_recompute_of_the_step_up_recovery_fixture():
    # Re-derive the canonical case by hand, independently of the self-test's own expectation,
    # so a green self-test cannot be trusting a wrong constant. p(3),p(4) fail their OWN
    # thresholds yet all of 1..5 are rejected because rank 5 passes.
    p = [0.001, 0.008, 0.039, 0.040, 0.041, 0.9]
    res = benjamini_hochberg(p, q=0.05)
    assert res.rejected == (0, 1, 2, 3, 4)
    assert res.threshold == 0.041
    # adjusted q-values, hand-computed (m/j*p(j) then running-min step-up):
    adj = bh_adjusted(p)
    assert math.isclose(adj[0], 0.006, abs_tol=1e-9)
    assert math.isclose(adj[1], 0.024, abs_tol=1e-9)
    assert all(math.isclose(adj[i], 0.0492, abs_tol=1e-9) for i in (2, 3, 4))
    assert math.isclose(adj[5], 0.9, abs_tol=1e-9)


def test_signals_layer_reuses_the_pure_computation_never_reimplements_it():
    from src.stats.fdr import benjamini_hochberg as pure_bh
    from src.stats.fdr import bh_adjusted as pure_adj

    # Identity, not a copy: one correction, one place (the src.signals thesis).
    assert benjamini_hochberg is pure_bh
    assert bh_adjusted is pure_adj


def _no_score_key(obj) -> bool:
    """Walk the structure and assert no key is score/rank/rating-shaped (the ban is on
    field NAMES, not values — a caveat legitimately says 'never a score')."""
    banned = ("score", "rating", "ranking")
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if any(b in kl for b in banned):
                return False
            if not _no_score_key(v):
                return False
    elif isinstance(obj, (list, tuple)):
        return all(_no_score_key(v) for v in obj)
    return True


def test_log_carries_no_score_shaped_field():
    assert _no_score_key(fdr_selftest())
