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
import re

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


def test_the_reported_disclosure_is_the_one_the_document_printed(edition):
    """Asking for the line REGISTERS its own frames, so a second call counts them in
    the total the line quotes: the document said "10 of 166" while the diagnostic's
    payload — a second call on the same translator — said "10 of 169" about that same
    document. Two numbers for one claim, in one report."""
    T = Translator("fr")
    md = render_markdown(edition, tr=T)
    printed = T.disclosure()
    assert printed and f"*{printed}*" in md, "the line under test must be in the document"
    assert T.disclosure() == printed, "one render owes one answer"
    # And the diagnostic's payload carries that line, not a re-derivation of it.
    assert language_report(edition, langs=("fr",))["languages"][0]["disclosure"] == printed
    # A fresh translator is free to count again — the memo is per render, not global.
    assert Translator("fr").disclosure() is None, "nothing rendered yet, nothing to say"


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


def _catalog_dir(monkeypatch, tmp_path, catalogs: dict[str, dict[str, str]]):
    """Point the loader at a catalog directory this test owns."""
    from src.bulletin import i18n

    for code, data in catalogs.items():
        (tmp_path / f"{code}.json").write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    monkeypatch.setattr(i18n, "CATALOG_DIR", tmp_path)
    i18n._CACHE.clear()


def test_a_catalog_with_no_gap_reads_as_complete_even_with_legitimate_identities(
    edition, monkeypatch, tmp_path
):
    """The defect this replaced: coverage counts only entries that DIFFER from the
    English, so a locale where "Asia" is Asia and "cyclone" is cyclone can never
    reach 1.0 — and was therefore filed under "started" forever, reporting unfinished
    work that does not exist. Complete answers the worklist question instead."""
    # The report's own offered stub, not one run's missing list: a sentence that
    # appears only once the catalog is good is absent from the latter by construction
    # (see test_filling_the_offered_stub_leaves_nothing_missing).
    asked = list(language_report(edition, langs=("zz",))["languages"][0]["catalog_stub"])
    assert asked, "the probe locale must have asked for something"
    # Every string answered; a handful answered with the English itself, as a real
    # language legitimately does for a proper noun or a unit.
    catalog = {s: (s if i % 20 == 0 else f"ZZ {s}") for i, s in enumerate(asked)}
    identities = sum(1 for k, v in catalog.items() if k == v)
    assert identities >= 2, "the fixture must actually contain legitimate identities"
    _catalog_dir(monkeypatch, tmp_path, {"zz": catalog})

    out = language_report(edition, langs=("zz",))
    row = out["languages"][0]
    assert row["missing"] == 0 and row["rejected"] == 0
    assert row["identical_to_english"] == identities
    assert row["coverage"] < 1.0, "identities keep coverage below one, by design"
    assert out["complete"] == ["zz"], "a finished catalog must be able to say so"
    assert "zz" not in out["started"], "finished is not in progress"
    assert "zz" not in out["not_started"]
    # The reason the stricter list is empty, published as a number a reader can check
    # rather than as a sentence they have to take on trust.
    assert out["identical_in_complete"] == {"zz": identities}
    assert out["fully_translated"] == []


