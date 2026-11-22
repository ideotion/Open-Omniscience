"""A rising Lead needs at least 3 articles in at least 2 outlets (R732, field test 2026-11-14 row 64).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Every "rising" lead on eight field instances came from one or two outlets: Tetum function words at n~7,370, a site's
"category" label, and 尼克松 at 404 mentions from ONE article. The ratio still counts mentions; the floor decides only
whether a term is shown, and a corpus where nothing passes it says so instead of relaxing it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article
from src.briefing import producers
from src.database.models import Article, Base, Source
from tests._app_engine import app_sqlite_engine


def _corpus(monkeypatch, tmp_path, *, spread: dict[str, list], quarantine: set[int] = frozenset()):
    """``spread[word]`` lists, per article that repeats ``word``, its source id or ``(source id, days ago)``. Source 4 is
    a second feed of Alpha's domain: the same outlet."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    engine = app_sqlite_engine(":memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    s.add_all([Source(name="Alpha", domain="alpha.test", country="fr"),
               Source(name="Beta", domain="beta.test", country="us"),
               Source(name="Gamma", domain="gamma.test", country="de"),
               Source(name="Alpha World", domain="alpha.test", country="fr", rss_url="https://alpha.test/world.xml")])
    s.commit()
    now = datetime.now(UTC)
    n = 0
    for word, sources in spread.items():
        for entry in sources:
            n += 1
            sid, ago = entry if isinstance(entry, tuple) else (entry, n % 3)
            a = Article(url=f"https://t.test/{n}", canonical_url=f"https://t.test/{n}", source_id=sid,
                        title=f"Story {n}", hash=f"h{n}", language="en",
                        content=f"The {word} {word} {word} report said {word} again today.",
                        published_at=now - timedelta(days=ago), created_at=now,
                        quarantined=n in quarantine)
            s.add(a)
            s.commit()
            index_article(s, a, extractor=BaselineExtractor(), country="fr")
    return s


def test_the_floor_is_named_and_is_what_the_ruling_says():
    assert producers.RISING_MIN_ARTICLES == 3 and producers.RISING_MIN_OUTLETS == 2


def test_a_term_in_three_articles_across_two_outlets_is_rising(monkeypatch, tmp_path):
    s = _corpus(monkeypatch, tmp_path, spread={"pipeline": [1, 1, 2]})
    cards = [c for c in producers.rising_now(s) if c.type == "rising"]
    assert [c.signal["articles"] for c in cards if "pipeline" in c.title] == [3]
    card = next(c for c in cards if "pipeline" in c.title)
    assert card.signal["outlets"] == 2
    labels = {r["label"]: r["value"] for r in card.trigger["math"]}
    assert labels["Articles carrying it in the last 7 days"].startswith("3 ")
    assert labels["Outlets carrying it in the last 7 days"].startswith("2 ")
    assert "at least 3 articles in at least 2 outlets" in card.method
    assert "3 articles in 2 outlets" in card.summary


def test_one_outlet_however_loud_is_held_and_said_so(monkeypatch, tmp_path):
    s = _corpus(monkeypatch, tmp_path, spread={"iha": [1, 1, 1, 1, 1, 1]})
    cards = producers.rising_now(s)
    assert not [c for c in cards if c.type == "rising"], "one outlet's own wording is never a rising lead"
    held = [c for c in cards if c.type == "rising_held"]
    assert len(held) == 1, "nothing qualified: the honest state, never a relaxed threshold"
    card = held[0]
    assert card.bucket == "rising" and card.n >= 1
    assert any(t["term"] == "iha" and t["outlets"] == 1 for t in card.signal["terms"])
    assert card.article_ids, "it opens the articles the narrow terms came from"
    assert card.caveat and card.method


def test_two_articles_in_two_outlets_is_still_below_the_floor(monkeypatch, tmp_path):
    s = _corpus(monkeypatch, tmp_path, spread={"nixon": [1, 2]})
    cards = producers.rising_now(s)
    assert not [c for c in cards if c.type == "rising" and "nixon" in c.title]
    held = next(c for c in cards if c.type == "rising_held")
    term = next(t for t in held.signal["terms"] if t["term"] == "nixon")
    assert (term["articles"], term["outlets"]) == (2, 2)


def test_quarantined_articles_never_count_toward_the_floor(monkeypatch, tmp_path):
    # three articles in two outlets, but the one from the second outlet is quarantined (R101)
    s = _corpus(monkeypatch, tmp_path, spread={"lomonosov": [1, 1, 2]}, quarantine={3})
    cards = producers.rising_now(s)
    assert not [c for c in cards if c.type == "rising" and "lomonosov" in c.title]
    held = next(c for c in cards if c.type == "rising_held")
    term = next(t for t in held.signal["terms"] if t["term"] == "lomonosov")
    assert term["articles"] == 2 and term["outlets"] == 1
    assert 3 not in held.article_ids, "a quarantined article is never opened from the card either"


