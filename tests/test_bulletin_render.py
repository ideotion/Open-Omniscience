"""
Rendering an edition.

The renders are pure, so most of what matters here is what they REFUSE to emit:
a local article link that would resolve to a different article on someone else's
install, an external resource that would tell a recipient's network what the
operator reads, or a caveat quietly dropped to make the document read cleaner.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re

import pytest

from src.bulletin.render import render, render_html, render_markdown

_EDITION = {
    "layer": "A",
    "filename": "20260731-OOS-weekly-abcd1234.json",
    "generated_at": "2026-08-01T06:00:00Z",
    "period": {
        "cadence": "weekly",
        "start": "2026-07-25",
        "end": "2026-08-01",
        "last_day": "2026-07-31",
        "days": 7,
    },
    "masthead": {
        "articles": 1240,
        "corpus_articles": 40000,
        "corpus_share": 0.031,
        "sources_contributing": 37,
        "top_3_share": 0.42,
        "top_sources": [
            {"name": "Le Monde", "domain": "lemonde.fr", "articles": 300, "share": 0.24},
            {"name": None, "domain": "example.test", "articles": 120, "share": 0.09},
        ],
        "languages": [{"language": "fr", "articles": 900}, {"language": None, "articles": 40}],
        "source_countries": [{"country": "fr", "articles": 900}],
        "source_unlocated_articles": 40,
        "days_with_ingest": 6,
        "period_days": 7,
        "caveat": "These figures describe the corpus, not the world.",
    },
    "sections": [
        {
            "section": "rising_concepts",
            "window": {"days": 7, "matches_period": True},
            # Faithful to what ``queries.trending`` emits: ``expected`` and
            # ``growth_is_ratio`` always travel with ``growth``, and 88/27.5 == 3.2.
            # A fixture that omits them describes a row the producer cannot make,
            # and the renderer is right to refuse to call such a count a multiple.
            "baseline_days": 30,
            "terms": [
                {"term": "flood", "recent": 88, "prior": 118, "expected": 27.5,
                 "growth": 3.2, "growth_is_ratio": True}
            ],
            "caveat": "A ratio, not a significance test.",
        },
        {
            "section": "through_time",
            "window": {"days": 7, "matches_period": True},
            "skipped": "the period spans 365 days",
        },
        {"section": "alerts", "error": "RuntimeError: boom"},
        {
            "section": "by_topic_tag",
            "window": {"days": 14, "matches_period": False},
            "topics": [{"topic": "climate", "articles": 40, "mentions": 90}],
        },
    ],
    "disclosures": {
        "quarantined_in_period": 12,
        "mentions_without_a_date": 5,
        "reindex_backlog": {"available": True, "articles_pending": 900},
        "baseline_coverage": {"complete": False, "note": "the corpus only reaches back 120 days"},
    },
    "method": "deterministic: exact SQL counts.",
    "caveat": "This is Layer A — the record.",
}

_WITH_STORIES = dict(
    _EDITION,
    stories={
        "stories": [
            {
                "article_ids": [1, 2],
                "articles": 2,
                "distinct_sources": 2,
                "shared_terms": ["flood", "valencia"],
                "single_source": False,
                "narration": {
                    "text": "Rescuers worked overnight in Valencia.",
                    "narrated": True,
                    "partial": True,
                    "model": "m",
                },
            },
            {
                "article_ids": [3],
                "articles": 3,
                "distinct_sources": 1,
                "shared_terms": ["ballot"],
                "single_source": True,
                "narration": {
                    "text": "3 articles from 1 source shared the terms: ballot.",
                    "narrated": False,
                    "fallback_reason": "the model returned nothing",
                },
            },
        ],
        "caveat": "A LEXICAL grouping, not a semantic one.",
    },
)


# -- what the document must not contain ------------------------------------- #


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_no_local_article_link_ever_leaves_this_machine(fmt):
    """A local article id resolves to a DIFFERENT article on a recipient's
    install — publishing one would send a reader to the wrong thing."""
    text = render(_WITH_STORIES, fmt)
    assert "/api/articles/" not in text
    assert not re.search(r"127\.0\.0\.1|localhost", text)


def test_the_html_is_self_contained():
    """A shared document that phones home would tell its recipient's network what
    the operator reads."""
    out = render_html(_WITH_STORIES)
    assert "<script" not in out.lower()
    assert not re.search(r'(src|href)\s*=\s*["\']https?://', out, re.I)
    assert "@import" not in out and "<link" not in out.lower()


def test_the_html_escapes_content_rather_than_trusting_it():
    hostile = dict(
        _EDITION,
        masthead=dict(_EDITION["masthead"], caveat="<script>alert(1)</script>"),
    )
    out = render_html(hostile)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_the_html_styles_both_light_and_dark():
    """A document is read wherever it is opened."""
    assert "prefers-color-scheme:dark" in render_html(_EDITION).replace(" ", "")


# -- what it must contain --------------------------------------------------- #


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_the_masthead_states_the_lens(fmt):
    text = render(_EDITION, fmt)
    assert "1,240" in text and "37" in text
    assert "42.0%" in text, "the concentration share is shown, not summarised away"
    assert "6" in text and "7" in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_every_section_caveat_is_printed(fmt):
    """A document that drops caveats reads as more certain than the data is."""
    text = render(_EDITION, fmt)
    assert "A ratio, not a significance test." in text
    assert "These figures describe the corpus, not the world." in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_a_section_window_that_differs_from_the_period_is_visible(fmt):
    """Section 12's whole point: a 14-day number in a 7-day edition must be seen."""
    text = render(_EDITION, fmt)
    assert "14 days" in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_a_failed_section_is_named_not_omitted(fmt):
    text = render(_EDITION, fmt)
    assert "could not be built" in text
    assert "boom" in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_a_skipped_section_states_its_reason(fmt):
    assert "the period spans 365 days" in render(_EDITION, fmt)


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_the_disclosures_are_rendered(fmt):
    text = render(_EDITION, fmt)
    assert "12" in text and "quarantined" in text
    assert "900" in text and "re-index" in text
    assert "only reaches back 120 days" in text


