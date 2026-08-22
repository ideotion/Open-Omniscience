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

import ast
import re
from pathlib import Path

_STATIC = Path(__file__).resolve().parent.parent / "src" / "static"


def app_modules() -> list[str]:
    """The app's JS module file names, in the order ``index.html`` loads them.

    Read from ``index.html`` itself rather than kept as a list here, for the same
    reason the i18n scope guard exists: a hand-maintained list drifts from the
    thing it claims to describe, silently. Whatever the browser loads is what a
    source assertion is entitled to see.
    """
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    return [
        m.group(1)
        for m in re.finditer(r'<script src="/static/(app(?:-[a-z0-9-]+)?\.js)"', html)
    ]


def app_js() -> str:
    """The whole UI engine's source, as one string.

    ``src/static/app.js`` was decomposed into ordered modules (S-3, 2026-08-20 --
    ``docs/design/APPJS_DECOMPOSITION_2026-08-20.md``). The split is a pure
    CONTIGUOUS slice: the concatenation of the modules, in load order, is
    byte-identical to the file that preceded it. So for a test asserting against
    source, this string is the exact semantic equivalent of the old single file.

    WHY THIS MATTERS MORE THAN CONVENIENCE. 151 test sites read that file, and
    161 test files assert against JavaScript source. A test that kept reading one
    module would still FAIL LOUDLY on a positive assertion -- but a NEGATIVE one
    (``assert_absent``, ``X not in app``) would pass **for free**, against a file
    that no longer contains the thing it is checking. That is precisely the
    vacuity failure this module exists to end, and the split would have
    reintroduced it at 151 sites at once, silently. Reading the engine as a whole
    keeps every assertion, positive and negative, exactly as meaningful as it was.

    Joined with ``""`` -- each module keeps its own trailing newline, so the
    concatenation is byte-exact rather than newline-shifted, and any ``.index()``
    offset or line count a caller computes stays consistent with the browser's view.
    """
    mods = app_modules()
    assert mods, "index.html loads no app module -- the script tags moved or were renamed"
    return "".join((_STATIC / m).read_text(encoding="utf-8") for m in mods)


def read_static(name: str) -> str:
    """The text of a file under src/static (reader.js, index.html...).

    ``"app.js"`` is accepted as the name of the UI ENGINE, which is now several
    ordered modules rather than one file, and returns :func:`app_js`. Callers mean
    "the engine's source" whenever they ask for it, and that is what they get.
    """
    if name == "app.js":
        return app_js()
    return (_STATIC / name).read_text(encoding="utf-8")


