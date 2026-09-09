"""
Guards: per-theme colour contrast, and the donut's slice-count guard.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

GUI audit 2026-07-28, findings G-1/G-3/V-4 -- with one CORRECTION to the
audit itself, recorded here so it is not re-derived wrongly:

  The audit reported "--warn fails WCAG AA 4.5:1 on 6 of 17 themes". That
  was a FALSE POSITIVE: it measured --warn as if it were a text colour. It
  is not -- ``--warn`` is only ever a border-left, a border-color mix or a
  ``.dot.warn`` background, and TEXT uses the dedicated ``--warn-fg``
  (``app.css``'s own "pillwarn-severe-contrast (P1)" note documents exactly
  that split, and --warn-fg already cleared AA everywhere). So the correct
  bar for --warn is WCAG 1.4.11 NON-TEXT contrast, 3:1 -- against which it
  genuinely failed on three themes (dawn 2.16, paper 2.12, solar 2.82).

  Measuring the right variables surfaced a real gap the audit MISSED:
  ``--muted``, which IS secondary text, was below AA 4.5:1 on dawn (2.87)
  and solar (4.11).

Both are fixed at source; this pins all four colour roles so no future
theme edit can regress any of them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.js_source_helper import app_js

_ROOT = Path(__file__).resolve().parent.parent
_CSS = _ROOT / "src" / "static" / "app.css"

# role -> (variable, minimum ratio, why)
_ROLES = (
    ("--fg", 4.5, "primary text"),
    ("--muted", 4.5, "secondary text"),
    ("--caveat", 4.5, "honesty caveats (visible-by-default mandate)"),
    ("--warn-fg", 4.5, "warning TEXT"),
    ("--warn", 3.0, "warning as a NON-TEXT mark (dot / border) - WCAG 1.4.11"),
)


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _ratio(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# (theme, variable, raw declaration) for every token a theme DECLARES in its own
# block that _theme_tokens() could not resolve to a colour. Repopulated on each
# call; read by the role test, which refuses to pass while it is non-empty.
unreadable: set[tuple[str, str, str]] = set()


def _mix_srgb(a: str, wa: float, b: str, wb: float) -> str:
    """``color-mix(in srgb, A wa%, B wb%)`` as a hex string.

    CSS mixes in sRGB as a straight per-channel weighted average of the 0-1
    channel values (for opaque colours), normalising the weights when they do not
    sum to 100. Measured against Chromium rather than assumed -- see
    test_the_color_mix_resolver_matches_what_the_browser_paints, which pins three
    real declarations against the values Chromium computed for them.
    """
    def chans(h: str) -> tuple[float, float, float]:
        h = h.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]

    total = wa + wb
    if total <= 0:
        raise ValueError("color-mix weights sum to zero")
    wa, wb = wa / total, wb / total
    ca, cb = chans(a), chans(b)
    return "#" + "".join(f"{round((ca[i] * wa + cb[i] * wb) * 255):02x}" for i in range(3))


_MIX_RE = re.compile(
    r"color-mix\(\s*in\s+srgb\s*,\s*(#[0-9a-fA-F]{3,8}|var\(\s*--[a-z-]+\s*\))\s*"
    r"([\d.]+)%\s*,\s*(#[0-9a-fA-F]{3,8}|var\(\s*--[a-z-]+\s*\))\s*([\d.]+)%\s*\)"
)


def _raw_decl(css: str, theme: str, var: str) -> str:
    """A theme's own raw declaration text for ``var`` -- for the error message."""
    sel = r":root" if theme == ":root" else r'html\[data-theme="' + re.escape(theme) + r'"\]'
    for m in re.finditer(sel + r"\s*\{([^}]*)\}", css):
        for d in re.finditer(r"--([a-z-]+)\s*:\s*([^;]+)", m.group(1)):
            if d.group(1) == var:
                return d.group(2).strip()[:60]
    return "<not found>"


