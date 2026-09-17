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
    for m in re.finditer(r"kwLabelHtml\(", app):
        before = app[: m.start()]
        fn = None
        for fm in re.finditer(r"\n\s*(?:async\s+)?function\s+(\w+)\s*\(", before):
            fn = fm.group(1)
        if fn:
            renderers.add(fn)
    # The helper itself and its own documentation mention the name; they are not surfaces.
    renderers -= {"kwLabelHtml", "kwQidHtml", "kwHoverText", "kwSensePickerHtml"}
    assert renderers, "no renderer found at all -- the scan is looking in the wrong place"

    # A renderer is COVERED when it is named in the repaint set, OR when every function
    # that calls it is. `termListHtml` is the case that forced this: it is a pure HTML
    # builder with no host of its own, and `loadTrendWindows` -- which is on the list --
    # is what draws it. Requiring the builder itself on the list would be asking for a
    # host that does not exist; ignoring builders by NAME ("anything not called load*")
    # would be a convention, not a property. Following the call is the property.
    def covered(fn: str, seen: set[str]) -> bool:
        if fn in body:
            return True
        if fn in seen:
            return False  # a cycle reaches no repainted surface
        seen.add(fn)
        callers = set()
        # `(?<!function )` matters: the DEFINITION `function termListHtml(` matches the
        # bare name pattern too, and the enclosing-function scan then attributes it to
        # whatever function happens to sit above it in the file -- a caller that does not
        # exist. That misattribution is what this pattern's first draft reported.
        for cm in re.finditer(rf"(?<![\w$.])(?<!function ){re.escape(fn)}\(", app):
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
