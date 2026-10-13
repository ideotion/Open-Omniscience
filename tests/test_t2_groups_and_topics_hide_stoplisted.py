"""R111 step T2: a keyword the stoplist hides is not counted by the group readers or the source topics.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE TWO RESOLVERS THAT TURN A GROUP'S MEMBERS INTO KEYWORD IDS (``resolve_member_keyword_ids``
for the Observatory, the rising test, the stats and the drill-through; ``_supergroup_totals`` for
the Groups panel) must agree, or the panel and the sky show two numbers for one group. Both are
pinned here against the same corpus. The shipped rings carry 13 terms that are on the shipped
list (``news`` in ``news-media``, ``work`` in ``occupation`` ...): left in, they drive a group's
share with a word the rest of the app hides.

``derive_source_topics`` counts DISTINCT articles per (domain, topic). A hidden keyword's
articles must leave that count, not be subtracted afterwards (which would double-count an
article carrying two keywords of one topic), so the filter is in the query.

``mathcal`` is a batch-1 stopword (a LaTeX macro); ``press`` is an ordinary word. Only the LIST hides
here, not the listing's too-short rule: a group member and a topic tag are deliberate picks (``ai``).

THE RING-LEVEL READERS ARE PINNED TOO (``group_stats.resolve_group_keyword_ids`` for the ring stats and
``queries.ring_country_split`` / ``ring_country_article_ids`` for the country split and its drill): one ring
must show one set of words in all of them, and the drill must be the split's own cell.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import global_stopwords
from src.analytics.source_topics import derive_source_topics
from src.analytics.supergroup_stats import resolve_member_keyword_ids
from src.api.insights import _supergroup_totals
from src.database.models import (
    Article,
    Base,
    Keyword,
    KeywordMention,
    KeywordTag,
    Source,
)

HIDDEN = "mathcal"
VISIBLE = "press"


@pytest.fixture()
def s():
    assert HIDDEN in global_stopwords(), "the fixture word must be on the shipped list"
    assert VISIBLE not in global_stopwords()
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()


def _kw(s, norm, *, n_articles=1):
    k = Keyword(
        term=norm, normalized_term=norm, language="en", frequency=0, is_entity=False,
        mention_count=n_articles, article_count=n_articles,
    )
    s.add(k)
    s.flush()
    return k


def _articles(s, n, domain="s.test"):
    src = s.query(Source).filter_by(domain=domain).first()
    if src is None:
        src = Source(name=domain, domain=domain)
        s.add(src)
        s.flush()
    out = []
    for i in range(n):
        a = Article(
            url=f"https://{domain}/{i}", canonical_url=f"https://{domain}/{i}", source_id=src.id,
            title="t", content="x", hash=f"{domain}{i}",
        )
        s.add(a)
        s.flush()
        out.append(a)
    return src, out


# ----------------------------------------------------------------------- the two member resolvers


def test_a_ring_member_keeps_its_visible_terms_and_loses_the_hidden_one(s):
    """`news-media` holds `news` (on the shipped list) and `press` (not)."""
    news = _kw(s, "news")
    press = _kw(s, VISIBLE)
    assert "news" in global_stopwords()
    ids = resolve_member_keyword_ids(s, [("news-media", "news-media")])
    assert ids["news-media"] == {press.id}, "the hidden term resolved to an id"
    assert news.id not in ids["news-media"]


def test_a_family_member_that_is_hidden_resolves_to_nothing_and_a_visible_one_does_not(s):
    hidden, visible = _kw(s, HIDDEN), _kw(s, VISIBLE)
    ids = resolve_member_keyword_ids(s, [(HIDDEN, None), (VISIBLE, None)])
    assert ids[HIDDEN] == set(), "a hidden family member must not resolve"
    assert ids[VISIBLE] == {visible.id}
    assert hidden.id not in ids[VISIBLE]


def test_a_variant_found_by_canonical_key_is_dropped_only_when_the_variant_itself_is_hidden(s):
    """The possessive scan is its own code path: `press's` shares a canonical key with `press`."""
    plain, possessive = _kw(s, VISIBLE), _kw(s, "press's")
    ids = resolve_member_keyword_ids(s, [(VISIBLE, None)])
    assert ids[VISIBLE] == {plain.id, possessive.id}
    hidden = _kw(s, HIDDEN)
    hidden_possessive = _kw(s, "mathcal's")
    ids = resolve_member_keyword_ids(s, [(HIDDEN, None)])
    assert hidden.id not in ids[HIDDEN], "the exact hidden term came back through the canonical scan"
    assert ids[HIDDEN] == {hidden_possessive.id}, "a variant is its own keyword, hidden only if it is on the list"


def test_a_deliberately_added_short_member_still_resolves(s):
    """Only the LIST hides here. `ai` is two letters (a listing's length rule would hide it) but it is a
    family people add on purpose, and the group would otherwise go empty without a word."""
    ai = _kw(s, "ai")
    assert "ai" not in global_stopwords()
    ids = resolve_member_keyword_ids(s, [("ai", None)])
    assert ids["ai"] == {ai.id}
    _totals, id_sets, _by_id = _supergroup_totals(s, {("ai", None)})
    assert id_sets["ai"] == {ai.id}


def test_the_groups_panel_totals_agree_with_the_observatory_resolver(s):
    """Same corpus, both resolvers: the same ids, and the hidden keyword's mentions are in no total."""
    news = _kw(s, "news", n_articles=9)
    press = _kw(s, VISIBLE, n_articles=3)
    members = {("news-media", "news-media"), (HIDDEN, None)}
    _hidden_family = _kw(s, HIDDEN, n_articles=7)
    totals, id_sets, mention_by_id = _supergroup_totals(s, members)
    resolved = resolve_member_keyword_ids(s, sorted(members))
    assert id_sets == resolved, "the panel and the sky resolve one group to two sets of ids"
    assert id_sets["news-media"] == {press.id}
    assert id_sets[HIDDEN] == set()
    assert totals["news-media"]["mentions"] == 3, "a hidden term's mentions are in the ring's total"
    assert totals[HIDDEN]["mentions"] == 0
    assert news.id not in mention_by_id and _hidden_family.id not in mention_by_id
    assert mention_by_id[press.id] == 3


# ------------------------------------------------------------------ the ring-level readers (one ring)


def _ring_corpus(s):
    """`news-media`: `news` (on the shipped list) on articles 0-3, `press` (not) on articles 2-3, one French source."""
    src, arts = _articles(s, 4, domain="fr.test")
    src.country = "FR"
    news, press = _kw(s, "news", n_articles=4), _kw(s, VISIBLE, n_articles=2)
    for kw, chosen in ((news, arts), (press, arts[2:])):
        for a in chosen:
            s.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=1,
                                 observed_on=date.today(), source_id=src.id))
    s.commit()
    return news, press, arts


