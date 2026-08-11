"""The bulletin has to contain the corpus it is about, and the app's own signals.

The field edition of 2026-08-10 described 72,225 articles and named none of them —
no title, no byline, no date, no excerpt — and surfaced none of the thirty-nine card
producers that are the app's whole signal layer.

Two properties are load-bearing beyond "it renders". First, the two classes of fact
stay apart: what the SOURCE asserted (title, byline, date, declared language) is not
what THIS APP deduced (detected language, word count, sentiment, keywords, places,
entities), and a document that blurred them would be less honest than the reader it
came from. Second, a card section is the ONE part of the edition whose figures are
not the period's — producers take no period — and it has to say so rather than
inherit the period's label.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.bulletin.articles import article_rows
from src.bulletin.cards import cards_by_type
from src.bulletin.period import resolve_period
from src.bulletin.render import render
from src.database.models import (
    Article,
    ArticleEntity,
    ArticleMentionedDate,
    ArticleMentionedPlace,
    Base,
    Keyword,
    KeywordMention,
    Source,
)


@pytest.fixture
def corpus():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    src = Source(name="Le Monde", domain="lemonde.fr", country="fr", source_type="news")
    s.add(src)
    s.flush()
    s.add(Keyword(term="retraites", normalized_term="retraites", language="fr"))
    s.flush()
    kid = s.query(Keyword).one().id
    s.add(Article(
        id=1, url="https://lemonde.fr/a", canonical_url="https://lemonde.fr/a",
        source_id=src.id, title="Grève des retraites", content="Le texte complet " * 60,
        hash=f"{1:064d}", language="fr", detected_language="fr", author="A. Dupont",
        published_at=datetime(2026, 8, 5, 9, 30), word_count=420, reading_time=2,
        sentiment_score=None, sentiment_label=None, quarantined=False,
    ))
    s.add(KeywordMention(keyword_id=kid, article_id=1, count=7,
                         observed_on=date(2026, 8, 5), country="fr", source_id=src.id))
    s.add(ArticleMentionedPlace(article_id=1, name="Paris", country="fr", kind="city", mentions=3))
    s.add(ArticleEntity(article_id=1, name="CGT", entity_class="org", mentions=2))
    s.add(ArticleMentionedDate(article_id=1, mentioned_on=date(2026, 9, 1),
                               precision="day", status="candidate"))
    s.add(ArticleMentionedDate(article_id=1, mentioned_on=date(1999, 1, 1),
                               precision="day", status="rejected"))
    # A quarantined article, which must never be described.
    s.add(Article(
        id=2, url="https://lemonde.fr/b", canonical_url="https://lemonde.fr/b",
        source_id=src.id, title="Nav soup", content="menu menu", hash=f"{2:064d}",
        published_at=datetime(2026, 8, 5, 10, 0), quarantined=True,
    ))
    s.commit()
    return s


# --------------------------------------------------------------------------- #
#  the two classes of fact
# --------------------------------------------------------------------------- #
def test_what_the_source_said_and_what_the_app_measured_are_kept_apart(corpus):
    row = article_rows(corpus, [1])[0]
    assert row["asserted"] == {
        "published_at": "2026-08-05T09:30:00", "author": "A. Dupont", "language": "fr"
    }
    assert row["deduced"]["word_count"] == 420
    assert row["deduced"]["detected_language"] == "fr"
    # and the deduced block never carries a field the source asserted
    assert "author" not in row["deduced"]
    assert "word_count" not in row["asserted"]


def test_the_corpus_derived_facts_travel_with_the_article(corpus):
    row = article_rows(corpus, [1])[0]
    assert [k["term"] for k in row["keywords"]] == ["retraites"]
    assert [p["name"] for p in row["places"]] == ["Paris"]
    assert [e["name"] for e in row["entities"]] == ["CGT"]
    assert [d["date"] for d in row["dates"]] == ["2026-09-01"]


def test_a_rejected_date_is_not_republished(corpus):
    """A human looked at that candidate and said no. Printing it anyway would ignore
    the one judgement in the set."""
    row = article_rows(corpus, [1])[0]
    assert "1999-01-01" not in [d["date"] for d in row["dates"]]


def test_an_absent_sentiment_is_absent_not_neutral(corpus):
    """VADER reads English and nothing else, so a French article has no score. The
    honest rendering of an unmeasured value is nothing, never zero."""
    row = article_rows(corpus, [1])[0]
    assert row["deduced"]["sentiment"] is None


def test_a_quarantined_article_is_never_described(corpus):
    assert [r["id"] for r in article_rows(corpus, [1, 2])] == [1]


def test_the_excerpt_is_bounded_and_says_when_it_was_cut(corpus):
    row = article_rows(corpus, [1], excerpt_chars=40)[0]
    assert len(row["excerpt"]) == 40
    assert row["excerpt_truncated"] is True


# --------------------------------------------------------------------------- #
#  §12: external links only
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("fmt", ["markdown", "html"])
def test_an_article_links_to_its_original_and_never_to_a_local_id(corpus, fmt):
    """A local article id resolves to a DIFFERENT article on a recipient's install,
    so the id may travel in the record and never as a link."""
    section = {
        "section": "cards",
        "types": [{"type": "rising", "cards_found": 1, "cards_shown": 1, "cards": [{
            "title": "retraites is rising", "summary": "s", "bucket": "rising",
            "signal": {"metric": "mentions", "value": 7}, "signal_line": "metric mentions",
            "method": "m", "caveat": "c", "n": 7, "corpus_articles": 1,
            "article_rows": article_rows(corpus, [1]),
        }]}],
        "caveat": "cards are as observed at generation",
    }
    text = render({"period": {"cadence": "weekly", "start": "2026-08-04",
                              "last_day": "2026-08-10", "days": 7},
                   "masthead": {"articles": 1}, "sections": [section]}, fmt)
    assert "https://lemonde.fr/a" in text
    assert "/api/articles/" not in text
    assert "Grève des retraites" in text
    assert "A. Dupont" in text


def test_describing_a_storys_articles_does_not_overwrite_its_count(corpus, monkeypatch):
    """``story["articles"]`` is the article COUNT and always was — the story header
    prints it. Attaching the described rows under that same key replaced an int with a
    list, so every story header rendered "— articles", and none of the tests written
    for the feature could see it: they asserted the deterministic sentence, which is
    built before the overwrite. One key, two meanings, again.
    """
    from src.bulletin.edition import build_edition
    from src.bulletin.render import render_markdown

    monkeypatch.setattr(
        "src.bulletin.stories.build_stories",
        lambda *_a, **_k: {
            "stories": [{"article_ids": [1], "articles": 1, "distinct_sources": 1,
                         "sources": ["Le Monde"], "shared_terms": ["retraites"],
                         "single_source": True}],
            "stories_found": 1, "stories_shown": 1,
        },
    )
    ed = build_edition(corpus, resolve_period("weekly", end=date(2026, 8, 11)))
    story = ed["stories"]["stories"][0]
    assert story["articles"] == 1, "the count must survive"
    assert isinstance(story["article_rows"], list), "the rows get their own key"
    assert story["article_rows"][0]["title"] == "Grève des retraites"
    assert "1 articles" in render_markdown(ed), "and the header still prints the count"


# --------------------------------------------------------------------------- #
#  cards
# --------------------------------------------------------------------------- #
def test_the_card_section_runs_the_real_producers_and_groups_them_by_type(corpus):
    out = cards_by_type(corpus, resolve_period("weekly", end=date(2026, 8, 11)))
    assert out["section"] == "cards"
    assert isinstance(out["producers_total"], int) and out["producers_total"] > 20, (
        "the real registry, not a double"
    )
    assert isinstance(out["types"], list)
    for entry in out["types"]:
        assert entry["cards_shown"] <= entry["cards_found"]


def test_the_card_section_says_its_figures_are_not_the_periods(corpus):
    """Every other section is anchored to the closed period, which is what makes it
    reproducible. Producers take no period, so this one must not borrow the label."""
    out = cards_by_type(corpus, resolve_period("weekly", end=date(2026, 8, 11)))
    assert out["window"]["matches_period"] is False
    assert "AS OBSERVED WHEN THIS EDITION WAS GENERATED" in out["caveat"]


def test_a_truncated_producer_run_is_reported_not_absorbed(corpus):
    """A document built from half the producers must say so, or a short list reads as
    a quiet corpus. The budget is a break in the loop, never an exception the
    per-producer isolation could swallow."""
    out = cards_by_type(corpus, resolve_period("weekly", end=date(2026, 8, 11)), budget_s=-1.0)
    assert out["truncated"] is True
    assert out["producers_run"] == 0
    text = render({"period": {"cadence": "weekly", "start": "2026-08-04",
                              "last_day": "2026-08-10", "days": 7},
                   "masthead": {"articles": 1}, "sections": [out]}, "markdown")
    assert "partial set" in text or "wall-clock budget" in text


def test_a_card_with_no_fixed_article_set_says_why(corpus):
    section = {
        "section": "cards",
        "types": [{"type": "reading_diet", "cards_found": 1, "cards_shown": 1, "cards": [{
            "title": "your reading diet", "summary": "s", "bucket": "context",
            "signal": {"metric": "share", "value": 0.14}, "signal_line": "metric share",
            "method": "m", "caveat": "c", "n": 2117, "corpus_articles": 0, "article_rows": [],
        }]}],
    }
    text = render({"period": {"cadence": "weekly", "start": "2026-08-04",
                              "last_day": "2026-08-10", "days": 7},
                   "masthead": {"articles": 1}, "sections": [section]}, "markdown")
    assert "names no fixed article set" in text


def test_a_card_layer_failure_never_costs_the_record(corpus, monkeypatch):
    monkeypatch.setattr(
        "src.briefing.registry.run_all_bounded",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("producers exploded")),
    )
    out = cards_by_type(corpus, resolve_period("weekly", end=date(2026, 8, 11)))
    assert "producers exploded" in out["error"]
    assert out["caveat"]