_UNREAD_QUARANTINE = "The count of quarantined articles could not be read — unknown, not zero."
_UNREAD_UNDATED = "The count of keyword mentions with no date could not be read — unknown, not zero."
_UNREAD_BACKLOG = "The re-index backlog could not be read — unknown, not zero."
_UNREAD_BASELINE = "The baseline coverage could not be read — unknown, not assumed complete."


def _with_disclosures(**d) -> dict:
    return dict(_EDITION, disclosures={"reindex_backlog": {"available": True, "articles_pending": 0}, **d})


@pytest.mark.parametrize("fmt", ["markdown", "html"])
@pytest.mark.parametrize(
    ("key", "sentence", "other"),
    [
        ("quarantined_in_period", _UNREAD_QUARANTINE, {"mentions_without_a_date": 0}),
        ("mentions_without_a_date", _UNREAD_UNDATED, {"quarantined_in_period": 0}),
    ],
    ids=["quarantine", "undated"],
)
def test_a_count_that_could_not_be_read_is_never_printed_as_nothing_excluded(fmt, key, sentence, other):
    """None is "could not read" (facts.disclosures), a different fact from 0: the document says so, and the closing
    "Nothing excluded" line must not stand over a count nobody read."""
    text = render(_with_disclosures(**{key: None}, **other), fmt)
    assert sentence in text
    assert "Nothing excluded" not in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_a_measured_zero_still_reads_as_nothing_excluded_and_says_nothing_about_an_unread_count(fmt):
    text = render(_with_disclosures(quarantined_in_period=0, mentions_without_a_date=0), fmt)
    assert "Nothing excluded" in text
    assert "could not be read" not in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_a_disclosures_record_that_never_had_the_count_says_nothing_about_it(fmt):
    """An absent key is not a failed read: only a recorded None is."""
    text = render(_with_disclosures(), fmt)
    assert _UNREAD_QUARANTINE not in text and _UNREAD_UNDATED not in text


def test_both_unread_counts_are_named_and_a_readable_one_still_prints_its_figure():
    text = render(_with_disclosures(quarantined_in_period=None, mentions_without_a_date=None), "markdown")
    assert _UNREAD_QUARANTINE in text and _UNREAD_UNDATED in text
    text = render(_with_disclosures(quarantined_in_period=None, mentions_without_a_date=5), "markdown")
    assert _UNREAD_QUARANTINE in text and "5 keyword mention(s) carry no date" in text
    assert _UNREAD_UNDATED not in text


def _baseline(earliest, **extra) -> dict:
    from datetime import date

    from src.bulletin.period import baseline_coverage, resolve_period

    return baseline_coverage(resolve_period("weekly", end=date(2026, 8, 1)), earliest) | extra


