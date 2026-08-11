"""A count is not a multiple, however large it is.

``queries.trending`` reports the recent COUNT in ``growth`` when the prior rate
scaled to the window comes to less than one mention -- a documented substitution,
because there is nothing to divide by. Nothing distinguished that sentinel from a
measured ratio except re-deriving it from ``expected``, and the bulletin renderer
did not: a field edition (2026-08-10, 72,225 articles) printed

    - **mitochondrial** - 5,701 mentions (x5701.0 vs the prior period)

on a term whose prior was 4. Nineteen of its twenty rows were that same sentinel,
so the section's ordering collapsed to raw volume and ``fission`` -- the one row
with a measurable baseline -- sat fourteenth, behind thirteen counts wearing a
multiplication sign.

Two directions are pinned here, because a fix that dropped every ratio would
satisfy the first alone: a sentinel must never read as a multiple, and a real
ratio must still read as one.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import queries as q
from src.bulletin.render import _is_ratio, render
from src.database.models import Base, Keyword, KeywordMention, Source


def _edition(terms: list[dict], *, baseline_days: int | None = 30) -> dict:
    section: dict = {"section": "rising_concepts", "terms": terms}
    if baseline_days is not None:
        section["baseline_days"] = baseline_days
    return {
        "period": {"cadence": "weekly", "start": "2026-08-04", "last_day": "2026-08-10", "days": 7},
        "masthead": {"articles": 10},
        "sections": [section],
    }


# The field row, verbatim from the edition that exposed this.
_SENTINEL = {"term": "mitochondrial", "recent": 5701, "prior": 4,
             "expected": 0.93, "growth": 5701.0, "growth_is_ratio": False}
_MEASURED = {"term": "fission", "recent": 2933, "prior": 10,
             "expected": 2.33, "growth": 1257.0, "growth_is_ratio": True}


# --------------------------------------------------------------------------- #
#  the two directions
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_the_sentinel_is_never_printed_as_a_multiple(fmt):
    text = render(_edition([_SENTINEL]), fmt)
    assert "5,701" in text, "the count itself is real and stays"
    assert "5701.0" not in text, "the sentinel value must not reach the page"
    assert "×5701" not in text and "x5701" not in text
    assert "vs the prior period" not in text, (
        "that phrase asserts a comparison this row cannot make"
    )


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_a_measured_ratio_still_prints_its_multiple(fmt):
    """The negative-space twin. Suppressing every ratio would pass the test above
    and destroy the only rows the section is actually about."""
    text = render(_edition([_MEASURED]), fmt)
    assert "1257.0" in text
    assert "vs the prior period" in text


# --------------------------------------------------------------------------- #
#  what the honest sentence says
# --------------------------------------------------------------------------- #
def test_a_brand_new_term_says_it_is_new():
    row = dict(_SENTINEL, term="drp1", recent=1908, prior=0, expected=0.0, growth=1908.0)
    text = render(_edition([row]), "markdown")
    assert "new in this period" in text
    assert "nothing prior to compare" in text


def test_a_thin_baseline_names_the_prior_it_was_measured_against():
    """Four mentions and none are different facts, and the record holds both --
    so the reader gets the number rather than a shrug."""
    text = render(_edition([_SENTINEL]), "markdown")
    assert "against 4 in the prior 30 days" in text
    assert "too thin a baseline" in text


def test_without_a_baseline_length_the_sentence_does_not_invent_one():
    text = render(_edition([_SENTINEL], baseline_days=None), "markdown")
    assert "against 4 in the prior period" in text
    assert "30 days" not in text


# --------------------------------------------------------------------------- #
#  three states, because two would force a guess
# --------------------------------------------------------------------------- #
def test_an_edition_written_before_the_flag_is_judged_from_expected():
    """Re-rendering is pure, so an old record renders through today's code. It
    still carries ``expected``, which is what the flag is computed from -- so the
    fix reaches editions already on disk instead of only new ones."""
    old = {k: v for k, v in _SENTINEL.items() if k != "growth_is_ratio"}
    assert _is_ratio(old) is False
    assert "5701.0" not in render(_edition([old]), "markdown")

    old_measured = {k: v for k, v in _MEASURED.items() if k != "growth_is_ratio"}
    assert _is_ratio(old_measured) is True
    assert "1257.0" in render(_edition([old_measured]), "markdown")


def test_a_record_that_cannot_say_claims_nothing_either_way():
    """No flag and no ``expected``: unknowable. A row that cannot prove it is a
    ratio does not get to print one, and the count is still true."""
    mute = {"term": "x", "recent": 88, "growth": 3.2}
    assert _is_ratio(mute) is None
    text = render(_edition([mute]), "markdown")
    assert "88 mentions" in text
    assert "3.2" not in text
    assert "None" not in text


def test_each_group_label_claims_only_what_its_members_support():
    text = render(_edition([_SENTINEL, _MEASURED, {"term": "x", "recent": 8, "growth": 2.0}]),
                 "markdown")
    assert "Rose against a measurable baseline (1 of 3)" in text
    assert "New or near-new — no baseline to divide by (1 of 3)" in text
    assert "does not say whether a ratio was measurable (1 of 3)" in text


def test_an_across_channels_row_is_untouched_by_the_split():
    """Both sections emit ``terms``; the partition is per ROW for the same reason
    the sentence is."""
    edition = _edition([{"term": "flood", "first_seen": "2026-08-04", "channel": "web"}])
    text = render(edition, "markdown")
    assert "first seen 2026-08-04 in web" in text
    assert "mentions" not in text


# --------------------------------------------------------------------------- #
#  the producer
# --------------------------------------------------------------------------- #
def test_growth_of_marks_the_boundary_where_a_ratio_becomes_a_count():
    assert q._growth_of(10, 2.0) == (5.0, True)
    assert q._growth_of(10, 1.0) == (10.0, True), "exactly 1 is still divisible"
    assert q._growth_of(10, 0.99) == (10.0, False)
    assert q._growth_of(10, 0.0) == (10.0, False)


def test_trending_always_says_which_kind_each_row_is(tmp_path):
    """The renderer's ``expected`` fallback exists for old records only. If the
    producer ever stopped setting the flag, every new edition would silently take
    that path -- so the flag's presence is pinned at the source."""
    engine = create_engine(f"sqlite:///{tmp_path / 'rh.db'}", future=True)
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    today = date.today()
    with Sess() as s:
        s.add(Source(name="S", domain="x.test"))
        s.add(Keyword(term="steady", normalized_term="steady", language="en"))
        s.add(Keyword(term="fresh", normalized_term="fresh", language="en"))
        s.flush()
        # "steady" earns a real baseline; "fresh" arrives only inside the window.
        # A distinct article per row: (keyword_id, article_id) is UNIQUE, so one
        # article cannot carry the same keyword on two days.
        art = 0
        for d in range(1, 40):
            art += 1
            s.add(KeywordMention(keyword_id=1, article_id=art, count=3,
                                 observed_on=today - timedelta(days=d)))
        for d in range(0, 5):
            art += 1
            s.add(KeywordMention(keyword_id=1, article_id=art, count=9,
                                 observed_on=today - timedelta(days=d)))
            art += 1
            s.add(KeywordMention(keyword_id=2, article_id=art, count=9,
                                 observed_on=today - timedelta(days=d)))
        s.commit()
        rows = q.trending(s, window_days=7, baseline_days=30, limit=10)["terms"]

    assert rows, "the fixture must actually surface something"
    for r in rows:
        assert "growth_is_ratio" in r, f"{r['term']} left the renderer to guess"
        assert r["growth_is_ratio"] is (r["expected"] >= 1)
    kinds = {r["term"]: r["growth_is_ratio"] for r in rows}
    assert kinds.get("steady") is True, "a term with a real baseline is a ratio"
    assert kinds.get("fresh") is False, "a term with no baseline is a count"
