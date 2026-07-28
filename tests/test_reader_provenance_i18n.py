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

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"
_MAIN = _ROOT / "src" / "api" / "main.py"
_APP_JS = _ROOT / "src" / "static" / "app.js"

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
    src = _APP_JS.read_text(encoding="utf-8")
    leftovers = re.findall(r'toast\("[^"]*failed: "\s*\+', src)
    assert not leftovers, (
        f"{len(leftovers)} concatenated failure toast(s) remain: {leftovers[:3]} "
        "-- route them through _failMsg(\"<Action> failed: {error}\", err)"
    )


def test_every_failure_template_is_keyed_and_keeps_its_placeholder():
    """Each _failMsg template needs a key x12, and every translation must
    keep {error} — a dropped placeholder silently swallows the detail the
    user needs to act on."""
    src = _APP_JS.read_text(encoding="utf-8")
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
    src = _APP_JS.read_text(encoding="utf-8")
    body = src.split("function _failMsg(", 1)[1].split("\n    }", 1)[0]
    assert "window.OOI18N" in body, "_failMsg must reach i18n via window.OOI18N"
    assert not re.search(r"[^.\w]OOI18N\.", body), (
        "_failMsg must not dereference the bare global OOI18N"
    )


def test_all_locales_carry_the_same_key_set():
    """A key added to en.json alone reddens the --min 100 gate."""
    counts = {c: len(_locale(c)) for c in _codes()}
    assert len(set(counts.values())) == 1, f"locale key counts diverge: {counts}"
