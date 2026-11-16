"""Row 67 (field test 2026-11-14, report 7.1): the reader's copies badge and Related list over an outlet's template.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

One hbl.fi article showed about twelve unrelated hbl.fi pages as "near-identical copies", and Related ranked
articles by 17 shared keywords that were all the platform's own page text. Pinned here, through the real route and
the real ``index_article``: twelve pages of one outlet that share only its template are neither copies nor each
other's top Related, a real copy of the story at another outlet still is both, and the pure pieces hold their
thresholds.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import outlet_furniture
from src.database.models import Article, Base, Source
from src.signals.near_dup import near_duplicate_clusters, shingles

_TEMPLATE = (
    "Prenumerera nu och läs Hufvudstadsbladet digitalt utan begränsningar varje dag Kundservice Annonsera "
    "Tipsa redaktionen Integritetspolicy Cookieinställningar Om oss Kontakta oss Logga in Nyhetsbrev "
    "Senaste nytt Mest läst Helsingfors Esbo Vanda Kultur Sport Opinion Ekonomi Utrikes Inrikes Väder "
    "Ladda ned appen Följ oss på sociala medier Ansvarig utgivare Chefredaktör Prenumerationsvillkor "
    "Användarvillkor Tillgänglighet Kundservice öppen vardagar Prenumerera nu och läs Hufvudstadsbladet "
    "Kundservice Annonsera Tipsa redaktionen Integritetspolicy Cookieinställningar Om oss Kontakta oss"
)
_VOCAB = (  # noqa: SIM905 - a word list kept readable
    "harbour ferry council budget tram school library museum festival bridge election minister parliament "
    "hospital nurse doctor theatre orchestra concert winter storm snow ice summer island archipelago fishing "
    "salmon forest wolf bear reindeer university student research climate energy wind solar nuclear grid "
    "railway station airport pilot strike union wage pension housing rent mortgage bank inflation export "
    "timber paper factory engineer startup software court judge police robbery fire rescue coast guard "
    "language minority bilingual newspaper editor author novel poetry painter gallery architect church"
).split() 


def _story(seed: int, n: int = 60) -> str:
    rnd = random.Random(seed)
    return " ".join(rnd.choice(_VOCAB) for _ in range(n)).capitalize() + "."


@pytest.fixture(autouse=True)
def _fresh_cache():
    outlet_furniture.clear_cache()
    yield
    outlet_furniture.clear_cache()


def test_twelve_template_pages_are_not_copies_and_a_real_copy_still_is(tmp_path):
    from src.analytics.extract import BaselineExtractor
    from src.analytics.store import index_article
    from src.database.session import get_db

    engine = create_engine(f"sqlite:///{tmp_path / 'r67.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="HBL", domain="hbl.test"))
        s.add(Source(name="Other", domain="other.test"))
        s.commit()
        arts = []
        for i in range(12):  # ids 1..12: the template around twelve unrelated stories
            arts.append(Article(url=f"https://hbl.test/{i}", canonical_url=f"https://hbl.test/{i}", source_id=1,
                                title=f"Story {i}", content=_TEMPLATE + "\n" + _story(i) + "\n" + _TEMPLATE,
                                hash=f"h{i}", language="sv", created_at=datetime.now(UTC)))
        # id 13: the first story, word for word, at another outlet, without the template
        arts.append(Article(url="https://other.test/copy", canonical_url="https://other.test/copy", source_id=2,
                            title="Story 0", content=_story(0), hash="copy", language="sv", created_at=datetime.now(UTC)))
        s.add_all(arts)
        s.commit()
        ex = BaselineExtractor()
        for art in arts:
            index_article(s, art, extractor=ex, country="fi")
        s.commit()

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as client:
            body = client.get("/api/articles/1/view").text
    finally:
        app.dependency_overrides.clear()
    assert 'class="dup-pill"' in body and "≈2" in body, body[body.find("dup-badge") - 200 : body.find("dup-badge") + 600]
    badge = body[body.find('class="dup-badge"') : body.find("</details>")]
    assert "/api/articles/13/view" in badge
    assert not any(f"/api/articles/{i}/view" in badge for i in range(2, 13))
    related = body[body.find("Related in your corpus") :]
    related = related[: related.find("</ul>")]
    first = related.find("/api/articles/")
    assert first != -1 and related[first:].startswith("/api/articles/13/view"), related


def test_repeated_shingles_need_half_the_pages_and_enough_pages():
    bodies = [_TEMPLATE + " " + _story(i) for i in range(6)]
    learned = outlet_furniture.repeated_shingles(bodies)
    assert shingles(_TEMPLATE) <= learned
    assert not (shingles(_story(0)) & learned - shingles(_TEMPLATE))  # one page's story is never learned
    assert outlet_furniture.repeated_shingles(bodies[:3]) == frozenset()  # three pages cannot tell
    # a story the outlet ran twice in six pages stays: two is under half
    twice = bodies[:4] + [_TEMPLATE + " " + _story(0), _TEMPLATE + " " + _story(9)]
    assert not (shingles(_story(0)) - shingles(_TEMPLATE)) & outlet_furniture.repeated_shingles(twice)


def test_the_ingest_furniture_list_is_applied_first():
    """A line ``is_furniture`` names never counts as the outlet's own text either way; reusing it keeps one list."""
    bodies = ["Advertisement\n" + _story(i) for i in range(6)]
    assert not (shingles("Advertisement") & outlet_furniture.repeated_shingles(bodies))


