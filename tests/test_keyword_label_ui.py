"""The driver for ``keyword_label_node_test.js`` + the ×12 coverage of its strings.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Two different claims, which is why they are two tests. The node suite proves the LABEL
GRAMMAR by running the shipped renderer (Q401's inversion, the four tiers, the two
refusals). This file proves that every string that grammar emits exists in all twelve
locale files — a claim the three i18n gates cannot make on these strings' behalf, because
they are RATCHETS over the whole tree: an improving codebase can move a max-gate the same
way a new key does, so "the gate is green" is not evidence that THESE strings are covered.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_LOCALES = _ROOT / "src" / "static" / "locales"

#: Every string the keyword label can put on screen. The two `{language}` templates are
#: FRAMES: the frame is keyed ×12 and the language NAME substituted into it comes from
#: CLDR in the reader's own locale (Q402 = a), so this is twelve keys rather than the
#: 144 hand-written language names the roadmap sheet's context assumed already existed.
#: (They do not — `fr.json` carried exactly one, "English". Checked, not assumed.)
_LABEL_STRINGS = [
    "translated from {language}",
    "in {language}",
    "Not translated — shown in its own language.",
    "Several senses",
    "Original",
    "Concept",
    "Across languages:",
    "Open a local preview of this source first",
]


def test_keyword_label_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "keyword_label_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "keyword_label_node_test.js: OK" in proc.stdout


def test_the_reader_draws_the_same_label_m7() -> None:
    """M7: the standalone reader's Keywords tab drew the bare stored word, because the page
    does not load the SPA helper. Its port is driven as real code, and its fetch asks for
    the reader's language -- without it the port would have nothing to draw."""
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "reader_label_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "reader_label_node_test.js: OK" in proc.stdout
    reader = (_ROOT / "src" / "static" / "reader.js").read_text(encoding="utf-8")
    assert '"&target_lang=" + encodeURIComponent(uiLang())' in reader
    assert "rdLabelHtml(t)" in reader, "renderKeywords no longer draws through the port"


def test_every_label_string_is_keyed_in_all_twelve_locales() -> None:
    missing: list[str] = []
    for path in sorted(_LOCALES.glob("*.json")):
        # encoding= is not optional: this tree's utf8 guard scans for it, and on a
        # cp1252 default these files (curly quotes, em dashes) would CRASH the read
        # rather than fail an assertion.
        data = json.loads(path.read_text(encoding="utf-8"))
        for s in _LABEL_STRINGS:
            if s not in data:
                missing.append(f"{path.name}: {s!r}")
    assert not missing, "label strings missing from a locale file:\n  " + "\n  ".join(missing)
    # ANTI-VACUITY: twelve files, or this passed over a directory it could not read.
    assert len(list(_LOCALES.glob("*.json"))) == 12


