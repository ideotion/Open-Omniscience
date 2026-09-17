"""Q502 — stacked per language with a legend, and Q417's per-language hover.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The stack's arithmetic and its four refusals are driven as real code in
``tests/stacked_series_node_test.js``. What is pinned here is the wiring and the
honesty around it: that the view is offered only when there is something to stack, that
the caller may pass ``stacked`` at all (its "an absent bucket is a zero" declaration is
true for a mention count over a complete grid and false for a price), that the overlap is
stated rather than left to a reader adding the bands up, and that a refusal reaches the
surface instead of being swallowed.

Required by ``test_every_node_suite_has_a_driver``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.js_source_helper import function_body, read_static, strip_comments

_ROOT = Path(__file__).resolve().parents[1]


def _analysis() -> str:
    return strip_comments(read_static("app-analysis.js"))


def _markets() -> str:
    return strip_comments(read_static("app-markets.js"))


def test_stacked_series_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "stacked_series_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_term_bars_hover_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "term_bars_hover_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_the_stack_goes_through_the_one_chart_toolkit() -> None:
    """Invariant #16: ONE chart toolkit. A second stacked renderer beside `ooChart`
    would be a second set of axis, zoom, legend and sparsity rules to keep true."""
    body = function_body(_analysis(), "_drawAnTrendByLang")
    assert "ooChart(" in body, "the stacked view draws itself instead of using ooChart"
    assert "stacked: true" in body and "zeroBase: true" in body, (
        "a stack whose axis does not start at zero states that the parts sum to "
        "something the axis never shows"
    )
    assert "canvas" not in body and "getContext" not in body, (
        "the stacked view reaches for a canvas of its own"
    )


def test_the_view_is_offered_only_when_there_is_something_to_stack() -> None:
    """A one-band stack is an area chart wearing a stack's clothes."""
    body = function_body(_analysis(), "drawAnTrend")
    assert "langKeys.length > 1" in body, (
        "the By-language view is offered for a single language too"
    )
    assert 'seg("bylang"' in body and "byLangOffered ?" in body, (
        "the third mode button is drawn unconditionally"
    )


def test_the_overlap_is_stated_beside_the_stack_not_left_to_the_reader() -> None:
    """The bands are mention counts per language and they OVERLAP.

    An article carrying two languages' forms is counted in both, so the stack's height
    is not the article total printed beside it. A stack asserts part-to-whole; when the
    parts do not sum to the whole, saying so is what keeps the picture from making a
    claim the data cannot support.
    """
    body = function_body(_analysis(), "_drawAnTrendByLang")
    assert "card-caveat" in body, "the caveat is not rendered as a caveat"
    assert "overlap" in body, "the overlap is not named"
    assert "{n} articles in total, counted once each" in body, (
        "the distinct article total is not printed beside the stack, so the only number "
        "on screen is the sum of overlapping parts"
    )


def test_a_sparse_stack_is_drawn_as_columns_not_as_a_ramp() -> None:
    """Invariant #16's sparse rule applies to a stack too, and it is the common case.

    A band is a POLYGON between measured points, so on a young corpus two samples become
    a wedge sweeping across a week — a trend the corpus never measured, which is exactly
    what *"NEVER interpolation faking a curve through 3 points"* forbids. Found by
    looking at the rendered chart, not by reading the code: six bands ramping diagonally
    across seven days from one or two real points each.

    The threshold is the SHARED `_SPARSE_BAR_MAX`, not a second number that could drift
    from the one the rest of the component uses.
    """
    chart = function_body(_markets(), "ooChart")
    assert "stk.times.length < _SPARSE_BAR_MAX" in chart, (
        "the stack has its own sparsity threshold, or none at all"
    )
    # A zero-height segment is not painted: an empty rectangle at a timestamp a language
    # was never seen in reads as a measured zero sitting inside the column.
    assert "if (p.hi === p.lo) continue;" in chart, (
        "a band with nothing to contribute is still drawn at that timestamp"
    )


