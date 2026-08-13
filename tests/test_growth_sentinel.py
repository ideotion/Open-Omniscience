"""The growth sentinel: the payload publishes the flag, and every render site reads it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``queries._growth_of`` substitutes the recent COUNT into ``growth`` when the prior rate
scaled to the window comes to less than one mention -- a documented substitution with
nothing to divide by. Told apart from a real ratio it is honest; conflated it is a
fabricated magnitude, and a field bulletin printed 5,701 mentions against a prior of 4 as
"x5701.0" on 19 of its 20 rows.

TWO layers, and the split matters because a fix to either alone is worse than useless:

* the PRODUCERS must publish ``growth_is_ratio``. Two of the three did not, so a renderer
  reading the flag would have seen ``undefined`` on every row -- and a renderer that reads
  a missing field as "not a ratio" states a sentinel that was never established, which is
  the mirror defect. Those are the tests here.
* the SIX render sites must read it. Those are driven as real code in
  ``tests/growth_sentinel_node_test.js``; only the WIRING (which argument each call site
  passes) is asserted on source, below, because that is a claim about the call and not
  about behaviour reachable from the extracted function.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from tests.js_source_helper import function_body, read_static, strip_comments

_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- producers


def test_growth_of_reports_the_sentinel_as_such() -> None:
    """The one implementation of the rule, and the boundary it turns on."""
    from src.analytics.queries import _growth_of

    # A real ratio: 18 mentions against an expectation of 5.
    assert _growth_of(18, 5.0) == (3.6, True)
    # The field case: the count is substituted and flagged as NOT a ratio.
    assert _growth_of(5701, 0.93) == (5701.0, False)
    # The boundary is on expected, at exactly 1.
    assert _growth_of(3, 1.0) == (3.0, True)
    assert _growth_of(3, 0.999) == (3.0, False)


def test_keyword_stats_publishes_the_flag_it_computes() -> None:
    """It computed ``_is_ratio`` and dropped it, while a comment claimed otherwise.

    The hover was the one consumer and had nothing to read, so it printed the sentinel as
    ``Nx``. ``_is_ratio`` matches ruff's dummy-variable pattern, so no unused-local rule
    could have caught it -- which is why this asserts the PAYLOAD rather than the source.
    """
    src = (_ROOT / "src" / "analytics" / "queries.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "keyword_stats"
    )
    # Every dict literal in the function that carries "growth" must carry the flag too --
    # there are two (the empty trend and the real one) and both were missing it.
    blocks = [
        d for d in ast.walk(fn)
        if isinstance(d, ast.Dict)
        and any(isinstance(k, ast.Constant) and k.value == "growth" for k in d.keys)
    ]
    assert len(blocks) == 2, f"expected the empty and computed trend blocks, got {len(blocks)}"
    for d in blocks:
        keys = {k.value for k in d.keys if isinstance(k, ast.Constant)}
        assert "growth_is_ratio" in keys, (
            "a payload that carries `growth` must carry the flag that says what it is; "
            f"this one has {sorted(keys)}"
        )


def test_group_rate_shares_the_one_implementation_and_publishes_the_flag() -> None:
    """It inlined the rule a third time, and inlining is what lost the flag.

    Asserted on the RESULT, not on the presence of an import: the property is that the
    payload can be read, and a helper imported but not used would satisfy a source grep.
    """
    from src.analytics import supergroup_stats

    calls: list[tuple] = []

    def fake_sum(_db, _ids, lo, hi):  # noqa: ANN001
        calls.append((lo, hi))
        return 5701 if len(calls) == 1 else 4

    orig = supergroup_stats._windowed_sum
    supergroup_stats._windowed_sum = fake_sum  # type: ignore[assignment]
    try:
        out = supergroup_stats.group_rate(None, [1, 2], window_days=7, baseline_days=30)
    finally:
        supergroup_stats._windowed_sum = orig  # type: ignore[assignment]

    # prior 4 over 30 days scaled to 7 is 0.93 -- below one mention, so the sentinel.
    assert out["growth"] == 5701.0
    assert out["growth_is_ratio"] is False, (
        "a group whose baseline is too thin to divide by must say so in the payload"
    )
    assert out["expected"] == 0.93


def test_group_rate_still_reports_a_real_ratio_as_one() -> None:
    """The negative-space twin: the fix must not turn every rate into a sentinel."""
    from src.analytics import supergroup_stats

    seq = iter([180, 300])

    def fake_sum(_db, _ids, lo, hi):  # noqa: ANN001
        return next(seq)

    orig = supergroup_stats._windowed_sum
    supergroup_stats._windowed_sum = fake_sum  # type: ignore[assignment]
    try:
        out = supergroup_stats.group_rate(None, [1], window_days=7, baseline_days=30)
    finally:
        supergroup_stats._windowed_sum = orig  # type: ignore[assignment]

    assert out["growth_is_ratio"] is True
    assert out["growth"] == 2.57  # 180 / ((300/30)*7)


# --------------------------------------------------------------- the card's math rows


def test_the_card_math_row_shows_a_division_that_produces_its_own_result() -> None:
    """The worst of the three, because it shows its work.

    The row branched on ``prior`` being truthy, so a prior of 3 -- a sentinel, since
    (3/30)*7 = 0.7 is under one mention -- printed "Growth = recent rate / earlier rate"
    beside ``(5701 / 7) / (3 / 30) = x5701``. That division is 8144.3. A reader who checked
    the arithmetic would find it wrong, which is worse than showing no arithmetic at all.
    """
    from src.briefing.producers import _growth_math_row

    label, value = _growth_math_row({"recent": 5701, "prior": 3, "growth": 5701.0})
    assert "Growth = recent rate" not in label, label
    assert "×5701" not in value, f"the count must not be dressed as a multiple: {value}"
    assert "5701" in value and "3" in value, value
    assert "under one mention" in value, value

    # And where a division IS claimed, it must be the one that yields the printed result.
    label, value = _growth_math_row({"recent": 180, "prior": 300, "growth": 2.57})
    assert label == "Growth = recent rate ÷ earlier rate"
    assert value == "(180 ÷ 7) ÷ (300 ÷ 30) = ×2.57"
    assert round((180 / 7) / (300 / 30), 2) == 2.57, (
        "the stated division must equal the stated result -- this is the assertion the "
        "old row would have failed"
    )


def test_the_card_math_row_still_distinguishes_new_from_thin() -> None:
    """Negative-space twin: two different absences must not collapse into one sentence."""
    from src.briefing.producers import _growth_math_row

    new_label, new_value = _growth_math_row({"recent": 12, "prior": 0, "growth": 12.0})
    thin_label, thin_value = _growth_math_row({"recent": 12, "prior": 4, "growth": 12.0})
    assert "Brand-new" in new_label
    assert "Brand-new" not in thin_label
    assert new_value != thin_value
    for v in (new_value, thin_value):
        assert "×" not in v, v


# ----------------------------------------------------------------------------- wiring


_SITES = {
    "loadHomeTrends": 1,
    "_renderOverviewTrends": 1,
    "sgCard": 1,
    "loadTrends": 1,
    "loadTrendWindows": 2,
}


def test_every_growth_render_site_routes_through_the_fallback() -> None:
    """No surface may print `growth` without first asking what it is.

    Comment-STRIPPED, because the comments beside each fix necessarily quote the "!N!"
    form they replaced -- the recorded trap where a source guard is satisfied (or here,
    tripped) by the explanation of the rule it guards.
    """
    app = strip_comments(read_static("app.js"))
    for name, expected in _SITES.items():
        body = strip_comments(function_body(app, name))
        if ".growth" not in body:
            raise AssertionError(f"{name} no longer renders growth -- update this guard")
        n = body.count("growthFallback(")
        assert n == expected, (
            f"{name} renders growth at {expected} site(s) but calls growthFallback {n} "
            "time(s); a site that prints the value without asking what it is prints a "
            "count as a multiple"
        )


def test_the_rising_bar_takes_its_length_only_from_a_measured_ratio() -> None:
    """The bar MAGNITUDE, not just its label -- and asserted as the CALL, not as text.

    A 5,701-mention sentinel on the same scale as a x3.6 ratio makes every real ratio
    round to nothing. The node suite proves ``termBarsHtml`` honours a null; this proves
    the call site actually passes one, which no behavioural test of the helper can see.
    """
    app = strip_comments(read_static("app.js"))
    body = function_body(app, "loadTrends")
    at = body.index("termBarsHtml(")
    # The first argument after the terms list is the value accessor.
    call = body[at : body.index("$(\"trd-top\")", at)]
    assert "growthIsRatio(" in call, (
        "trd-rising must gate its bar length on growthIsRatio; passing `t => t.growth` "
        "puts a count on a rate scale, which is the defect this fix is about"
    )
    assert ": null" in call, "a row off the rate scale must be handed null, not 0"


def test_the_shared_reader_mirrors_the_bulletin_renderer() -> None:
    """Both surfaces answer the same question, so they must answer it the same way.

    Pinned because a drift here is invisible: each surface would stay internally
    consistent while disagreeing with the other about what the same row means.
    """
    py = (_ROOT / "src" / "bulletin" / "render.py").read_text(encoding="utf-8")
    js = strip_comments(function_body(read_static("app.js"), "growthIsRatio"))
    # Same three states, same fallback field, same boundary.
    assert "growth_is_ratio" in py and "growth_is_ratio" in js
    assert "expected" in py and "expected" in js
    assert ">= 1" in py and ">= 1" in js
    assert "return null" in js, "the third state must exist on the JS side too"


def test_growth_sentinel_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "growth_sentinel_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout
