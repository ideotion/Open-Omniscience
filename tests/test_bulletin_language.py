"""
The bulletin's language layer, and the render-integrity checks beside it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The four properties the layer rests on, each with its NEGATIVE-SPACE TWIN, because
every one of them fails in two directions:

* English is untouched — and a translated locale really does change.
* A missing translation falls back to English AND is reported — and a present one
  is used rather than reported as missing.
* A frame whose holes were changed is refused — and a frame whose holes are merely
  REORDERED is honoured, since word order is the whole reason to translate a frame.
* An entry copied from the English is not counted as coverage — and a real one is.

The last pair is the one that would otherwise let a lazy catalog report itself
complete, which is the fabricated pass this file exists to prevent.
"""

from __future__ import annotations

import json

import pytest

from src.bulletin.i18n import Translator, load_catalog
from src.bulletin.render import render, render_html, render_markdown
from src.monitoring.bulletin_language import (
    language_report,
    render_integrity,
    run_bulletin_language_selftest,
    sample_edition,
    stored_prose,
)


@pytest.fixture
def edition() -> dict:
    return sample_edition()


# --------------------------------------------------------------------------- #
#  English is untouched
# --------------------------------------------------------------------------- #
def test_english_renders_byte_identically_through_the_layer(edition):
    """The document an operator has today cannot change because a layer was added."""
    plain = render_markdown(edition)
    through = render_markdown(edition, tr=Translator("en"))
    assert plain == through
    assert render_markdown(edition, lang="en") == plain


def test_an_english_render_carries_no_language_line(edition):
    """There is nothing to disclose, and a line would change every existing edition."""
    md = render_markdown(edition, lang="en")
    assert "was requested in" not in md
    assert "was written in" not in md


def test_a_translated_locale_really_changes_the_document(edition):
    """The twin of the identity test: a layer that changed nothing would pass that one."""
    T = Translator("zz")
    T.catalog = {"Stories": "Récits", "References": "Références"}
    md = render_markdown(edition, tr=T)
    assert "## Récits" in md
    assert "## Références" in md
    assert "## Stories" not in md


# --------------------------------------------------------------------------- #
#  a gap falls back AND is named
# --------------------------------------------------------------------------- #
def test_a_missing_translation_falls_back_to_english_and_is_reported(edition):
    T = Translator("zz")
    T.catalog = {"Stories": "Récits"}
    md = render_markdown(edition, tr=T)
    rep = T.report()
    assert "## References" in md, "an untranslated heading must still print, in English"
    assert "References" in rep["missing_strings"]
    assert "Stories" not in rep["missing_strings"]
    assert rep["translated"] == 1


def test_a_present_translation_is_not_reported_as_missing(edition):
    """The twin: a reporter that listed everything would make the worklist useless."""
    T = Translator("zz")
    T.catalog = {"Stories": "Récits"}
    render_markdown(edition, tr=T)
    assert "Stories" not in T.report()["missing_strings"]


def test_a_locale_with_no_catalog_is_english_and_says_so(edition):
    md = render_markdown(edition, lang="zz")
    rep = Translator("zz").report()
    assert rep["catalog_entries"] == 0
    assert rep["catalog_present"] is False
    assert "## Stories" in md
    assert "was requested in" in md, "a document that reads as English must say why"


# --------------------------------------------------------------------------- #
#  a broken frame is refused, a reordered one is honoured
# --------------------------------------------------------------------------- #
def test_a_frame_that_loses_a_hole_is_refused_and_rendered_in_english(edition):
    """A lost hole means a value never reaches the reader. English is the safe answer."""
    T = Translator("zz")
    T.catalog = {"{cadence} bulletin — {start} to {end}": "Bulletin {cadence} du {start}"}
    md = render_markdown(edition, tr=T)
    rep = T.report()
    assert "bulletin — 2026-08-04 to 2026-08-10" in md
    assert any("placeholders differ" in r["reason"] for r in rep["rejected_strings"])
    assert rep["translated"] == 0, "a refused entry is not coverage"