def _function_span(js: str, name: str) -> tuple[int, int, int]:
    """``(decl_at, body_at, body_end)`` for one function declaration.

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
                if j + 1 - body_at < 3:
                    raise AssertionError(
                        f"{name!r} sliced to an empty body: {js[body_at : j + 1]!r}"
                    )
                return at, body_at, j + 1
    raise AssertionError(f"unbalanced braces while slicing {name!r}")


def function_body(js: str, name: str) -> str:
    """One function's body -- the braced block only, brace-matched from the BODY
    brace. Use this to assert about what a function DOES."""
    _, body_at, body_end = _function_span(js, name)
    return js[body_at:body_end]


def function_source(js: str, name: str) -> str:
    """One function's WHOLE declaration -- signature and body.

    ``function_body`` deliberately drops the signature, which is right for an
    assertion about a function's behaviour and wrong for the other use of these
    slices: lifting the real implementation out of ``app.js`` to DRIVE it under
    node, where a body without its ``function name(args)`` header is not a
    program. Every test that wanted that was re-deriving the parameter-list walk
    locally -- the exact re-derivation this module exists to end, and the thing
    ``test_source_slicing_discipline`` counts -- so the shape lives here, sharing
    one brace-matcher with ``function_body`` rather than owning a second copy.
    """
    decl_at, _, body_end = _function_span(js, name)
    return js[decl_at:body_end]


def python_function_source(src: str, *names: str) -> str:
    """The source of one or more PYTHON functions, taken from the parser.

    The module is named for JavaScript because that is where the technique started,
    but the same failure applies to a test that slices a .py file with
    ``split("def foo", 1)[1].split(DELIM, 1)[0]``: pick a delimiter that does not
    occur and the "body" silently becomes the whole rest of the module, so the
    assertion is satisfied by any other function in the file. That really happened
    -- ``split("\\ndef test_")`` against ``src/api/main.py``, a source file with no
    tests in it, made the slice 108,272 characters long.

    Here the bounds come from ``ast``, so they are exact by construction rather
    than by a guessed delimiter. Several names may be given when a guard genuinely
    spans a caller and its helper; each must exist.
    """
    tree = ast.parse(src)
    out = []
    for name in names:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
                seg = ast.get_source_segment(src, node)
                assert seg, f"no source segment for {name!r}"
                out.append(seg)
                break
        else:
            raise AssertionError(f"no def of {name!r} found in the source")
    return "\n".join(out)


def css_rule(css: str, selector: str) -> str:
    """One CSS rule's declaration block, brace-matched from its selector.

    The same failure again in a third language: a test bounded the AI pill's rules
    by splitting on ``"\\n    .pill"``, the next selector it happened to think of,
    and got 820 lines instead of 20 -- inside which ``var(--border)`` occurs 73
    times, so "every colour is theme-derived" was true of app.css at large and said
    nothing about the pill.
    """
    at = css.find(selector + " {")
    if at == -1:
        at = css.find(selector + "{")
    assert at != -1, f"no rule for selector {selector!r}"
    body_at = css.index("{", at)
    depth = 0
    for j in range(body_at, len(css)):
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                return css[body_at : j + 1]
    raise AssertionError(f"unbalanced braces while slicing {selector!r}")


def _match_delimited(js: str, open_at: int, open_ch: str, close_ch: str, what: str) -> str:
    """Balance ``open_ch``/``close_ch`` from ``open_at``, IGNORING string and comment text.

    Counting raw characters is not enough, and the test that proves it caught this very
    helper: ``const L = {a: "x}y", ...}`` truncates at the brace inside the string, so the
    slice ends after one key and every assertion over it passes against a fragment -- the
    same failure the whole module is about, one level down. Template literals need the same
    treatment and additionally nest through ``${...}``.

    HONEST LIMIT: a JS regex literal containing an unbalanced delimiter (``/[}]/``) is not
    recognised, because telling a regex from a division needs the preceding token. No
    declaration literal in this tree contains one; if one appears, this raises "unbalanced"
    rather than silently truncating, which is the safe direction.
    """
    depth = 0
    i, n = open_at, len(js)
    tmpl: list[int] = []          # ${} nesting depth per open template literal
    while i < n:
        c = js[i]
        if c == "\\":
            i += 2
            continue
        if c in "'\"":            # a plain string: skip to its unescaped close
            q, i = c, i + 1
            while i < n and js[i] != q:
                i += 2 if js[i] == "\\" else 1
            i += 1
            continue
        if c == "`":
            tmpl.append(0)
            i += 1
            while i < n and tmpl:
                d = js[i]
                if d == "\\":
                    i += 2
                    continue
                if d == "$" and js[i + 1 : i + 2] == "{":
                    tmpl[-1] += 1
                    i += 2
                    continue
                if d == "}" and tmpl[-1] > 0:
                    tmpl[-1] -= 1
                elif d == "`":
                    tmpl.pop()
                elif d == "{" and tmpl[-1] > 0:
                    tmpl[-1] += 1
                i += 1
            continue
        if js.startswith("//", i):
            i = js.find("\n", i)
            if i == -1:
                break
            continue
        if js.startswith("/*", i):
            end = js.find("*/", i)
            i = n if end == -1 else end + 2
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                out = js[open_at : i + 1]
                if len(out) < 3:
                    raise AssertionError(f"{what!r} sliced to an empty literal: {out!r}")
                return out
        i += 1
    raise AssertionError(f"unbalanced {open_ch}{close_ch} while slicing {what!r}")


def array_literal(js: str, name: str) -> str:
    """One ``const NAME = [ … ]`` array literal, BRACKET-matched from its opening ``[``.

    The fourth shape of the same failure. A test that wanted the ``_FIG_STYLES``
    series table sliced it as::

        src = APP[APP.index("const _FIG_STYLES = ["):]
        src = src[: src.index("];") + 2]

    which is correct only while no element of the array happens to contain ``];``
    before the array's own close — a nested array, or that pair inside a string
    literal, silently truncates the slice and every assertion over it then passes
    against a fragment. Bracket-matching cannot truncate.

    Raises rather than returning empty, for the reason ``function_body`` does: a
    slice that comes back empty is how a guard passes vacuously.
    """
    for decl in (f"const {name} = [", f"const {name}=[",
                 f"let {name} = [", f"var {name} = ["):
        at = js.find(decl)
        if at != -1:
            break
    else:
        raise AssertionError(f"no array literal named {name!r} found in the source")

    return _match_delimited(js, js.index("[", at), "[", "]", name)


def object_literal(js: str, name: str) -> str:
    """One ``const NAME = { … }`` object literal, BRACE-matched from its opening ``{``.

    The fifth shape, and the ratchet in ``test_source_slicing_discipline`` is what
    produced it: a guard over the ``LIB_QUAL_LABELS`` table sliced it as::

        at = app.index("const LIB_QUAL_LABELS")
        table = app[at : app.index("}", at) + 1]

    which is correct only while no value contains a ``}`` — a nested object, a template
    literal, or that character inside a string silently truncates the slice, and every
    assertion over the fragment then passes for free. Its sibling sliced from one
    declaration to the NEXT one by name, which is correct only while the two stay
    adjacent in that order. Brace-matching depends on neither.

    Raises rather than returning empty, for the reason ``function_body`` does.
    """
    for decl in (f"const {name} = {{", f"const {name}={{",
                 f"let {name} = {{", f"var {name} = {{"):
        at = js.find(decl)
        if at != -1:
            break
    else:
        raise AssertionError(f"no object literal named {name!r} found in the source")

    return _match_delimited(js, js.index("{", at), "{", "}", name)


_LINE_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)


def strip_ps_comments(ps: str) -> str:
    """PowerShell source with ``<# block #>`` and unquoted ``#`` comments removed.

    The JS ``strip_comments`` above cannot serve here: PowerShell comments are
    ``#``/``<# #>``, its escape character is a BACKTICK rather than a backslash,
    and a Windows path inside a string (``"...\\Scripts\\python.exe"``) would be
    mangled by backslash-escape rules that do not apply to it.

    Stripping matters for the same recorded reason it does in JS: a script that
    DOCUMENTS the trap it avoids ("activating a venv needs Activate.ps1, which the
    execution policy blocks") would otherwise satisfy -- or defeat -- an assertion
    about whether the code does that thing.
    """
    ps = re.sub(r"<#.*?#>", "", ps, flags=re.DOTALL)
    out: list[str] = []
    for line in ps.splitlines():
        quote: str | None = None
        cut = len(line)
        i = 0
        while i < len(line):
            ch = line[i]
            if quote:
                if ch == "`" and quote == '"':      # backtick escapes inside "..."
                    i += 2
                    continue
                if ch == quote:
                    quote = None
            elif ch in "'\"":
                quote = ch
            elif ch == "#":
                cut = i
                break
            i += 1
        out.append(line[:cut])
    return "\n".join(out)


def ps_function_body(ps: str, name: str) -> str:
    """One PowerShell function's body -- the braced block only, brace-matched.

    The shape this replaces was written three times in one file::

        ps.split("function Install-WingetPackage", 1)[1].split("\\nfunction ", 1)[0]

    which is the module's recorded OVER-RUN bug in a new language: the closing
    delimiter is guessed, so if the target happens to be the LAST function in the
    file the "body" silently becomes the whole rest of the script and every
    assertion over it passes against unrelated code. It works only for as long as
    some other function happens to follow.

    Brace-matching is string- and comment-aware, because a ``#`` or a brace inside
    a string is data. Raises rather than returning empty -- a slice that comes back
    empty is how a guard passes vacuously.

    HONEST LIMIT: here-strings (``@' ... '@``) are not recognised. None appear in
    this tree; if one does, the unbalanced case raises rather than truncating
    silently, which is the safe direction.
    """
    m = re.search(rf"\bfunction\s+{re.escape(name)}(?![\w-])", ps)
    if m is None:
        raise AssertionError(f"no PowerShell function named {name!r} in the source")

    i, n = m.end(), len(ps)
    while i < n and ps[i] not in "({":     # an optional ($a, $b) parameter list
        i += 1
    if i < n and ps[i] == "(":
        depth = 0
        while i < n:
            if ps[i] == "(":
                depth += 1
            elif ps[i] == ")":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
    while i < n and ps[i] != "{":
        i += 1
    if i >= n:
        raise AssertionError(f"no body brace found for PowerShell function {name!r}")

    body_at, depth, quote = i, 0, None
    while i < n:
        ch = ps[i]
        if quote:
            if ch == "`" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "`":
            i += 2
            continue
        elif ch == "#":
            i = ps.find("\n", i)
            if i == -1:
                break
            continue
        elif ch == "<" and ps.startswith("<#", i):
            end = ps.find("#>", i)
            if end == -1:
                break
            i = end + 2
            continue
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                if i + 1 - body_at < 3:
                    raise AssertionError(
                        f"{name!r} sliced to an empty body: {ps[body_at : i + 1]!r}"
                    )
                return ps[body_at : i + 1]
        i += 1
    raise AssertionError(f"unbalanced braces while slicing PowerShell {name!r}")


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
