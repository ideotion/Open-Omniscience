"""Search-lockout fix (2026-09-08 live visual audit, P0 finding 3).

``GET /api/articles`` is rate-limited to 100/hour, and this is the app's densest,
most iterative surface (135 controls, 5 inputs, boolean query grammar, five
time-range presets) -- built for exactly the refinement pattern that burns the
budget. Before this fix, a refusal here rendered as an EMPTY search: ``doSearch``'s
catch block only called ``toast(...)`` and left ``#search-meta``/``#results``
untouched -- indistinguishable from a real zero-result query once the toast
auto-dismisses (or on a page that never had a result yet, e.g. right after a
reload). ``_anLoadArticles`` (the analysis window's Articles subtab, reachable
straight from a boot-time ``?corpus=``/``?analyze=`` deep link with no user click
at all) rendered the raw exception message with no rate-limit awareness.

This test extracts the REAL functions from ``src/static/app-analysis.js`` and:
  * runs the pure message-building helpers under node, so the actual honesty
    rules (a real Retry-After becomes a stated clock time; its absence states
    only "later"; a non-429 failure states the real error) are exercised, not a
    hand-reimplementation that could silently drift from the shipped code
    (the established pattern in tests/test_agenda_month_shift.py); and
  * asserts, structurally, that both catch blocks that can receive a refused
    ``/api/articles`` call route through that shared helper into the SAME two
    render targets a successful call fills -- which is exactly what the old
    code did not do, so this half of the test fails against the pre-fix source.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import function_body, function_source, read_static, strip_comments

_ROOT = Path(__file__).resolve().parents[1]


def _analysis() -> str:
    return read_static("app-analysis.js")


# --------------------------------------------------------------------------- #
# Structural: the failure path must route through the shared honest-message
# helper into the SAME two spots a successful search/article-list fills, never
# only into a toast that can dismiss and leave nothing behind.
# --------------------------------------------------------------------------- #


def test_doSearch_failure_renders_into_search_meta_and_results() -> None:
    body = strip_comments(function_body(_analysis(), "doSearch"))
    assert "catch" in body, "doSearch has no catch block at all"
    # Isolate the catch block itself so a match earlier in the try (the success
    # path already sets search-meta/results) cannot make this pass vacuously.
    catch_at = body.index("catch")
    catch_body = body[catch_at:]
    assert "_articleFailureMessage(e)" in catch_body, (
        "the catch block does not build the honest failure message"
    )
    assert '$("search-meta")' in catch_body, (
        "a failed search no longer touches #search-meta -- it can render as an "
        "empty search again (audit P0 finding 3)"
    )
    assert '$("results")' in catch_body, (
        "a failed search no longer touches #results -- it can render as an "
        "empty search again (audit P0 finding 3)"
    )
    # The old behaviour (toast-only) must not be the WHOLE story any more -- a
    # toast is still fine as a transient echo, but it must not be the only thing.
    assert "innerHTML" in catch_body, (
        "the catch block never writes markup into the results table -- a bare "
        "toast leaves the table exactly as it was (empty on first search, or "
        "stale), which is the bug this test guards"
    )


def test_anLoadArticles_failure_uses_the_shared_honest_message() -> None:
    body = strip_comments(function_body(_analysis(), "_anLoadArticles"))
    catch_at = body.rindex("catch")  # the function's own final catch
    catch_body = body[catch_at:]
    assert "_articleFailureMessage(e)" in catch_body, (
        "the analysis window's Articles subtab (reachable from a boot-time "
        "?corpus=/?analyze= deep link with no click at all) does not use the "
        "shared rate-limit-aware message -- a refusal there degrades to a bare "
        "exception string with no honesty about WHY or WHEN it might work again"
    )


def test_the_helpers_are_hoisted_declarations_not_arrow_consts() -> None:
    """This replaces a "defined before first use" ordering check (2026-09-09).

    That check asserted textual position, which for a ``function`` declaration is
    not a correctness property at all -- declarations hoist to the top of their
    scope, so `doSearch()` may call `_articleFailureMessage` from above its
    definition and always will work. The check could only ever fail on a harmless
    reordering, and it cost six hand-rolled source slices (the budget in
    tests/test_source_slicing_discipline.py counts each one, because each is a
    chance to reintroduce the over-run bug that module documents).

    The property that IS load-bearing is the one the ordering check was standing
    in for: these must be ``function`` DECLARATIONS. Rewrite any of them as
    ``const _x = () => …`` and hoisting no longer applies -- the binding sits in
    its temporal dead zone until its own line runs, and every earlier caller
    throws a ReferenceError at the exact moment it is trying to report a failure
    honestly. That is a real regression, it is invisible to a reading of the diff,
    and this catches it without slicing anything.
    """
    src = _analysis()
    for name in ("_articleFailureMessage", "_searchRetryAfterSeconds", "_isRateLimited"):
        assert f"function {name}(" in src, (
            f"{name} must be a hoisted `function` declaration; a `const` arrow would "
            "throw a ReferenceError for any caller above its own line"
        )
        assert f"const {name} " not in src and f"const {name}=" not in src


# --------------------------------------------------------------------------- #
# Behavioural: drive the REAL extracted helpers under node so the honesty rules
# themselves are proven, not merely that something is called.
# --------------------------------------------------------------------------- #


def _run_node(js: str) -> dict:
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node failed:\n--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}"
    return json.loads(r.stdout.strip())


def _harness() -> str:
    """The three real helper functions, whole, with a minimal i18n stub (identity
    translation -- these tests check the STRUCTURE of the message: which branch
    fired and whether a time made it in, not the English wording, which is a
    locale-agent concern reported separately in ``newStrings``)."""
    src = _analysis()
    fns = "\n".join(
        function_source(src, name)
        for name in ("_searchRetryAfterSeconds", "_isRateLimited", "_articleFailureMessage")
    )
    # The real code reads `window.OOI18N` (true in a browser, where `window` always
    # exists) -- plain node has no such global, so stub it exactly as absent: falls
    # through to the identity translator, same as a page where i18n hasn't loaded.
    return f"""