def test_the_ring_readers_leave_out_a_hidden_member_too(s):
    """`/ring-stats` (group_stats), the country split and its drill read ONE ring; they must count the words
    the super-group holding that ring counts, and must agree with each other."""
    from src.analytics.group_stats import resolve_group_keyword_ids
    from src.analytics.queries import ring_country_article_ids, ring_country_split

    news, press, arts = _ring_corpus(s)
    assert resolve_group_keyword_ids(s, "news-media") == {press.id}
    split = ring_country_split(s, ring_id="news-media")
    assert split["n_keywords"] == 1, "the hidden `news` was counted as a keyword of the ring"
    (fr,) = split["countries"]
    assert fr["articles"] == 2, "the two articles of `press`, not the four of `news`"
    drill = ring_country_article_ids(s, ring_id="news-media", country="FR")
    assert sorted(drill["article_ids"]) == sorted(a.id for a in arts[2:]), "the drill must be the split's cell"
    assert len(drill["article_ids"]) == fr["articles"]
    assert news.id not in resolve_member_keyword_ids(s, [("news-media", "news-media")])["news-media"]


def test_a_ring_whose_every_member_is_hidden_reads_as_empty_not_as_unmeasured(s):
    from src.analytics.group_stats import resolve_group_keyword_ids
    from src.analytics.queries import ring_country_article_ids, ring_country_split

    news, _press, _arts = _ring_corpus(s)
    # remove the visible member from the corpus: only the hidden `news` is left in the ring
    s.query(KeywordMention).filter(KeywordMention.keyword_id != news.id).delete()
    s.query(Keyword).filter(Keyword.id != news.id).delete()
    s.commit()
    assert resolve_group_keyword_ids(s, "news-media") == set()
    split = ring_country_split(s, ring_id="news-media")
    assert split["found"] is True and split["countries"] == [] and split["n_keywords"] == 0
    drill = ring_country_article_ids(s, ring_id="news-media", country="FR")
    assert drill["article_ids"] == []
    for caveat in (split["caveat"], drill["caveat"]):
        assert "hidden by the stoplist" in caveat and "No indexed keywords" not in caveat, caveat
    # the frame is a fixed template the UI translates, and the count is data beside it (tf), never part of the key
    for payload, noun in ((split, "ring"), (drill, "group")):
        assert payload["caveat_i18n"] == f"Every keyword of this {noun} in your corpus ({{n}}) is hidden by the stoplist " \
            "or your own exclusions, so there is nothing to count."
        assert payload["caveat_vars"] == {"n": 1}
        assert payload["caveat"] == payload["caveat_i18n"].format(**payload["caveat_vars"])