def test_a_frame_that_gains_an_unknown_hole_is_refused(edition):
    """The other direction: an invented hole would print a literal brace to a reader."""
    T = Translator("zz")
    T.catalog = {
        "{cadence} bulletin — {start} to {end}": "{cadence} {start} {end} {jours}",
    }
    md = render_markdown(edition, tr=T)
    assert "{jours}" not in md
    assert any("placeholders differ" in r["reason"] for r in T.report()["rejected_strings"])


def test_a_frame_whose_holes_are_merely_REORDERED_is_honoured(edition):
    """Word order is the whole point of translating a frame, so order must not matter."""
    T = Translator("zz")
    T.catalog = {"{cadence} bulletin — {start} to {end}": "Bulletin {end} ← {start} {cadence}"}
    md = render_markdown(edition, tr=T)
    assert "Bulletin 2026-08-10 ← 2026-08-04" in md
    assert not T.report()["rejected_strings"]


# --------------------------------------------------------------------------- #
#  an entry copied from the English is not coverage
# --------------------------------------------------------------------------- #
def test_an_entry_identical_to_english_is_counted_apart_from_coverage(edition):
    """A catalog that copies the source language would otherwise report itself done."""
    T = Translator("zz")
    T.catalog = {"Stories": "Stories", "References": "Références"}
    render_markdown(edition, tr=T)
    rep = T.report()
    assert rep["identical_to_english"] == 1
    assert rep["translated"] == 1, "the copied entry must not inflate coverage"
    assert "Stories" not in rep["missing_strings"], "nor be reported as work to do"


def test_coverage_is_published_with_its_numerator_and_denominator(edition):
    T = Translator("zz")
    T.catalog = {"Stories": "Récits"}
    render_markdown(edition, tr=T)
    rep = T.report()
    assert rep["coverage"] == pytest.approx(rep["translated"] / rep["strings_seen"])
    assert rep["strings_seen"] > 50


# --------------------------------------------------------------------------- #
#  the disclosure line
# --------------------------------------------------------------------------- #
def test_a_partly_translated_document_states_how_much(edition):
    T = Translator("zz")
    T.catalog = {"Stories": "Récits"}
    md = render_markdown(edition, tr=T)
    assert "was requested in" in md
    assert "printed in English" in md


def test_a_fully_translated_document_says_so_without_a_shortfall(edition):
    """The twin: a document with nothing missing must not print a "1 of 180" line."""
    T = Translator("zz")
    render_markdown(edition, tr=T)  # learn what this record asks for
    T2 = Translator("zz")
    T2.catalog = {s: f"[{s}]" for s in T.report()["missing_strings"]}
    md = render_markdown(edition, tr=T2)
    assert "was written in" in md
    assert "printed in English" not in md


def test_the_html_page_declares_its_language_and_direction(edition):
    T = Translator("ar")
    T.catalog = {"Stories": "قصص"}
    html = render_html(edition, tr=T)
    assert '<html lang="ar" dir="rtl">' in html
    T2 = Translator("zz")
    assert 'dir="rtl"' not in render_html(edition, tr=T2), "only RTL scripts get rtl"


# --------------------------------------------------------------------------- #
#  the corpus is never translated
# --------------------------------------------------------------------------- #
def test_a_source_s_own_words_are_never_looked_up(edition):
    """Titles, authors, keywords and excerpts are DATA. A translation layer that
    reached them would be rewriting somebody else's text."""
    T = Translator("zz")
    render_markdown(edition, tr=T)
    seen = set(T._seen)
    for data in (
        "Sample article title",
        "A. Author",
        "grève",
        "An excerpt of the source's own words.",
        "example.org",
        "A deterministic sentence composed from the cluster's own counts.",
    ):
        assert data not in seen, f"{data!r} is the corpus, not this app's prose"


# --------------------------------------------------------------------------- #
#  the shipped French catalog
# --------------------------------------------------------------------------- #
def test_the_shipped_french_catalog_is_used_and_holds_no_broken_frame(edition):
    """The catalog on disk must actually reach the renderer — a typo'd key would
    silently never match, which is exactly what this asserts against."""
    T = Translator("fr")
    assert T.catalog, "the shipped fr.json must load"
    md = render_markdown(edition, tr=T)
    render_html(edition, tr=T)
    rep = T.report()
    assert not rep["rejected_strings"], f"broken frames: {rep['rejected_strings']}"
    assert rep["translated"] > 100, "the shipped catalog must cover the document's skeleton"
    assert "## Concepts en hausse" in md
    assert "## Récits" in md


