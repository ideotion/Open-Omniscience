"""Wave-6 (frontend) guard — RING-TRANSLATION BINDING on the Families + Groups
landscape (language-aware keywords, Phase 3).

The ledger REMAINING item was: "bind translations through families + super-groups
in the UI." Super-groups already rendered the verified cross-language translation on
their member chips (``loadSuperGroups`` passes ``&target_lang`` and ``sgCard`` calls
``kwTransHtml``). The two surfaces that did NOT were the Insights *landscape*
(``loadLandscape``) and the *Families* review list (``loadFamilies``): neither
appended the target language, so a foreign-language keyword family showed no
translation.

This is an ADDITIVE display-only change:
  1. Both ``/api/insights/top?group=true`` fetches now append ``tgtLangParam()``
     (exactly like ``loadSuperGroups``), so the backend annotates each family/ring
     row with its VERIFIED Wikidata-ring ``translation``.
  2. ``kwTransHtml(<row>)`` renders that "original -> translation" inline on the
     landscape chip and beside the Families family label.

HONESTY: ``kwTransHtml`` shows ONLY a verified ring translation and returns "" for
any untranslated term (no guess, no score). The ``translation`` field is added by
``queries._annotate_translations``, which is purely additive — it never removes the
per-language ``language_breakdown`` split that ``showRingMap`` consumes, so the
ring-map's language breakdown is unaffected (the CRITICAL regression guard below).

Frontend-source scan (no browser); mirrors the ``test_ui_invariants`` grep style.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_APP_JS = _ROOT / "src" / "static" / "app.js"


@pytest.fixture(scope="module")
def app() -> str:
    return _APP_JS.read_text(encoding="utf-8")


def _region(src: str, start_marker: str, end_marker: str) -> str:
    """Return the slice of ``src`` between two anchors (start inclusive, end
    exclusive). Fails loudly if either anchor is missing so a rename can't make an
    assertion silently vacuous."""
    i = src.find(start_marker)
    assert i != -1, f"anchor not found: {start_marker!r}"
    j = src.find(end_marker, i + len(start_marker))
    assert j != -1, f"end anchor not found after {start_marker!r}: {end_marker!r}"
    return src[i:j]


# --------------------------------------------------------------------------- #
# 1. Both grouped-terms fetches carry the target language.                     #
# --------------------------------------------------------------------------- #
def test_landscape_fetch_carries_target_lang(app: str) -> None:
    region = _region(app, "async function loadLandscape(", "async function loadFamilies(")
    # the fetch appends tgtLangParam() so the row gets a verified `translation`
    assert 'api("/api/insights/top?group=true&limit=200" + tgtLangParam())' in region, (
        "loadLandscape must append tgtLangParam() to its /top?group=true fetch"
    )


def test_families_fetch_carries_target_lang(app: str) -> None:
    region = _region(app, "async function loadFamilies(", "function renderFamOverrides(")
    assert "/api/insights/top?group=true&limit=80" in region, "families fetch anchor moved"
    # the same fetch must now append tgtLangParam()
    assert "tgtLangParam()" in region, (
        "loadFamilies must append tgtLangParam() to its /top?group=true fetch"
    )
    # and it must be appended to THAT fetch (the template-literal + tgtLangParam pattern)
    assert re.search(r"group=true&limit=80.*?`\s*\+\s*tgtLangParam\(\)", region, re.S), (
        "tgtLangParam() must be concatenated onto the /top?group=true families fetch"
    )


def test_all_grouped_top_fetches_carry_target_lang(app: str) -> None:
    """Completeness: EVERY /api/insights/top?group=true call in app.js is language-aware
    (landscape + families were the gap; supergroups already was)."""
    for m in re.finditer(r'api\(\s*[`"]/api/insights/top\?group=true', app):
        # grab a generous window covering the full api(...) argument list
        window = app[m.start(): m.start() + 260]
        assert "tgtLangParam()" in window, (
            "a /top?group=true fetch is missing tgtLangParam(): " + window[:120]
        )


# --------------------------------------------------------------------------- #
# 2. The chips render the verified translation via kwTransHtml.                #
# --------------------------------------------------------------------------- #
def test_landscape_chip_renders_translation(app: str) -> None:
    region = _region(app, "async function loadLandscape(", "async function loadFamilies(")
    # rendered on the top-level family/ring row `f` (where `translation` lives)
    assert "kwTransHtml(f)" in region, "landscape chip must render kwTransHtml(f)"


def test_families_label_renders_translation(app: str) -> None:
    region = _region(app, "async function loadFamilies(", "function renderFamOverrides(")
    # the translation is a concept-level field on the family ROW `f`, so it is rendered
    # on the family label (mirroring the top-level-row pattern at anRenderKwChips)
    assert "kwTransHtml(f)" in region, "Families family label must render kwTransHtml(f)"
    assert re.search(r"<b>\$\{esc\(f\.term\)\}</b>\$\{kwTransHtml\(f\)\}", region), (
        "kwTransHtml(f) must sit beside the family term label"
    )


# --------------------------------------------------------------------------- #
# 3. Honesty: kwTransHtml only shows a VERIFIED ring translation.             #
# --------------------------------------------------------------------------- #
def test_kwtranshtml_only_shows_verified_translation(app: str) -> None:
    region = _region(app, "function kwTransHtml(row)", "function kwTentativeHtml(")
    # returns "" for an untranslated row (never a guess), and marks it a verified
    # cross-language concept — no score, no fabricated translation.
    assert "if (!row || !row.translation) return" in region, (
        "kwTransHtml must render nothing for an untranslated term"
    )
    assert "Verified translation (cross-language concept)." in region


# --------------------------------------------------------------------------- #
# 4. CRITICAL REGRESSION GUARD: showRingMap's per-language split is untouched. #
# --------------------------------------------------------------------------- #
def test_ring_map_language_split_still_wired(app: str) -> None:
    """Adding &target_lang to the grouped fetches must NOT break showRingMap, which
    consumes the SAME /top?group=true payload's per-language mention split. The split
    (`language_breakdown` -> `_ringLangIndex`) is built in loadSuperGroups and read in
    showRingMap; translations are additive fields, so both must remain wired."""
    sg = _region(app, "async function loadSuperGroups(", "function sgCard(")
    # supergroups still indexes the per-language split from the grouped rows...
    assert "_ringLangIndex[f.ring_id] = f.language_breakdown" in sg, (
        "loadSuperGroups must still index language_breakdown into _ringLangIndex"
    )
    # ...and its own grouped fetch stays language-aware (unchanged reference pattern)
    assert 'api("/api/insights/top?group=true&limit=200" + tgtLangParam())' in sg

    ring = _region(app, "async function showRingMap(", "async function loadSuperGroups(")
    # showRingMap still reads the split it renders as "By language"
    assert "_ringLangIndex[ringId]" in ring, "showRingMap must still read _ringLangIndex"
    assert "mentions per language" in ring, "the per-language mention split must still render"
