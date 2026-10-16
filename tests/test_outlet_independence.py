"""Gates that STATE independence, coordination or convergence count OUTLETS, not feeds (row J, R146 (a)).

One outlet (a domain) can hold several sources once a source is keyed on (domain, feed). A near-duplicate story carried
by BBC News, BBC Arabic and BBC Persian is ONE publisher repeating itself; reading it as three voices would manufacture
agreement. Each test builds the sibling case and the control, and the mutation check is reverting the gate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source
from src.database.outlet import OutletMap, outlet_expr
from src.integrity import collapse as collapse_mod
from src.integrity.actors import corpus_actors

_TEXT = (
    "The ministry announced sweeping new measures on Tuesday afternoon, declaring that the reforms would transform "
    "the sector within a year and promising that every region would benefit from the unprecedented and historic "
    "national modernisation programme, officials told reporters at a briefing in the capital."
)


@pytest.fixture()
def s(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, future=True)()
    yield session
    session.close()


def _feed(s, name, domain, feed, text=_TEXT, minutes=0):
    src = Source(name=name, domain=domain, rss_url=feed)
    s.add(src)
    s.flush()
    now = datetime.now(UTC)
    s.add(Article(url=f"https://{domain}/{src.id}", canonical_url=f"https://{domain}/{src.id}", source_id=src.id,
                  title="Reforms announced", content=text, hash=f"h{src.id}", language="en",
                  published_at=now + timedelta(minutes=minutes), created_at=now))
    s.flush()
    return src.id


def test_outlet_map_names_an_outlet_by_its_oldest_source(s):
    a = _feed(s, "BBC News", "bbc.com", "https://bbc.com/en")
    b = _feed(s, "BBC Arabic", "bbc.com", "https://bbc.com/ar")
    c = _feed(s, "DW", "dw.com", "https://dw.com/rss")
    s.commit()
    m = OutletMap(s)
    assert m.key(a) == m.key(b) == "bbc.com" and m.key(c) == "dw.com"
    assert m.label(b, "BBC Arabic", "bbc.com") == "BBC News"  # stored signatures are keyed on this name
    assert m.primary_id(b) == a
    assert m.key(999, "gone.example") == "gone.example" and m.key(999) == "source-999"


def test_outlet_expr_is_the_domain_or_a_stable_placeholder(s):
    a = _feed(s, "BBC News", "bbc.com", "https://bbc.com/en")
    s.commit()
    from sqlalchemy import func
    n = (s.query(func.count(func.distinct(outlet_expr(Article.source_id, Source.domain))))
         .select_from(Article).outerjoin(Source, Source.id == Article.source_id).scalar())
    assert n == 1 and a


def test_one_outlets_feeds_are_not_a_coordinated_actor(s):
    for i, (name, feed) in enumerate([("BBC News", "en"), ("BBC Arabic", "ar"), ("BBC Persian", "fa")]):
        _feed(s, name, "bbc.com", f"https://bbc.com/{feed}", minutes=i)
    s.commit()
    assert corpus_actors(s, days=7, threshold=0.6).actors == []  # one publisher repeating itself


def test_two_outlets_make_one_event_of_two_members_not_four(s):
    for i, (name, feed) in enumerate([("BBC News", "en"), ("BBC Arabic", "ar"), ("BBC Persian", "fa")]):
        _feed(s, name, "bbc.com", f"https://bbc.com/{feed}", minutes=i)
    _feed(s, "DW", "dw.com", "https://dw.com/rss", minutes=5)
    s.commit()
    actors = corpus_actors(s, days=7, threshold=0.6).actors
    assert len(actors) == 1
    assert sorted(actors[0].sources) == ["BBC News", "DW"]  # the oldest source's name stands for the outlet


def test_story_voices_are_outlets(s):
    for i, (name, feed) in enumerate([("BBC News", "en"), ("BBC Arabic", "ar"), ("BBC Persian", "fa")]):
        _feed(s, name, "bbc.com", f"https://bbc.com/{feed}", minutes=i)
    _feed(s, "DW", "dw.com", "https://dw.com/rss", minutes=5)
    s.commit()
    story = max(collapse_mod.story_prominence(s, days=7)["stories"], key=lambda x: x["voices_raw"])
    assert story["voices_raw"] == 2, "four feeds of two outlets counted as four independent voices"


_SHARED = ("officials said the measure would take effect immediately across every province and that no exceptions "
           "would be granted to any ministry or agency under the new framework")


def _doc(s, name, domain, feed, tail, *, days_ago=1, text=None):
    src = Source(name=name, domain=domain, rss_url=feed)
    s.add(src)
    s.flush()
    when = datetime.now(UTC) - timedelta(days=days_ago)
    body = text or (f"{tail} " * 12 + _SHARED + f" {tail} " * 6)
    s.add(Article(url=f"https://{domain}/{src.id}", canonical_url=f"https://{domain}/{src.id}", source_id=src.id,
                  title=f"T {tail}", content=body, hash=f"d{src.id}", language="en",
                  published_at=when, created_at=when))
    s.flush()
    return src.id


def test_copypasta_counts_outlets_as_sources(s):
    from src.analytics.copypasta import find_copypasta

    _doc(s, "BBC News", "bbc.com", "https://bbc.com/en", "alpha story about floods")
    _doc(s, "BBC Arabic", "bbc.com", "https://bbc.com/ar", "bravo story about taxes")
    _doc(s, "DW", "dw.com", "https://dw.com/rss", "charlie story about energy")
    s.commit()
    # three feeds, two outlets: a gate of three distinct sources must NOT fire
    assert find_copypasta(s, k=8, min_sources=3, min_chars=50)["items"] == []
    got = find_copypasta(s, k=8, min_sources=2, min_chars=50)["items"]
    assert got and all(i["distinct_sources"] == 2 for i in got)
    assert all(i["sources"] == ["BBC News", "DW"] for i in got)


def test_recycled_claim_names_an_outlet_once(s):
    from src.analytics.recycled_claim import find_recycled_claims

    text = _TEXT
    _doc(s, "BBC News", "bbc.com", "https://bbc.com/en", "x", days_ago=300, text=text)
    _doc(s, "BBC Arabic", "bbc.com", "https://bbc.com/ar", "x", days_ago=2, text=text)
    s.commit()
    out = find_recycled_claims(s, min_chars=50)
    assert out["count"] == 1
    c = out["clusters"][0]
    assert c["distinct_sources"] == 1 and c["single_source"] is True and c["sources"] == ["BBC News"]


def test_convergence_independence_gate_counts_outlets(s):
    from datetime import date

    from src.analytics.convergence import find_convergences
    from src.database.models import ArticleMentionedDate, ArticleMentionedPlace

    a = _feed(s, "BBC News", "bbc.com", "https://bbc.com/en")
    b = _feed(s, "BBC Arabic", "bbc.com", "https://bbc.com/ar")
    for aid in (a, b):
        s.add(ArticleMentionedPlace(article_id=aid, name="Gaza", country="ps", kind="city", mentions=1,
                                    lat=31.5, lon=34.45, extractor="lexical-v1"))
        s.add(ArticleMentionedDate(article_id=aid, mentioned_on=date(2024, 5, 11), precision="day",
                                   extractor="dateextract", status="candidate"))
    s.commit()
    out = find_convergences(s, window_days=7, min_articles=2, min_sources=2)
    assert out["clusters_total"] == 0, "two feeds of one outlet read as convergence of two independent sources"
    c = _feed(s, "DW", "dw.com", "https://dw.com/rss")
    s.add(ArticleMentionedPlace(article_id=c, name="Gaza", country="ps", kind="city", mentions=1,
                                lat=31.5, lon=34.45, extractor="lexical-v1"))
    s.add(ArticleMentionedDate(article_id=c, mentioned_on=date(2024, 5, 12), precision="day",
                               extractor="dateextract", status="candidate"))
    s.commit()
    out = find_convergences(s, window_days=7, min_articles=2, min_sources=2)
    assert out["clusters_total"] == 1 and out["clusters"][0]["distinct_sources"] == 2
    assert out["clusters"][0]["source_names"] == ["BBC News", "DW"]


def _kw_session(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    from src.database.derived_views import ensure_derived_views

    ensure_derived_views(engine)
    return sessionmaker(bind=engine, future=True)()


def _mention_spread(session, term, source_days):
    from src.database.models import Keyword, KeywordMention

    kw = Keyword(term=term, normalized_term=term, language="en")
    session.add(kw)
    session.flush()
    today = datetime.now(UTC).date()
    for sid, ago in source_days:
        art = session.query(Article).filter_by(source_id=sid).first()
        session.add(KeywordMention(keyword_id=kw.id, article_id=art.id, count=2,
                                   observed_on=today - timedelta(days=ago), source_id=sid))
    session.commit()


def test_story_propagation_needs_outlets_not_feeds(tmp_path, monkeypatch):
    """Three feeds of ONE site are not a story that travelled across three sources."""
    from src.analytics.story_propagation import find_story_propagation

    session = _kw_session(tmp_path, monkeypatch)
    ids = [_feed(session, n, "bbc.com", f"https://bbc.com/{n}") for n in ("a", "b", "c")]
    session.commit()
    _mention_spread(session, "reformterm", [(ids[0], 8), (ids[1], 4), (ids[2], 1)])
    assert find_story_propagation(session)["items"] == []  # one outlet, three feeds
    other = [_feed(session, "DW", "dw.com", "https://dw.com/rss"), _feed(session, "ZDF", "zdf.de", "https://zdf.de/rss")]
    session.commit()
    _mention_spread(session, "reformterm2", [(ids[0], 8), (other[0], 4), (other[1], 1)])  # the positive control
    items = find_story_propagation(session)["items"]
    assert [(i["term"], i["distinct_sources"], i["first_source"]) for i in items] == [("reformterm2", 3, _name(session, ids[0]))]


def _name(session, sid):
    return session.get(Source, sid).name
