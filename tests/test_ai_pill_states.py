"""The top-bar AI pill: green when a backend serves, red + crossed when it does not.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer 2026-08-02: "decrease the size of the top bar's AI button, make it red and
crossed (diagonal) when off, keep green when on."

Two states must be readable at a glance, so EVERY branch that is not a serving backend
carries the off marking -- including the one where the health probe itself failed, where
a neutral pill would read as "fine" on no evidence.
"""


from __future__ import annotations

from pathlib import Path

import pytest
from tests.js_source_helper import function_body

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def js() -> str:
    return (_ROOT / "src" / "static" / "app.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css() -> str:
    return (_ROOT / "src" / "static" / "app.css").read_text(encoding="utf-8")


def _paint_body(js: str) -> str:
    """The loadLlmHealth body only -- a whole-file search would match any other pill."""
    return function_body(js, "loadLlmHealth")


def test_every_non_serving_branch_marks_the_pill_off(js):
    body = _paint_body(js)
    # the three ways the pill can be not-green: hardware-impractical, backend down,
    # and the probe itself failing
    assert body.count('"pill warn ai-off"') == 3, (
        "each non-serving branch must mark the pill off -- including the catch, where a "
        "neutral pill would claim health the probe never established"
    )


def test_the_serving_state_stays_green_and_uncrossed(js):
    body = _paint_body(js)
    green = body.split("if (h.available)", 1)[1].split("} else", 1)[0]
    assert '"pill ok"' in green
    assert "ai-off" not in green, "a serving backend must never be crossed out"


def test_off_is_red_and_carries_a_diagonal_bar(css):
    rule = css.split("#llm.ai-off {", 1)[1].split("}", 1)[0]
    assert "var(--err)" in rule, "off is RED"
    after = css.split("#llm.ai-off::after {", 1)[1].split("}", 1)[0]
    assert "linear-gradient" in after and "to top right" in after, (
        "the diagonal bar is the non-colour signal -- colour must never be the only one"
    )


def test_every_colour_is_theme_derived(css):
    """A hardcoded hue failed 8/17 themes when --caveat was introduced. The pill is
    painted from --err through color-mix, exactly as .pill.err already is."""
    block = css.split("#llm.ai-off {", 1)[1].split("#llm.ai-off::after {", 1)[1].split("}", 1)[0]
    whole = css.split("/* The AI pill (maintainer 2026-08-02)", 1)[1].split("\n    .pill", 1)[0]
    assert "#" not in block, "no hex literals in the bar"
    for token in ("var(--err)", "var(--border)", "var(--panel2)"):
        assert token in whole, f"{token} must come from the theme"


def test_the_pill_is_smaller_but_still_a_FIXED_footprint(css):
    """Invariant #3: top-bar elements keep constant footprints so nothing to their right
    shifts. The label is a constant "AI", so a smaller fixed width is safe -- 96px was
    sized for the old "<N> LLM" text and has been oversized since the count was dropped."""
    rule = css.split("#llm {", 1)[1].split("}", 1)[0]
    assert "min-width:" in rule, "the fixed footprint must survive (invariant #3)"
    px = int(rule.split("min-width:", 1)[1].split("px", 1)[0].strip())
    assert px < 96, "the ask was to make it smaller"
    assert px >= 34, "still wide enough for the label plus the bar, at a constant width"
