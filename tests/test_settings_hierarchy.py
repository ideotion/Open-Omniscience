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
    adv = adv[: adv.index('<div class="set-view"')]
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
def test_a_section_name_outranks_everything_inside_it():
    """Maintainer 2026-08-11: "some inner parts of the sections appear bigger or
    brighter than section titles which is confusing."

    Asserted as an ORDERING over the declared sizes rather than as the presence of
    any particular number, so it fails for the reason it is named: something inside a
    section grew past the section's own title.
    """
    body = _font_px("body")
    fold = _font_px(".adv-sec-t")
    h2 = _font_px("#tab-settings .panel h2")
    h3 = _font_px("#tab-settings .panel h3")
    small = _font_px(".small")
    hint = _font_px(".hint")

    assert fold > h2 > h3 > body, (
        f"headings must step DOWN and stay above body text: fold {fold} > h2 {h2} "
        f"> h3 {h3} > body {body}"
    )
    assert body > small >= hint, f"body {body} > small {small} >= hint {hint}"


def test_the_hierarchy_survives_translation():
    """It steps on size and weight only. ``text-transform: uppercase`` does nothing
    in Arabic, Chinese, Japanese, Hindi or Bengali, so a title that relied on it read
    as small dim text in five of the twelve locales — the old .panel h2 did exactly
    that. A heading may not lean on case again."""
    for sel in ("#tab-settings .panel h2", "#tab-settings .panel h3"):
        rule = css_rule(CSS, sel)
        assert "uppercase" not in rule, f"{sel} must not encode rank as letter case"
        assert "font-weight:700" in rule.replace(" ", ""), f"{sel} must carry its own weight"
        assert "var(--fg)" in rule, f"{sel} must be full-brightness, not --muted"


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