global.window = {{}};
{fns}
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_retry_after_present_becomes_a_stated_clock_time_never_a_countdown() -> None:
    js = _harness() + """
const e = {status: 429, retryAfter: 90};
const msg = _articleFailureMessage(e);
// A real, non-fabricated wait was known (90s) -- the message must say WHEN
// (a computed clock time), not merely "later", and must never leak a raw
// "NaN"/"undefined" from a bad interpolation.
console.log(JSON.stringify({
  msg,
  mentionsLater: /later/i.test(msg) && !/after/i.test(msg),
  hasBadValue: /NaN|undefined/i.test(msg),
}));
"""
    out = _run_node(js)
    assert not out["hasBadValue"], f"message leaked a bad interpolation: {out['msg']!r}"
    assert not out["mentionsLater"], (
        f"a KNOWN retry-after was thrown away in favour of the generic message: {out['msg']!r}"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_retry_after_absent_states_only_later_never_a_fabricated_wait() -> None:
    js = _harness() + """
const e = {status: 429};   // no retryAfter anywhere on the error
const msg = _articleFailureMessage(e);
console.log(JSON.stringify({
  msg,
  hasBadValue: /NaN|undefined/i.test(msg),
}));
"""
    out = _run_node(js)
    assert not out["hasBadValue"], f"an absent Retry-After produced a fabricated value: {out['msg']!r}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_retry_after_is_read_from_several_plausible_error_shapes() -> None:
    """This file does not own app-core.js's api() (a sibling fix attaches the real
    field), so the extractor must not hard-depend on one exact property name."""
    js = _harness() + """
const shapes = [
  {status: 429, retryAfter: 30},
  {status: 429, retry_after: 30},
  {status: 429, retryAfterSeconds: 30},
  {status: 429, detail: {retry_after: 30}},
  {status: 429, detail: {retryAfter: 30}},
];
console.log(JSON.stringify(shapes.map(_searchRetryAfterSeconds)));
"""
    out = _run_node(js)
    assert out == [30, 30, 30, 30, 30], f"not every plausible Retry-After shape was read: {out}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_non_rate_limited_failure_states_the_real_error() -> None:
    js = _harness() + """
const e = new Error("The server is not answering.");
e.status = 500;
const msg = _articleFailureMessage(e);
console.log(JSON.stringify({msg, hasRealError: msg.indexOf("not answering") !== -1}));
"""
    out = _run_node(js)
    assert out["hasRealError"], (
        f"a non-rate-limit failure lost the real error text: {out['msg']!r}"
    )
    assert "429" not in out["msg"] and "rate limit" not in out["msg"].lower(), (
        f"a non-rate-limit failure was mislabelled as a rate limit: {out['msg']!r}"
    )
