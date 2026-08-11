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