def test_a_qualifying_term_means_no_held_card(monkeypatch, tmp_path):
    s = _corpus(monkeypatch, tmp_path, spread={"pipeline": [1, 2, 3], "iha": [1, 1, 1, 1]})
    cards = producers.rising_now(s)
    assert any(c.type == "rising" and "pipeline" in c.title for c in cards)
    assert not [c for c in cards if c.type == "rising_held"], "the held card is only for when nothing qualifies"


@pytest.mark.parametrize("field", ["title", "summary", "caveat", "method"])
def test_every_sentence_of_both_cards_is_keyed(monkeypatch, tmp_path, field):
    s = _corpus(monkeypatch, tmp_path, spread={"pipeline": [1, 2, 3]})
    rising = next(c for c in producers.rising_now(s) if c.type == "rising")
    if field == "title":
        assert "pipeline" in rising.title, "the rising card's title is the term itself"
    else:
        assert rising.i18n.get(field), f"the rising card's {field} reads in the UI language"
    s2 = _corpus(monkeypatch, tmp_path / "b", spread={"iha": [1, 1, 1, 1]})
    held = next(c for c in producers.rising_now(s2) if c.type == "rising_held")
    assert held.i18n.get(field), f"the held card's {field} reads in the UI language"


def test_two_feeds_of_one_domain_are_one_outlet(monkeypatch, tmp_path):
    s = _corpus(monkeypatch, tmp_path, spread={"pipeline": [1, 4, 1, 4]})
    cards = producers.rising_now(s)
    assert not [c for c in cards if c.type == "rising"], "two feeds of alpha.test are one outlet"
    held = next(c for c in cards if c.type == "rising_held")
    assert next(t for t in held.signal["terms"] if t["term"] == "pipeline")["outlets"] == 1


def test_mentions_outside_the_seven_day_window_do_not_count(monkeypatch, tmp_path):
    # the third article and the second outlet are both ten days back: outside trending's recent window
    s = _corpus(monkeypatch, tmp_path, spread={"pipeline": [(1, 0), (1, 1), (2, 10)]})
    assert not [c for c in producers.rising_now(s) if c.type == "rising" and "pipeline" in c.title]


def test_as_of_closes_the_window(monkeypatch, tmp_path):
    s = _corpus(monkeypatch, tmp_path, spread={"pipeline": [(1, 3), (1, 3), (2, 0)]})
    as_of = (datetime.now(UTC) - timedelta(days=1)).date()
    assert not [c for c in producers.rising_now(s, as_of=as_of) if c.type == "rising" and "pipeline" in c.title], \
        "an article after as_of never lifts a period card over the floor"


def test_a_spread_term_below_five_narrow_ones_is_still_found(monkeypatch, tmp_path):
    narrow = {w: [1] * 6 for w in ("alef", "bet", "gimel", "dalet", "he", "vav")}
    s = _corpus(monkeypatch, tmp_path, spread={**narrow, "pipeline": [1, 2, 3]})
    cards = producers.rising_now(s)
    assert any(c.type == "rising" and "pipeline" in c.title for c in cards), \
        "candidates are read past the top five, so a narrow top does not hide a spread term"


def test_both_cards_pass_the_card_quality_checks(monkeypatch, tmp_path):
    from src.briefing.card_quality import check_card

    s = _corpus(monkeypatch, tmp_path, spread={"pipeline": [1, 2, 3]})
    s2 = _corpus(monkeypatch, tmp_path / "b", spread={"iha": [1] * 6, "zork": [2] * 4})
    for card in [*producers.rising_now(s), *producers.rising_now(s2)]:
        d = card.to_dict()
        d.setdefault("created_at", datetime.now(UTC).isoformat())
        found = {f["check"] for f in check_card(d)}
        assert not found - {"date_missing"}, (card.type, found)


def test_a_different_held_state_is_a_different_card(monkeypatch, tmp_path):
    a = next(c for c in producers.rising_now(_corpus(monkeypatch, tmp_path, spread={"iha": [1] * 4}))
             if c.type == "rising_held")
    b = next(c for c in producers.rising_now(_corpus(monkeypatch, tmp_path / "b", spread={"zork": [1] * 4}))
             if c.type == "rising_held")
    assert a.key != b.key, "dismissing one 'nothing rising' state never hides the next"
