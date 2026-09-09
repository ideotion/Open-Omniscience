"""CSS structural regression tests for the 2026-09-08 visual-audit css-tokens fixes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Four measured root causes from ``docs/audit/ui-visual-2026-09-08/contrast-corrected.csv``
(the orchestrator's corrected 17-theme sweep), all live in ``src/static/app.css``:

  1. ``--line`` was referenced ~50 times and defined nowhere, so every
     ``border:1px solid var(--line)`` was invalid at computed-value time (no border,
     in any theme) -- #oo-tip (invariant #17), #net-coach, .gw-dot, .gw-lang,
     .carousel-dot.
  2. ``.seg-toggle`` buttons rendered OUTSIDE their own group box (60x67px overlap
     measured at 1440px, "Super-groups" 90% covered by "Mind-map"; 2 overlaps in
     German, 3 at 1024px, also in Arabic) -- the classic flexbox min-width:auto trap,
     compounded by a selected-state class mismatch (.active vs .sel).
  3. Five composited-contrast root causes: an accent-filled pill under muted text
     (.lead-flip-hint.back, 1.01:1 on mint, 17/17 themes), element-opacity dimming
     crushing an already-thin colour (.ag-cell.out -> .ag-dn, 1.56:1 on paper,
     17/17), two parallel colour systems bypassing the theme tokens entirely
     (span.chip's hash-derived hex, .tier-badge's fixed rgb), and --muted/
     --accent-as-text falling short of AA against --panel2 (and other panel
     levels) on solar/paper/mist/dawn.
  4. ``main > *`` capped every top-level surface at 1100px with no media query
     above 900px, leaving 8 of 9 surfaces a fixed column in empty space at
     1440-2560px.

These are STRUCTURAL assertions against the CSS source -- the pixel contrast ratios
themselves were verified separately with the orchestrator's live-browser sweep
(``contrast_sweep.py``), not re-derived here (a Python re-implementation of a
browser's ``color-mix``/compositing pipeline would be a second, unvalidated model of
the same thing test_ui_invariants already warns against: a slice is only as good as
what it actually proves).
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.js_source_helper import css_rule as _css_rule

_ROOT = Path(__file__).resolve().parents[1]
_APP_CSS = _ROOT / "src" / "static" / "app.css"


def _css() -> str:
    return _APP_CSS.read_text(encoding="utf-8")


def _root_block(css: str) -> str:
    """The ``:root { ... }`` block's own declarations (brace-matched)."""
    return _css_rule(css, ":root")


def _theme_block(css: str, name: str) -> str:
    """One ``html[data-theme="name"]{ ... }`` block's own declarations."""
    return _css_rule(css, f'html[data-theme="{name}"]')


# --------------------------------------------------------------------------- #
# 1. --line is defined (root cause: referenced everywhere, defined nowhere)
# --------------------------------------------------------------------------- #


def test_line_token_is_defined_in_root():
    root = _root_block(_css())
    assert re.search(r"--line\s*:\s*var\(--border\)\s*;", root), (
        "--line must be defined in :root (aliasing --border) -- every "
        "`border:1px solid var(--line)` in app.css/reader.css/index.html/app-*.js "
        "was invalid at computed-value time with no definition at all"
    )


def test_line_token_referenced_by_at_least_one_declared_border():
    css = _css()
    # A representative call site the audit named directly.
    assert "border: 1px solid var(--line)" in css or "border:1px solid var(--line)" in css, (
        "expected at least one existing border:1px solid var(--line) declaration "
        "(e.g. #oo-tip) to now resolve against a real value"
    )


# --------------------------------------------------------------------------- #
# 2. .seg-toggle overlap: min-width:auto flexbox trap + .active/.sel mismatch
# --------------------------------------------------------------------------- #


def test_seg_toggle_button_has_min_width_zero():
    rule = _css_rule(_css(), ".seg-toggle button")
    assert "min-width:0" in rule.replace(" ", ""), (
        ".seg-toggle button must set min-width:0 -- without it, a flex item's "
        "default min-width:auto floors its shrink at its content's min-content "
        "size (the longest unbreakable word), so once the group ran out of room "
        "the buttons rendered outside their own group box instead of shrinking "
        "or wrapping their text"
    )
    assert "flex:1" in rule.replace(" ", "")