def test_a_ring_the_corpus_never_indexed_still_says_so(s):
    from src.analytics.queries import ring_country_split

    split = ring_country_split(s, ring_id="news-media")
    assert split["countries"] == [] and "No indexed keywords in this ring yet" in split["caveat"]
    assert split["caveat_i18n"] == split["caveat"] and split["caveat_vars"] == {}


def test_a_user_exclusion_hides_a_ring_member_in_every_ring_reader(s, monkeypatch):
    """The second half of the hide set: the user's own exclusions, not only the shipped list."""
    from src.analytics.filters import KeywordFilter
    from src.analytics.group_stats import resolve_group_keyword_ids
    from src.analytics.queries import ring_country_split

    _news, press, _arts = _ring_corpus(s)
    assert VISIBLE not in global_stopwords()
    monkeypatch.setattr("src.analytics.filters.load_settings", lambda: KeywordFilter(excluded=[VISIBLE]))
    assert resolve_group_keyword_ids(s, "news-media") == set()
    assert resolve_member_keyword_ids(s, [("news-media", "news-media")])["news-media"] == set()
    assert ring_country_split(s, ring_id="news-media")["n_keywords"] == 0
    assert press.id not in _supergroup_totals(s, {("news-media", "news-media")})[1]["news-media"]


# ------------------------------------------------------------------------------- source topics


def _topic_corpus(s, hidden_term):
    """Six articles of one source: 1-3 carry `press` (topic: politics), 4-6 carry only `hidden_term`."""
    src, arts = _articles(s, 6)
    visible = _kw(s, VISIBLE, n_articles=3)
    other = _kw(s, hidden_term, n_articles=3)
    for kw in (visible, other):
        s.add(KeywordTag(keyword_id=kw.id, axis="topic", tag="politics", source="baseline"))
    for a in arts[:3]:
        s.add(KeywordMention(keyword_id=visible.id, article_id=a.id, count=1,
                             observed_on=date.today(), source_id=src.id))
    for a in arts[3:]:
        s.add(KeywordMention(keyword_id=other.id, article_id=a.id, count=1,
                             observed_on=date.today(), source_id=src.id))
    s.commit()


def test_a_hidden_keyword_is_not_evidence_of_a_source_topic(s):
    _topic_corpus(s, HIDDEN)
    # three articles of a visible keyword are under the floor of five; the hidden three must not lift them
    assert derive_source_topics(s, min_articles=5) == []


def test_the_same_corpus_with_a_visible_second_keyword_does_clear_the_floor(s):
    """The control: the only difference is that the second keyword is not on the list."""
    _topic_corpus(s, "ballot")
    assert "ballot" not in global_stopwords()
    rows = derive_source_topics(s, min_articles=5)
    assert [r["domain"] for r in rows] == ["s.test"] and rows[0]["topics"] == ["politics"]


def test_a_short_topic_tagged_keyword_is_still_evidence(s):
    """The topic axis is curated labels (`ai`); the length rule must not erase them."""
    src, arts = _articles(s, 5)
    ai = _kw(s, "ai")
    s.add(KeywordTag(keyword_id=ai.id, axis="topic", tag="technology", source="baseline"))
    for a in arts:
        s.add(KeywordMention(keyword_id=ai.id, article_id=a.id, count=1,
                             observed_on=date.today(), source_id=src.id))
    s.commit()
    assert [r["topics"] for r in derive_source_topics(s, min_articles=5)] == [["technology"]]


def test_an_article_carrying_a_hidden_and_a_visible_keyword_of_one_topic_is_counted_once(s):
    """Visible `press` on articles 0-3 (four), hidden `mathcal` on 3-5 (three), one article in common.
    Without the hide the topic has six distinct articles and clears the floor of five; with it, four.
    The overlap is the point of filtering in SQL: a count subtracted afterwards would be wrong here."""
    src, arts = _articles(s, 6)
    visible, hidden = _kw(s, VISIBLE), _kw(s, HIDDEN)
    for kw, chosen in ((visible, arts[:4]), (hidden, arts[3:])):
        s.add(KeywordTag(keyword_id=kw.id, axis="topic", tag="politics", source="baseline"))
        for a in chosen:
            s.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=1,
                                 observed_on=date.today(), source_id=src.id))
    s.commit()
    assert derive_source_topics(s, min_articles=5) == []
    assert len(derive_source_topics(s, min_articles=4)) == 1, "the four visible articles are counted, once each"
