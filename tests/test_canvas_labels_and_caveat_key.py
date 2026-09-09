"""Two i18n routing defects whose root cause lives outside the DOM the walker
can reach: the Observatory's canvas-painted domain labels, and the Agenda's
dynamic top caveat.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Owned by the canvas-and-caveat fix agent (docs/audit/11_VISUAL_UI_AUDIT_2026-09-08.md).
This file is new and exclusively owned by that pass -- it must not collide with
any other test file.

(a) ``src/static/oosky.js``'s ``drawSky`` paints the 12 domain-wedge labels with
    ``ctx.fillText`` directly on a canvas. A canvas has no DOM node, so neither
    OOI18N's TreeWalker nor its MutationObserver can ever reach that text --  it
    must be translated BEFORE it is painted, using the exact same
    ``OOI18N.t`` every other JS-built string in this app goes through. This is
    verified by actually EXECUTING ``drawSky`` under Node with a fake canvas
    context that records every ``fillText`` call, once with no translator
    present (the pre-existing, English-only behaviour a browser without
    OOI18N would still need to survive) and once with a translator installed --
    proving the painted text changes and, just as importantly, that the
    underlying coordinates do NOT (translation must change the label, never the
    geometry -- invariant #31).

(b) ``src/api/events.py``'s ``_CAVEAT`` is rendered into a single DOM text node
    client-side (``app-agenda.js``'s ``$("agenda-monthhint").textContent =
    AG.caveat``), and OOI18N's DOM walker only ever does a whole-node EXACT
    match against a locale key (``src/static/i18n.js``'s ``tr()``). The fix
    keeps the app's current "agenda" terminology (the tab's own static header,
    index.html, already reads "Agenda -- major world events") but restores the
    same period-separated sentence boundaries as the three sentences the
    locale files already carry real, non-English-passthrough translations for
    -- so only the first sentence's one changed word is new translation work.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from src.api.events import _CAVEAT

_ROOT = Path(__file__).resolve().parents[1]
_OOSKY = _ROOT / "src" / "static" / "oosky.js"
_LOCALES = _ROOT / "src" / "static" / "locales"

# --------------------------------------------------------------------------- #
# (a) the canvas domain labels
# --------------------------------------------------------------------------- #

_NODE_HARNESS = r"""
const path = require("path");
const S = require(process.argv[2]);

const payload = {
  galaxies: [
    { id: "g1", name: "alpha", domain: "Technology",
      measures: { distinct_sources: 3, mentions: 10 } },
    { id: "g2", name: "beta", domain: "Sport & infrastructure",
      measures: { distinct_sources: 1, mentions: 2 } },
  ],
  clusters: [],
  nebula: null,
};
const layout = S.skyLayout(payload, {});
const theme = {
  bg: "#000", muted: "#888", border: "#333", tickFont: "10px sans",
  edge: "#555", fg: "#fff", colorOf: () => "#fff",
};
const view = { w: 400, h: 400, ox: 0, oy: 0, scale: 1, focus: null, hover: null };

function fakeCtx() {
  const c = {
    calls: [],
    save() {}, restore() {}, beginPath() {}, stroke() {}, fill() {},
    moveTo() {}, lineTo() {}, arc() {}, clearRect() {}, fillRect() {},
    setLineDash() {},
    measureText(s) { return { width: (s || "").length * 6 }; },
    fillText(s, x, y) { c.calls.push([s, x, y]); },
  };
  return c;
}

// Run 1: no translator installed at all (must not throw -- this module is
// dual node/browser and tests/oosky_node_test.js requires it in plain Node
// with no `window`/`OOI18N` global of any kind).
delete global.OOI18N;
const ctxNoTr = fakeCtx();
S.drawSky(ctxNoTr, layout, theme, view);

// Run 2: the SAME translation function every other JS-built string in this
// app uses (window.OOI18N.t), reachable here as global.OOI18N.t since Node's
// `global` IS the `globalThis` this module captured as `root` at load time.
global.OOI18N = {
  t(s) {
    if (s === "Technology") return "TR_TECHNOLOGY";
    if (s === "Sport & infrastructure") return "TR_SPORT";
    return s;
  },
};
const ctxTr = fakeCtx();
S.drawSky(ctxTr, layout, theme, view);

function domainCalls(calls) {
  return calls.filter(([s]) => s === "Technology" || s === "Sport & infrastructure"
    || s === "TR_TECHNOLOGY" || s === "TR_SPORT");
}