def test_every_shipped_catalog_is_valid_json_with_no_empty_value():
    """An empty value would render as an empty sentence — worse than the English."""
    from src.bulletin.i18n import CATALOG_DIR

    files = sorted(CATALOG_DIR.glob("*.json"))
    assert files, "at least the reference locale must ship"
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        for key, value in data.items():
            assert isinstance(value, str) and value.strip(), f"{path.name}: {key!r} is empty"


def test_no_shipped_catalog_entry_changes_a_frame_s_holes():
    """Checked over the CATALOG rather than over one render, so an entry for a
    sentence this record happens not to produce is checked too."""
    import re

    from src.bulletin.i18n import CATALOG_DIR

    hole = re.compile(r"\{(\w+)\}")
    for path in sorted(CATALOG_DIR.glob("*.json")):
        for key, value in json.loads(path.read_text(encoding="utf-8")).items():
            assert set(hole.findall(key)) == set(hole.findall(value)), (
                f"{path.name}: {key!r} → {value!r} changes the frame's holes"
            )


# --------------------------------------------------------------------------- #
#  render integrity — the recursive-improvement half
# --------------------------------------------------------------------------- #
def test_the_sample_edition_renders_cleanly_on_every_integrity_check(edition):
    out = render_integrity(edition)
    assert out["deterministic"] is True
    assert out["unresolved_placeholders"] == []
    assert out["sections_missing_from_document"] == []
    assert out["articles_not_printed_total"] == 0
    assert out["dangling_references"] == []
    assert out["suspicious_none_total"] == 0


def test_an_unprinted_article_is_named_by_the_integrity_check(edition):
    """The defect that shipped: a record naming 115 articles and a renderer that
    printed none of them. The check must FAIL loudly on it, by name."""
    edition["stories"]["stories"][0]["article_rows"] = [
        {"id": 999, "title": "A title no renderer will print"}
    ]
    # Neuter the one place stories print their rows, the way the bug did.
    import src.bulletin.render as R

    original = R._story_article_lines
    R._story_article_lines = lambda story, T: []
    try:
        out = render_integrity(edition)
    finally:
        R._story_article_lines = original
    assert "A title no renderer will print" in out["articles_not_printed"]
    assert out["articles_not_printed_total"] >= 1


def test_a_missing_section_is_named_by_the_integrity_check(edition):
    edition["sections"].append({"section": "a_section_nothing_renders"})
    import src.bulletin.render as R

    original = R._md_section
    R._md_section = lambda section, T: (
        [] if section.get("section") == "a_section_nothing_renders" else original(section, T)
    )
    try:
        out = render_integrity(edition)
    finally:
        R._md_section = original
    assert "a_section_nothing_renders" in out["sections_missing_from_document"]


def test_an_unfilled_frame_hole_survives_visibly_rather_than_crashing(edition):
    """The S4.5 lesson: a missing value must not abort a whole render over one
    sentence, and must not vanish either — it stays visible so the check below
    can find it."""
    T = Translator("zz")
    md = T.f("a sentence with {a_hole_nothing_fills} in it")
    assert "{a_hole_nothing_fills}" in md
    assert T.report()["strings_seen"] == 1


def test_a_frame_hole_that_reaches_the_page_is_named_by_the_integrity_check(edition):
    """And the check finds it. Driven through a real render, with a renderer made to
    forget one value, because a hand-built string would prove nothing about the
    check's own filtering."""
    import src.bulletin.render as R

    original = R._title
    R._title = lambda ed, T: T.f("{cadence} bulletin — {start} to {end}", cadence="x")
    try:
        out = render_integrity(edition)
    finally:
        R._title = original
    assert "start" in out["unresolved_placeholders"]
    assert "end" in out["unresolved_placeholders"]


def test_a_source_s_own_braces_are_never_reported_as_our_bug(edition):
    """The twin, and the reason the check reads the FRAMES rather than the output: a
    publisher who writes braces in a title has not broken our renderer."""
    edition["stories"]["stories"][0]["shared_terms"] = ["{not_a_frame_hole}"]
    out = render_integrity(edition)
    assert out["unresolved_placeholders"] == []


