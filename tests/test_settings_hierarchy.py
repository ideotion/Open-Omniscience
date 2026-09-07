"""Settings: where a surface lives, and which text in it looks most important.

Two maintainer asks from 2026-08-11, one PR: move every diagnostic out of Data &
backup into its own Advanced section, and make a section's NAME outrank everything
inside it. The second one had a mechanical cause worth pinning rather than
remembering — ``class="small"`` had no rule anywhere in the tree, so 32 Settings
elements an author had marked small rendered at the full body size, several of them
bold, above section titles set two-and-a-half pixels smaller and dimmer.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re

from tests.js_source_helper import css_rule, function_body, object_literal, read_static

HTML = read_static("index.html")
CSS = read_static("app.css")
APP = read_static("app.js")


def _view_of(anchor: str) -> str:
    """Which Settings sub-view an element ends up in."""
    views = [(m.start(), m.group(1)) for m in re.finditer(r'<div class="set-view" id="([^"]+)"', HTML)]
    at = HTML.index(anchor)
    return [name for pos, name in views if pos < at][-1]


def _font_px(selector: str) -> float:
    """The font-size a selector declares, in px."""
    rule = css_rule(CSS, selector)
    m = re.search(r"font-size:\s*([\d.]+)px", rule)
    assert m, f"{selector} declares no px font-size: {rule}"
    return float(m.group(1))


def _font_px_exact(selector: str) -> float:
    """``_font_px`` for a selector that is a SUFFIX of another one.

    ``css_rule`` finds ``selector + " {"`` as a plain substring, so ``.card h4``
    resolves to ``.brief-bucket .card h4 {`` — which occurs first and declares only
    line-clamping, no size. The guard then failed against perfectly correct CSS: the
    recorded non-unique-needle trap, and the helper's own docstring warns about it.
    Anchoring on the rule's start (newline + indent) is what makes the needle unique.
    """
    m = re.search(
        r"\n\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS
    )
    assert m, f"no rule starting exactly at selector {selector!r}"
    size = re.search(r"font-size:\s*([\d.]+)px", m.group(1))
    assert size, f"{selector} declares no px font-size: {m.group(1)}"
    return float(size.group(1))


# --------------------------------------------------------------------------- #
#  the move
# --------------------------------------------------------------------------- #
def test_diagnostics_lives_in_its_own_advanced_section():
    """Maintainer 2026-08-11: "move all diagnostics from the data / backup subtab
    into a new section in the advanced subtab".

    This supersedes the 2026-08-09 guard that pinned the general diagnostics to Data
    & backup while the AI half moved out. That guard was right for its ask and said
    so; the ask has now changed, and updating it deliberately is the point of having
    written it that way.
    """
    assert _view_of('id="diagnostics-panel"') == "set-advanced"
    assert 'data-adv="diagnostics"' in HTML, "it needs the foldable Advanced wrapper"
    # and it is genuinely a SECTION of Advanced, not loose markup after the last one
    adv = HTML[HTML.index('id="set-advanced"'):]
    # Bounded by the next TAB PAGE, not the next set-view. Advanced is now the LAST
    # Settings view (rulings 26/42 folded Safety into it and retired that subtab), so
    # "the next set-view" no longer occurs and this slice raised rather than failing --
    # a stale ANCHOR, not a broken property. The tab-page that follows Settings (Help)
    # provably occurs, so the slice still ends where Advanced ends, and the assertions
    # below are unchanged: a diagnostics panel left loose after the last section still
    # fails them.
    _end = adv.find('<div class="tab-page"')
    adv = adv[:_end] if _end != -1 else adv
    sec = adv[adv.index('data-adv="diagnostics"'):]
    assert '<section class="panel" id="diagnostics-panel">' in sec
    assert sec.index("</details>") > sec.index('id="diagnostics-panel"'), (
        "the section must close AFTER the panel it wraps"
    )


def test_nothing_was_lost_in_the_move():
    """Absorption, the Desk lesson: the panel moved WHOLE. Every control it carried
    must still exist, and still inside the new section — a diagnostic that quietly
    stayed behind in Data & backup is the failure this pins, not a tidier subtab."""
    for el in (
        "all-diag-btn", "session-forensics-box", "p0-validation-box",
        "discover-cc", "discover-world-status", "gold-builder-path",
        "ir-eval-path", "lemma-preview-body", "reindex-all-status",
    ):
        assert f'id="{el}"' in HTML, f"{el} disappeared in the move"
        assert _view_of(f'id="{el}"') == "set-advanced", f"{el} was left behind"
    # The button, not the bare endpoint: "/api/insights/lunar-correlation" also appears
    # in prose ABOVE the first Settings view, and _view_of reads the first occurrence —
    # the needle has to be unique to the thing being located.
    for endpoint in (
        "/api/diagnostics/keywords?format=zip",
        "/api/diagnostics/rollup-benchmark",
        "/api/signals/flood",
        "/api/signals/bury",
        "/api/insights/lunar-correlation",
    ):
        click = f"window.open('{endpoint}','_blank')"
        assert HTML.count(click) == 1, f"{click} is not a unique anchor"
        assert _view_of(click) == "set-advanced", f"{endpoint}'s button was left behind"


def test_data_and_backup_kept_what_is_actually_about_data():
    """The negative-space twin. This was a move of the diagnostics, not a gutting of
    the subtab: importing, the mailbox pull and the newsletter removal are how a
    corpus goes in and out, and they stay."""
    for el in ("mbox-host", "nl-files", "pdf-files", "nl-remove-panel"):
        assert _view_of(f'id="{el}"') == "set-data", f"{el} should not have moved"
    assert 'id="diagnostics-panel"' not in HTML[
        HTML.index('id="set-data"') : HTML.index('id="set-advanced"')
    ]


def test_opening_advanced_still_fetches_nothing_for_diagnostics():
    """Folded must not mean fetched — satisfied here by construction rather than by a
    loader, because every report in the section is button-driven. Pinned so that a
    future eager load has to be a deliberate edit to this test."""
    loaders = object_literal(APP, "_ADV_LOADERS")
    assert "diagnostics:" not in loaders, (
        "the diagnostics section needs no loader; adding one means something now "
        "fetches on expand, which is a decision, not a refactor"
    )
    show = function_body(APP, "showSetCat")
    data_line = next(ln for ln in show.splitlines() if 'cat === "data"' in ln)
    for gone in ("loadSessionForensics", "runAllDiagnostics", "loadLemmaPreview"):
        assert gone not in data_line


# --------------------------------------------------------------------------- #
#  the type scale
# --------------------------------------------------------------------------- #
#  Retargeted 2026-09-07 (PRH-32) from ``#tab-settings .panel h2/h3`` to the app-wide
#  selectors.  The scale shipped scoped to Settings "because that is what was asked",
#  and the same inversion was still live on every other tab -- measured in Chromium on
#  all 17 themes before the lift: Home's "By channel" rendered 12.5px --muted at
#  4.56-12.71:1 while a briefing card's own <h4> inside it rendered 15px full --fg at
#  6.07-18.10:1.  These guards keep their original PROPERTY and only widen their scope,
#  which is the deliberate supersession the file's other retargeting note describes.
SCALE_H2 = ":where(.panel, dialog) :where(h2)"
SCALE_H3 = ":where(.panel, dialog) :where(h3)"


def test_a_section_name_outranks_everything_inside_it():
    """Maintainer 2026-08-11: "some inner parts of the sections appear bigger or
    brighter than section titles which is confusing."

    Asserted as an ORDERING over the declared sizes rather than as the presence of
    any particular number, so it fails for the reason it is named: something inside a
    section grew past the section's own title.
    """
    body = _font_px("body")
    fold = _font_px(".adv-sec-t")
    h2 = _font_px(SCALE_H2)
    h3 = _font_px(SCALE_H3)
    small = _font_px(".small")
    hint = _font_px(".hint")

    assert fold > h2 > h3 > body, (
        f"headings must step DOWN and stay above body text: fold {fold} > h2 {h2} "
        f"> h3 {h3} > body {body}"
    )
    assert body > small >= hint, f"body {body} > small {small} >= hint {hint}"
    # A card title is the loudest thing a briefing card contains and must still sit
    # UNDER the section that holds it -- this is the pair that was actually inverted
    # on Home, and reading the ladder without it would miss the reported defect.
    card = _font_px_exact(".card h4")
    assert h2 > card, f"a card title ({card}px) must not outrank its section ({h2}px)"


def test_the_hierarchy_survives_translation():
    """It steps on size and weight only. ``text-transform: uppercase`` does nothing
    in Arabic, Chinese, Japanese, Hindi or Bengali, so a title that relied on it read
    as small dim text in five of the twelve locales — the old .panel h2 did exactly
    that. A heading may not lean on case again."""
    for sel in (SCALE_H2, SCALE_H3):
        rule = css_rule(CSS, sel)
        assert "uppercase" not in rule, f"{sel} must not encode rank as letter case"
        assert "font-weight:700" in rule.replace(" ", ""), f"{sel} must carry its own weight"
        assert "var(--fg)" in rule, f"{sel} must be full-brightness, not --muted"


def test_the_old_muted_uppercase_section_title_cannot_come_back():
    """The negative-space twin of the two guards above, and the one that actually
    fails if the lift is reverted: the defect was not "no scale exists", it was a
    MORE SPECIFIC rule re-imposing 12.5px/--muted/uppercase on ``.panel h2``.  A
    zero-specificity ``:where()`` default loses to any such rule silently, so the
    ordering assertions above would still pass while every section title on every tab
    outside Settings went back to being the dimmest thing in its own panel.

    Comment-stripped, because the comment beside the fix necessarily quotes the very
    declarations being forbidden (the recorded must-be-gone-guard trap, in CSS).
    """
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    for banned in (".panel h2 {", ".panel h2{", "#tab-settings .panel h2 {"):
        assert banned not in css, (
            f"{banned!r} re-introduces a class-specificity rule for a section title; the "
            "scale is deliberately zero-specificity so component classes can override it"
        )


def test_a_deliberately_small_label_still_beats_the_scale():
    """Why the scale is written with ``:where()`` and not as ``.panel h3``.

    Three classes name headings that are SUPPOSED to be small -- a briefing family
    lens, a figure caption, a Library sub-heading.  A plain ``.panel h3`` rule carries
    (0,1,1) and would have beaten all three, blowing 12-13px labels up to 15.5px; the
    zero-specificity form loses to every one of them by construction.  Measured live
    before and after the lift: all three read the same px in Chromium.

    Asserted as the specificity RELATION, not as "the classes exist" -- the classes
    existed before the lift too and said nothing about which rule wins.
    """
    for sel, expected in ((".brief-bucket > h3", 12.0), (".fig-title", 13.0), (".lib-sub", 13.0)):
        assert _font_px(sel) == expected, f"{sel} changed size; the scale may be overriding it"
    scale = css_rule(CSS, SCALE_H3)
    assert scale, "the scale rule must exist for this comparison to mean anything"
    # The mechanism itself: every selector in the scale is wrapped, so it contributes
    # no specificity at all.  Drop the :where() and these three labels lose.
    for sel in (SCALE_H2, SCALE_H3):
        assert sel.count(":where(") == 2, (
            f"{sel} must keep BOTH :where() wrappers -- one unwrapped half restores enough "
            "specificity to beat .fig-title and .lib-sub"
        )


def test_the_small_class_actually_has_a_rule():
    """The mechanism behind the report. 35 elements say class="small"; before this
    change none of them were small, and the ones that also set font-weight:600 as an
    ad-hoc sub-heading were therefore louder than the h2 above them."""
    assert _font_px(".small") < _font_px("body")
    used = len(re.findall(r'class="[^"]*\bsmall\b[^"]*"', HTML))
    assert used > 20, f"expected the class to be widely used ({used} found)"


def test_bold_divs_that_act_as_headings_became_headings():
    """Three sub-headings were a bare <div style="font-weight:600">, which is body
    size — bigger than the h3 rule and level with the h2. A heading has to be one."""
    for text in (
        "In the background — enriching your corpus",
        "When you ask — reading and writing for you",
        "Add a custom extractor",
    ):
        at = HTML.index(text)
        tag = HTML.rindex("<", 0, at)
        assert HTML[tag : tag + 3] == "<h3", f"{text!r} is still a {HTML[tag:at][:40]!r}"
    # and the one JS retitles kept its hook
    assert 'id="ai-prompt-form-title"' in HTML
    assert '$("ai-prompt-form-title").textContent' in APP