@pytest.mark.parametrize("fmt", ["markdown", "html"])
@pytest.mark.parametrize("extra", [{}, {"error": "RuntimeError"}], ids=["no-earliest-date", "probe-raised"])
def test_a_baseline_coverage_that_could_not_be_measured_is_never_printed_as_nothing_excluded(fmt, extra):
    """``complete: None`` is "unknown, not assumed complete" (``baseline_coverage(period, None)``): the same defect as an unread count."""
    cov = _baseline(None, **extra)
    assert cov["complete"] is None
    text = render(_with_disclosures(quarantined_in_period=0, mentions_without_a_date=0, baseline_coverage=cov), fmt)
    assert "baseline coverage is unknown" in text
    assert "Nothing excluded" not in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
@pytest.mark.parametrize("cov", [{"complete": None}, {"complete": None, "note": ""}], ids=["no-note", "empty-note"])
def test_an_unknown_baseline_with_no_note_still_says_it_is_unknown(fmt, cov):
    """The note is how ``baseline_coverage`` names the cause; a record that says ``complete: None`` without one is still
    "unknown, not assumed complete", in a fixed sentence, and never the closing "Nothing excluded"."""
    text = render(_with_disclosures(quarantined_in_period=0, mentions_without_a_date=0, baseline_coverage=cov), fmt)
    assert _UNREAD_BASELINE in text and "Nothing excluded" not in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_the_fixed_baseline_sentence_is_only_for_a_record_with_no_note(fmt):
    text = render(_with_disclosures(quarantined_in_period=0, mentions_without_a_date=0, baseline_coverage=_baseline(None)), fmt)
    # (a slice of the note without the apostrophe the HTML form escapes)
    assert "earliest observed date could not be read" in text and _UNREAD_BASELINE not in text
    text = render(_with_disclosures(quarantined_in_period=0, mentions_without_a_date=0), fmt)
    assert _UNREAD_BASELINE not in text, "an absent baseline record is not an unknown one"


@pytest.mark.parametrize("fmt", ["markdown", "html"])
@pytest.mark.parametrize(
    "backlog",
    [{"available": False}, {"available": None}, {"articles_pending": 4}, {}, None, "unreadable"],
    ids=["false", "none", "no-available-key", "empty", "null", "not-a-mapping"],
)
def test_a_recorded_backlog_that_is_not_a_measurement_is_never_printed_as_nothing_excluded(fmt, backlog):
    """Only ``available: True`` is a reading. A recorded backlog without it (False, None, missing, or no mapping at all)
    is an unread one, like an unread count."""
    text = render(_with_disclosures(quarantined_in_period=0, mentions_without_a_date=0, reindex_backlog=backlog), fmt)
    assert _UNREAD_BACKLOG in text and "Nothing excluded" not in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_a_measured_backlog_and_an_absent_one_do_not_claim_it_could_not_be_read(fmt):
    measured_zero = _with_disclosures(quarantined_in_period=0, mentions_without_a_date=0)
    text = render(measured_zero, fmt)
    assert "Nothing excluded" in text and _UNREAD_BACKLOG not in text
    pending = _with_disclosures(
        quarantined_in_period=0, mentions_without_a_date=0, reindex_backlog={"available": True, "articles_pending": 7}
    )
    text = render(pending, fmt)
    assert "7 imported article(s) await re-index" in text and _UNREAD_BACKLOG not in text
    assert "Nothing excluded" not in text
    absent = dict(_EDITION, disclosures={"quarantined_in_period": 0, "mentions_without_a_date": 0})
    text = render(absent, fmt)
    assert "Nothing excluded" in text and _UNREAD_BACKLOG not in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_an_operator_exclusion_alone_keeps_the_closing_line_off(fmt):
    """The closing "Nothing excluded" is for a section that states nothing; a selection line is a statement."""
    edition = dict(
        _EDITION,
        disclosures={"quarantined_in_period": 0, "mentions_without_a_date": 0},
        selection={"sections_shown": 1, "sections_total": 3},
    )
    text = render(edition, fmt)
    assert "excluded by the operator" in text and "Nothing excluded" not in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_a_baseline_the_corpus_spans_still_reads_as_nothing_excluded(fmt):
    from datetime import date

    cov = _baseline(date(2020, 1, 1))
    assert cov["complete"] is True
    text = render(_with_disclosures(quarantined_in_period=0, mentions_without_a_date=0, baseline_coverage=cov), fmt)
    assert "Nothing excluded" in text and "baseline coverage is unknown" not in text