console.log(JSON.stringify({
  untranslated: domainCalls(ctxNoTr.calls),
  translated: domainCalls(ctxTr.calls),
}));
"""


def _run_canvas_harness() -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(_NODE_HARNESS)
        script = f.name
    try:
        proc = subprocess.run(
            ["node", script, str(_OOSKY)],
            capture_output=True, text=True, cwd=str(_ROOT), check=False,
        )
        assert proc.returncode == 0, (
            f"the drawSky harness crashed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
        return json.loads(proc.stdout.strip().splitlines()[-1])
    finally:
        Path(script).unlink(missing_ok=True)


def test_canvas_domain_labels_survive_with_no_translator_present() -> None:
    """Node-safety: oosky.js must not crash when there is no OOI18N global at
    all (a bare Node environment, or a future browser context where it hasn't
    loaded yet) -- and must fall back to the raw English domain name, exactly
    as every other `(window.OOI18N && OOI18N.t) ? OOI18N.t : (s) => s` call
    site in this app does on first paint.
    """
    result = _run_canvas_harness()
    painted = [s for s, _x, _y in result["untranslated"]]
    assert "Technology" in painted
    assert "Sport & infrastructure" in painted


def test_canvas_domain_labels_are_translated_before_painting() -> None:
    """THE regression: against the old code, `ctx.fillText(da.domain, ...)`
    painted the raw backend string no matter what OOI18N.t said, so this
    assertion fails on the old `oosky.js` (TR_TECHNOLOGY / TR_SPORT never
    appear) and passes once the label is routed through the translator before
    being painted.
    """
    result = _run_canvas_harness()
    painted = [s for s, _x, _y in result["translated"]]
    assert "TR_TECHNOLOGY" in painted, (
        "the translated domain label never reached fillText -- the label is "
        "still being painted untranslated"
    )
    assert "TR_SPORT" in painted
    # And the untranslated raw strings must be GONE from this run -- a mix
    # would mean only some labels route through the translator.
    assert "Technology" not in painted
    assert "Sport & infrastructure" not in painted


def test_translating_the_label_never_moves_its_coordinate() -> None:
    """Invariant #31: the sky is deterministic by construction and translation
    is a LABEL change, never a geometry change. Same domain, same wedge, same
    (x, y) whether or not a translator is installed -- only the painted string
    may differ.
    """
    result = _run_canvas_harness()
    by_text_untr = {s: (x, y) for s, x, y in result["untranslated"]}
    by_text_tr = {s: (x, y) for s, x, y in result["translated"]}
    assert by_text_untr["Technology"] == by_text_tr["TR_TECHNOLOGY"]
    assert by_text_untr["Sport & infrastructure"] == by_text_tr["TR_SPORT"]


def test_drawsky_never_references_a_bare_window_global() -> None:
    """This module is dual node/browser (its own header says so) and is
    `require()`d directly by tests/oosky_node_test.js under plain Node, where a
    bare `window` identifier throws a ReferenceError rather than evaluating to
    undefined. The translation lookup this fix adds must go through `root`
    (the module's own self/globalThis capture), never a bare `window.*`
    reference, or it would crash the existing node suite the moment any code
    path reaches it.
    """
    src = _OOSKY.read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    assert not re.search(r"[^.\w]window\s*\.\s*OOI18N", src), (
        "found a bare `window.OOI18N` reference in oosky.js -- use `root.OOI18N` "
        "instead so this module stays safe to require() under plain Node"
    )


def test_oosky_node_suite_still_passes() -> None:
    """The translation fix must not disturb the pure-geometry suite this file's
    own header says is the honesty spine's real test coverage.
    """
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "oosky_node_test.js")],
        capture_output=True, text=True, cwd=str(_ROOT), check=False,
    )
    assert proc.returncode == 0, f"oosky_node_test.js failed:\n{proc.stdout}\n{proc.stderr}"


# --------------------------------------------------------------------------- #
# (b) the Agenda's top caveat -- stale-key drift, not a missing translation
# --------------------------------------------------------------------------- #

_REUSED_SENTENCES = [
    "Fixed civic dates are confirmed.",
    "Summit/meeting dates move each year — follow the official source for the exact date.",
    "Nothing here is fabricated.",
]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.findall(r"[^.]+\.", text)]


def test_caveat_has_no_semicolon_joined_sentence() -> None:
    """THE regression: the old `_CAVEAT` joined its middle two sentences with a
    semicolon ("confirmed; summit/meeting..."), which does not merely read
    oddly -- it moves the sentence boundary away from the ones the locale
    files already carry real translations for, in every one of the 12
    languages, no matter how the wording itself is fixed. This assertion fails
    against the old string (which contains ";") and passes against the new one.
    """
    assert ";" not in _CAVEAT


def test_caveat_reuses_the_three_already_translated_sentence_keys() -> None:
    """Sentences 2-4 of the served caveat must be BYTE-IDENTICAL to keys that
    already carry real (non-English-passthrough) translations in all 12
    locale files -- proven here by reading the files directly, not assumed.
    This is what lets a locale agent close the gap by adding ONE new key (the
    first sentence's "agenda" wording) instead of retranslating the whole
    paragraph from scratch.
    """
    sentences = _sentences(_CAVEAT)
    assert len(sentences) == 4, (
        f"expected 4 whole sentences (one fillable, three already-keyed), got {sentences!r}"
    )
    assert sentences[1:] == _REUSED_SENTENCES

    locale_files = sorted(_LOCALES.glob("*.json"))
    assert len(locale_files) == 12, f"expected 12 locales, found {len(locale_files)}"
    for path in locale_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for s in _REUSED_SENTENCES:
            assert s in data, f"{path.name} is missing the existing key {s!r}"


def test_caveat_keeps_the_current_agenda_wording() -> None:
    """The "calendar" wording sitting orphaned in every locale file is the
    PRE-RENAME term (the Agenda tab's own static header two lines above this
    same caveat in index.html already reads "Agenda -- major world events").
    The right repair is a new key for the current wording, not a revert to the
    stale one -- pin that decision here so a future edit cannot silently flip
    it back while chasing the same i18n bug.
    """
    assert "A forward-looking agenda of major recurring events." in _CAVEAT
    assert "calendar" not in _CAVEAT.lower()


def test_caveat_first_sentence_is_not_already_a_key_anywhere() -> None:
    """Sanity check on the report to the locale agent: confirm the ONE new
    string this fix actually needs translated (the first sentence, current
    wording) is not already sitting in a locale file under some other guise --
    if it were, this would be a missing-wiring bug, not a missing-translation
    one, and the fix would be different.
    """
    sentences = _sentences(_CAVEAT)
    first = sentences[0]
    for path in sorted(_LOCALES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert first not in data, (
            f"{path.name} unexpectedly already has a key for {first!r} -- "
            "re-check whether this still needs reporting as a new string"
        )


def test_the_served_caveat_is_a_whole_paragraph_key_in_every_locale() -> None:
    """THE GUARD THE REST OF THIS SECTION DOES NOT PROVIDE, added 2026-09-09.

    Everything above pins the caveat's SHAPE — no semicolon, four sentences, the
    last three byte-identical to existing keys. None of it makes the caveat
    translate, and it is worth being exact about why, because the shape work is
    what makes the real fix cheap rather than being the fix.

    ``src/static/i18n.js``'s ``tr()`` looks up ``map[core]`` where ``core`` is one
    whole TEXT NODE with its internal whitespace normalised — an exact, whole-node
    match, with no sentence splitting and no substring replacement anywhere in the
    walker. ``app-agenda.js`` renders this caveat into a single ``<p class="hint">``
    via ``esc(v.caveat)``, so the node the walker sees is the ENTIRE paragraph.
    Only a key equal to the entire paragraph can ever match it: with the four
    sentences keyed individually and the paragraph not, the Agenda caveat renders
    in English in all eleven non-English locales, exactly as it did before the
    sentence boundaries were moved.

    So assert the thing the user actually sees. Verified in Chromium at fr, ar,
    ja and zh after this key was added.
    """
    assert _CAVEAT.strip() == _CAVEAT, "a stray edge space would change the lookup key"
    for path in sorted(_LOCALES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert _CAVEAT in data, (
            f"{path.name} has no whole-paragraph key for the served Agenda caveat — "
            "the four sentences being keyed individually does NOT translate it, "
            "because i18n.js matches whole text nodes"
        )
        value = data[_CAVEAT]
        assert isinstance(value, str) and value.strip(), f"{path.name}: empty translation"
        if path.stem != "en":
            assert value != _CAVEAT, (
                f"{path.name} carries the English string as its own translation — "
                "an untranslated passthrough, not a translation"
            )
        # The composed paragraph must still END with that locale's OWN translation
        # of the three shared sentences, so the caveat can never drift away from
        # the identical sentences the rest of the app already shows.
        for sentence in _REUSED_SENTENCES:
            assert data[sentence] in value, (
                f"{path.name}: the paragraph no longer contains its own translation of "
                f"{sentence!r} — it has drifted from the shared wording"
            )


def test_the_caveat_paragraph_never_double_spaces_cjk_punctuation() -> None:
    """Composed from per-sentence translations, so the JOIN is a real decision.

    Japanese and Chinese sentence-final punctuation (。) already carries the space
    a reader expects; an ASCII space after it is a visible typographic error, and
    it is exactly the kind of thing a mechanical join produces and nobody reads
    back. Devanagari and Bengali danda, and Arabic full stops, DO take a following
    space — so this is asserted only where it is wrong.
    """
    for stem in ("ja", "zh"):
        value = json.loads((_LOCALES / f"{stem}.json").read_text(encoding="utf-8"))[_CAVEAT]
        assert "。 " not in value, f"{stem}: a space follows a full-width stop in {value!r}"