def _theme_tokens() -> dict[str, dict[str, str]]:
    """Each theme's colour tokens, with :root inheritance applied and any
    ``color-mix()`` declaration RESOLVED to the hex the browser paints.

    Modelling the inheritance matters: a theme that does not redefine a
    variable still uses it, and ignoring that UNDER-reports failures (paper
    defines no --warn at all, and inherited the failing :root value).

    RESOLVING color-mix() matters for the same reason, learned on 2026-09-09.
    This used to match only ``#hex``. The 2026-09-08 contrast fixes re-derived
    ``--muted``/``--accent-text`` on five themes THROUGH
    ``color-mix(in srgb, var(--fg) N%, #hex M%)``, which this skipped -- so it
    kept scoring the ORIGINAL, superseded value and reported ``solar 4.31`` for a
    token Chromium paints at 7.51:1 against the same panel. A false failure here;
    on a theme whose stale value happened to pass, it would have been a false pass.

    That was the third time in one fix pass that changing how a value is WRITTEN
    made it invisible to a checker (the live contrast harness's colour parser and
    the Agenda caveat's sentence keys were the others), which is why the general
    rule is now in docs/ledger/LESSONS.md.
    """
    # Comments stripped FIRST, and not for tidiness. Scanning declarations in
    # ORDER (needed so a later color-mix supersedes the hex above it) means the
    # value pattern runs to the next ";" -- and app.css documents its tokens in
    # prose containing "--caveat: the dedicated colour for honesty caveats…" with
    # no ";" for four lines, so that COMMENT swallowed the real "--caveat:#eab44e;"
    # below it and the token went unscored on all 17 themes. Caught by this
    # module's own declared-but-unresolved check, which exists for exactly that:
    # an unscored token reads like a passing one.
    css = re.sub(r"/\*.*?\*/", "", _CSS.read_text(encoding="utf-8"), flags=re.S)

    blocks: dict[str, dict[str, str]] = {}
    for m in re.finditer(r'(?::root|html\[data-theme="([a-z-]+)"\])\s*\{([^}]*)\}', css):
        name = m.group(1) or ":root"
        found: dict[str, str] = {}
        for decl in re.finditer(r"--([a-z-]+)\s*:\s*([^;]+)", m.group(2)):
            var, raw = decl.group(1), decl.group(2).strip()
            if re.fullmatch(r"#[0-9a-fA-F]{3,8}", raw) or _MIX_RE.search(raw):
                found[var] = raw
        if found:
            blocks.setdefault(name, {}).update(found)

    # What each theme DECLARES in its own block, regardless of whether the value
    # was readable -- the difference between "inherits, fine" and "sets it and we
    # could not read it, not fine".
    # `:root` is included, not just the themes. It declares tokens every theme
    # inherits, so one going unreadable there goes unscored on all 17 at once with
    # nothing to inherit from -- the widest possible blind spot, and the one this
    # module actually had (a comment swallowed `--caveat:#eab44e`). Verified by
    # mutation: removing the comment-stripping above must fail HERE.
    own: dict[str, set[str]] = {}
    for m in re.finditer(r'(?::root|html\[data-theme="([a-z-]+)"\])\s*\{([^}]*)\}', css):
        own.setdefault(m.group(1) or ":root", set()).update(
            d.group(1) for d in re.finditer(r"--([a-z-]+)\s*:", m.group(2))
        )

    root = blocks.get(":root", {})
    merged = {name: {**root, **tokens} for name, tokens in blocks.items()}

    unreadable.clear()
    resolved: dict[str, dict[str, str]] = {}
    for name, tokens in merged.items():
        out: dict[str, str] = {}
        # Two passes: a mix may reference another token (var(--fg)), and --fg is
        # always a plain hex, so one dependency level is all this needs. A mix
        # whose operand cannot be resolved is DROPPED, never guessed.
        for var, raw in tokens.items():
            if re.fullmatch(r"#[0-9a-fA-F]{3,8}", raw):
                out[var] = raw
        for var, raw in tokens.items():
            if var in out:
                continue
            m2 = _MIX_RE.search(raw)
            if not m2:
                continue

            # `known=out` binds THIS theme's resolved hexes; closing over the loop
            # variable would make every operand read whichever theme ran last
            # (ruff B023).
            def _operand(tok: str, known: dict[str, str] = out) -> str | None:
                if tok.startswith("#"):
                    return tok
                ref = re.search(r"--([a-z-]+)", tok)
                return known.get(ref.group(1)) if ref else None

            a, b = _operand(m2.group(1)), _operand(m2.group(3))
            if a and b:
                out[var] = _mix_srgb(a, float(m2.group(2)), b, float(m2.group(4)))
        resolved[name] = out

        # A value this parser could not read is NOT "absent": the merge above has
        # already handed this theme :root's inherited value, so the token gets
        # SCORED -- against a colour this theme does not paint. A wrong answer
        # wearing a right answer's clothes. Compare what the theme DECLARES
        # (`own`) against what was ACCEPTED from its block (`blocks`); checking
        # `merged` would never fire, because merged already carries :root's
        # readable hex under the same name -- the exact masking this exposes.
        # (Written the wrong way first; caught by mutating solar's --muted to an
        # `oklch()` value, which was then silently scored as :root's colour.)
        for var in sorted(own.get(name, ())):
            if var not in blocks.get(name, {}):
                unreadable.add((name, var, _raw_decl(css, name, var)))
    return resolved


