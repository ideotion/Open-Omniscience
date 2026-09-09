"""Declare what you expect BEFORE you look.

The docket recorded the lunar framework as built and fully wired with one piece missing:
"the screen exists, 'declare what you expect before you look' does not." A single test on
one hand-picked series, where the operator reads whichever sign turns up as the thing they
meant, is exactly the degree of freedom the FDR correction handles for the screen and
nothing handled for the single test.

THE LOAD-BEARING PROPERTY, and the one worth writing down: a declaration must not be able
to touch the statistic. `matches_expectation` is a post-hoc LABEL derived from the sign of
an `r` that was computed before the declaration was consulted. If declaring a direction
could move r, p, or n, this would not be pre-registration -- it would be a new way to
p-hack with an honest-sounding name. The first test below is that property, asserted as
byte-equality across every declaration.

The second thing pinned here is that a CONTRADICTED expectation is reported as plainly as
a matched one. Reporting only the matches is the publication bias pre-registration exists
to prevent, so it would be a strange thing to reproduce in the tool that offers it.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.analytics import lunar


def _series() -> dict[str, float]:
    """A dense 90-day daily series with real variation, so the correlator returns a result
    rather than an honest skip."""
    from datetime import date, timedelta

    start = date(2026, 1, 1)
    out: dict[str, float] = {}
    for i in range(90):
        out[(start + timedelta(days=i)).isoformat()] = float(1 + (i % 7) + (i % 3) * 2)
    return out


def test_a_declaration_cannot_move_the_statistic():
    """The whole point. Same series, three declarations, identical r / p / n / window."""
    daily = _series()
    none_ = lunar.correlate_daily_series("t", daily)
    pos = lunar.correlate_daily_series("t", daily, expected_direction="positive")
    neg = lunar.correlate_daily_series("t", daily, expected_direction="negative")
    assert none_ is not None and pos is not None and neg is not None
    for got in (pos, neg):
        assert got.r == none_.r, "declaring a direction must not move r"
        assert got.p_value == none_.p_value, "declaring a direction must not move the p-value"
        assert got.n == none_.n and got.active_days == none_.active_days
        assert got.window == none_.window


def test_the_label_reads_the_sign_and_nothing_else():
    assert lunar._expectation_label(0.42, "positive") is True
    assert lunar._expectation_label(0.42, "negative") is False
    assert lunar._expectation_label(-0.42, "negative") is True
    assert lunar._expectation_label(-0.42, "positive") is False
    assert lunar._expectation_label(0.42, None) is None, "no declaration -> no verdict"


def test_both_outcomes_are_carried_never_only_the_flattering_one():
    """A contradicted expectation must reach the payload exactly like a matched one."""
    daily = _series()
    r = lunar.correlate_daily_series("t", daily, expected_direction="positive")
    assert r is not None
    flipped = "negative" if r.expected_direction == "positive" else "positive"
    other = lunar.correlate_daily_series("t", daily, expected_direction=flipped)
    assert other is not None
    assert r.matches_expectation is not other.matches_expectation, (
        "one of the two declarations must be contradicted -- and be reported as such"
    )
    for got in (r, other):
        d = got.to_dict()
        assert "expected_direction" in d and "matches_expectation" in d


def test_a_typod_declaration_fails_loudly_even_on_an_untestable_series():
    """Validated BEFORE the honest-skip returns: otherwise a garbage declaration on a
    too-short series is swallowed and silently becomes 'nothing was declared'."""
    with pytest.raises(ValueError):
        lunar.correlate_daily_series("t", _series(), expected_direction="sideways")
    with pytest.raises(ValueError):
        lunar.correlate_daily_series("t", {"2026-01-01": 1.0}, expected_direction="sideways")


def test_no_declaration_still_means_no_verdict_not_a_default():
    r = lunar.correlate_daily_series("t", _series())
    assert r is not None
    assert r.expected_direction is None
    assert r.matches_expectation is None, "an undeclared test must not acquire a verdict"


def test_the_note_refuses_to_oversell_what_preregistration_buys():
    note = lunar.PREREGISTRATION_NOTE
    for claim in ("not evidence", "does not change r", "does not rule out"):
        assert claim in note, f"the note must disclaim: {claim}"
    assert "CONTRADICTED expectation is as informative" in note


# ---- the endpoint's refusals ------------------------------------------------------- #


def _endpoint(**kw):
    from src.api.insights import insights_lunar_correlation

    params = {"term": None, "limit": 40, "fdr_q": 0.05, "expected_direction": None, "db": None}
    params.update(kw)
    return insights_lunar_correlation(**params)


def test_a_single_test_without_a_declaration_is_refused():
    """400, not a silent default. The refusal lives in the ENDPOINT and not only in the
    form, for the same reason the OpenTimestamps consent gate does (invariant #14f): a
    caller that never went through the UI gets the same honest answer."""
    with pytest.raises(HTTPException) as exc:
        _endpoint(term="election")
    assert exc.value.status_code == 400
    assert "expected_direction is required" in exc.value.detail
    assert "BEFORE" in exc.value.detail, "the refusal must say what it is asking for"


def test_a_declaration_on_the_exploratory_screen_is_also_refused():
    """The screen tests many series at once, so there is no single hypothesis to declare;
    accepting one would let it look pre-registered when its honesty mechanism is the FDR
    correction instead."""
    with pytest.raises(HTTPException) as exc:
        _endpoint(expected_direction="positive")
    assert exc.value.status_code == 400
    assert "does not apply to the screen" in exc.value.detail


def test_the_declaration_is_part_of_the_cache_key():
    """The cached payload carries matches_expectation, so a result computed under one
    declaration must never be served to a caller who made the other -- that would hand
    back a verdict on a hypothesis they did not make."""
    import inspect

    from src.api import insights

    src = inspect.getsource(insights.insights_lunar_correlation)
    assert 'expected_direction=expected_direction or ""' in src, (
        "the cache key must include the declaration"
    )


# ---- the form makes the requirement structural ------------------------------------- #


def test_the_test_button_is_disabled_until_a_direction_is_declared():
    """A label asking you to declare first is a request; a disabled button is the thing
    that actually happens before you look. The requirement is structural on both sides."""
    from tests.js_source_helper import app_js, assert_present, function_source, read_static

    html = read_static("index.html")
    assert 'id="lunar-direction"' in html
    assert 'id="lunar-test-btn"' in html and "disabled" in html.split('id="lunar-test-btn"')[1][:200]
    assert 'value="positive"' in html and 'value="negative"' in html
    assert 'onchange="lunarSyncDirection()"' in html

    sync = function_source(app_js(), "lunarSyncDirection")
    assert_present(sync, "btn.disabled = !sel.value", why="the button follows the declaration")


def test_the_form_sends_the_declaration_and_reports_either_outcome():
    from tests.js_source_helper import app_js, assert_present, function_source

    fn = function_source(app_js(), "lunarTestTerm")
    assert_present(fn, "expected_direction=", why="the declaration must reach the endpoint")
    assert_present(fn, "matches_expectation", why="the outcome must be rendered")
    assert_present(fn, "CONTRADICTS your declaration.",
                   why="a contradicted expectation must be reported, not hidden")
    assert_present(fn, "MATCHES your declaration.")
    assert_present(fn, "d.preregistration", why="the disclaimer travels with the verdict")


def test_every_new_string_is_keyed_in_all_twelve_locales():
    import json
    import pathlib

    keys = [
        "Declare the direction you expect before running a single test.",
        "You declared:",
        "the measured sign MATCHES your declaration.",
        "the measured sign CONTRADICTS your declaration.",
        "Declare first: what do you expect?",
        "— declare before testing —",
        "positive (more coverage as the moon fills)",
        "negative (less coverage as the moon fills)",
    ]
    for p in sorted(pathlib.Path("src/static/locales").glob("*.json")):
        d = json.loads(p.read_text("utf-8"))
        missing = [k for k in keys if k not in d]
        assert not missing, f"{p.stem} is missing: {missing}"
