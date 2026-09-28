"""Batch B11 of the 2026-09-26 delegated click-through, pinned: byte sizes written for the
reader's language (P8), and the export panel's Licences lines and Elapsed value
(J-licences, J-elapsed).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each fix was reproduced in Chromium first and measured there after. CI runs no browser,
so the behaviour runs as real, EXTRACTED code under node
(``tests/clickthrough_b11_node_test.js``) against the real locale files; this file pins
the keys the behaviour depends on and the source shape that keeps a second English-only
byte formatter from coming back. The licence lines' keys are pinned beside the other
server sentences the export panel translates, in
``tests/test_export_folder.py::test_every_server_sentence_the_panel_translates_is_keyed_in_all_12_locales``.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from tests.js_source_helper import app_js, function_body, page_source

_ROOT = Path(__file__).resolve().parent.parent
_LOCALES = _ROOT / "src" / "static" / "locales"

_UNIT_FRAMES = ["{n} B", "{n} KB", "{n} MB", "{n} GB", "{n} TB"]
_ELAPSED_FRAMES = [
    "{d} for the corpus",
    "not recorded for the corpus",
    "{d} for the files",
    "not recorded for the files",
]


def _locales() -> dict[str, dict]:
    out = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in _LOCALES.glob("*.json")}
    assert len(out) == 12, f"expected 12 locale files, found {len(out)}"
    return out


def test_the_behaviour_runs_as_real_code_under_node():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "clickthrough_b11_node_test.js")],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


# --- P8: the byte units ----------------------------------------------------- #

def test_every_byte_unit_frame_is_keyed_in_all_12_locales():
    for lang, m in _locales().items():
        for k in _UNIT_FRAMES:
            assert k in m, f"{lang}.json has no key for {k!r}"
            assert m[k].count("{n}") == 1, f"{lang}.json {k!r} lost its number: {m[k]!r}"


def test_a_locale_that_writes_a_unit_its_own_way_does():
    """SI units stay the convention; what translates is the unit's WRITTEN form, where the
    language has one. The locales that keep the Latin abbreviations (de, es, pt, id, ja,
    zh, hi, bn) keep them on purpose -- that is how those languages write it."""
    loc = _locales()
    assert [loc["fr"][k].split("{n}")[1].strip() for k in _UNIT_FRAMES] == ["o", "ko", "Mo", "Go", "To"]
    assert [loc["ru"][k].split("{n}")[1].strip() for k in _UNIT_FRAMES] == ["Б", "КБ", "МБ", "ГБ", "ТБ"]
    ar = [loc["ar"][k].split("{n}")[1].strip() for k in _UNIT_FRAMES]
    assert all(re.fullmatch(r"[\u0600-\u06ff]+", u) for u in ar), ar
    # The GB word matches the one the lane-budget frame already used, so the Storage row
    # and its budget cell name the unit the same way.
    assert loc["ar"]["{n} GB"].replace("{n}", "{gb}") == loc["ar"]["{gb} GB"]
    assert loc["ru"]["{n} GB"].replace("{n}", "{gb}") == loc["ru"]["{gb} GB"]


def test_the_arabic_rate_frame_no_longer_says_s_in_latin_letters():
    """A changed value, with its reason: once the size inside it carries an Arabic unit,
    a Latin "/s" beside it read as a different script mid-figure."""
    v = _locales()["ar"]["{rate}/s"]
    assert "{rate}" in v and "/ث" in v and "/s" not in v, v


def test_every_byte_formatter_goes_through_one_localised_writer():
    app = app_js()
    assert "_sizeText(" in function_body(app, "humanBytes")
    assert "_sizeText(" in function_body(app, "_fmtBytes")
    assert "_sizeText(" in function_body(app, "_storageSignedBytes")
    body = function_body(app, "_sizeText")
    # The number keeps the app's one ruled convention (fmtNum's decimal POINT in every
    # locale); only the unit's written form follows the UI language.
    assert "v.toFixed(dec)" in body and "Intl.NumberFormat" not in body, (
        "a byte size must not take the locale's decimal mark: fmtNum writes a point app-wide"
    )
    assert '"\\u2068"' in body and '"\\u2069"' in body, "the size is not isolated for right-to-left text"
    for frame in _UNIT_FRAMES:
        assert f'TF("{frame}"' in body, f"{frame!r} is not written through the keyed frame"
    # The task-manager page cannot load app-core.js, so it carries its own copy; it must
    # write through the same frames.
    tm = function_body(page_source("taskmanager.html"), "fmtBytes")
    for frame in _UNIT_FRAMES:
        assert f'TF("{frame}"' in tm, f"taskmanager.html: {frame!r} is not written through the keyed frame"
    assert 'TF("{rate}/s"' in function_body(page_source("taskmanager.html"), "fmtRate")


def test_the_reclaimable_space_figure_is_redrawn_once_the_locale_is_there():
    """Measured in Chromium: written once by loadSettings at boot, before the locale map
    had loaded, it read "0 B" in French even after a full reload. It is now kept and
    re-drawn when the map is ready and on every language switch."""
    app = app_js()
    paint = function_body(app, "_paintReclaim")
    assert "_fmtBytes(_dbReclaimBytes)" in paint
    assert 'document.addEventListener("oo:langchange", _paintReclaim)' in app
    assert "OOI18N.ready.then(_paintReclaim)" in app
    settings = function_body(app, "loadSettings")
    assert "_paintReclaim()" in settings and '$("vacuum-reclaim").textContent' not in settings


def test_no_english_only_byte_unit_list_comes_back():
    """The shape the three old formatters shared: a literal list of English unit names
    indexed by the scale step. A fourth copy would print English units in every locale
    again, so the shape itself is refused anywhere in the front end."""
    shape = re.compile(r"\[\s*[\"']B[\"']\s*,\s*[\"']KB[\"']")
    static = _ROOT / "src" / "static"
    hits = [p.name for p in sorted(static.glob("*.js")) if shape.search(p.read_text(encoding="utf-8"))]
    hits += [p.name for p in sorted(static.glob("*.html")) if shape.search(p.read_text(encoding="utf-8"))]
    assert not hits, f"an English-only byte-unit list is back in: {hits}"


# --- J-elapsed: one keyed frame per case ------------------------------------ #

def test_the_elapsed_frames_are_keyed_and_translated_in_all_12_locales():
    for lang, m in _locales().items():
        for k in _ELAPSED_FRAMES:
            assert k in m, f"{lang}.json has no key for {k!r}"
            if lang != "en":
                assert m[k] != k, f"{lang}.json leaves {k!r} in English"
            if "{d}" in k:
                assert m[k].count("{d}") == 1, f"{lang}.json {k!r} lost its time: {m[k]!r}"


def test_the_elapsed_row_renders_the_frames_not_a_state_beside_a_noun():
    panel = function_body(app_js(), "_uxRenderExportPanel")
    for k in _ELAPSED_FRAMES:
        assert f'"{k}"' in panel, f"the Elapsed row does not use {k!r}"
    assert 't("not recorded")' not in panel, "the welded 'not recorded' + noun form is back"


def test_the_arabic_elapsed_frames_name_the_corpus_as_the_checklist_does():
    """J9 settled one Arabic noun for the corpus across the checklist and this row; the
    frames keep it (with the preposition's contraction of its article)."""
    ar = _locales()["ar"]
    noun = ar["Corpus"].removeprefix("ال")
    assert noun and all(noun in ar[k] for k in _ELAPSED_FRAMES[:2]), (noun, [ar[k] for k in _ELAPSED_FRAMES[:2]])


# --- J-licences: the line is looked up, not printed ------------------------- #

def test_the_licence_line_is_passed_through_t():
    panel = function_body(app_js(), "_uxRenderExportPanel")
    assert "esc(t(l.text))" in panel
    assert "esc(l.text)" not in panel, "the server's English licence line is printed as-is again"
