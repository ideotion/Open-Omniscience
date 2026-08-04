"""Shared, correct slicing for tests that assert against JavaScript SOURCE.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS. 161 of the 669 test files assert against source text rather than
behaviour, carrying ~819 positive and ~244 negative assertions. That is a
legitimate technique here -- app.js is a 21,300-line file with no module
boundaries and much of the UI contract is only visible in the source. But every
one of those assertions is only as good as the SLICE it runs over, and the slice
was re-derived per file: 18 local helpers across 16 files, in three mutually
incompatible strategies.

The ledger records three separate occasions when that went wrong, all with green
tests:

  * ``function ooChart(el, seriesList, opts = {})`` -- taking the first ``{``
    after the name lands in a DEFAULT PARAMETER, so depth goes 1 -> 0 immediately
    and the "body" is the signature alone. Every assertion over it passed for
    free (Session D, 2026-08-01).
  * ``test_commodities_category_subtabs`` asserted a whole-file substring that
    matched the HOME families call site, never the commodities one it was named
    for -- passing by accident for months.
  * Three "this string must be GONE" guards failed against CORRECT code, on the
    comments that explained why the string was removed (2026-07-31, re-hit
    2026-08-03).

The correct implementation already existed, in ``test_bench_roster.py``, and was
never shared. This module promotes it so a future test gets it by import rather
than by re-derivation.
"""

from __future__ import annotations

import re
from pathlib import Path

_STATIC = Path(__file__).resolve().parent.parent / "src" / "static"


def read_static(name: str) -> str:
    """The text of a file under src/static (app.js, reader.js, index.html...)."""
    return (_STATIC / name).read_text(encoding="utf-8")


def function_body(js: str, name: str) -> str:
    """One function's body, brace-matched from the BODY brace.

    Balances the PARAMETER LIST first, then brace-matches -- so a default
    parameter (``opts = {}``) cannot be mistaken for the body, and the result is
    never over-run into a sibling function the way "split on the next
    declaration" is when the delimiter guessed is not the one that follows.

    Raises rather than returning empty: a slice that silently comes back empty is
    how a guard passes vacuously, which is the whole failure this module exists
    to end.
    """
    for decl in (f"function {name}(", f"{name} = function("):
        at = js.find(decl)
        if at != -1:
            i = at + len(decl) - 1
            break
    else:
        raise AssertionError(f"no declaration of {name!r} found in the source")

    depth = 0
    while True:  # walk the parameter list to its close
        if js[i] == "(":
            depth += 1
        elif js[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1

    body_at = js.index("{", i)  # the FIRST brace after the params IS the body
    depth = 0
    for j in range(body_at, len(js)):
        if js[j] == "{":
            depth += 1
        elif js[j] == "}":
            depth -= 1
            if depth == 0:
                out = js[body_at : j + 1]
                if len(out) < 3:
                    raise AssertionError(f"{name!r} sliced to an empty body: {out!r}")
                return out
    raise AssertionError(f"unbalanced braces while slicing {name!r}")


_LINE_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)


def strip_comments(js: str) -> str:
    """Drop whole-line ``//`` comments, leaving code (and string literals) intact.

    Whole-line only, deliberately: a trailing ``//`` cannot be removed without a
    real tokenizer, because ``"https://..."`` inside a string literal is not a
    comment. Whole-line covers the case that actually bites -- the block comment
    above a removal explaining what was removed.
    """
    return _LINE_COMMENT.sub("", js)


def assert_absent(haystack: str, needle: str, *, why: str = "") -> None:
    """Assert a string is gone from CODE, ignoring the comments that explain it.

    A "must be gone" guard is always written next to a comment saying what was
    removed and why -- and that comment necessarily quotes the removed string. So
    the naive form fails against correct code, and the tempting fix (reword the
    comment) deletes the explanation a future reader needs before deciding the
    removal was a mistake.
    """
    stripped = strip_comments(haystack)
    assert needle not in stripped, (
        f"{needle!r} must not appear in the code" + (f" -- {why}" if why else "")
    )


def assert_present(haystack: str, needle: str, *, why: str = "") -> None:
    """Assert a string is present in CODE, not merely in a comment about it.

    The mirror of the above, and the more insidious of the two: a guard that
    accepts a mention in a comment certifies an implementation that does not
    exist.
    """
    stripped = strip_comments(haystack)
    assert needle in stripped, (
        f"{needle!r} must appear in the code (a comment mentioning it is not the "
        f"implementation)" + (f" -- {why}" if why else "")
    )