# --------------------------------------------------------------------------- #
#  the report and the selftest
# --------------------------------------------------------------------------- #
def test_english_reports_not_applicable_rather_than_nought_per_cent(edition):
    """English is the SOURCE. "0 of 166 translated, coverage 0%" reads as an
    unstarted locale; the honest answer is that there is nothing to translate."""
    T = Translator("en")
    render_markdown(edition, tr=T)
    rep = T.report()
    assert rep["coverage"] is None
    assert rep["missing"] == 0
    assert rep["missing_strings"] == []
    assert rep["strings_seen"] > 50, "the denominator is still published"
    assert rep["catalog_present"] is True


def test_english_is_neither_started_nor_unstarted_in_the_report(edition):
    """The twin: a locale list that filed English under "not started" would send a
    reader to translate the language the renderer is written in."""
    out = language_report(edition, langs=("en", "fr"))
    assert "en" not in out["not_started"]
    assert "en" not in out["started"]


def test_the_selftest_passes_and_names_each_property():
    out = run_bulletin_language_selftest()
    assert out["passed"] is True
    assert set(out["checks"]) >= {
        "english_reports_no_gap_and_no_ratio",
        "a_real_translation_is_used",
        "a_broken_frame_is_refused",
        "an_identical_entry_is_not_coverage",
        "a_gap_is_reported",
    }


def test_the_report_carries_a_fillable_stub_and_names_the_file(edition):
    out = language_report(edition, langs=("en", "fr", "zz"))
    by_lang = {r["language"]: r for r in out["languages"]}
    assert set(by_lang) == {"en", "fr", "zz"}
    assert by_lang["zz"]["catalog_entries"] == 0
    assert by_lang["zz"]["catalog_stub"], "a locale with nothing done needs the whole stub"
    assert by_lang["zz"]["catalog_file"].endswith("zz.json")
    # Every key of the stub is a sentence to translate, and its value is empty so the
    # file can be filled in place rather than transcribed.
    assert set(by_lang["zz"]["catalog_stub"].values()) == {""}
    assert "zz" in out["not_started"]
    assert out["render_integrity"]["deterministic"] is True


def test_the_report_says_which_record_it_measured(edition):
    out = language_report(edition, langs=("en",))
    assert out["edition"]["synthetic"] is True


def test_stored_prose_finds_the_caveats_a_single_edition_cannot_exhibit():
    """A record with no alerts carries no alert caveat, so rendering alone would
    report a worklist complete while half the possible sentences had no entry."""
    found = stored_prose()
    joined = [s for rows in found.values() for s in rows]
    assert any("provider published" in s for s in joined)
    assert any("Two classes of fact" in s for s in joined)
    assert len(joined) > 30


# --------------------------------------------------------------------------- #
#  the annexes say when they are not in the report's language
# --------------------------------------------------------------------------- #
def test_the_contents_page_states_when_it_is_not_in_the_reports_language(edition):
    from src.bulletin.annexes import assign_refs, contents_markdown

    index = assign_refs(edition)
    en = contents_markdown(
        edition, index, stem="S", analyses_by_id={}, full_text=True, truncated_from=None
    )
    fr = contents_markdown(
        edition,
        index,
        stem="S",
        analyses_by_id={},
        full_text=True,
        truncated_from=None,
        report_lang="fr",
    )
    assert "in English" not in en, "an English report needs no such note"
    assert "in English" in fr
    assert "never translated" in fr


def test_render_dispatch_passes_the_language_through(edition):
    T = Translator("zz")
    T.catalog = {"Stories": "Récits"}
    assert "## Récits" in render(edition, "markdown", tr=T)
    T2 = Translator("zz")
    T2.catalog = {"Stories": "Récits"}
    assert "Récits" in render(edition, "html", tr=T2)


def test_a_region_subtagged_locale_finds_its_catalog():
    """``fr-CA`` is French. A locale that arrives with a region must not miss a
    catalog that exists, which is the store-raw / normalise-on-read convention."""
    assert load_catalog("fr-CA") == load_catalog("fr")
    assert Translator("FR_ca").lang == "fr"
