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

_ROOT = Path(__file__).resolve().parent.parent
_CSS = _ROOT / "src" / "static" / "app.css"
_APP_JS = _ROOT / "src" / "static" / "app.js"

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


def _theme_tokens() -> dict[str, dict[str, str]]:
    """Each theme's colour tokens, with :root inheritance applied.

    Modelling the inheritance matters: a theme that does not redefine a
    variable still uses it, and ignoring that UNDER-reports failures (paper
    defines no --warn at all, and inherited the failing :root value).
    """
    css = _CSS.read_text(encoding="utf-8")
    blocks: dict[str, dict[str, str]] = {}
    for m in re.finditer(r'(?::root|html\[data-theme="([a-z-]+)"\])\s*\{([^}]*)\}', css):
        name = m.group(1) or ":root"
        found = dict(re.findall(r"--([a-z-]+)\s*:\s*(#[0-9a-fA-F]{3,8})", m.group(2)))
        if found:
            blocks.setdefault(name, {}).update(found)
    root = blocks.get(":root", {})
    return {name: {**root, **tokens} for name, tokens in blocks.items()}


@pytest.mark.parametrize("variable,minimum,why", _ROLES)
def test_colour_role_clears_its_contrast_bar_on_every_theme(variable, minimum, why):
    tokens = _theme_tokens()
    assert len(tokens) >= 17, f"expected >=17 themes, parsed {len(tokens)}"
    failures = []
    for name, t in sorted(tokens.items()):
        colour, panel = t.get(variable.lstrip("-")), t.get("panel")
        if not (colour and panel):
            continue
        r = _ratio(colour, panel)
        if r < minimum:
            failures.append(f"{name} {r:.2f}")
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
    src = _APP_JS.read_text(encoding="utf-8")
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
    src = _APP_JS.read_text(encoding="utf-8")
    body = src.split("function _ooShareBars(", 1)[1].split("\n    }", 1)[0]
    assert "items.map(" in body, "the fallback must render every item"
    assert ".slice(" not in body, (
        "the bars fallback truncates -- it must show every category "
        "(anti-capping rule: change the encoding, never drop the data)"
    )
