"""Poll transparency — a disclosure CHECKLIST (Tier 2), never a score.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pins the binding rules: presence-only (never judges a disclosed value), non-disclosure
outranks disclosed-imperfection (transparency is never penalized), never a composite score,
never a "useless" label, the verbatim question echo, and the honest disclosure floor.
"""

from __future__ import annotations

from src.analytics.poll_transparency import (
    CORE_ITEMS,
    SUPPLEMENTARY_ITEMS,
    PollTransparency,
    assess_poll_transparency,
)


def _keys(items):
    return {k for k, _, _ in items}


def test_fully_disclosed_meets_the_floor():
    fields = {
        "pollster": "Acme Research", "sponsor": "The Daily", "fielding_dates": "2026-06-01/03",
        "sample_size": 1200, "population": "adults 18+", "question_wording": "Do you approve?",
        "sampling_method": "probability", "margin_of_error": "±3%", "mode": "online",
        "weighting": "age/sex/region", "response_rate": "12%",
    }
    r = assess_poll_transparency(fields)
    assert r.meets_floor is True
    assert r.core_gaps == ()
    assert set(r.disclosed) >= _keys(CORE_ITEMS)
    assert r.n_disclosed == r.n_items == len(CORE_ITEMS) + len(SUPPLEMENTARY_ITEMS)
    assert r.question == "Do you approve?"


def test_missing_core_items_are_flagged_but_never_useless():
    # Only the question + a big n disclosed; everything else absent.
    r = assess_poll_transparency({"question_wording": "Who will you vote for?", "sample_size": 5000})
    assert r.meets_floor is False
    assert "pollster" in r.core_gaps and "population" in r.core_gaps
    assert "fielding_dates" in r.core_gaps
    # The verbatim question is still echoed (the strongest, checkable, language-agnostic fact).
    assert r.question == "Who will you vote for?"
    # It never LABELS the poll: no top-level grade/verdict/score KEY, and every checklist
    # item carries only a presence flag + a factual "not disclosed" note (never a quality
    # judgment). The caveat/method text may *mention* the word 'useless' precisely to state
    # the policy that we never apply it -- so we assert on structure, not substrings.
    out = r.to_dict()
    assert set(out) & {"grade", "score", "verdict", "rating", "rank"} == set()
    for c in out["checklist"]:
        assert set(c) == {"key", "label", "why", "tier", "disclosed", "note"}
        assert c["note"] in (None, "not disclosed")


def test_disclosure_not_quality_a_tiny_n_is_still_disclosed():
    # A disclosed n=2 (imperfect) is treated EXACTLY like a huge n -> both 'disclosed'.
    tiny = assess_poll_transparency({"sample_size": 2})
    big = assess_poll_transparency({"sample_size": 50000})
    assert "sample_size" in tiny.disclosed and "sample_size" in big.disclosed
    # No note or flag penalizes the small n (transparency is never penalized on value).
    tiny_item = next(c for c in tiny.checklist if c["key"] == "sample_size")
    assert tiny_item["disclosed"] is True and tiny_item["note"] is None


def test_margin_without_n_is_a_factual_disclosure_gap_not_a_judgment():
    r = assess_poll_transparency({"margin_of_error": "±2%"})  # margin but no n
    joined = " ".join(r.notes).lower()
    assert "margin" in joined and "cannot be independently checked" in joined
    # It is a DISCLOSURE gap note, not a claim the margin is wrong.
    assert "wrong" not in joined and "false" not in joined


def test_empty_input_is_honest_all_undisclosed():
    r = assess_poll_transparency(None)
    assert r.n_disclosed == 0
    assert set(r.undisclosed) == _keys(CORE_ITEMS) | _keys(SUPPLEMENTARY_ITEMS)
    assert r.meets_floor is False and r.question is None


def test_no_score_fields_on_the_dataclass():
    # The dataclass is guarded by assert_no_score_fields at import; assert no score-shaped
    # key surfaces in the serialized output either.
    from src.briefing.card import assert_no_score_fields

    assert_no_score_fields(PollTransparency)  # would raise if a score field were added
    out = assess_poll_transparency({"pollster": "X"}).to_dict()
    for k in out:
        assert not any(bad in k.lower() for bad in ("score", "rating", "rank", "grade", "verdict"))


def test_present_helper_semantics():
    from src.analytics.poll_transparency import _present

    assert _present(0) is True            # a disclosed 0 IS a disclosure
    assert _present("") is False          # blank string = not disclosed
    assert _present("  ") is False
    assert _present(None) is False
    assert _present(False) is False       # explicit False = not disclosed / N/A
    assert _present([]) is False and _present(["a"]) is True