def test_a_doc_emptied_by_the_drop_is_never_a_copy():
    docs = {"a": _TEMPLATE, "b": _TEMPLATE, "c": _story(1)}
    drop = {d: shingles(_TEMPLATE) for d in docs}
    res = near_duplicate_clusters(docs, threshold=0.7, drop_shingles=drop)
    assert not any(len(c.members) >= 2 for c in res.clusters)
    assert any(len(c.members) == 2 for c in near_duplicate_clusters(docs, threshold=0.7).clusters)  # without it, they are


def test_the_memo_tells_two_drops_apart():
    docs = {"a": _TEMPLATE + " " + _story(1, 12), "b": _TEMPLATE + " " + _story(2, 12)}
    plain = near_duplicate_clusters(docs, threshold=0.5)
    dropped = near_duplicate_clusters(docs, threshold=0.5, drop_shingles={d: shingles(_TEMPLATE) for d in docs})
    assert any(len(c.members) == 2 for c in plain.clusters)
    assert not any(len(c.members) >= 2 for c in dropped.clusters)


def test_furniture_keywords_need_half_the_sources_articles(tmp_path):
    from src.database.models import Keyword, KeywordMention

    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, future=True)
    with S() as s:
        s.add(Source(id=1, name="S", domain="s.test"))
        s.add_all([Keyword(id=k, term=t, normalized_term=t) for k, t in ((1, "kundservice"), (2, "harbour"), (3, "ferry"))])
        s.flush()
        for i in range(1, 13):
            s.add(Article(id=i, url=f"u{i}", canonical_url=f"u{i}", source_id=1, title="t", content="c", hash=f"k{i}"))
        s.flush()
        for i in range(1, 13):
            s.add(KeywordMention(keyword_id=1, article_id=i, source_id=1))  # every page
            if i <= 6:
                s.add(KeywordMention(keyword_id=2, article_id=i, source_id=1))  # half the pages
            if i <= 5:
                s.add(KeywordMention(keyword_id=3, article_id=i, source_id=1))  # under half
        s.commit()
        assert outlet_furniture.outlet_furniture_keywords(s, 1, [1, 2, 3]) == {1, 2}
        assert outlet_furniture.outlet_furniture_keywords(s, 1, [1], min_articles=13) == set()  # too few articles
        assert outlet_furniture.outlet_furniture_keywords(s, None, [1]) == set()
