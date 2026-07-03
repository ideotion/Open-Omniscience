"""Signals-layer facade for Benjamini-Hochberg FDR + a mechanism self-test.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The pure Benjamini-Hochberg computation already lives in :mod:`src.stats.fdr` (the
textbook step-up procedure, no dependency, no I/O) and is reused by every screening
analytic — the lunar screen, the flood/bury manipulation cards. This module is the
``src.signals`` HOME for that spine: it RE-EXPORTS the pure functions (never a second
implementation — one correction, one place, per the ``src.signals`` "reused, never
duplicated" thesis) and adds one thing the pure module deliberately leaves out — a
mechanism SELF-TEST.

WHY A SELF-TEST. FDR correction is the shared spine under the manipulation cards and the
lunar screen: if the step-up were wrong, every screen that reports "survived
multiple-testing correction" would be quietly fabricating. :func:`fdr_selftest` proves
the mechanism on hand-computed fixtures (the canonical step-up recovery, the all-reject
and none-reject boundaries, order-invariance of the returned original indices, the
adjusted-<=-q ⇔ rejected equivalence, the BH-Yekutieli conservatism, and the input
validation) so a regression reddens BOTH the in-app export the operator can share AND
CI — mirroring the keyword / ir-eval self-tests. No DB, no network, no score.
"""

from __future__ import annotations

from src.stats.fdr import (
    FdrError,
    FdrResult,
    benjamini_hochberg,
    bh_adjusted,
)

__all__ = [
    "FdrError",
    "FdrResult",
    "benjamini_hochberg",
    "bh_adjusted",
    "fdr_selftest",
    "run_fdr_selftest",
]

_SCHEMA = "oo-fdr-selftest-1"

_METHOD = (
    "Runs the Benjamini-Hochberg step-up procedure (src.stats.fdr) on hand-computed "
    "fixtures and compares the surviving set (by ORIGINAL index), the BH cutoff, and the "
    "adjusted p-values against values worked out by hand. Proves the correction MECHANISM "
    "is correct — it is NOT a measurement of any corpus. A real screen needs real p-values; "
    "this verifies the spine those screens rely on. No DB, no network, no score."
)
_CAVEAT = (
    "A self-test of the multiple-testing correction, not a finding. Every case is a fixture "
    "with a known answer; all cases passing means the FDR spine behaves correctly, so a "
    "screen that reports 'survived FDR correction' can be trusted to mean it."
)

# Absolute tolerance for the adjusted (q-value) comparisons — the fixtures below are
# worked out to well within this, and the step-up is exact rational arithmetic.
_TOL = 1e-4


def _close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return abs(float(a) - float(b)) <= _TOL


def _adj_close(got: tuple[float, ...], want: tuple[float, ...]) -> bool:
    return len(got) == len(want) and all(_close(g, w) for g, w in zip(got, want, strict=False))


def _case_reject(
    name: str,
    pvalues: list[float],
    q: float,
    *,
    expect_rejected: tuple[int, ...],
    expect_threshold: float | None,
    expect_adjusted: tuple[float, ...] | None = None,
    dependency: str = "independent",
    note: str = "",
) -> dict:
    """One golden case: run BH and compare against a hand-computed expectation."""
    res = benjamini_hochberg(pvalues, q=q, dependency=dependency)
    checks: list[str] = []
    if res.rejected != expect_rejected:
        checks.append(f"rejected {res.rejected} != expected {expect_rejected}")
    if res.n_rejected != len(expect_rejected):
        checks.append(f"n_rejected {res.n_rejected} != {len(expect_rejected)}")
    if not _close(res.threshold, expect_threshold):
        checks.append(f"threshold {res.threshold} != expected {expect_threshold}")
    if expect_adjusted is not None and not _adj_close(res.adjusted, expect_adjusted):
        checks.append(f"adjusted {res.adjusted} != expected {expect_adjusted}")
    # The module's own equivalence claim: rejected iff adjusted <= q.
    equiv = tuple(sorted(i for i in range(res.m) if res.adjusted[i] <= q))
    if equiv != res.rejected:
        checks.append(f"adjusted<=q set {equiv} != rejected {res.rejected}")
    ok = not checks
    return {
        "name": name,
        "ok": ok,
        "note": note,
        "detail": "; ".join(checks) if checks else "matches the hand-computed result",
        "q": q,
        "dependency": dependency,
        "n_rejected": res.n_rejected,
        "threshold": res.threshold,
    }


def _case_raises(name: str, fn, *, note: str = "") -> dict:
    """A validation case: the call must raise FdrError (bad p-value or bad q)."""
    try:
        fn()
    except FdrError:
        return {"name": name, "ok": True, "note": note, "detail": "raised FdrError as required"}
    except Exception as exc:  # noqa: BLE001 - any non-FdrError is a real failure to report
        return {"name": name, "ok": False, "note": note,
                "detail": f"raised {type(exc).__name__}, expected FdrError"}
    return {"name": name, "ok": False, "note": note, "detail": "did not raise; expected FdrError"}


