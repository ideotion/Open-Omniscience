"""Local coverage and international coverage are two different questions.

Maintainer ask, 2026-08-11: top keywords per country and per continent, with the
article counts behind them, AND the top keywords of articles MENTIONING that
country — "to see difference between local coverage and international coverage of
each country".

The fixture is built so the two can be told apart: French sources write about
``retraites``, American sources naming France write about ``protest``, and one
American article names nothing French at all. That last one is what makes the test
discriminating — an implementation that simply aggregated everything, or that keyed
the international side on the source's country, would pull it into France's list.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.bulletin.coverage import country_coverage
from src.bulletin.period import resolve_period
from src.database.models import (
    Article,
    ArticleMentionedPlace,
    Base,
    Keyword,
    KeywordMention,
    Source,
)

_DAY = date(2026, 8, 5)


@pytest.fixture
def seeded():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    fr = Source(name="Le Monde", domain="lemonde.fr", country="fr")
    us = Source(name="NYT", domain="nytimes.com", country="us")
    ng = Source(name="Punch", domain="punchng.com", country="ng")
    s.add_all([fr, us, ng])
    s.flush()
    for t, lang in (("retraites", "fr"), ("grève", "fr"), ("protest", "en"),
                    ("election", "en"), ("lagos", "en")):
        s.add(Keyword(term=t, normalized_term=t, language=lang))
    s.flush()
    kid = {k.normalized_term: k.id for k in s.query(Keyword).all()}
    state = {"aid": 0}

    def article(src, *, mentions: str | None = None, terms: tuple[str, ...] = ()):
        state["aid"] += 1
        aid = state["aid"]
        s.add(Article(
            id=aid, url=f"u{aid}", canonical_url=f"u{aid}", source_id=src.id,
            title=f"t{aid}", content="body", hash=f"{aid:064d}",
            published_at=datetime(2026, 8, 5, 12, 0), quarantined=False,
        ))
        if mentions:
            s.add(ArticleMentionedPlace(article_id=aid, name=mentions.upper(),
                                        country=mentions, kind="country", mentions=1))
        for t in terms:
            s.add(KeywordMention(keyword_id=kid[t], article_id=aid, count=3,
                                 observed_on=_DAY, country=src.country, source_id=src.id))
        return aid

    # France, from inside.
    for _ in range(3):
        article(fr, mentions="fr", terms=("retraites", "grève"))
    # France, from outside.
    for _ in range(2):
        article(us, mentions="fr", terms=("protest",))
    # Nothing to do with France, from a US source.
    article(us, terms=("election",))
    # Nigeria: local only.
    for _ in range(4):
        article(ng, mentions="ng", terms=("lagos",))
    s.commit()
    return s


def _period():
    return resolve_period("daily", end=date(2026, 8, 6))


def _country(out: dict, code: str) -> dict:
    return next(c for c in out["countries"] if c["country"] == code)


# --------------------------------------------------------------------------- #
#  the two vantages
# --------------------------------------------------------------------------- #
def test_local_coverage_is_what_sources_there_published(seeded):
    fr = _country(country_coverage(seeded, _period()), "fr")
    assert [t["term"] for t in fr["local"]["terms"]] == ["grève", "retraites"]
    assert fr["local"]["articles"] == 3


def test_international_coverage_is_what_everyone_else_said_about_it(seeded):
    fr = _country(country_coverage(seeded, _period()), "fr")
    assert [t["term"] for t in fr["international"]["terms"]] == ["protest"]
    assert fr["international"]["articles"] == 2


def test_an_article_that_never_names_the_country_is_in_neither_list(seeded):
    """The discriminating case. "election" is in a US article about nothing French,
    so an implementation that aggregated by source country, or that forgot the
    mentioned-place filter, would surface it under France."""
    fr = _country(country_coverage(seeded, _period()), "fr")
    for side in ("local", "international"):
        assert "election" not in [t["term"] for t in fr[side]["terms"]], side


def test_a_source_in_the_country_is_not_counted_as_international(seeded):
    """French articles name France, so without the exclusion they would be the
    international coverage of their own country."""
    fr = _country(country_coverage(seeded, _period()), "fr")
    intl = [t["term"] for t in fr["international"]["terms"]]
    assert "retraites" not in intl and "grève" not in intl


# --------------------------------------------------------------------------- #
#  the n behind every figure
# --------------------------------------------------------------------------- #
def test_every_term_carries_the_articles_it_came_from(seeded):
    """"including statistics about how many articles were used for calculations".
    Per side AND per term: one article mentioning a word forty times and forty
    articles mentioning it once are different facts at the same total."""
    fr = _country(country_coverage(seeded, _period()), "fr")
    assert fr["local"]["articles"] == 3
    for t in fr["local"]["terms"]:
        assert t["articles"] == 3
        assert t["mentions"] == 9


def test_an_asymmetry_is_read_out_rather_than_left_to_the_reader(seeded):
    out = country_coverage(seeded, _period())
    assert _country(out, "fr")["reading"] == "covered from inside and from outside"
    ng = _country(out, "ng")
    assert ng["international"]["articles"] == 0
    assert "no source elsewhere named it" in ng["reading"]


# --------------------------------------------------------------------------- #
#  continents
# --------------------------------------------------------------------------- #
def test_a_continent_is_computed_from_its_members_not_summed_from_them(seeded):
    """An article naming two countries on one continent must count ONCE. Summing
    per-country article totals would count it twice — mentions are extensive and
    article spread is not, so one aggregate cannot serve both.

    TWO European SOURCE countries are needed for this to discriminate at all. The
    first draft had only France, so Europe's member set was ``[fr]``, the sum and
    the recomputation agreed, and a mutation that summed them passed all sixteen
    tests. A fixture missing the very condition the property is about proves
    nothing about it.
    """
    s = seeded
    de = Source(name="Spiegel", domain="spiegel.de", country="de")
    s.add(de)
    s.flush()
    kid = {k.normalized_term: k.id for k in s.query(Keyword).all()}
    # A German source contributing, so Germany joins Europe's member set.
    s.add(Article(id=98, url="u98", canonical_url="u98", source_id=de.id, title="t98",
                  content="body", hash=f"{98:064d}",
                  published_at=datetime(2026, 8, 5, 12, 0), quarantined=False))
    s.add(ArticleMentionedPlace(article_id=98, name="DE", country="de", kind="country"))
    s.add(KeywordMention(keyword_id=kid["election"], article_id=98, count=2,
                         observed_on=_DAY, country="de", source_id=de.id))
    # One US article naming BOTH France and Germany — the article that must not be
    # counted twice for Europe.
    s.add(Article(id=99, url="u99", canonical_url="u99", source_id=2, title="t99",
                  content="body", hash=f"{99:064d}",
                  published_at=datetime(2026, 8, 5, 12, 0), quarantined=False))
    s.add(ArticleMentionedPlace(article_id=99, name="FR", country="fr", kind="country"))
    s.add(ArticleMentionedPlace(article_id=99, name="DE", country="de", kind="country"))
    s.add(KeywordMention(keyword_id=kid["protest"], article_id=99, count=1,
                         observed_on=_DAY, country="us", source_id=2))
    s.commit()

    out = country_coverage(s, _period())
    fr = _country(out, "fr")
    de_row = _country(out, "de")
    assert fr["international"]["articles"] == 3, "2 US-about-France + the one naming both"
    assert de_row["international"]["articles"] == 1, "only the one naming both"

    europe = next(c for c in out["continents"] if c["continent"] == "Europe")
    assert europe["international"]["articles"] == 3, (
        "the distinct articles are {4, 5, 99}; summing the two members would give 4"
    )
    assert europe["international"]["articles"] < (
        fr["international"]["articles"] + de_row["international"]["articles"]
    ), "and the sum must genuinely differ, or this test cannot see the defect"


def test_a_continent_names_how_many_of_its_countries_contributed(seeded):
    out = country_coverage(seeded, _period())
    africa = next(c for c in out["continents"] if c["continent"] == "Africa")
    assert africa["countries_contributing"] == 1
    assert africa["local"]["articles"] == 4


# --------------------------------------------------------------------------- #
#  bounded list, exact figures
# --------------------------------------------------------------------------- #
def test_the_country_list_is_bounded_and_says_how_many_it_left_out(seeded):
    out = country_coverage(seeded, _period(), limit_countries=1)
    assert out["countries_listed"] == 1
    assert out["countries_total"] == 3
    assert out["countries_unlisted"] == 2


# --------------------------------------------------------------------------- #
#  how it reads
# --------------------------------------------------------------------------- #
def _rendered(seeded, fmt="markdown", **kw):
    from src.bulletin.render import render

    section = country_coverage(seeded, _period(), **kw)
    return render(
        {
            "period": {"cadence": "daily", "start": "2026-08-05",
                       "last_day": "2026-08-05", "days": 1},
            "masthead": {"articles": 10},
            "sections": [section],
        },
        fmt,
    )


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_the_two_vantages_are_printed_side_by_side_never_merged(seeded, fmt):
    text = _rendered(seeded, fmt)
    assert "Local" in text and "International" in text
    # France's own words and the outside words must be on separate lines, each with
    # its own n — a merged ranking would answer neither question.
    assert "from 3 articles" in text
    assert "from 2 articles" in text


@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_an_empty_vantage_says_so_with_its_zero(seeded, fmt):
    """Omitting the side would read as "not applicable". Nigeria was covered by
    nobody outside, and that is a finding about this corpus worth printing."""
    text = _rendered(seeded, fmt)
    assert "nothing in this period" in text
    assert "from 0 articles" in text


def test_the_bounded_country_list_says_what_it_left_out_and_what_still_covers_it(seeded):
    text = _rendered(seeded, limit_countries=2)
    assert "listed here: 2 of 3" in text
    assert "Counted and not printed: 1" in text
    assert "continent figures below cover every contributing country" in text


def test_a_continent_heading_does_not_try_to_conjugate(seeded):
    """A count interpolated into a sentence cannot agree with the noun beside it.
    "1 countries here" was the first draft; label:value is correct in every locale."""
    text = _rendered(seeded)
    assert "contributing countries: 1" in text
    assert "1 countries here" not in text


def test_the_section_states_its_method_and_its_caveat(seeded):
    out = country_coverage(seeded, _period())
    assert "denormalised source country" in out["method"]
    assert "never confirmed" in out["caveat"]
    assert "not blended" in out["caveat"]
    # no score-shaped key anywhere in the payload
    import json

    for banned in ("score", "ranking", "rating", "grade"):
        assert f'"{banned}' not in json.dumps(out).lower().replace("degraded", "")
