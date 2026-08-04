"""The source-assertion technique is guarded by one shared, tested slicer.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

161 test files assert against source text. That is a legitimate technique here --
app.js has no module boundaries and much of the UI contract is visible only in
the source -- but it is only as sound as the slice it runs over, and the slice
used to be re-derived per file. This module proves the shared slicer handles the
three failure modes the ledger actually recorded, and ratchets the number of
ad-hoc re-implementations so it can only go down.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.js_source_helper import (
    assert_absent,
    assert_present,
    function_body,
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

#: Local re-implementations of function-body slicing, counted 2026-08-04. The
#: shared helper above is the correct one (promoted from test_bench_roster.py,
#: the only local copy that balanced the parameter list). This number may only go
#: DOWN: migrate a file to tests.js_source_helper and lower it.
_ADHOC_SLICER_BUDGET = 0

_ADHOC = re.compile(
    r"^def (?:_fn|_fn_body|_func_body|_paint_body|_body)\(.*?(?=^\S|\Z)",
    re.MULTILINE | re.DOTALL,
)


#: The mechanics of slicing. A local helper containing any of these is doing the
#: work itself; one that contains none is delegating.
_SLICING_MECHANICS = ("depth", ".index(", ".split(", ".find(", "re.search(")


def _adhoc_sites() -> list[str]:
    """Local helpers that still IMPLEMENT slicing.

    Tested by the PROPERTY (does the body do brace/offset arithmetic?) rather than
    by looking for a call to ``function_body`` -- several files import the shared
    slicer under an alias, and a detector keyed to one spelling would report them
    as re-derivations forever while a genuinely hand-rolled helper that happened to
    call something named function_body would slip past.

    A thin wrapper keeps its local name so call sites are untouched; that is not a
    re-derivation and does not count.
    """
    out = []
    for path in sorted(_TESTS.glob("test_*.py")):
        for m in _ADHOC.finditer(path.read_text(encoding="utf-8")):
            body = m.group(0)
            if any(tok in body for tok in _SLICING_MECHANICS):
                out.append(path.name)
    return out


def test_adhoc_slicers_do_not_multiply():
    sites = _adhoc_sites()
    assert len(sites) <= _ADHOC_SLICER_BUDGET, (
        f"{len(sites)} local source-slicers, budget {_ADHOC_SLICER_BUDGET}. Each "
        f"re-derivation is a chance to reintroduce the default-parameter or "
        f"over-run bug this module documents. Import tests.js_source_helper "
        f"instead: {sorted(set(sites))}"
    )


def test_the_budget_is_not_left_above_the_real_count():
    """A ratchet parked above the truth is not a ratchet -- it silently grants room
    to regrow. If this fails, lower _ADHOC_SLICER_BUDGET to the reported number."""
    sites = _adhoc_sites()
    assert len(sites) == _ADHOC_SLICER_BUDGET, (
        f"lower _ADHOC_SLICER_BUDGET to {len(sites)}"
    )