def test_a_catalog_of_copied_english_is_complete_but_never_fully_translated(
    edition, monkeypatch, tmp_path
):
    """The twin, and the reason coverage keeps its stricter definition: a catalog
    that copies the source language has no gap, so it IS complete as a worklist —
    but it must not read as translated. Both numbers are published beside it, so the
    copy is visible rather than counted as work."""
    asked = list(language_report(edition, langs=("zz",))["languages"][0]["catalog_stub"])
    _catalog_dir(monkeypatch, tmp_path, {"zz": {s: s for s in asked}})

    out = language_report(edition, langs=("zz",))
    row = out["languages"][0]
    assert row["missing"] == 0
    assert out["complete"] == ["zz"]
    assert out["fully_translated"] == [], "copied English is not a translation"
    assert row["coverage"] == 0.0
    assert row["identical_to_english"] == row["strings_seen"], (
        "the copy is stated at full size, which is what makes it legible"
    )
    # And the DOCUMENT says it too. The app has no dictionary, so it cannot tell a
    # legitimate identity from an untranslated copy — it publishes the component and
    # lets the reader judge, and at full size that reads as what it is.
    #
    # The two numbers are read out of the line rather than compared to strings_seen:
    # the line quotes the total AT COMPOSITION TIME, deliberately excluding its own
    # frames (see test_the_reported_disclosure_is_the_one_the_document_printed), so
    # pinning it to the report's later total would pin the drift instead of the claim.
    quoted = re.search(r"([\d,]+) of ([\d,]+) sentences", row["disclosure"] or "")
    assert quoted, "a whole-copy must say so in the document, not only in a diagnostic"
    assert quoted.group(1) == quoted.group(2), (
        "every sentence answered with the English means the count equals the total"
    )


def test_filling_the_offered_stub_leaves_nothing_missing(edition, monkeypatch, tmp_path):
    """The stub is what the report tells a translator to fill, so filling it has to be
    enough — and it was not. A sentence that appears only once the catalog is good
    (the disclosure line, which reads one way when nothing is missing and another when
    something is) could never show up in a probe run against an empty catalog, so the
    stub was permanently one string short and the next report reported the shortfall.
    The string it omitted was a caveat, which is the class that must exist in every
    locale. This drives the real loop: take the offered stub, fill it, re-measure."""
    offered = language_report(edition, langs=("zz",))["languages"][0]
    assert offered["stub_beyond_missing"] >= 1, (
        "the fixture only means something while at least one sentence is reachable "
        "solely behind a branch this run did not take"
    )
    # Named directly, so a probe regime cannot be dropped without failing: the two
    # disclosure lines are mutually exclusive at render time, and a stub that offers
    # only the one THIS run took is the defect. Substrings, because both are frames
    # whose holes are filled after translation.
    stub = offered["catalog_stub"]
    assert any("was written in {language}" in s for s in stub), (
        "the complete-catalog line is reachable only once nothing is missing"
    )
    assert any("was requested in {language}" in s for s in stub), (
        "the shortfall line is reachable only while something IS missing"
    )
    assert any("spelled the same in both languages" in s for s in stub), (
        "and the identity count only once a sentence is answered with the English"
    )
    _catalog_dir(
        monkeypatch, tmp_path, {"zz": {s: f"ZZ {s}" for s in offered["catalog_stub"]}}
    )

    out = language_report(edition, langs=("zz",))
    row = out["languages"][0]
    assert row["missing"] == 0, "filling the offered stub must close the gap"
    assert row["rejected"] == 0
    assert row["identical_to_english"] == 0
    assert row["coverage"] == 1.0
    assert out["complete"] == ["zz"]
    # The negative-space twin of the identity count. Without it, a field that simply
    # listed every complete locale would pass every other test here — and would keep
    # offering "some entries are legitimately identical" as the reason the strict list
    # is empty for a locale that has no identical entry at all, which is a fabricated
    # explanation rather than a derived one.
    assert out["fully_translated"] == ["zz"], "nothing copied, so the strict list holds"
    assert out["identical_in_complete"] == {}, (
        "no identity means no reason to publish; an entry here would be a claim the "
        "data does not support"
    )


