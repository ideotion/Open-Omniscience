"""The source-assertion technique is guarded by one shared, tested slicer.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

161 test files assert against source text. That is a legitimate technique here --
app.js has no module boundaries and much of the UI contract is visible only in
the source -- but it is only as sound as the slice it runs over, and the slice
used to be re-derived per file. This module proves the shared slicer handles the
three failure modes the ledger actually recorded, and ratchets the number of
hand-rolled slicing SITES so it can only go down.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.js_source_helper import (
    assert_absent,
    assert_present,
    css_rule,
    function_body,
    python_function_source,
    read_static,
    strip_comments,
)

_TESTS = Path(__file__).resolve().parent


# --- the three recorded failure modes -------------------------------------- #


def test_a_default_parameter_brace_does_not_truncate_the_body():
    """Session D, 2026-08-01: ``function ooChart(el, seriesList, opts = {})``.

    Taking the first ``{`` after the name lands in the default parameter, depth
    goes 1 -> 0 immediately, and the "body" is the signature alone -- so every
    assertion over it passes for free.
    """
    js = "function ooChart(el, seriesList, opts = {}) {\n  const real = 1;\n}\n"
    body = function_body(js, "ooChart")
    assert "const real = 1;" in body, body
    # And against the real file, where this bug actually lived:
    real = function_body(read_static("app.js"), "ooChart")
    assert len(real) > 500, "the live ooChart body must not slice to near-nothing"


def test_an_empty_slice_raises_instead_of_passing_vacuously():
    """The property that makes the rest safe: a slicer that returns '' on failure
    turns every downstream assertion into a no-op."""
    with pytest.raises(AssertionError, match="no declaration"):
        function_body("function other() { return 1; }", "missing")


def test_the_body_does_not_over_run_into_the_next_function():
    """The other half of the mis-slice: 'split on the next declaration' sweeps in
    unrelated code when the delimiter guessed is not the one that follows, so an
    assertion can match something else entirely."""
    js = (
        "function first(a) {\n  const mine = 1;\n}\n"
        "const helper = 2;\n"
        "function second() {\n  const theirs = 3;\n}\n"
    )
    body = function_body(js, "first")
    assert "mine" in body
    assert "theirs" not in body and "helper" not in body


def test_a_must_be_gone_guard_ignores_the_comment_that_explains_the_removal():
    """2026-07-31, re-hit 2026-08-03: three such guards failed against CORRECT
    code, on their own explanations. Rewording the comment is the wrong repair --
    it deletes what a future session reads before deciding the removal was a
    mistake."""
    js = '// we removed ensureOnline here because the write is loopback-only\nfetchIt();\n'
    assert_absent(js, "ensureOnline")  # must not raise
    with pytest.raises(AssertionError):
        assert_absent("ensureOnline();\n", "ensureOnline")


def test_stripping_comments_leaves_urls_inside_string_literals_alone():
    """The reason stripping is whole-line only: `"https://..."` is not a comment,
    and a naive strip-to-end-of-line would corrupt the code being asserted over."""
    js = 'const u = "https://example.test/x"; // a trailing note\n'
    assert 'https://example.test/x' in strip_comments(js)


def test_a_comment_mentioning_a_call_does_not_satisfy_assert_present():
    js = "// this used to call startSweep()\nsomethingElse();\n"
    with pytest.raises(AssertionError):
        assert_present(js, "startSweep()")


# --- the ratchet ------------------------------------------------------------ #

#: Hand-rolled source-slicing sites, counted 2026-08-04. This number may only go
#: DOWN: migrate a slice to tests.js_source_helper and lower it.
#:
#: WHY IT IS NOT ZERO, AND WHY IT WAS. The first version of this ratchet read 0 --
#: not because the tree was clean, but because its detector was a regex anchored to
#: five hardcoded helper NAMES (_fn, _fn_body, _func_body, _paint_body, _body). It
#: could not see a slice written inline (the common case: `html[a:b]`,
#: `src.split("\n    function ")`), nor one in a helper named anything else. So it
#: certified a budget of zero over 276 real sites, and its sibling
#: "the budget is not left above the real count" agreed -- both sides computed from
#: the same blind detector, which makes the pair a tautology rather than a check.
#: That is the exact failure mode this module exists to document, committed into the
#: module documenting it. The detector below tests the PROPERTY instead.
_ADHOC_SLICER_BUDGET = 234

#: A string literal that anchors into SOURCE CODE rather than into data. A
#: `.index`/`.split`/`.find` taking one of these is slicing a program, which is the
#: operation the shared helper exists to get right.
_CODE_ANCHOR = re.compile(r"(?:^|\n)?\s*(?:async\s+)?(?:def |function |const |let |var |class )")

_SLICING_CALLS = ("index", "find", "split", "rindex", "partition")


def _anchor_literal(call: ast.Call) -> bool:
    """Does this call take a code-anchor string? f-strings count -- the common
    parametrised form is ``src.split(f"def {name}(")``, and reading only
    ``ast.Constant`` would miss every one of them."""
    for arg in call.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            if _CODE_ANCHOR.search(arg.value):
                return True
        elif isinstance(arg, ast.JoinedStr):
            for part in arg.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    if _CODE_ANCHOR.search(part.value):
                        return True
    return False


def _adhoc_sites() -> list[tuple[str, int, int]]:
    """Every hand-rolled source-slicing site, wherever it is written.

    HONEST LIMIT: this finds a slice whose anchor is a literal (or an f-string with
    a literal part). A slice whose anchor is built entirely in a variable is not
    detected -- so this is a floor, not a total. It is still the right shape: the
    previous detector's limit was a list of five names, which is a floor of a
    different and much smaller kind, and one that a rename defeats.
    """
    out: list[tuple[str, int, int]] = []
    for path in sorted(_TESTS.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _SLICING_CALLS
                and _anchor_literal(node)
            ):
                out.append((path.name, node.lineno, node.col_offset))
    return out


def test_the_detector_sees_an_inline_slice_not_just_a_named_helper():
    """The mutation check on the ratchet itself: the shapes that were invisible.

    Both of these are how the tree actually writes slices, and neither is inside a
    helper whose name a regex could enumerate."""
    inline = ast.parse('seg = JS[JS.index("function a"): JS.index("function b")]\n')
    fstring = ast.parse('body = src.split(f"def {name}(", 1)[1]\n')
    for tree in (inline, fstring):
        calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in _SLICING_CALLS
            and _anchor_literal(n)
        ]
        assert calls, ast.dump(tree)


def test_adhoc_slicers_do_not_multiply():
    sites = _adhoc_sites()
    assert len(sites) <= _ADHOC_SLICER_BUDGET, (
        f"{len(sites)} hand-rolled source-slicing sites, budget "
        f"{_ADHOC_SLICER_BUDGET}. Each one is a chance to reintroduce the "
        f"default-parameter or over-run bug this module documents. Import "
        f"tests.js_source_helper instead. New since the budget: "
        f"{sorted(set(s for s, _, _ in sites))}"
    )


def test_the_budget_is_not_left_above_the_real_count():
    """A ratchet parked above the truth is not a ratchet -- it silently grants room
    to regrow. If this fails, lower _ADHOC_SLICER_BUDGET to the reported number."""
    sites = _adhoc_sites()
    assert len(sites) == _ADHOC_SLICER_BUDGET, (
        f"lower _ADHOC_SLICER_BUDGET to {len(sites)}"
    )


def test_a_python_slice_is_bounded_by_the_parser_not_a_guessed_delimiter():
    """The Python half of the same failure, from a real case.

    ``main_src.split("def run_deferred_startup", 1)[1].split("\\ndef test_", 1)[0]``
    used a delimiter that does not occur in ``src/api/main.py``, so the slice was the
    whole rest of the module and the guard was satisfied by a DIFFERENT function --
    the one its own docstring said must not satisfy it.
    """
    src = (
        "def wanted():\n    mine = 1\n\n\n"
        "def other():\n    theirs = 2\n"
    )
    body = python_function_source(src, "wanted")
    assert "mine" in body
    assert "theirs" not in body, "the parser bound must not run into the next def"
    with pytest.raises(AssertionError, match="no def of"):
        python_function_source(src, "missing")


def test_a_css_rule_is_brace_matched_not_split_on_the_next_selector():
    """The third language, same failure. Bounding a rule by "the next selector I can
    think of" took 820 lines of app.css for a 20-line block."""
    css = "#a { color: red; }\n.other { color: blue; }\n#b { color: green; }\n"
    assert "red" in css_rule(css, "#a")
    assert "blue" not in css_rule(css, "#a") and "green" not in css_rule(css, "#a")
    with pytest.raises(AssertionError, match="no rule for selector"):
        css_rule(css, "#missing")