def test_a_refusal_reaches_the_surface() -> None:
    """Without this the reader sees ordinary lines under a control labelled
    "By language" and has no way to learn the stack was declined, or why."""
    markets = _markets()
    chart = function_body(markets, "ooChart")
    assert "el.dataset.stackRefusal" in chart, (
        "the refusal is not published on the host, so no caller can report it"
    )
    body = function_body(_analysis(), "_drawAnTrendByLang")
    assert "dataset.stackRefusal" in body, "the caller never reads the refusal"
    for reason in ("gap:", "indexed:", "log:", '"one-series":', "empty:"):
        assert reason in body, f"the refusal {reason!r} has no sentence of its own"


def test_the_hover_reports_the_part_and_labels_the_whole() -> None:
    """In a stack the reader points at a cumulative HEIGHT.

    Reporting that number under the series' own label is the easiest way for a stack to
    misattribute a part, so the band's own value comes first and the running total is
    labelled separately.
    """
    chart = function_body(_markets(), "ooChart")
    assert "running total {n}" in chart, "the cumulative height is not labelled"
    assert "not reported in this bucket" in chart, (
        "a densified zero is presented as a measurement"
    )
    # The series' OWN value is still what the label refers to.
    assert "${b.s.label}: ${fmtV(b.p.v)}" in chart, (
        "the readout no longer names the series' own value first"
    )
    # ...and it is the band the reader is POINTING AT. The hit test was time-only, and
    # every band shares the timestamp grid, so it tied on every point and answered with
    # whichever series iterated first -- the bottom band, wherever the pointer was. The
    # two-dimensional pick is driven in the node suite; what is pinned here is that
    # `nearest` goes through it rather than keeping a second rule of its own.
    nearest = function_body(_markets(), "nearest")
    assert "_stackPick(" in nearest, (
        "the hover picks a band by time alone, so a stack reports its bottom band "
        "wherever the reader points"
    )
    assert "_lastYof" in nearest, "the pick is handed no y-projection, so it cannot separate bands"
    # The PIN is the same question one interaction later: `pinned.v` is the series' own
    # value, so pinning by value alone circles a point near the baseline while the reader
    # clicked halfway up the chart. A wiring guard only -- the mark's position is canvas
    # drawing, and the Chromium walk exercises the stack without clicking it.
    draw = function_body(_markets(), "draw")
    assert "pinBand" in draw and "Yof(vt(pinAt.hi))" in draw, (
        "the pinned mark is placed by the series' own value, so on a stack it lands "
        "somewhere the reader did not click"
    )


def test_the_stack_builder_is_pure_and_refuses_rather_than_throws() -> None:
    """A throw inside `draw()` blanks the chart; a refusal lets it degrade to lines."""
    body = function_body(_markets(), "_stackSeries")
    assert "throw" not in body, "the stack builder throws instead of refusing"
    assert "ctx" not in body and "canvas" not in body, (
        "the stack builder touches the canvas, so its arithmetic cannot be driven "
        "without one"
    )
    for rule in ('refusal: "gap"', 'refusal: "indexed"', 'refusal: "log"',
                 'refusal: "one-series"'):
        assert rule in body, f"missing refusal: {rule}"
    # The hit test is pure for the same reason: which band the reader is pointing at is
    # the difference between naming a part and naming the wrong one, and a decision that
    # needs a canvas to run is a decision no test drives.
    pick = function_body(_markets(), "_stackPick")
    assert "ctx" not in pick and "getBoundingClientRect" not in pick, (
        "the hit test reaches for the canvas instead of taking the projection it needs"
    )
    assert "yOf" in pick, "the hit test builds its own y-projection rather than being handed one"