def fdr_selftest() -> dict:
    """Prove the Benjamini-Hochberg mechanism on hand-computed fixtures.

    Returns an exportable log (schema ``oo-fdr-selftest-1``): a summary plus per-case
    pass/fail with detail. Every fixture's expected rejected-set, cutoff, and adjusted
    p-values were worked out by hand from the BH 1995 definitions, so a green run is never
    vacuous. Pure: no DB, no network, no score.
    """
    cases: list[dict] = []

    # 1. A single survivor at the strict end (m=4). Thresholds (k/4)*0.05 are
    #    0.0125/0.025/0.0375/0.05; only p(1)=0.005 clears its own (0.0125).
    cases.append(_case_reject(
        "single-survivor (m=4)",
        [0.005, 0.03, 0.5, 0.9], 0.05,
        expect_rejected=(0,), expect_threshold=0.005,
        expect_adjusted=(0.02, 0.06, 2.0 / 3.0, 0.9),
        note="only the smallest p clears its BH threshold; the rest do not.",
    ))

    # 2. THE canonical step-up recovery (m=6): p(3) and p(4) fail their OWN thresholds,
    #    yet all of 1..5 are rejected because the largest passing rank is k=5. This is the
    #    behaviour a naive per-comparison filter would get wrong.
    cases.append(_case_reject(
        "step-up recovery (m=6)",
        [0.001, 0.008, 0.039, 0.040, 0.041, 0.9], 0.05,
        expect_rejected=(0, 1, 2, 3, 4), expect_threshold=0.041,
        expect_adjusted=(0.006, 0.024, 0.0492, 0.0492, 0.0492, 0.9),
        note="p(3),p(4) fail their own thresholds but survive because rank 5 passes.",
    ))

    # 3. All reject at the boundary (m=5): every ordered p sits exactly on (k/5)*0.05.
    cases.append(_case_reject(
        "all-reject boundary (m=5)",
        [0.01, 0.02, 0.03, 0.04, 0.045], 0.05,
        expect_rejected=(0, 1, 2, 3, 4), expect_threshold=0.045,
        expect_adjusted=(0.045, 0.045, 0.045, 0.045, 0.045),
        note="every p is at its BH cutoff; the step-up pulls all q-values to 0.045.",
    ))

    # 4. None reject (m=3): the smallest p (0.2) exceeds the largest cutoff (0.05).
    cases.append(_case_reject(
        "none-reject (m=3)",
        [0.2, 0.5, 0.9], 0.05,
        expect_rejected=(), expect_threshold=None,
        expect_adjusted=(0.6, 0.75, 0.9),
        note="nothing survives — the common, honest outcome; threshold stays None.",
    ))

    # 5. Empty input: a valid, empty, honest result.
    cases.append(_case_reject(
        "empty input",
        [], 0.05,
        expect_rejected=(), expect_threshold=None, expect_adjusted=(),
        note="no hypotheses -> nothing rejected, no fabricated threshold.",
    ))

    # 6. Order-invariance: the SAME p-values as case 2 in a shuffled order must reject the
    #    same underlying hypotheses, reported by their ORIGINAL input indices.
    #    input = [0.9, 0.001, 0.041, 0.008, 0.040, 0.039] -> only index 0 (0.9) is NOT rejected.
    cases.append(_case_reject(
        "order-invariance (original indices)",
        [0.9, 0.001, 0.041, 0.008, 0.040, 0.039], 0.05,
        expect_rejected=(1, 2, 3, 4, 5), expect_threshold=0.041,
        note="shuffled inputs reject the same hypotheses, keyed by original index.",
    ))

    # 7. BH-Yekutieli conservatism: under arbitrary dependence the same family rejects
    #    FEWER (q scaled by the harmonic number H(5)). Independent rejects all 5; arbitrary
    #    rejects only the smallest.
    yek_pvals = [0.001, 0.01, 0.02, 0.03, 0.04]
    indep = benjamini_hochberg(yek_pvals, q=0.05, dependency="independent")
    cases.append(_case_reject(
        "BH-Yekutieli is more conservative (m=5)",
        yek_pvals, 0.05,
        expect_rejected=(0,), expect_threshold=0.001,
        dependency="arbitrary",
        note=(f"arbitrary-dependence variant rejects 1 where independent rejects "
              f"{indep.n_rejected}; the harmonic-number penalty is applied."),
    ))

    # 8. Input validation: a p-value outside [0,1], a NaN, and a bad q must all raise.
    cases.append(_case_raises(
        "rejects a p-value > 1", lambda: benjamini_hochberg([0.5, 1.5], q=0.05),
        note="a p-value outside [0,1] is a caller bug, not a silent skip.",
    ))
    cases.append(_case_raises(
        "rejects a NaN p-value", lambda: benjamini_hochberg([0.5, float("nan")], q=0.05),
        note="a non-finite p-value must raise, never be treated as significant.",
    ))
    cases.append(_case_raises(
        "rejects q outside (0,1]", lambda: benjamini_hochberg([0.01, 0.2], q=0.0),
        note="the FDR level must be a real probability in (0,1].",
    ))

    n_passed = sum(1 for c in cases if c["ok"])
    return {
        "schema": _SCHEMA,
        "n_cases": len(cases),
        "n_passed": n_passed,
        "n_failed": len(cases) - n_passed,
        "all_passed": n_passed == len(cases),
        "cases": cases,
        "method": _METHOD,
        "caveat": _CAVEAT,
    }


# Alias mirroring the run_*_selftest naming used by the keyword / ir-eval harnesses.
run_fdr_selftest = fdr_selftest
