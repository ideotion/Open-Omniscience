"""The document must carry what the record already holds.

Layer A computed far more than the renderer printed. In the field edition of
2026-08-10: 114 source countries reached the page as 8, with nothing to say the
other 106 existed; 34 languages as 8; seven per-channel volumes and seven daily
counts as nothing at all; and two sections carried caveats describing fields the
render dropped —

* "the untagged count beside it is the rest of the period, not an empty category",
  printed beside no untagged count (17,080 of 12,468,182 mentions carried a tag);
* "every field here is what the provider published — magnitude, severity tier,
  coordinates, time — carried through unchanged", over the single line
  "earthquake - 92", while twelve fully-detailed events sat in the record.

A caveat may claim only what its document can exhibit.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.bulletin.facts import TOP_SOURCES
from src.bulletin.i18n import Translator
from src.bulletin.render import _listed, render

_MASTHEAD = {
    "articles": 100,
    "sources_contributing": 3,
    "articles_by_day": [{"day": "2026-08-04", "articles": 60},
                        {"day": "2026-08-05", "articles": 40}],
    "channels": [{"source_type": "news", "articles": 90},
                 {"source_type": "scientific", "articles": 10}],
    "languages": [{"language": "en", "articles": 70}, {"language": None, "articles": 30}],
    "source_countries": [{"country": "fr", "articles": 55}, {"country": "de", "articles": 45}],
    "source_unlocated_articles": 7,
    "caveat": "These figures describe the corpus, not the world.",
}


def _edition(sections=None, masthead=None) -> dict:
    return {
        "period": {"cadence": "weekly", "start": "2026-08-04", "last_day": "2026-08-10", "days": 7},
        "masthead": dict(_MASTHEAD, **(masthead or {})),
        "sections": sections or [],
    }


# --------------------------------------------------------------------------- #
#  the masthead splits, in BOTH renderers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_the_channel_mix_reaches_the_page(fmt):
    """The line that explains a rising section at a glance: a week of news reads
    very differently from a week of one journal's back catalogue."""
    text = render(_edition(), fmt)
    assert "scientific" in text and "news" in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_the_daily_shape_reaches_the_page(fmt):
    text = render(_edition(), fmt)
    assert "08-04" in text and "60" in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_both_renderers_carry_the_same_splits(fmt):
    """The masthead was the one block the two renderers did not share, and the HTML
    page had drifted to four bullet points with none of these lines."""
    text = render(_edition(), fmt)
    for needle in ("By day", "Channels", "Languages", "Source countries"):
        assert needle in text, f"{needle} missing from {fmt}"


# --------------------------------------------------------------------------- #
#  a bounded list, an exact total
# --------------------------------------------------------------------------- #
def test_a_long_tail_is_accounted_for_rather_than_dropped():
    rows = [{"country": f"c{i}", "articles": 10} for i in range(30)]
    shown, tail = _listed(rows, limit=20, label="carried", T=Translator("en"))
    assert len(shown) == 20
    assert "20 of 30 shown" in tail
    assert "the other 10" in tail
    assert "100" in tail, "the tail's own total must be exact, not an estimate"


def test_a_short_list_gets_no_remainder_note():
    """The twin: an over-eager helper would print "(2 of 2 shown; the other 0 …)",
    which invents an absence."""
    shown, tail = _listed(
        [{"articles": 1}, {"articles": 2}], limit=20, label="carried", T=Translator("en")
    )
    assert len(shown) == 2
    assert tail == ""


def test_the_truncated_masthead_says_how_many_it_left_out():
    many = [{"country": f"c{i}", "articles": 5} for i in range(40)]
    text = render(_edition(masthead={"source_countries": many}), "markdown")
    assert "20 of 40 shown" in text
    assert "8,445" not in text  # not this fixture's number; guards a copy-paste
    assert "7 from sources with no country recorded" in text


# --------------------------------------------------------------------------- #
#  the caveats' own promises
# --------------------------------------------------------------------------- #
def test_the_topic_table_states_what_it_does_not_cover():
    section = {
        "section": "by_topic_tag",
        "topics": [{"topic": "politics", "articles": 1989, "mentions": 7058}],
        "mentions_total": 12_468_182,
        "mentions_tagged": 17_080,
        "mentions_untagged": 12_451_102,
        "caveat": "the untagged count beside it is the rest of the period",
    }
    text = render(_edition([section]), "markdown")
    assert "12,451,102" in text, "the untagged count the caveat promises"
    assert "12,468,182" in text, "and the denominator that makes it readable"
    assert "0.1%" in text


def test_an_alert_carries_the_fields_its_caveat_names():
    section = {
        "section": "alerts",
        "events": 92,
        "by_event_type": [{"event_type": "earthquake", "events": 92}],
        "by_provider": [{"provider": "usgs", "events": 92}],
        "examples": [{"provider": "usgs", "event_type": "earthquake", "severity": "moderate",
                      "magnitude": 4.8, "place": "80 km ESE of Isangel, Vanuatu",
                      "event_time": "2026-08-10 08:34:28.098000"}],
        "caveat": "Every field here is what the provider published",
    }
    text = render(_edition([section]), "markdown")
    assert "Isangel" in text
    assert "M 4.8" in text
    assert "moderate" in text
    assert "2026-08-10 08:34" in text
    assert "usgs" in text
    assert "12 of 92" not in text, "the count of shown examples must match reality"
    assert "1 of 92" in text


def test_a_changed_document_is_named_not_only_counted():
    section = {
        "section": "changes_of_record",
        "law_revisions": 2,
        "law_revisions_flagged": 1,
        "wiki_revisions": 0,
        "wiki_revisions_flagged": 0,
        "law_examples": [
            {"title": "Data Protection Act 2018", "jurisdiction": "uk",
             "observed_at": "2026-08-07 10:00:00", "delta_bytes": 412, "flagged": True},
        ],
    }
    text = render(_edition([section]), "markdown")
    assert "Data Protection Act 2018" in text
    assert "uk" in text
    assert "412 bytes changed" in text
    assert "flagged as large" in text
    # the counts stay too — an example list is not a replacement for the total
    assert "Law revisions" in text


# --------------------------------------------------------------------------- #
#  the reference list
# --------------------------------------------------------------------------- #
def test_the_reference_list_is_a_reference_list():
    """Three of 621 contributing sources is a podium. The References section is the
    one place a reader learns who fed the corpus they are being shown."""
    assert TOP_SOURCES > 3
