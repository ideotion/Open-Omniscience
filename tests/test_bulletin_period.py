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


def test_an_incapable_machine_still_gets_the_document_and_is_refused_narration():
    """RULED 2026-09-07 (open question 4): the gate covers the narration layer, not
    the document. The two verdicts must disagree here — that disagreement is the
    whole ruling, and one key could not have carried it."""
    out = bulletin_available(
        capability={"practical": False, "reason": "no accelerator detected", "warnings": []}
    )
    assert out["available"] is True, "the deterministic document needs no model"
    assert out["narration_available"] is False
    assert "no accelerator" in out["narration_reason"]
    assert "produced on this machine" in out["reason"]


def test_a_capable_machine_is_available_and_carries_its_warnings_verbatim():
    out = bulletin_available(
        capability={"practical": True, "reason": "NVIDIA", "warnings": ["low VRAM"]}
    )
    assert out["available"] is True
    assert out["narration_available"] is True
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
    assert out["narration_available"] is False
    assert "probe exploded" in out["reason"], "a probe failure must never read as a pass"
    assert "probe exploded" in out["narration_reason"]


def test_an_unreadable_probe_reports_unmeasured_never_below_the_bar(monkeypatch):
    """An unreadable hardware fact is *unmeasured*, never *below* (§3 invariant 3).
    The caveat on that path must therefore make no claim about the gate at all —
    including no claim that the document was withheld, which it was not measured
    to have been."""
    monkeypatch.setattr(
        "src.llm.backend.inference_capability",
        lambda *a, **k: (_ for _ in ()).throw(OSError("nvidia-smi missing")),
    )
    out = bulletin_available()
    assert "could not be read" in out["caveat"]
    assert "unmeasured" in out["caveat"]
    assert "gated" not in out["caveat"], (
        "an unmeasured machine must not be told it fell short of a bar nobody measured"
    )


def test_open_question_four_is_one_constant():
    """RULED False 2026-09-07. The read count is the load-bearing half: a second
    read is a second place to flip, and the whole point of answering this question
    in one line is that there is only ever one line."""
    assert LAYER_A_REQUIRES_CAPABLE_HARDWARE is False
    src = (__import__("pathlib").Path("src/bulletin/gate.py")).read_text(encoding="utf-8")
    assert src.count("LAYER_A_REQUIRES_CAPABLE_HARDWARE") == 2, (
        "the definition and exactly one read — a second read is a second place to flip"
    )


# --------------------------------------------------------------------------- #
#  THE DISCLOSURE MUST BE RIGHT IN BOTH STATES OF THE CONSTANT
#
#  Answering open question 4 is a one-line change either way; the work was making the
#  wording true on both sides of it. A caveat that is only correct in the state that
#  happens to ship turns the one-line flip into a lie, and nothing about flipping a
#  boolean would tell you so. These drive the flipped state directly.
# --------------------------------------------------------------------------- #
_INCAPABLE = {"practical": False, "reason": "no accelerator detected", "warnings": []}


def test_flipping_the_constant_back_gates_the_document_and_says_so(monkeypatch):
    monkeypatch.setattr("src.bulletin.gate.LAYER_A_REQUIRES_CAPABLE_HARDWARE", True)
    out = bulletin_available(capability=dict(_INCAPABLE))
    assert out["available"] is False, "the flipped state must really gate the document"
    assert "gated as a whole" in out["caveat"]
    assert "withheld only because" in out["caveat"]


def test_the_ruled_state_never_claims_the_document_was_withheld(monkeypatch):
    """The twin, and the one that catches a stale disclosure: on the shipped setting
    the document is NOT withheld, so a caveat still saying it is would be a refusal
    the operator never received."""
    monkeypatch.setattr("src.bulletin.gate.LAYER_A_REQUIRES_CAPABLE_HARDWARE", False)
    out = bulletin_available(capability=dict(_INCAPABLE))
    assert out["available"] is True
    assert "withheld only because" not in out["caveat"]
    assert "needs no model" in out["caveat"]


def test_the_narration_verdict_is_a_hardware_fact_and_ignores_the_constant(monkeypatch):
    """Flipping open question 4 must change what the DOCUMENT does and nothing about
    what is true of the machine. If the narration verdict moved with the constant,
    the constant would be gating two things and the ruling would only have answered
    one of them."""
    seen = []
    for flag in (True, False):
        monkeypatch.setattr("src.bulletin.gate.LAYER_A_REQUIRES_CAPABLE_HARDWARE", flag)
        seen.append(bulletin_available(capability=dict(_INCAPABLE))["narration_available"])
    assert seen == [False, False]

    seen = []
    for flag in (True, False):
        monkeypatch.setattr("src.bulletin.gate.LAYER_A_REQUIRES_CAPABLE_HARDWARE", flag)
        cap = {"practical": True, "reason": "NVIDIA", "warnings": []}
        seen.append(bulletin_available(capability=cap)["narration_available"])
    assert seen == [True, True]


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