@pytest.mark.parametrize("variable,minimum,why", _ROLES)
def test_colour_role_clears_its_contrast_bar_on_every_theme(variable, minimum, why):
    tokens = _theme_tokens()
    assert len(tokens) >= 17, f"expected >=17 themes, parsed {len(tokens)}"
    v = variable.lstrip("-")
    # A token the resolver could not compute is scored as :root's inherited value,
    # which is somebody else's colour. Refuse to pass on one rather than let an
    # unchecked token read as a clean one -- the same trap the live browser
    # harness fell into: "nothing found" is not "nothing wrong".
    unscored = [f"{th} ({raw})" for th, var, raw in sorted(unreadable) if var == v]
    failures = []
    for name, t in sorted(tokens.items()):
        colour, panel = t.get(v), t.get("panel")
        if not (colour and panel):
            continue
        r = _ratio(colour, panel)
        if r < minimum:
            failures.append(f"{name} {r:.2f}")
    assert not unscored, (
        f"{variable} is DECLARED but could not be resolved to a colour on: "
        f"{', '.join(unscored)} -- so those themes were scored against :root's "
        "INHERITED value instead, which is a colour they do not paint. Extend "
        "_theme_tokens()'s resolver rather than letting an unchecked token be "
        "measured as somebody else's."
    )
    assert not failures, (
        f"{variable} ({why}) is below {minimum}:1 against its panel on: "
        f"{', '.join(failures)}. Pick a hue-preserving lighter/darker value for "
        "those themes rather than lowering the bar."
    )


def test_warn_is_never_used_as_a_text_colour():
    """The --warn / --warn-fg split is load-bearing.

    --warn is tuned for non-text marks (3:1); using it for text would apply
    the 4.5:1 bar to a value never chosen to meet it. --warn-fg exists for
    that. This pins the split so the two cannot be quietly merged.
    """
    css = _CSS.read_text(encoding="utf-8")
    text_uses = re.findall(r"(?<![-\w])color\s*:\s*var\(--warn\)", css)
    assert not text_uses, (
        "var(--warn) is being used as a text colour -- use var(--warn-fg), "
        "which is the dedicated text-safe value"
    )


def test_prefers_contrast_is_handled_and_theme_derived():
    """A `contrast` theme existed but the media feature was unhandled."""
    css = _CSS.read_text(encoding="utf-8")
    assert "@media (prefers-contrast: more)" in css, (
        "prefers-contrast: more is unhandled -- users asking the OS for more "
        "contrast get none"
    )
    block = css.split("@media (prefers-contrast: more)", 1)[1][:900]
    assert "color-mix" in block, (
        "the prefers-contrast block must derive from the active theme's own "
        "tokens (color-mix), never hardcode hues -- otherwise it only works "
        "for whichever theme it was written against"
    )
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", block), (
        "hardcoded hex in the prefers-contrast block -- see above"
    )


