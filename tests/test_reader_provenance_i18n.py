"""
Guard: the reader's two-class provenance labels, and the failure-toast
frames, are translatable in every locale.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS (GUI audit 2026-07-28, finding I-2): the reader's group
headings — "From the source", "Deduced by this app — less reliable",
"AI-derived — unreliable" — are the labels that CARRY the reliability claim.
They are server-rendered in ``src/api/main.py``; the reader page loads
``i18n.js``, so they translate IF (and only if) a matching locale key
exists. None did, so they rendered English-only in all 11 non-English
locales — the informed-consent layering degraded exactly where it is
load-bearing ("Every consent/caveat string ships ×12 locales").

And finding I-3: ~37 failure toasts were built by CONCATENATION
(``"Save failed: " + e.message``). A concatenated message is NOT reachable
by i18n.js's DOM walker — the text node is the whole assembled string, which
can never match a static key — so those needed an explicit ``tf()`` frame
whose KEY is the template and whose error detail stays DATA.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.js_source_helper import app_js

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"
_MAIN = _ROOT / "src" / "api" / "main.py"

# The labels that carry the reliability claim, plus the reader chrome around
# them. Each must be a key in EVERY locale or it renders English-only.
_PROVENANCE_LABELS = (
    "From the source",
    "Deduced by this app — less reliable",
    "AI-derived — unreliable",
    "Sources this article cites",
    "Dates mentioned in this text",
)


def _locale(code: str) -> dict:
    return json.loads((_LOCALES / f"{code}.json").read_text(encoding="utf-8"))


def _codes() -> list[str]:
    return sorted(p.stem for p in _LOCALES.glob("*.json"))


def _rendered_main() -> str:
    """main.py with Python implicit string concatenation collapsed.

    The headings are emitted across adjacent string literals, so a naive read
    of the source would not contain the rendered text.
    """
    return re.sub(r'"\s*\n\s*"', "", _MAIN.read_text(encoding="utf-8"))


@pytest.mark.parametrize("label", _PROVENANCE_LABELS)
def test_provenance_label_is_actually_emitted_by_the_reader(label):
    """A key for a string the reader never renders would be dead weight."""
    assert label in _rendered_main(), (
        f"{label!r} is no longer emitted by src/api/main.py -- if the reader "
        "wording changed, update this guard AND re-key the new string; do not "
        "just delete the assertion (that would silently drop it back to "
        "English in 11 locales)"
    )


@pytest.mark.parametrize("label", _PROVENANCE_LABELS)
def test_provenance_label_is_keyed_in_every_locale(label):
    missing = [c for c in _codes() if label not in _locale(c)]
    assert not missing, (
        f"{label!r} has no locale key in {missing} -- this label carries the "
        "reliability claim (asserted vs deduced vs AI-derived), so an "
        "English-only rendering breaches the informed-consent non-negotiable"
    )


def test_provenance_labels_are_really_translated_not_echoed():
    """A key present but echoing English is a silent non-translation."""
    for code in _codes():
        if code == "en":
            continue
        data = _locale(code)
        echoed = [s for s in _PROVENANCE_LABELS if data.get(s) == s]
        assert not echoed, f"{code}: untranslated (English echoed back): {echoed}"


def test_failure_toasts_use_the_translatable_frame_not_concatenation():
    """No `toast("X failed: " + err)` may survive.

    That shape is unreachable by the DOM walker (the text node is the whole
    concatenation) AND unreachable by t() (no lookup happens), so it is
    permanently English however many keys exist.
    """
    src = app_js()
    leftovers = re.findall(r'toast\("[^"]*failed: "\s*\+', src)
    assert not leftovers, (
        f"{len(leftovers)} concatenated failure toast(s) remain: {leftovers[:3]} "
        "-- route them through _failMsg(\"<Action> failed: {error}\", err)"
    )


def test_every_failure_template_is_keyed_and_keeps_its_placeholder():
    """Each _failMsg template needs a key x12, and every translation must
    keep {error} — a dropped placeholder silently swallows the detail the
    user needs to act on."""
    src = app_js()
    templates = sorted(set(re.findall(r'_failMsg\("([^"]+)"', src)))
    assert templates, "no _failMsg call sites found -- did the helper get renamed?"

    for code in _codes():
        data = _locale(code)
        missing = [t for t in templates if t not in data]
        assert not missing, f"{code}: unkeyed failure template(s): {missing[:3]}"
        dropped = [t for t in templates if "{error}" not in data[t]]
        assert not dropped, (
            f"{code}: translation dropped the {{error}} placeholder for "
            f"{dropped[:3]} -- the failure detail would vanish"
        )


def test_failmsg_helper_does_not_depend_on_the_bare_global():
    """The helper must dereference window.OOI18N, not the ambient global.

    The older house idiom `(window.OOI18N && OOI18N.tf)` works only because a
    browser aliases window properties into global scope; it throws in a
    module scope and makes the helper untestable.
    """
    src = app_js()
    body = src.split("function _failMsg(", 1)[1].split("\n    }", 1)[0]
    assert "window.OOI18N" in body, "_failMsg must reach i18n via window.OOI18N"
    assert not re.search(r"[^.\w]OOI18N\.", body), (
        "_failMsg must not dereference the bare global OOI18N"
    )


def test_all_locales_carry_the_same_key_set():
    """A key added to en.json alone reddens the --min 100 gate."""
    counts = {c: len(_locale(c)) for c in _codes()}
    assert len(set(counts.values())) == 1, f"locale key counts diverge: {counts}"


# --------------------------------------------------------------------------- #
# The reader FOOTER caveats (2026-09-10) -- same class, same non-negotiable
# --------------------------------------------------------------------------- #
# Both are server-rendered in main.py and were English-only in all 11 non-English
# locales. One states PROVENANCE ("what you are reading is a frozen copy"), the
# other is a CONSENT warning about outbound exposure (invariant #6/#7). They sit
# beside the labels above and were missed by the same sweep.
_FOOTER_CAVEATS = (
    "This is the copy captured at ingest — it does not change if the source is later edited or removed.",
    "Opening the source makes a live request from your machine; the site may see your visit. You'll be asked to confirm.",
)

#: The skip list this guard was written against. It is NOT the one used below --
#: it is the value a change must be compared to. A hardcoded MIRROR would be worse
#: than useless here: widening the engine's list would leave the copy narrow, so the
#: reach check would keep passing while the caveat silently stopped being translated.
#: (Written as a mirror first, and a mutant that added FOOTER to i18n.js sailed
#: straight through -- the same defect this session had just fixed in the scale-bench
#: drift guard, reproduced in the comment claiming it could not happen.)
_I18N_SKIP_AS_REVIEWED = frozenset({"SCRIPT", "STYLE", "TEXTAREA", "CODE", "PRE"})


def _i18n_skip_tags() -> frozenset[str]:
    """The skip list i18n.js ACTUALLY applies, read out of the engine."""
    src = (_ROOT / "src" / "static" / "i18n.js").read_text(encoding="utf-8")
    m = re.search(r"SKIP\s*=\s*/\^\(([A-Z|]+)\)\$/", src)
    assert m, (
        "could not find i18n.js's SKIP regex -- it was rewritten in a shape this "
        "guard cannot read, so re-derive which elements the walker refuses "
        "instead of assuming the old set still holds"
    )
    return frozenset(m.group(1).split("|"))


def test_the_engines_skip_list_still_matches_what_this_guard_was_reviewed_against():
    """Pin the engine's list so WIDENING it is a red test rather than a silent
    behaviour change. The reach check below uses the engine's real value, so
    without this the two could drift apart in the safe-looking direction."""
    actual = _i18n_skip_tags()
    assert actual == _I18N_SKIP_AS_REVIEWED, (
        f"i18n.js's SKIP list changed: {sorted(actual)} vs the reviewed "
        f"{sorted(_I18N_SKIP_AS_REVIEWED)}. Re-check every server-rendered caveat "
        "against the new set before updating this constant -- a widened list can "
        "silently un-translate strings that keep all twelve of their keys."
    )


def _reader_text_node_parents() -> dict[str, str]:
    """Parent tag of the text node each caveat lives in, from the rendered template.

    Parsed rather than reasoned about: i18n.js's walker tests ``n.parentNode``'s
    nodeName against its skip list, so the only thing that decides whether a
    server-rendered caveat is translatable is which element DIRECTLY contains it.
    """
    from html.parser import HTMLParser

    html = _rendered_main()
    html = html[html.index("<!DOCTYPE html>"):]

    class _P(HTMLParser):
        VOID = {"br", "img", "meta", "link", "hr", "input"}

        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.stack: list[str] = []
            self.found: dict[str, str] = {}

        def handle_starttag(self, tag, attrs):
            if tag not in self.VOID:
                self.stack.append(tag)

        def handle_endtag(self, tag):
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass

        def handle_data(self, data):
            for caveat in _FOOTER_CAVEATS:
                if caveat[:40] in data and caveat not in self.found:
                    self.found[caveat] = self.stack[-1] if self.stack else "<root>"

    parser = _P()
    parser.feed(html)
    return parser.found


@pytest.mark.parametrize("caveat", _FOOTER_CAVEATS)
def test_footer_caveat_is_actually_emitted_by_the_reader(caveat):
    assert caveat in _rendered_main(), (
        f"{caveat[:60]!r}... is no longer emitted by src/api/main.py -- if the "
        "wording changed, re-key the new string rather than deleting this "
        "assertion, or it drops back to English in 11 locales"
    )


@pytest.mark.parametrize("caveat", _FOOTER_CAVEATS)
def test_footer_caveat_is_keyed_in_every_locale(caveat):
    missing = [c for c in _codes() if caveat not in _locale(c)]
    assert not missing, (
        f"{caveat[:60]!r}... has no locale key in {missing} -- one states that "
        "the copy is frozen at ingest and the other warns that opening the "
        "source exposes the reader to the site, so English-only breaches the "
        "informed-consent non-negotiable"
    )


def test_footer_caveats_are_really_translated_not_echoed():
    for code in _codes():
        if code == "en":
            continue
        data = _locale(code)
        echoed = [c[:50] for c in _FOOTER_CAVEATS if data.get(c) == c]
        assert not echoed, f"{code}: untranslated (English echoed back): {echoed}"


@pytest.mark.parametrize("caveat", _FOOTER_CAVEATS)
def test_the_i18n_walker_can_actually_REACH_each_footer_caveat(caveat):
    """A key proves the translation EXISTS; this proves the engine would apply it.

    i18n.js walks text nodes and refuses any whose DIRECT parent is SCRIPT, STYLE,
    TEXTAREA, CODE or PRE. So a caveat moved into a <pre> block -- or wrapped in
    <code> to style it as literal -- would keep its twelve keys and silently
    render English forever, with every other assertion in this file still green.
    That is the shape of failure this project keeps meeting: the wiring checks out
    and the output never changes.
    """
    parents = _reader_text_node_parents()
    parent = parents.get(caveat)
    assert parent is not None, (
        f"{caveat[:60]!r}... was not found as a TEXT NODE in the reader template "
        "-- if it moved into an attribute, this guard needs the attribute path "
        "instead (i18n.js translates title/placeholder/aria-label separately)"
    )
    assert parent.upper() not in _i18n_skip_tags(), (
        f"{caveat[:60]!r}... now sits directly inside <{parent}>, which i18n.js "
        f"SKIPS -- it keeps its locale keys and renders English in every locale"
    )