def _shipped_catalogs() -> list[str]:
    from pathlib import Path

    return sorted(p.stem for p in (Path(__file__).resolve().parents[1] / "configs" / "bulletin_i18n").glob("*.json"))


def test_the_catalog_folder_is_the_eleven_languages_this_test_expects():
    assert _shipped_catalogs() == ["ar", "bn", "de", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"]


@pytest.mark.parametrize("lang", _shipped_catalogs())
def test_the_unread_disclosure_sentences_are_translated_and_printed_translated_in_every_shipped_catalog(lang):
    """Read from the catalog folder, not a list here; checks the DOCUMENT (a sentence printed without ``T.t`` is English in every locale
    and is never "seen", so ``missing_strings`` cannot flag it) as well as the catalog."""
    from src.bulletin.i18n import Translator

    note = _baseline(None)["note"]
    sentences = (_UNREAD_QUARANTINE, _UNREAD_UNDATED, note, _UNREAD_BACKLOG, _UNREAD_BASELINE)
    tr = Translator(lang)
    translated = [tr.t(sentence) for sentence in sentences]
    for sentence, got in zip(sentences, translated, strict=True):
        assert got != sentence, f"{lang}: {sentence}"
    assert len(set(translated)) == len(translated), f"{lang}: two of the sentences share a translation"
    tr = Translator(lang)
    text = render(
        _with_disclosures(
            quarantined_in_period=None,
            mentions_without_a_date=None,
            reindex_backlog={"available": False},
            baseline_coverage=_baseline(None),
        ),
        "markdown",
        tr=tr,
    )
    text += render(_with_disclosures(baseline_coverage={"complete": None}), "markdown", tr=tr)
    for got in translated:
        assert got in text, f"{lang}: {got!r} is not in the rendered document"
    assert not set(sentences) & set(tr.report()["missing_strings"])


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_the_framing_verb_is_what_rose_never_what_trended(fmt):
    text = render(_EDITION, fmt)
    assert "What rose in this corpus" in text or "What rose" in text
    assert "trending" not in text.lower()


# -- the narration is marked where it appears ------------------------------- #


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_model_sentences_are_labelled_beside_the_prose(fmt):
    """Not once in a footer — beside the text, because that is where the reader is
    when it matters."""
    text = render(_WITH_STORIES, fmt)
    assert "AI-derived" in text
    idx_label = text.index("AI-derived")
    idx_text = text.index("Rescuers worked overnight in Valencia.")
    assert 0 < idx_text - idx_label < 600, "the label must sit next to the sentence"


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_a_partly_validated_paragraph_says_what_was_removed(fmt):
    assert "removed" in render(_WITH_STORIES, fmt)


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_a_template_paragraph_is_not_labelled_ai(fmt):
    """The fallback is Layer A's own counts. Calling it AI-derived would be a
    fabricated attribution in the other direction."""
    only_fallback = dict(
        _EDITION,
        stories={"stories": [_WITH_STORIES["stories"]["stories"][1]], "caveat": "c"},
    )
    text = render(only_fallback, fmt)
    assert "the model returned nothing" in text
    assert "AI-derived" not in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_a_single_source_story_says_so(fmt):
    assert "one source only" in render(_WITH_STORIES, fmt)


# -- two sections, one key, different shapes -------------------------------- #

_CHANNELS = dict(
    _EDITION,
    sections=[
        {
            "section": "across_channels",
            "window": {"days": 7, "matches_period": True},
            "channels": [{"provenance": "web", "concepts_first_here": 1}],
            "terms": [
                {"term": "flood", "normalized": "flood", "first_seen": "2026-07-26",
                 "channel": "web", "channels_tied": None},
                {"term": "ballot", "normalized": "ballot", "first_seen": "2026-07-27",
                 "channel": None, "channels_tied": ["newsletter", "wikipedia"]},
            ],
        }
    ],
)


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_an_across_channels_row_is_not_rendered_as_a_rising_row(fmt):
    """Both sections emit a ``terms`` key with DIFFERENT shapes. Dispatching on
    the key rendered one through the other's sentence, and the result was
    literally "— — mentions (×None vs the prior period)"."""
    text = render(_CHANNELS, fmt)
    assert "None" not in text
    assert "mentions (" not in text, "an attribution row must not borrow the counts sentence"
    assert "first seen 2026-07-26" in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_a_tie_names_every_tied_channel(fmt):
    """The mention clock is a date, so same-day is as fine as it gets. Naming one
    of two tied channels would invent a sequence the data does not contain."""
    text = render(_CHANNELS, fmt)
    assert "newsletter" in text and "wikipedia" in text
    assert "tied" in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_a_section_with_two_lists_labels_them(fmt):
    """Across-channels carries per-concept attributions AND a per-channel tally.
    Run into one list, "web" reads as if it were a concept."""
    text = render(_CHANNELS, fmt)
    assert "Where each concept appeared first" in text
    assert "Concepts first seen in each channel" in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_a_section_with_one_list_is_left_plain(fmt):
    """A label on a single-list section is noise, not clarity."""
    text = render(_EDITION, fmt)
    assert "Where each concept appeared first" not in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_a_rising_row_still_reads_as_counts(fmt):
    text = render(_EDITION, fmt)
    assert "88 mentions" in text
    assert "3.2" in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_a_missing_growth_prints_the_count_not_a_none(fmt):
    edition = dict(
        _EDITION,
        sections=[{"section": "rising_concepts", "terms": [{"term": "x", "recent": 4}]}],
    )
    text = render(edition, fmt)
    assert "4 mentions" in text
    assert "None" not in text


# -- purity and shape ------------------------------------------------------- #


def test_rendering_is_pure_and_repeatable():
    """Re-rendering must not change a number — that is what makes toggling a
    producer a re-render rather than a re-computation."""
    assert render_markdown(_EDITION) == render_markdown(_EDITION)
    assert render_html(_EDITION) == render_html(_EDITION)


def test_an_edition_with_almost_nothing_still_renders():
    """Never blank-and-silent."""
    for fmt in ("markdown", "html"):
        out = render({"period": {}, "masthead": {}, "sections": []}, fmt)
        assert out.strip()


def test_a_section_with_no_rows_says_so_rather_than_rendering_empty():
    out = render_markdown(
        dict(_EDITION, sections=[{"section": "alerts", "window": {"days": 7, "matches_period": True}}])
    )
    assert "Nothing to report" in out


def test_an_unknown_format_is_refused():
    with pytest.raises(ValueError, match="unknown format"):
        render(_EDITION, "pdf")


def test_the_html_declares_its_charset_and_viewport():
    out = render_html(_EDITION)
    assert 'charset="utf-8"' in out
    assert "viewport" in out


def test_the_footer_names_the_record_the_numbers_came_from():
    for fmt in ("markdown", "html"):
        assert "20260731-OOS-weekly-abcd1234.json" in render(_EDITION, fmt)


# -- a keyword's language, named in the document (M7) ------------------------ #


def _labelled_edition():
    rising = {
        "section": "rising_concepts",
        "window": {"days": 7, "matches_period": True},
        "baseline_days": 30,
        "terms": [
            {"term": "выборы", "normalized": "выборы", "language": "ru", "recent": 40,
             "prior": 30, "expected": 7.0, "growth": 5.7, "growth_is_ratio": True},
            {"term": "climat", "normalized": "climat", "language": "fr", "recent": 30,
             "prior": 20, "expected": 5.0, "growth": 6.0, "growth_is_ratio": True},
        ],
    }
    # The across-channels rows are the SAME keywords and name only the term.
    across = {
        "section": "across_channels",
        "window": {"days": 7, "matches_period": True},
        "channels": [{"provenance": "news", "concepts_first_here": 1}],
        "terms": [{"term": "выборы", "normalized": "выборы", "first_seen": "2026-07-26",
                   "channel": "news"}],
    }
    return dict(_EDITION, sections=[rising, across])


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_a_keyword_in_another_language_says_so_in_the_document(fmt):
    """M7: a French edition printed a Russian keyword bare, as though it were French.

    The word stays quoted in its own language (the disclosure line's promise); the
    document now adds what it is: the VERIFIED ring translation first, else "(in X)",
    with the language as its 639-2/T code like every other language in the document --
    and a row that names only the term (across channels) reads the same as its rising
    row."""
    en = render(_labelled_edition(), fmt, lang="en")
    assert en.count("выборы (in rus)") == 2, en
    assert "climate” (translated from fra: climat)" in en
    fr = render(_labelled_edition(), fmt, lang="fr")
    assert fr.count("выборы (en rus)") == 2
    # Already in the document's language: nothing is added.
    assert "climat (en fra)" not in fr and "(traduit de fra" not in fr
