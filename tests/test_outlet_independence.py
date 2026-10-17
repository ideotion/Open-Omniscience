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


def test_the_link_board_counts_citing_outlets_not_citing_feeds(tmp_path):
    """Two feeds of one site citing a page are one path (single_origin); a second OUTLET makes two."""
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.database.models import ArticleLink
    from src.database.session import get_db

    engine = create_engine(f"sqlite:///{tmp_path / 'l.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        a = _feed(s, "S en", "s.test", "https://s.test/en", text="alpha")
        b = _feed(s, "S fr", "s.test", "https://s.test/fr", text="beta")
        c = _feed(s, "O", "o.test", "https://o.test/rss", text="gamma")
        arts = {sid: s.query(Article).filter_by(source_id=sid).one().id for sid in (a, b, c)}
        x, y = "https://cited.example/x", "https://cited.example/y"
        s.add_all([ArticleLink(article_id=arts[a], url=x, normalized_url=x, link_type="external"),
                   ArticleLink(article_id=arts[b], url=x, normalized_url=x, link_type="external"),
                   ArticleLink(article_id=arts[a], url=y, normalized_url=y, link_type="external"),
                   ArticleLink(article_id=arts[c], url=y, normalized_url=y, link_type="external")])
        s.commit()

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            items = {i["normalized_url"]: i for i in client.get("/api/links/corpus?min_citations=2").json()["items"]}
    finally:
        app.dependency_overrides.clear()
    assert (items[x]["citations"], items[x]["citing_sources"], items[x]["independence"]) == (2, 1, "single_origin")
    assert (items[y]["citations"], items[y]["citing_sources"], items[y]["independence"]) == (2, 2, "distinct_sources")


def test_a_term_born_wide_across_feeds_of_one_site_is_not_born_wide(tmp_path, monkeypatch):
    from src.analytics.emergence import find_manufactured_emergence

    session = _kw_session(tmp_path, monkeypatch)
    ids = [_feed(session, n, "bbc.com", f"https://bbc.com/{n}", text=n) for n in ("a", "b", "c")]
    session.commit()
    _mention_spread(session, "bornwide", [(i, 1) for i in ids])
    gates = {"min_recent_articles": 3, "min_sources": 2}
    assert find_manufactured_emergence(session, **gates)["items"] == []  # three feeds, one outlet
    other = _feed(session, "DW", "dw.com", "https://dw.com/rss", text="dw")
    session.commit()
    _mention_spread(session, "bornwide2", [(ids[0], 1), (ids[1], 1), (other, 1)])  # the positive control
    items = find_manufactured_emergence(session, **gates)["items"]
    assert [(i["term"], i["recent_sources"]) for i in items] == [("bornwide2", 2)]


def test_a_rising_theme_reports_distinct_outlets(tmp_path, monkeypatch):
    from src.analytics.supergroup_rising import _distinct_sources_windowed

    session = _kw_session(tmp_path, monkeypatch)
    a = _feed(session, "BBC News", "bbc.com", "https://bbc.com/en", text="a")
    b = _feed(session, "BBC Arabic", "bbc.com", "https://bbc.com/ar", text="b")
    c = _feed(session, "DW", "dw.com", "https://dw.com/rss", text="c")
    session.commit()
    _mention_spread(session, "risingterm", [(a, 1), (b, 1), (c, 1)])
    from src.database.models import Keyword

    kid = session.query(Keyword).filter_by(normalized_term="risingterm").one().id
    today = datetime.now(UTC).date()
    assert _distinct_sources_windowed(session, {kid}, today - timedelta(days=5), today + timedelta(days=1)) == 2


def test_a_cited_domain_is_cited_by_outlets_not_feeds(s):
    from src.database.models import ArticleLink
    from src.discovery.cited_sources import cited_domain_stats

    a = _feed(s, "S en", "s.test", "https://s.test/en", text="a")
    b = _feed(s, "S fr", "s.test", "https://s.test/fr", text="b")
    c = _feed(s, "O", "o.test", "https://o.test/rss", text="c")
    for sid in (a, b, c):
        aid = s.query(Article).filter_by(source_id=sid).one().id
        s.add(ArticleLink(article_id=aid, url="https://cited.example/p", normalized_url="https://cited.example/p",
                          link_type="external"))
    s.commit()
    stats = cited_domain_stats(s)["cited.example"]
    assert len(stats["articles"]) == 3 and len(stats["sources"]) == 2  # two outlets, three feeds


def test_the_ripple_independence_gate_counts_outlets(tmp_path, monkeypatch):
    from src.analytics.supply_chain_ripple import _source_counts
    from src.database.models import Keyword

    session = _kw_session(tmp_path, monkeypatch)
    a = _feed(session, "BBC News", "bbc.com", "https://bbc.com/en", text="a")
    b = _feed(session, "BBC Arabic", "bbc.com", "https://bbc.com/ar", text="b")
    c = _feed(session, "DW", "dw.com", "https://dw.com/rss", text="c")
    session.commit()
    _mention_spread(session, "oilterm", [(a, 1), (b, 1), (c, 1)])
    kid = session.query(Keyword).filter_by(normalized_term="oilterm").one().id
    today = datetime.now(UTC).date()
    assert _source_counts(session, [kid], today - timedelta(days=5), today + timedelta(days=1)) == {kid: 2}


def test_a_claim_trail_joins_the_feeds_of_one_site_into_one_path():
    from src.analytics.claim_workspace import group_paths

    arts = [
        {"id": 1, "source_id": 1, "source": "BBC News", "outlet": "bbc.com", "outlet_label": "BBC News"},
        {"id": 2, "source_id": 2, "source": "BBC Arabic", "outlet": "bbc.com", "outlet_label": "BBC News"},
        {"id": 3, "source_id": 3, "source": "DW", "outlet": "dw.com", "outlet_label": "DW"},
    ]
    out = group_paths(arts, {}, [])
    assert out["n_paths"] == 2
    top = out["paths"][0]
    assert top["article_ids"] == [1, 2] and [(j["kind"], j["detail"]) for j in top["joins"]] == [("same_source", "BBC News")]


def test_a_feed_level_count_says_it_counts_feeds_on_every_surface(tmp_path, monkeypatch):
    """R146 (b): the passport, the evidence plan and the upcoming-dates view each carry the sentence."""
    from datetime import date

    from fastapi.testclient import TestClient

    from src.analytics.passport import METHOD, corpus_passport
    from src.api.main import app
    from src.database.models import ArticleMentionedDate
    from src.database.outlet import FEEDS_NOT_OUTLETS
    from src.database.session import get_db
    from src.timemap.datestore import upcoming_deduced

    assert FEEDS_NOT_OUTLETS in METHOD
    engine = create_engine(f"sqlite:///{tmp_path / 'c.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        ids = [_feed(s, n, "bbc.com", f"https://bbc.com/{n}", text=n) for n in ("a", "b")]
        arts = [s.query(Article).filter_by(source_id=i).one().id for i in ids]
        for aid in arts:
            s.add(ArticleMentionedDate(article_id=aid, mentioned_on=date.today() + timedelta(days=3), status="candidate",
                                       snippet="x"))
        s.commit()
        from sqlalchemy import select

        assert FEEDS_NOT_OUTLETS in corpus_passport(s, select(Article.id))["method"]
        assert FEEDS_NOT_OUTLETS in upcoming_deduced(s, min_articles=1)["method"]

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            r = client.post("/api/reports/evidence/plan", json={"article_ids": arts})
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    assert r.json()["sources"] == 2 and r.json()["sources_note"] == FEEDS_NOT_OUTLETS


# --- the language-ubiquity denominator is the same unit as its numerator (Opus read, finding 1) ---------------------
def _lang_feed(s, name, dom, url, lang):
    sid = _feed(s, name, dom, url)
    s.get(Source, sid).language = lang
    return sid


def _lang_mention(session, term, lang, pairs):
    from src.database.models import Keyword, KeywordMention

    kw = Keyword(term=term, normalized_term=term, language=lang)
    session.add(kw)
    session.flush()
    today = datetime.now(UTC).date()
    for sid, ago in pairs:
        art = session.query(Article).filter_by(source_id=sid).first()
        session.add(KeywordMention(keyword_id=kw.id, article_id=art.id, count=2,
                                   observed_on=today - timedelta(days=ago), source_id=sid))
    session.commit()


def test_an_outlets_second_language_service_counts_in_that_languages_denominator(tmp_path, monkeypatch):
    """Three outlets whose OLDEST feed is English carry a Spanish service; five native Spanish outlets are active.
    3 of 8 Spanish-active outlets (0.375) is below the 0.40 furniture line, so the term is a story: dividing by the
    5 natives alone (0.6) hid it, and only because of which sibling happened to be created first."""
    from src.analytics.story_propagation import find_story_propagation

    s = _kw_session(tmp_path, monkeypatch)
    multi_es = []
    for dom in ("bbc.com", "dw.com", "france24.com"):
        _lang_feed(s, f"{dom} en", dom, f"https://{dom}/en/rss", "en")
        multi_es.append(_lang_feed(s, f"{dom} es", dom, f"https://{dom}/es/rss", "es"))
    natives = [_lang_feed(s, f"n{i}", f"native{i}.es", f"https://native{i}.es/rss", "es") for i in range(5)]
    s.commit()
    _lang_mention(s, "otrotermino", "es", [(n, 2) for n in natives])
    _lang_mention(s, "reformatermino", "es", [(multi_es[0], 8), (multi_es[1], 4), (multi_es[2], 1)])
    assert "reformatermino" in [i["term"] for i in find_story_propagation(s)["items"]]


def test_outlets_per_language_counts_an_outlet_once_per_language_it_is_active_in(tmp_path, monkeypatch):
    """The shared helper both language-ubiquity gates read (story propagation, rising themes)."""
    from src.analytics.managed import normalize_lang
    from src.database.outlet import OutletMap, outlets_per_language

    s = _kw_session(tmp_path, monkeypatch)
    en = _lang_feed(s, "bbc en", "bbc.com", "https://bbc.com/en/rss", "en")
    es = _lang_feed(s, "bbc es", "bbc.com", "https://bbc.com/es/rss", "es")
    es2 = _lang_feed(s, "bbc es2", "bbc.com", "https://bbc.com/es2/rss", "es")
    nat = _lang_feed(s, "nat", "nat.es", "https://nat.es/rss", "es")
    s.commit()
    got = outlets_per_language(s, [en, es, es2, nat], OutletMap(s), normalize_lang)
    assert got == {"en": 1, "es": 2}  # bbc is one Spanish outlet however many Spanish feeds it has
    assert outlets_per_language(s, [en], OutletMap(s), normalize_lang) == {"en": 1}  # only the ACTIVE feeds count


def test_galaxy_breadth_counts_outlets_not_feeds(tmp_path, monkeypatch):
    """The breadth every galaxy is ranked by (and the Observatory's radius) reads outlets (Opus read, finding 3)."""
    from src.analytics.supergroup_stats import _distinct_source_count
    from src.database.models import Keyword

    s = _kw_session(tmp_path, monkeypatch)
    ids = [_feed(s, n, "bbc.com", f"https://bbc.com/{n}") for n in ("a", "b", "c")]
    other = _feed(s, "DW", "dw.com", "https://dw.com/rss")
    s.commit()
    _mention_spread(s, "breadthterm", [(i, 1) for i in ids])
    kid = s.query(Keyword.id).filter_by(normalized_term="breadthterm").scalar()
    assert _distinct_source_count(s, [kid]) == 1  # one outlet, three feeds
    _mention_spread(s, "breadthterm2", [(i, 1) for i in ids] + [(other, 1)])
    kid2 = s.query(Keyword.id).filter_by(normalized_term="breadthterm2").scalar()
    assert _distinct_source_count(s, [kid2]) == 2


def test_the_framing_split_producer_groups_by_outlet():
    """A tone comparison is between outlets; one site's two feeds are not two outlets framing a term differently."""
    import inspect

    from src.briefing import producers

    assert "outlets.label(" in inspect.getsource(producers.framing_split)


def test_a_briefing_leads_evidence_carries_the_outlet_so_two_feeds_of_a_site_count_once(s):
    """The evidence builder writes the OUTLET (the source's domain) beside the feed label; the leads count reads it."""
    from src.briefing.card import Card
    from src.briefing.leads import _distinct_outlets
    from src.briefing.producers import _evidence_from_articles

    en = _feed(s, "BBC News", "bbc.com", "https://bbc.com/en.xml")
    ar = _feed(s, "BBC Arabic", "bbc.com", "https://bbc.com/ar.xml")
    other = _feed(s, "Reuters", "reuters.com", "https://reuters.com/rss")
    rows = [(a, s.get(Source, a.source_id).name) for a in s.query(Article).order_by(Article.id)]
    evidence = _evidence_from_articles(rows)
    assert {e["source"]: e["outlet"] for e in evidence} == {
        "BBC News": "bbc.com", "BBC Arabic": "bbc.com", "Reuters": "reuters.com",
    }
    assert {en, ar, other}  # three feeds, two outlets
    card = Card(type="rising", title="t", summary="s", bucket="rising", method="m", caveat="c", key="k", n=3,
                evidence=evidence)
    assert _distinct_outlets(card) == 2