def test_donut_falls_back_to_bars_past_the_framework_s_slice_limit():
    """docs/research/dataviz/chart_decision_framework.md: "Pie/donut only if
    <=4-5 slices ... otherwise bars", and "many-slice pie" is on its REJECT
    list. ooDonut had no guard and its only caller feeds it an unbounded
    language set."""
    src = app_js()
    assert "_DONUT_MAX_SLICES" in src, "the slice-count guard is gone"
    limit = re.search(r"_DONUT_MAX_SLICES\s*=\s*(\d+)", src)
    assert limit and int(limit.group(1)) <= 5, (
        "the donut slice limit must stay <=5, per the project's own committed "
        "chart-decision framework"
    )
    body = src.split("function ooDonut(", 1)[1].split("\n    }", 1)[0]
    assert "_ooShareBars" in body, (
        "ooDonut must fall back to sorted bars past the limit"
    )
    assert "_DONUT_MAX_SLICES" in body, "the guard must be applied inside ooDonut"


def test_the_donut_fallback_never_truncates_categories():
    """Anti-capping: a display cap may bound the ENCODING, never the data.

    The bars path must render every item it is handed -- no slice(), no
    top-N, no silent "and N more".
    """
    src = app_js()
    body = src.split("function _ooShareBars(", 1)[1].split("\n    }", 1)[0]
    assert "items.map(" in body, "the fallback must render every item"
    assert ".slice(" not in body, (
        "the bars fallback truncates -- it must show every category "
        "(anti-capping rule: change the encoding, never drop the data)"
    )


def test_the_color_mix_resolver_matches_what_the_browser_paints():
    """The resolver above is the whole basis of every ratio on a mixed token, and
    nothing else here would notice if its arithmetic were wrong -- proven by
    mutation on 2026-09-09: swapping the two weights in ``_mix_srgb`` left all
    nine tests in this module green.

    So pin it against measurement. These are three real declarations from
    ``app.css`` and the values Chromium actually computed for them, read out of
    ``getComputedStyle`` in a live page (it serialises a ``color-mix()`` result as
    ``color(srgb r g b)`` with 0-1 floats, which is what the hex below rounds).
    A resolver that is merely self-consistent would satisfy the rest of this file;
    only a fixed vector catches one that is consistently wrong.
    """
    cases = [
        # mint --muted: color-mix(in srgb, var(--fg) 20%, #5f7466 80%), --fg #1f2a23
        # -> Chromium: color(srgb 0.322353 0.396863 0.347451)
        ("#1f2a23", 20.0, "#5f7466", 80.0, "#526559"),
        # solar --muted: color-mix(in srgb, var(--fg) 55%, #8d9d9e 45%), --fg #eee8d5
        ("#eee8d5", 55.0, "#8d9d9e", 45.0, "#c2c6bc"),
        # dawn --muted: color-mix(in srgb, var(--fg) 75%, #756f86 25%), --fg #575279
        ("#575279", 75.0, "#756f86", 25.0, "#5e597c"),
    ]
    for a, wa, b, wb, expected in cases:
        got = _mix_srgb(a, wa, b, wb)
        assert got == expected, (
            f"color-mix(in srgb, {a} {wa}%, {b} {wb}%) resolved to {got}, but Chromium "
            f"paints {expected}. The mix is a straight per-channel sRGB average; if this "
            "no longer holds, re-measure in a browser before changing the expectation."
        )

    # Asymmetry is the property the weight-swap mutant violated: the mix must lean
    # toward whichever colour carries the larger weight.
    assert _mix_srgb("#000000", 90.0, "#ffffff", 10.0) == "#1a1a1a"
    assert _mix_srgb("#000000", 10.0, "#ffffff", 90.0) == "#e6e6e6"

    # Weights that do not sum to 100 normalise, rather than silently clipping.
    assert _mix_srgb("#000000", 1.0, "#ffffff", 1.0) == _mix_srgb("#000000", 50.0, "#ffffff", 50.0)