def test_every_string_the_stacked_view_renders_is_keyed_in_all_twelve_locales() -> None:
    body = function_body(_analysis(), "_drawAnTrendByLang")
    keys = [
        "By language",
        "mentions",
        "Bands are mention counts per language and they overlap: an article carrying "
        "two languages' forms of the concept is counted in both, so the stack's height "
        "is not the article total beside it.",
        "These series could not be stacked, so they are drawn as lines.",
        "One of these series has a published gap, and a gap is not a zero.",
        "Indexed values cannot be added, so they are not stacked.",
        "Heights on a logarithmic axis do not add, so they are not stacked.",
        "Only one language is present, so there is nothing to stack.",
        "No points in this window.",
    ]
    rendered = body + function_body(_analysis(), "drawAnTrend")
    for key in keys:
        assert key in rendered, f"{key!r} is not rendered"
    # The chart chrome's own two frames live in the toolkit, not here.
    chart = function_body(_markets(), "ooChart")
    chart_keys = ["running total {n}", "not reported in this bucket"]
    for key in chart_keys:
        assert key in chart, f"{key!r} is not rendered"
    locales = _ROOT / "src/static/locales"
    files = sorted(locales.glob("*.json"))
    assert len(files) == 12
    for path in files:
        table = json.loads(path.read_text(encoding="utf-8"))
        for key in keys + chart_keys:
            assert key in table, f"{path.name} has no entry for {key[:60]!r}"


def _corpus() -> str:
    return strip_comments(read_static("app-corpus.js"))


def test_the_breakdown_is_one_sentence_with_two_callers() -> None:
    """Q417's hover reaches two surfaces; a second copy is how they come to disagree.

    The composition was written inline inside ``kwHoverText`` -- the keyword-LABEL path --
    and the ruling names the AGGREGATES, which ``termBarsHtml`` draws. Extending it by
    pasting the loop would have left two orderings, two zero-rules and two caveats to keep
    in step, and the one that drifts is the one nobody is looking at.
    """
    corpus = _corpus()
    assert "function kwLangBreakdownText(" in corpus
    for caller in ("kwHoverText", "termBarsHtml"):
        body = function_body(corpus, caller)
        assert "kwLangBreakdownText(" in body, f"{caller} does not go through the helper"
        assert "language_breakdown" not in body, (
            f"{caller} still reads row.language_breakdown itself, so there are two "
            "implementations of one sentence"
        )


def test_the_breakdown_survives_the_handler_that_overwrites_the_title() -> None:
    """The aggregate rows carry ``data-kwstat``, and that handler REPLACES the title.

    ``ooKwStatInit.applyTo`` writes the composed keyword-stats line into both
    ``dataset.ooTip`` and the ``title``, so a fact the renderer put in the title is true
    in the DOM at render time and destroyed by the first hover, forever. The Chromium walk
    read the bubble back and found the stats line standing where the breakdown should
    have been.

    ``data-oo-tip-extra`` is the channel that handler APPENDS. Pinned in both halves,
    because either alone is silent: an attribute nobody reads, or a reader with nothing
    to read.
    """
    boot = strip_comments(read_static("app-boot.js"))
    apply_to = function_body(boot, "applyTo")
    assert "ooTipExtra" in apply_to, (
        "the stats handler overwrites the title with no way for a row to keep a fact of "
        "its own"
    )
    assert "el.dataset.ooTip = full" in apply_to and "full" in apply_to, (
        "the addendum is read and then not used"
    )
    bars = function_body(_corpus(), "termBarsHtml")
    assert "data-oo-tip-extra=" in bars, "no row ever sets the attribute"
    assert "kwLangBreakdownText(" in bars


def test_the_aggregate_hover_is_translatable_in_all_twelve_locales() -> None:
    """The row's own hover was a bare English literal on every locale until now.

    It is asserted here rather than left to the i18n ratchet because the ratchet only
    counts: it would stay green with this key added and the CALL left unwrapped, or with
    the call wrapped and eleven files short.
    """
    body = function_body(_corpus(), "termBarsHtml")
    key = "open in analysis (trend + worldwide spread)"
    assert f'T("{key}")' in body, "the row hover is still a bare English literal"
    files = sorted((_ROOT / "src/static/locales").glob("*.json"))
    assert len(files) == 12
    for path in files:
        table = json.loads(path.read_text(encoding="utf-8"))
        assert key in table, f"{path.name} has no entry for the aggregate row hover"