def test_seg_toggle_unselected_rule_excludes_active_as_well_as_sel():
    css = _css()
    rule = _css_rule(css, ".seg-toggle button:not(.sel):not(.active)")
    assert "color:var(--fg-soft)" in rule.replace(" ", "")
    # The old, narrower selector must be gone -- not just superseded textually
    # elsewhere, but actually absent as a distinct rule head.
    assert ".seg-toggle button:not(.sel) {" not in css, (
        "the unselected-chip rule must exclude .active as well as .sel: the "
        "mind-map level/view toggle (#mm-levels/#mm-views) marks its selected "
        "button with class=active (not .sel), so :not(.sel) alone still matched "
        "it and painted it as an UNSELECTED chip (--fg-soft on --panel2, "
        "measured 4.31:1 on dawn) instead of the accent-filled button default"
    )


# --------------------------------------------------------------------------- #
# 3a. .lead-flip-hint.back: no accent-filled pill under muted text
# --------------------------------------------------------------------------- #


def test_lead_flip_hint_back_has_no_accent_fill():
    rule = _css_rule(_css(), ".lead-flip-hint.back").replace(" ", "")
    assert "background:transparent" in rule, (
        ".lead-flip-hint.back is a real <button> and inherits the base `button` "
        "rule's accent-filled background unless it explicitly cancels it -- "
        "muted text on that fill measured 1.01:1 on mint, 17/17 themes"
    )
    assert "border:0" in rule


# --------------------------------------------------------------------------- #
# 3b. .ag-cell.out: no element-opacity dimming
# --------------------------------------------------------------------------- #


def test_ag_cell_out_does_not_use_opacity():
    rule = _css_rule(_css(), ".ag-cell.out")
    assert "opacity" not in rule, (
        ".ag-cell.out must not dim via element opacity -- opacity composites the "
        "WHOLE subtree (including .ag-dn's text) over the page, which crushed "
        "adjacent-month day numbers to 1.56:1 on paper (17/17 themes); this is "
        "the exact defect already fixed elsewhere in this file for .ag-cal and "
        ".gov-strat-refused (see the comments above .gov-strat-refused)"
    )


def test_ag_dn_default_color_is_unchanged_by_the_out_state():
    # .ag-dn's own declared colour must still be --muted -- the fix removes the
    # opacity dilution rather than recolouring the day number itself, so a
    # same-month day and an adjacent-month day render at the SAME (now AA-safe)
    # colour.
    rule = _css_rule(_css(), ".ag-dn")
    assert "color:var(--muted)" in rule.replace(" ", "")


# --------------------------------------------------------------------------- #
# 3c. span.chip / .tier-badge: hash-derived / fixed hex routed through color-mix
# --------------------------------------------------------------------------- #


def test_brief_chip_color_is_mixed_toward_theme_fg():
    rule = _css_rule(_css(), ".brief-bucket .card .chip").replace(" ", "")
    assert "color:color-mix(insrgb,var(--fg)" in rule.replace(" ", ""), (
        "the family-hue chip text must be mixed toward this theme's own --fg "
        "rather than used raw -- --fam is a hash-derived hex IDENTICAL in every "
        "theme (a second colour system parallel to the tokens), measured as low "
        "as 1.47:1 on dawn"
    )
    assert "var(--fam" in rule


def test_tier_badge_colors_no_longer_fixed_hex_only():
    css = _css()
    dev_m = re.search(r"\.corpus-tier\.tier-developing\s*\{[^}]*\}", css)
    est_m = re.search(r"\.corpus-tier\.tier-established\s*\{[^}]*\}", css)
    assert dev_m and est_m, "expected .tier-developing/.tier-established rules to exist"
    dev, est = dev_m.group(0), est_m.group(0)
    assert "color-mix(in srgb, var(--fg)" in dev, (
        "--tier-ac for tier-developing must route the old fixed rgb(59,130,196) "
        "through a color-mix toward --fg, not use the flat hex directly -- it "
        "measured 3.20:1 against --panel on solar (14/17 themes)"
    )
    assert "color-mix(in srgb, var(--fg)" in est
    assert re.search(r"--tier-ac\s*:\s*#3b82c4\s*;", css) is None
    assert re.search(r"--tier-ac\s*:\s*#2e9e6b\s*;", css) is None


# --------------------------------------------------------------------------- #
# 3d/e. --muted / --accent-as-text on --panel2 (and other panel levels)
# --------------------------------------------------------------------------- #