def test_a_translated_frame_keeps_its_placeholder_verbatim() -> None:
    """A `{placeholder}` with no matching var renders a LITERAL `{language}` to the
    reader, and a translator who renamed or localised the brace would produce exactly
    that — in one locale, invisibly, on a surface no English-speaking reviewer opens.

    Asserted per LOCALE and per STRING, because a check whose subject is broader than its
    claim can pass for the wrong reason: a sweep over the concatenation of all twelve
    would be satisfied by eleven correct files."""
    bad: list[str] = []
    for path in sorted(_LOCALES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for s in ("translated from {language}", "in {language}"):
            value = data.get(s)
            if value is None:
                continue  # the coverage test above is what reports an absence
            if "{language}" not in value:
                bad.append(f"{path.name}: {s!r} -> {value!r} lost its placeholder")
    assert not bad, "a translated frame cannot render its data:\n  " + "\n  ".join(bad)


def test_the_card_title_template_is_the_ruling_verbatim() -> None:
    """Q411 = a gives the template in the ruling itself:
    ``"{term_translation}" (translated from {term_lang}: {term})``.

    Pinned against the RULING rather than against whatever the code happens to emit,
    because this is the one string in the slice whose exact wording a maintainer chose.
    The quotes in the shipped constant are curly (typographic), which is the house
    convention every other card title already follows — asserted on the HOLES, not on the
    punctuation, so a future typographic change cannot redden it while the frame is intact.
    """
    from src.api.briefing import _TRANSLATED_TITLE

    holes = set(re.findall(r"\{(\w+)\}", _TRANSLATED_TITLE))
    assert holes == {"term_translation", "term_lang", "term"}, (
        f"the card template's holes drifted from Q411 = a: {sorted(holes)}"
    )
    assert "translated from" in _TRANSLATED_TITLE
    # ...and it is keyed ×12 like every other frame, or eleven locales render it in English.
    for path in sorted(_LOCALES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert _TRANSLATED_TITLE in data, f"{path.name}: the Q411 card template has no key"
        value = data[_TRANSLATED_TITLE]
        assert set(re.findall(r"\{(\w+)\}", value)) == holes, (
            f"{path.name}: the translated frame lost a hole -> {value!r}"
        )


def test_every_surface_that_renders_a_keyword_label_also_repaints_on_a_language_switch() -> None:
    """The guard that makes the repaint list a PROPERTY instead of a memory.

    The keyword label opts out of the i18n DOM walker (`data-i18n-dyn`), because the
    walker translates any text node that exactly matches a key and cannot tell a keyword
    from chrome. That opt-out costs the repaint: nothing re-renders these labels on a
    language switch, so each surface must be re-run explicitly.

    THE FIRST VERSION OF THAT LIST WAS WRITTEN FROM MEMORY AND WAS WRONG ABOUT THREE OF
    ITS FOUR HOST IDS. No test could see it — the helper was correct, the keys were in all
    twelve locale files, the node suite passed — and a Chromium walk through en → fr → ar →
    zh showed the Home trends panel reading "in Russian" in all four, because `#home-trends`
    was not on the list. So the list is now DERIVED from the call sites, and this asserts
    that derivation holds: every function that renders a label is named in the repaint set.
    A new keyword surface therefore fails HERE, at the moment it is added, rather than
    silently freezing in whichever locale painted it first.
    """
    import re

    from tests.js_source_helper import app_js, function_body

    app = app_js()
    # The SHARED extractor, not a hand-rolled slice: `tests/js_source_helper.py` carries
    # brace-, bracket- and literal-matching with each failure mode pinned, and the
    # slicing-discipline ratchet exists precisely to stop a thirty-ninth private copy.
    body = function_body(app, "ooKwRepaintOnLangChange")
    renderers = set()
    # `kwLabelParts` too (M7): the analysis mind map draws the label as SVG text from the
    # same rules, and a renderer reaching them through the parts is as frozen as one
    # reaching them through the HTML if nothing re-runs it.
    for m in re.finditer(r"kwLabel(?:Html|Parts)\(", app):
        before = app[: m.start()]
        fn = None
        for fm in re.finditer(r"\n\s*(?:async\s+)?function\s+(\w+)\s*\(", before):
            fn = fm.group(1)
        if fn:
            renderers.add(fn)
    # The helper itself and its own documentation mention the name; they are not surfaces.
    renderers -= {"kwLabelHtml", "kwLabelParts", "_kwLabelState", "kwQidHtml", "kwHoverText",
                  "kwSensePickerHtml", "kwHasTag"}
    assert renderers, "no renderer found at all -- the scan is looking in the wrong place"
    assert "renderAnMindmap" in renderers, (
        "the scan no longer sees the mind map's label -- is it reading kwLabelParts?"
    )
    # A repaint entry may be a function that RE-FETCHES and then re-draws (the mind map's
    # `anMindmapRepaint`, whose nodes carry translations into the old language, so drawing
    # the held payload again would be wrong). What it re-draws is covered through it.
    repaint_fns = set(re.findall(r'\[\s*(?:"[^"]*"|null)\s*,\s*"(\w+)"', body))
    # ...and every repainter the `oo:langchange` listeners call DIRECTLY (2026-09-27 re-walk
    # M-3/M-5): the Bulletin's `_bulRepaint` redraws its Review from the payload it holds,
    # and the Review's story terms now draw the label. Re-running it is the same guarantee
    # as a list entry, so a function the listener runs counts as a repaint too; listing it
    # again in the keyword list would only paint the panel twice.
    from tests.js_source_helper import event_listener_bodies

    for lb in event_listener_bodies(app, "oo:langchange"):
        for called in re.findall(r"(?<![\w$.])(\w+)\(", lb):
            if re.search(rf"\n\s*(?:async\s+)?function\s+{re.escape(called)}\s*\(", app):
                repaint_fns.add(called)
    redrawn = {
        callee
        for r in repaint_fns
        for callee in re.findall(r"(?<![\w$.])(\w+)\(", function_body(app, r))
    }

    # A renderer is COVERED when it is named in the repaint set, OR when every function
    # that calls it is. `termListHtml` is the case that forced this: it is a pure HTML
    # builder with no host of its own, and `loadTrendWindows` -- which is on the list --
    # is what draws it. Requiring the builder itself on the list would be asking for a
    # host that does not exist; ignoring builders by NAME ("anything not called load*")
    # would be a convention, not a property. Following the call is the property.
    def covered(fn: str, seen: set[str]) -> bool:
        if fn in body or fn in redrawn:
            return True
        if fn in seen:
            return False  # a cycle reaches no repainted surface
        seen.add(fn)
        callers = set()
        # `(?<!function )` matters: the DEFINITION `function termListHtml(` matches the
        # bare name pattern too, and the enclosing-function scan then attributes it to
        # whatever function happens to sit above it in the file -- a caller that does not
        # exist. That misattribution is what this pattern's first draft reported.
        # A renderer handed over BY REFERENCE (`.map(sgCard)`) is called by the function
        # that hands it over, so that function is a caller too (M7: the super-group cards).
        for cm in re.finditer(rf"(?<![\w$.])(?<!function ){re.escape(fn)}(?:\(|\s*[),])", app):
            head = app[: cm.start()]
            outer = None
            for fm in re.finditer(r"\n\s*(?:async\s+)?function\s+(\w+)\s*\(", head):
                outer = fm.group(1)
            if outer and outer != fn:
                callers.add(outer)
        return bool(callers) and all(covered(c, seen) for c in callers)

    missing = sorted(fn for fn in renderers if not covered(fn, set()))
    assert not missing, (
        "these functions render a keyword label and neither they nor any of their callers "
        "are re-run on oo:langchange, so their labels freeze in whichever locale painted "
        f"them first: {missing}"
    )


# --------------------------------------------------------------------------- #
#  The delegated click-through of 2026-09-26, row M (M2, M3, M4, M8)
# --------------------------------------------------------------------------- #


def test_a_tag_inside_a_keyword_row_keeps_its_own_hover_m2() -> None:
    """M2: on a ``data-kwstat`` chip the keyword-stats handler took the enclosing chip for
    every hover and overwrote the bubble ooTipInit had just opened for the tier tag, so
    Q418's hover (original, language, QID) was unreachable. The handler must stand down
    when the pointer is on a hover target of its own INSIDE the row, and the chips must
    carry the tag's hover on the row for a keyboard reader."""
    from tests.js_source_helper import app_js, function_body, function_source, strip_comments

    app = app_js()
    boot = function_source(app, "ooKwStatInit")
    on_hover = strip_comments(function_body(boot, "onHover"))
    assert 'closest(".oo-tip-target")' in on_hover, "the stats handler no longer looks for an inner hover target"
    assert "inner !== el && el.contains(inner)" in on_hover and "hovered = null" in on_hover
    chips = strip_comments(function_body(app, "anRenderKwChips"))
    assert "kwTipExtraAttr(term)" in chips, "the analysis chips carry no tier hover for the keyboard"


def test_the_tag_inside_a_filled_chip_takes_the_chips_text_colour_m3() -> None:
    """M3: the analysis chips are ``<button class="chip">``, filled with --accent by the
    global button rule; the tag's own accent/muted colours measured 1.14:1 on that fill.
    Inside a filled chip the tag inherits the chip's --accent-fg, and that pair clears
    AA on every theme."""
    from tests.js_source_helper import css_rule
    from tests.test_theme_contrast_and_donut_guard import _ratio, _theme_tokens

    css = (_ROOT / "src" / "static" / "app.css").read_text(encoding="utf-8")
    rule = css_rule(css, "button.chip .kw-tag, button.chip .kw-qid")
    assert "color: inherit" in rule and "currentColor" in rule, rule
    tokens = _theme_tokens()
    assert len(tokens) >= 17
    weak = []
    for name, t in sorted(tokens.items()):
        fg, fill = t.get("accent-fg"), t.get("accent")
        if fg and fill and _ratio(fg, fill) < 4.5:
            weak.append(f"{name} {_ratio(fg, fill):.2f}")
    assert not weak, f"the chip's own text colour fails AA on its fill: {weak}"


def test_the_sense_picker_sits_outside_the_chip_and_a_pick_is_read_m4() -> None:
    """M4: the picker's buttons nested inside the chip's <button> were hoisted out by the
    parser, and no code read ``data-kwpin``, so a pick changed nothing."""
    from tests.js_source_helper import app_js, event_listener_bodies, function_body, strip_comments

    app = app_js()
    chips = strip_comments(function_body(app, "anRenderKwChips"))
    assert "kwLabelHtml(term, {inButton: true})" in chips
    assert "</button>${kwSensesAfterHtml(term, pins)}" in chips, "the picker is not drawn after the chip"
    insights = (_ROOT / "src" / "static" / "app-insights.js").read_text(encoding="utf-8")
    assert "kwLabelHtml(f, {inButton: true})" in insights and "</button>${kwSensesAfterHtml(f)}" in insights, (
        "the landscape chip is a <button> too"
    )
    clicks = event_listener_bodies(app, "click")
    assert any("[data-kwpin]" in h and "kwPickSense(" in h and "stopPropagation" in h for h in clicks), (
        f"no delegated click listener reads the sense picker ({len(clicks)} click listener(s) found)"
    )


def test_a_language_switch_reloads_what_holds_translations_m8() -> None:
    """M8: the repaint called ``loadLandscape()``, which returns early once loaded, and
    re-rendered the analysis chips from a payload fetched for the OLD target language."""
    from tests.js_source_helper import app_js, function_body, strip_comments

    app = app_js()
    body = strip_comments(function_body(app, "ooKwRepaintOnLangChange"))
    assert '["ins-landscape", "loadLandscape", true]' in body
    assert '[null, "anRenderKwChips", {refetch: true}]' in body
    assert "window[fn](arg)" in body, "the per-surface argument is never passed"
    chips = strip_comments(function_body(app, "anRenderKwChips"))
    assert "opts.refetch" in chips and "_anRefetchKw()" in chips
    refetch = strip_comments(function_body(app, "_anRefetchKw"))
    assert "tgtLangParam()" in refetch and "corpus-keywords" in refetch
    landscape = strip_comments(function_body(app, "loadLandscape"))
    assert "if (_landscapeLoaded && !force) return;" in landscape


def test_the_trend_rows_draw_the_label_through_the_one_helper_m7() -> None:
    """M7 (the row's closing criterion: every keyword surface draws a foreign word with its
    tier tag). Home's "Trending now" row, the three-window sparkline rows and the Trends
    bars drew ``esc(x.term)`` -- the bare original, never the translation, never a tag.

    Each is a LINK, so each calls the helper with ``{inLink: true}`` and draws the QID
    after its closing tag: a nested anchor closes the outer one early and spills the rest
    of the row out of it. The rendered strings are driven in
    ``term_bars_hover_node_test.js`` and ``keyword_label_node_test.js``; this pins that
    the surfaces still call them."""
    from tests.js_source_helper import app_js, function_body, strip_comments

    app = app_js()
    for fn in ("_renderOverviewTrends", "loadTrendWindows", "termBarsHtml", "termListHtml"):
        body = strip_comments(function_body(app, fn))
        assert re.search(r"kwLabelHtml\((?:x|t), \{inLink: true\}\)", body), f"{fn} draws a bare keyword"
        assert "kwQidHtml(" in body, f"{fn} drops the QID the label left for it"
        assert not re.search(r">\$\{esc\((?:x|t)\.term\)\}</a>", body), f"{fn} still draws a bare term"