def test_a_partly_filled_catalog_is_started_and_not_complete(
    edition, monkeypatch, tmp_path
):
    """The third state has to stay distinguishable from the other two, or the fix
    would have collapsed "half done" into "done"."""
    T = Translator("zz")
    render_markdown(edition, tr=T)
    asked = list(T.report()["missing_strings"])
    half = {s: f"ZZ {s}" for s in asked[: len(asked) // 2]}
    _catalog_dir(monkeypatch, tmp_path, {"zz": half})

    out = language_report(edition, langs=("zz",))
    assert out["languages"][0]["missing"] > 0
    assert out["started"] == ["zz"]
    assert out["complete"] == []


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
    # English is the source, so it owes no worklist: an unguarded probe would offer
    # every sentence in the document as English-to-translate-into-English.
    assert by_lang["en"]["catalog_stub"] == {}
    assert by_lang["en"]["stub_beyond_missing"] == 0
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


# --------------------------------------------------------------------------- #
#  value-bearing prose: excluded from coverage, and SAID rather than hidden
#
#  A producer composes a card summary around live values ("~3.2x the prior rate
#  (18 recent vs 5 before)"), so no fixed key can ever match one. Counting those as
#  missing depressed every locale's coverage forever -- a fabricated FAIL, exactly as
#  dishonest as a fabricated pass -- and put them in the stub, inviting a translation
#  that would match one corpus and read as working.
# --------------------------------------------------------------------------- #
_SUMMARY = "Mentions of “flooding” are running ~3.2× the prior-period rate (18 recent vs 5 before)."


def test_a_value_bearing_summary_is_passthrough_and_not_a_missing_translation(edition):
    T = Translator("zz")
    T.catalog = {}
    md = render_markdown(edition, tr=T)
    rep = T.report()
    assert _SUMMARY in md, "it must still print -- excluded from coverage, never dropped"
    assert _SUMMARY not in rep["missing_strings"], (
        "listing it as missing invites a translation good for exactly one corpus"
    )
    assert rep["passthrough"] >= 1 and _SUMMARY in rep["passthrough_examples"]


def test_chrome_is_still_counted_while_data_is_not(edition):
    """The twin, and the one that matters: an exclusion wide enough to swallow real
    chrome would report a fabricated coverage instead of a fabricated gap."""
    T = Translator("zz")
    T.catalog = {}
    render_markdown(edition, tr=T)
    rep = T.report()
    assert "References" in rep["missing_strings"], "a fixed heading is chrome and must count"
    assert rep["strings_seen"] > 0 and rep["missing"] > 0


def test_coverage_denominator_excludes_passthrough_and_the_report_says_so(edition):
    T = Translator("zz")
    T.catalog = {}
    render_markdown(edition, tr=T)
    rep = T.report()
    assert rep["passthrough"] >= 1
    assert "passthrough" in rep["method"], "an exclusion must be stated where the ratio is"
    assert "keyable frame" in rep["passthrough_note"], "and it must name the real fix"


def test_a_signal_label_translates_while_its_value_does_not(edition):
    """The whole reason to split label from value: welded together, neither could be
    translated and the composed line sat in the denominator."""
    T = Translator("zz")
    T.catalog = {"distinct sources": "sources distinctes"}
    md = render_markdown(edition, tr=T)
    assert "sources distinctes 3" in md, "the label translates, the number is untouched"
    assert "distinct sources 3" not in md


def test_english_still_prints_the_measured_line_unchanged(edition):
    """No output change for the locale every existing edition was written in."""
    md = render_markdown(edition, lang="en")
    assert "distinct sources 3 · articles 9" in md


def test_an_edition_written_before_signal_pairs_still_prints_its_measured_line(edition):
    """The fallback, exercised by the reading_diet card, which deliberately carries a
    composed signal_line and no pairs. It is data, so it passes through rather than
    pretending a catalog could match it."""
    legacy = "top three share 0.14 · sources 21"
    T = Translator("zz")
    T.catalog = {}
    md = render_markdown(edition, tr=T)
    assert legacy in md
    assert legacy not in T.report()["missing_strings"]
    assert legacy in T.report()["passthrough_examples"] or T.report()["passthrough"] >= 2


def test_the_stub_does_not_invite_a_value_bearing_translation(edition):
    from src.monitoring.bulletin_language import bulletin_language_report

    rep = bulletin_language_report()
    for row in rep["languages"]:
        stub = row.get("catalog_stub") or {}
        assert _SUMMARY not in stub, f"{row['language']}: the stub must not ask for this"