def test_accent_text_token_exists_and_defaults_to_accent():
    root = _root_block(_css())
    assert re.search(r"--accent-text\s*:\s*var\(--accent\)\s*;", root), (
        "a dedicated --accent-text token must exist (mirrors the --warn-fg "
        "pattern: --warn/--accent stay untouched for non-text uses like button "
        "fills; a distinct token carries the text-safe value) and default to "
        "--accent for the 13 themes the sweep did not flag"
    )


def test_base_link_and_active_subtab_use_accent_text_not_accent():
    css = _css()
    assert re.search(r"\ba\s*\{\s*color\s*:\s*var\(--accent-text\)", css), (
        "the base `a` rule must read --accent-text, not --accent directly -- "
        "raw --accent as link text measured as low as 3.47:1 on solar"
    )
    active_rule = _css_rule(css, "nav.tabs button.active, nav.tabs button[aria-selected=\"true\"]")
    assert "color:var(--accent-text)" in active_rule.replace(" ", "")


def test_four_failing_themes_override_muted_and_accent_text():
    css = _css()
    for theme in ("solar", "paper", "mist", "dawn"):
        block = _theme_block(css, theme)
        assert "--muted:color-mix(in srgb, var(--fg)" in block, (
            f"{theme}'s --muted must be re-derived via color-mix toward its own "
            f"--fg -- the corrected sweep measured it below 4.5:1 against "
            f"--panel2 (and, for some of these four, --bg2/--panel3 too)"
        )
        assert "--accent-text:color-mix(in srgb, var(--fg)" in block, (
            f"{theme}'s --accent-text must be overridden with a color-mix "
            f"toward its own --fg -- raw --accent as text measured below 4.5:1 "
            f"against multiple panel levels on this theme"
        )


def test_dawn_also_overrides_fg_soft():
    # dawn is the one theme where --fg-soft ITSELF (not just --muted/--accent)
    # failed against --panel2 (4.31:1, e.g. p.sum / .card .why-plain).
    block = _theme_block(_css(), "dawn")
    assert "--fg-soft:color-mix(in srgb, var(--fg)" in block


def test_other_thirteen_themes_do_not_override_muted():
    # Negative-space check: only the four themes the sweep actually flagged get
    # the override -- a theme that already passed must not be touched (the
    # --caveat/--chip-off lesson: change only where measurement says to).
    css = _css()
    untouched = (
        "slate",
        "midnight",
        "arctic",
        "cyber",
        "forest",
        "aubergine",
        "garnet",
        "sepia",
        "terminal",
        "contrast",
        "light",
        "mint",
    )
    for theme in untouched:
        block = _theme_block(css, theme)
        assert "--muted:color-mix" not in block, f"{theme} should not have gotten the muted override"
        assert "--accent-text:" not in block, f"{theme} should not have gotten an --accent-text override"


# --------------------------------------------------------------------------- #
# 4. Wide-screen choke point: main > * had no media query above 900px
# --------------------------------------------------------------------------- #


def test_main_content_width_is_a_custom_property_with_wide_breakpoints():
    css = _css()
    rule = _css_rule(css, "main > *")
    assert "var(--content-w" in rule.replace(" ", ""), (
        "main > * must resolve its max-width through a --content-w custom "
        "property (with a 1100px fallback) so a surface (Agenda already does, "
        "via #tab-agenda{max-width:none}) can override it, and so a wide-screen "
        "breakpoint can raise the default in one place"
    )
    assert re.search(r"@media\s*\(min-width:\s*1440px\)\s*\{\s*main\s*>\s*\*\s*\{\s*--content-w\s*:\s*1400px", css), (
        "expected a >=1440px breakpoint raising --content-w above the old fixed "
        "1100px cap -- the audit measured 8 of 9 surfaces stuck at a fixed "
        "column at 1440-2560px with no media query above 900px"
    )
    assert re.search(r"@media\s*\(min-width:\s*1920px\)\s*\{\s*main\s*>\s*\*\s*\{\s*--content-w\s*:\s*1600px", css)


def test_agenda_opt_out_still_wins_over_the_new_default():
    # #tab-agenda{max-width:none} is an ID selector -- it must still exist and
    # will always out-specify `main > *` regardless of what --content-w resolves
    # to, so raising the default cannot regress Agenda's existing opt-out.
    css = _css()
    assert re.search(r"#tab-agenda\s*\{\s*max-width\s*:\s*none\s*;\s*\}", css)
