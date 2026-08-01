"""
The Bulletin's period arithmetic and hardware gate.

The windows are the whole feature's foundation: get the tiling wrong and
consecutive editions either double-count a day or skip one, silently. These tests
pin the two properties that cannot be inspected by reading output — that the
rising window EQUALS the coverage window, and that consecutive periods partition
time exactly — plus the honesty rails around a baseline the corpus cannot fill.

Pure: no DB, no network, no model.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.bulletin.gate import LAYER_A_REQUIRES_CAPABLE_HARDWARE, bulletin_available
from src.bulletin.period import (
    CADENCES,
    baseline_coverage,
    resolve_period,
    run_bulletin_period_selftest,
    top_share,
)

_ANCHOR = date(2026, 8, 1)


# -- the §5.1 rule ---------------------------------------------------------- #


def test_the_rising_window_equals_the_coverage_window_for_every_cadence():
    """The rule the whole design rests on. A rising window narrower than the
    coverage window puts a period's biggest story inside its own baseline, so it
    reads as falling in the edition covering it."""
    for cadence, (coverage, _baseline) in CADENCES.items():
        p = resolve_period(cadence, end=_ANCHOR)
        assert p.days == coverage, cadence
        # trending() is handed exactly these two, so equality here IS the rule.
        assert (p.end - p.start).days == p.days


def test_the_baseline_abuts_the_coverage_window_without_sharing_a_day():
    p = resolve_period("weekly", end=_ANCHOR)
    assert p.baseline_start + timedelta(days=p.baseline_days) == p.start
    assert not p.contains(p.baseline_start)


# -- half-open tiling ------------------------------------------------------- #


def test_consecutive_periods_tile_with_no_gap_and_no_overlap():
    p = resolve_period("weekly", end=_ANCHOR)
    prev = p.preceding()
    assert prev.end == p.start
    covered = set()
    for period in (prev, p):
        d = period.start
        while d < period.end:
            assert d not in covered, f"{d} counted twice"
            covered.add(d)
            d += timedelta(days=1)
    assert len(covered) == p.days * 2


def test_the_end_day_belongs_to_the_next_period_only():
    p = resolve_period("daily", end=_ANCHOR)
    assert p.contains(p.start)
    assert not p.contains(p.end)
    assert p.last_day == p.end - timedelta(days=1)
    assert p.to_dict()["end_is_exclusive"] is True


def test_the_default_period_is_closed_and_excludes_today():
    """Today is a partial bucket — an edition built over it is not reproducible
    tomorrow, and understates its own last day."""
    p = resolve_period("weekly")
    assert p.end == date.today()
    assert not p.contains(date.today())
    assert p.last_day == date.today() - timedelta(days=1)


# -- the API is shaped so a bad window is unrepresentable -------------------- #


def test_no_start_end_pair_is_accepted():
    """A start/end pair could disagree with the width — which is exactly the
    defect fixed in trending() on 2026-07-31 (a window one day wider than its own
    rate normalisation)."""
    with pytest.raises(TypeError):
        resolve_period("weekly", start=date(2026, 7, 1), end=_ANCHOR)  # type: ignore[call-arg]


def test_hourly_is_refused_rather_than_silently_rounded():
    """The mention clock is a DATE and the time is destroyed at write, so there is
    no sub-day keyword signal to round to."""
    with pytest.raises(ValueError, match="cadence"):
        resolve_period("hourly", end=_ANCHOR)


def test_a_sub_day_coverage_window_is_refused():
    with pytest.raises(ValueError, match="at least 1 day"):
        resolve_period("weekly", end=_ANCHOR, coverage_days=0)


def test_operator_overrides_are_honoured_and_keep_the_cadence_name():
    p = resolve_period("weekly", end=_ANCHOR, coverage_days=10, baseline_days=40)
    assert (p.days, p.baseline_days) == (10, 40)
    assert p.cadence == "weekly", "the edition still reports how it was generated"


# -- the long-cadence honesty rail ------------------------------------------ #


def test_a_corpus_younger_than_the_baseline_reports_the_shortfall():
    """expected divides by the NOMINAL baseline days regardless of corpus age, so
    a young corpus inflates every growth ratio. The rail states it."""
    p = resolve_period("yearly", end=_ANCHOR)
    cov = baseline_coverage(p, date(2026, 1, 1))
    assert cov["complete"] is False
    assert cov["actual_days"] < cov["nominal_days"]
    assert "inflated" in cov["note"]


def test_a_corpus_older_than_the_baseline_reports_complete():
    p = resolve_period("yearly", end=_ANCHOR)
    cov = baseline_coverage(p, date(2001, 1, 1))
    assert cov["complete"] is True
    assert cov["actual_days"] == cov["nominal_days"]


def test_an_unreadable_date_range_is_unknown_never_complete():
    """"Could not read" and "covers everything" must not render the same."""
    cov = baseline_coverage(resolve_period("weekly", end=_ANCHOR), None)
    assert cov["complete"] is None
    assert cov["actual_days"] is None
    assert "not assumed complete" in cov["note"]


# -- shares ----------------------------------------------------------------- #


def test_a_share_of_nothing_is_undefined_not_zero():
    assert top_share([]) is None
    assert top_share([0, 0]) is None


def test_top_share_is_exact():
    assert top_share([50, 30, 10, 10], 3) == 0.9
    assert top_share([1, 1], 3) == 1.0


# -- the hardware gate ------------------------------------------------------ #


def test_the_gate_reads_inference_capability_not_detect_gpu():
    """Two predicates on purpose: detect_gpu() answers "can vLLM run HERE", and
    vLLM ships manylinux wheels only. Collapsing them routes every Mac to a
    backend that cannot run there."""
    src = (__import__("pathlib").Path("src/bulletin/gate.py")).read_text(encoding="utf-8")
    body = src.split('def bulletin_available', 1)[1]
    assert "inference_capability" in body
    assert "detect_gpu" not in body


def test_an_incapable_machine_is_refused_with_the_ruled_reason():
    out = bulletin_available(
        capability={"practical": False, "reason": "no accelerator detected", "warnings": []}
    )
    assert out["available"] is False
    assert "no accelerator" in out["reason"]


def test_a_capable_machine_is_available_and_carries_its_warnings_verbatim():
    out = bulletin_available(
        capability={"practical": True, "reason": "NVIDIA", "warnings": ["low VRAM"]}
    )
    assert out["available"] is True
    assert out["warnings"] == ["low VRAM"]


def test_the_override_is_surfaced_not_silent():
    out = bulletin_available(
        capability={"practical": True, "reason": "override", "overridden": True, "warnings": []}
    )
    assert out["available"] is True and out["overridden"] is True


def test_a_probe_that_raises_degrades_instead_of_taking_the_surface_down(monkeypatch):
    monkeypatch.setattr(
        "src.llm.backend.inference_capability",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("probe exploded")),
    )
    out = bulletin_available()
    assert out["available"] is False
    assert "probe exploded" in out["reason"], "a probe failure must never read as a pass"


def test_open_question_four_is_one_constant():
    """The ruling gates the whole feature; the recorded consequence is that a
    GPU-less operator loses the model-free half too. Making that reversible in one
    place is the design record's own instruction."""
    assert LAYER_A_REQUIRES_CAPABLE_HARDWARE is True
    src = (__import__("pathlib").Path("src/bulletin/gate.py")).read_text(encoding="utf-8")
    assert src.count("LAYER_A_REQUIRES_CAPABLE_HARDWARE") == 2, (
        "the definition and exactly one read — a second read is a second place to flip"
    )


# -- loop registration ------------------------------------------------------ #


def test_selftest_passes_and_the_loop_can_read_its_verdict():
    out = run_bulletin_period_selftest()
    assert out["failed_count"] == 0, [c for c in out["cases"] if not c["passed"]]
    assert isinstance(out["passed"], bool)

    from src.monitoring.recursive_loop import LOOP_SELFTESTS, _selftest_passed

    assert _selftest_passed(out) is True
    assert any(
        mod == "src.bulletin.period" and fn == "run_bulletin_period_selftest"
        for _, mod, fn in LOOP_SELFTESTS
    )
