"""
Scientific-rigor API (the "honesty gate"): real statistical tests on supplied data.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Exposes the salvaged Pillar-2 statistics so a journalist can check whether a
pattern in their data is actually significant -- every result carries the real
statistic, p-value, sample size, effect size and method (scipy/statsmodels),
never a fabricated number. Requires the [analysis] extra; the router is included
defensively so a core-only install still boots without it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.analysis.confidence_intervals import ConfidenceIntervals
from src.analysis.statistical_tests import StatisticalTests

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

_stats = StatisticalTests()
_ci = ConfidenceIntervals()


class TwoSample(BaseModel):
    sample1: list[float] = Field(..., min_length=2)
    sample2: list[float] = Field(..., min_length=2)
    alternative: str = "two-sided"


class Paired(BaseModel):
    sample1: list[float] = Field(..., min_length=2)
    sample2: list[float] = Field(..., min_length=2)


class XY(BaseModel):
    x: list[float] = Field(..., min_length=3)
    y: list[float] = Field(..., min_length=3)


class Groups(BaseModel):
    groups: list[list[float]] = Field(..., min_length=2)


class MeanCI(BaseModel):
    data: list[float] = Field(..., min_length=2)
    confidence_level: float = Field(0.95, gt=0, lt=1)


def _result(obj) -> dict:
    return obj.to_dict()


@router.post("/t-test/independent")
def t_test_independent(req: TwoSample) -> dict:
    """Two-sample t-test for a difference in means."""
    return _result(_stats.t_test_independent(req.sample1, req.sample2, alternative=req.alternative))


@router.post("/t-test/paired")
def t_test_paired(req: Paired) -> dict:
    """Paired t-test (same subjects, two conditions)."""
    if len(req.sample1) != len(req.sample2):
        raise HTTPException(status_code=400, detail="paired samples must be the same length")
    return _result(_stats.t_test_paired(req.sample1, req.sample2))


@router.post("/correlation/pearson")
def pearson(req: XY) -> dict:
    """Pearson linear correlation (coefficient + real two-sided p-value)."""
    if len(req.x) != len(req.y):
        raise HTTPException(status_code=400, detail="x and y must be the same length")
    return _result(_stats.pearson_correlation(req.x, req.y))


@router.post("/correlation/spearman")
def spearman(req: XY) -> dict:
    """Spearman rank correlation (monotonic, non-parametric)."""
    if len(req.x) != len(req.y):
        raise HTTPException(status_code=400, detail="x and y must be the same length")
    return _result(_stats.spearman_correlation(req.x, req.y))


@router.post("/anova/one-way")
def one_way_anova(req: Groups) -> dict:
    """One-way ANOVA across >= 2 groups."""
    return _result(_stats.one_way_anova(*req.groups))


@router.post("/mann-whitney")
def mann_whitney(req: TwoSample) -> dict:
    """Mann-Whitney U (non-parametric two-sample)."""
    return _result(_stats.mann_whitney_u(req.sample1, req.sample2, alternative=req.alternative))


@router.post("/confidence-interval/mean")
def mean_confidence_interval(req: MeanCI) -> dict:
    """Confidence interval for a population mean (t-distribution)."""
    return _result(_ci.mean_ci(req.data, confidence_level=req.confidence_level))
