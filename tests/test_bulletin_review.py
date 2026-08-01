"""
Review, selection and publishing.

The mechanic under test is that toggling a producer RE-RENDERS from the persisted
record — it recomputes nothing and edits nothing. So most of what matters here is
what a selection is NOT allowed to do: change a number, silently swallow a
section it does not recognise, or produce a document that reads as complete when
it is a selection.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json

import pytest

from src.bulletin.render import render, render_markdown
from src.bulletin.review import apply_selection, review_view, story_key

_EDITION = {
    "filename": "20260731-OOS-weekly-abcd1234.json",
    "state": "draft",
    "period": {"cadence": "weekly", "start": "2026-07-25", "end": "2026-08-01", "days": 7},
    "masthead": {"articles": 10, "top_sources": [{"name": "A", "domain": "a.test", "articles": 10}]},
    "disclosures": {"quarantined_in_period": 2},
    "sections": [
        {
            "section": "rising_concepts",
            "window": {"days": 7, "matches_period": True},
            "terms": [{"term": "flood", "recent": 9, "growth": 2.0}],
            "caveat": "A ratio, not a significance test.",
            "method": "windowed counts",
        },
        {"section": "alerts", "window": {"days": 7}, "skipped": "no hazard providers"},
        {"section": "by_topic_tag", "window": {"days": 7}, "error": "RuntimeError: boom"},
    ],
    "stories": {
        "stories": [
            {
                "article_ids": [1, 2],
                "articles": 2,
                "distinct_sources": 2,
                "shared_terms": ["flood"],
                "single_source": False,
                "narration": {"text": "Rescuers worked overnight.", "narrated": True, "partial": True},
            },
            {
                "article_ids": [3],
                "articles": 1,
                "distinct_sources": 1,
                "shared_terms": ["ballot"],
                "single_source": True,
                "narration": {"text": "1 article.", "narrated": False, "fallback_reason": "nothing"},
            },
        ],
        "caveat": "A LEXICAL grouping.",
    },
    "narration": {
        "paragraphs": [
            {
                "article_ids": [1, 2],
                "sentences": [
                    {"text": "Rescuers worked overnight.", "kept": True, "unsupported": [],
                     "checks_applied": ["numbers", "names"]},
                    {"text": "It cost 9,000 euro.", "kept": False, "unsupported": ["9000"],
                     "checks_applied": ["numbers", "names"]},
                ],
            }
        ]
    },
}


# -- the review shows what there is to decide ------------------------------- #


def test_every_section_appears_including_the_ones_that_produced_nothing():
    """An operator deciding what to publish should SEE that a producer had
    nothing to say, not find it missing from the list."""
    v = review_view(_EDITION)
    keys = [s["section"] for s in v["sections"]]
    assert keys == ["rising_concepts", "alerts", "by_topic_tag"]
    assert v["sections"][1]["skipped"] == "no hazard providers"
    assert "boom" in v["sections"][2]["error"]


def test_a_section_reports_how_many_rows_it_would_render():
    v = review_view(_EDITION)
    assert v["sections"][0]["rows"] == 1
    assert v["sections"][1]["rows"] == 0


def test_each_sentence_carries_its_own_verdict():
    """§13's actual requirement: per SENTENCE, not per paragraph. A paragraph
    labelled "validated" is not the same thing as a sentence you can see was."""
    v = review_view(_EDITION)
    sents = v["stories"][0]["sentences"]
    assert [s["kept"] for s in sents] == [True, False]
    assert sents[1]["unsupported"] == ["9000"]
    assert sents[1]["checks_applied"] == ["numbers", "names"]


def test_a_template_paragraph_says_why_rather_than_showing_no_sentences():
    v = review_view(_EDITION)
    assert v["stories"][1]["narrated"] is False
    assert v["stories"][1]["fallback_reason"] == "nothing"


def test_the_review_states_that_nothing_has_left_the_machine_yet():
    v = review_view(_EDITION)
    assert v["state"] == "draft"
    assert "DRAFT" in v["caveat"]


# -- selection filters a copy; it never touches the record ------------------ #


def test_excluding_a_section_leaves_the_original_untouched():
    """The whole mechanic: toggling re-renders from the persisted JSON. If the
    filter mutated the record, a toggle would be a one-way edit."""
    before = json.dumps(_EDITION, sort_keys=True, default=str)
    apply_selection(_EDITION, exclude_sections=["rising_concepts"])
    assert json.dumps(_EDITION, sort_keys=True, default=str) == before


def test_an_excluded_section_is_gone_from_the_render_and_the_rest_is_unchanged():
    full = render_markdown(_EDITION)
    trimmed = render_markdown(apply_selection(_EDITION, exclude_sections=["rising_concepts"]))
    assert "A ratio, not a significance test." in full
    assert "A ratio, not a significance test." not in trimmed
    assert "Rescuers worked overnight." in trimmed, "excluding one thing excludes only it"


def test_an_excluded_story_is_gone_but_the_others_stay():
    key = story_key(_EDITION["stories"]["stories"][0])
    out = apply_selection(_EDITION, exclude_stories=[key])
    kept = out["stories"]["stories"]
    assert len(kept) == 1 and kept[0]["shared_terms"] == ["ballot"]


def test_an_unknown_key_is_ignored_rather_than_failing_the_render():
    """A selection saved before a section was renamed should drop the stale
    entry, not make the document unrenderable."""
    out = apply_selection(_EDITION, exclude_sections=["a_section_that_never_existed"])
    assert len(out["sections"]) == 3


def test_an_empty_selection_returns_the_edition_itself():
    assert apply_selection(_EDITION) is _EDITION


def test_selection_is_exclusion_not_inclusion():
    """A section added after a selection was saved must be INCLUDED by default.
    The opposite convention makes "absent from the list" silently mean "rejected"
    — the same trap as an aggregation keyed only by observed entries."""
    grown = dict(_EDITION, sections=[*_EDITION["sections"], {"section": "brand_new", "terms": []}])
    out = apply_selection(grown, exclude_sections=["alerts"])
    assert "brand_new" in [s["section"] for s in out["sections"]]


# -- a selection is disclosed in what it produces --------------------------- #


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_the_document_says_it_is_a_selection(fmt):
    """The operator chooses what to publish; a reader is still entitled to know
    they are reading a selection."""
    out = apply_selection(_EDITION, exclude_sections=["alerts", "by_topic_tag"])
    text = render(out, fmt)
    assert "1 of 3 sections" in text
    assert "excluded by the operator" in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_excluded_stories_are_counted_too(fmt):
    key = story_key(_EDITION["stories"]["stories"][0])
    text = render(apply_selection(_EDITION, exclude_stories=[key]), fmt)
    assert "1 of 2 stories" in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_an_unselected_edition_says_nothing_about_selection(fmt):
    assert "excluded by the operator" not in render(_EDITION, fmt)


def test_the_selection_note_prints_even_with_no_other_disclosure():
    """The one case where the document is least complete must not be the case
    where it says least about itself."""
    bare = dict(_EDITION)
    bare.pop("disclosures")
    text = render_markdown(apply_selection(bare, exclude_sections=["alerts"]))
    assert "2 of 3 sections" in text


def test_selection_never_changes_a_number():
    """A published number must always be a number the record contains."""
    trimmed = render_markdown(apply_selection(_EDITION, exclude_sections=["alerts"]))
    assert "**flood** — 9 mentions" in trimmed


# -- publishing ------------------------------------------------------------- #


@pytest.fixture()
def _editions(tmp_path, monkeypatch):
    from src.bulletin import store

    # store.editions_dir() imports data_dir INSIDE the function, so patching the
    # source is what reaches it. (Patching the module attribute would fail here,
    # and patching a module-level import elsewhere would pass or fail by import
    # order — a worse outcome than either.)
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    return store


def test_an_edition_starts_as_a_draft(_editions):
    from src.bulletin.period import resolve_period

    p = _editions.persist_edition({"masthead": {}}, resolve_period("weekly"))
    assert json.loads(p.read_text(encoding="utf-8"))["state"] == "draft"


def test_publishing_stamps_the_state_and_the_time(_editions):
    from src.bulletin.period import resolve_period

    p = _editions.persist_edition({"masthead": {}}, resolve_period("weekly"))
    out = _editions.mark_published(p.name)
    assert out["state"] == "published"
    assert out["published_at"]
    assert json.loads(p.read_text(encoding="utf-8"))["state"] == "published"


def test_the_state_history_appends_rather_than_overwrites(_editions):
    """§17, vintages: an edition published, revised and republished must still be
    able to say what happened and when."""
    from src.bulletin.period import resolve_period

    p = _editions.persist_edition({"masthead": {}}, resolve_period("weekly"))
    _editions.mark_published(p.name, selection={"sections_shown": 3, "sections_total": 3})
    out = _editions.mark_published(p.name, selection={"sections_shown": 2, "sections_total": 3})
    hist = out["state_history"]
    assert len(hist) == 2
    assert hist[0]["selection"]["sections_shown"] == 3
    assert hist[1]["selection"]["sections_shown"] == 2
    assert out["published_at"] == hist[0]["at"], "the first publication time is not rewritten"


def test_publishing_records_what_was_left_out(_editions):
    """"What was published" is not answerable from a document showing only what
    survived it."""
    from src.bulletin.period import resolve_period

    p = _editions.persist_edition({"masthead": {}}, resolve_period("weekly"))
    out = _editions.mark_published(p.name, selection={"sections_excluded": ["alerts"]})
    assert out["selection"]["sections_excluded"] == ["alerts"]


def test_publishing_an_unknown_or_traversing_name_is_refused(_editions):
    for name in ("nope.json", "../escape.json", "sub/dir.json"):
        with pytest.raises(FileNotFoundError):
            _editions.mark_published(name)


def test_no_score_shaped_field_in_the_review(_editions):
    flat = json.dumps(review_view(_EDITION), default=str).lower()
    for banned in ("score", "ranking", "rating", "grade"):
        assert f'"{banned}"' not in flat and f'_{banned}"' not in flat
