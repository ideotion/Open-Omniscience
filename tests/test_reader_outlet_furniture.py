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
from src.signals import near_dup
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


_RND = random.Random(99)
_HEAVY = " ".join(_RND.choice(_VOCAB) + str(i % 7) for i in range(300))  # ~300 distinct shingles


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
                                title=f"Story {i}", content=_TEMPLATE + "\n" + _HEAVY + "\n" + _story(i, 30),
                                hash=f"h{i}", language="sv", created_at=datetime.now(UTC)))
        # id 13: the first story, word for word, at another outlet, without the template
        arts.append(Article(url="https://other.test/copy", canonical_url="https://other.test/copy", source_id=2,
                            title="Story 0", content=_story(0, 30), hash="copy", language="sv", created_at=datetime.now(UTC)))
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


def test_repeated_shingles_need_half_the_distinct_pages_and_enough_pages():
    bodies = [_TEMPLATE + " " + _story(i) for i in range(10)]
    learned = outlet_furniture.repeated_shingles(bodies)
    assert shingles(_TEMPLATE) <= learned
    assert not (shingles(_story(0)) - shingles(_TEMPLATE)) & learned  # one page's story is never learned
    assert outlet_furniture.repeated_shingles(bodies[:7]) == frozenset()  # seven pages cannot tell
    # a story the outlet ran twice in ten pages stays: two is under half
    twice = bodies[:8] + [_TEMPLATE + " " + _story(0), _TEMPLATE + " " + _story(9)]
    assert not (shingles(_story(0)) - shingles(_TEMPLATE)) & outlet_furniture.repeated_shingles(twice)


def test_one_story_on_most_of_the_pages_counts_as_one_page():
    """The independent read: three versions of one story among five pages, or a live blog, are not a template."""
    story = _story(42, 120)
    bodies = [story + " update " + str(i) for i in range(6)] + [_story(i) for i in range(100, 108)]
    assert not (shingles(story) & outlet_furniture.repeated_shingles(bodies))


def test_a_template_that_makes_whole_pages_alike_is_still_learned():
    """The second independent read: unrelated pages over a heavy template are near-identical as WHOLE pages, so
    grouping on whole pages merged them into one and learned nothing. Grouping on what is left once the
    provisional template is out keeps them apart."""
    pages = [_HEAVY + " " + _story(i, 20) for i in range(20)]
    a, b = shingles(pages[0]), shingles(pages[1])
    assert len(a & b) / len(a | b) >= 0.7  # the field shape: the pages are alike as a whole
    assert shingles(_HEAVY) <= outlet_furniture.repeated_shingles(pages, titles=[f"Story {i} of the day" for i in range(20)])


def test_a_live_blog_on_most_pages_still_finds_its_copy_elsewhere():
    blog = _story(5, 150)
    bodies = [blog + " " + _story(200 + i, 15) for i in range(12)] + [_story(300 + i, 80) for i in range(8)]
    titles = ["Live: the winter storm hits the coast"] * 12 + [f"Other story number {i}" for i in range(8)]
    learned = outlet_furniture.repeated_shingles(bodies, titles=titles)
    # A title on most of the sample groups nothing (the site-name guard), so the blog may be learned; the reader's
    # per-pair rule still finds the blog's copy at an outlet that did not learn it.
    docs = {"mine": bodies[0], "elsewhere": blog}
    assert frozenset(docs) in _copies(docs, {"mine": 1, "elsewhere": 2}, {1: learned, 2: frozenset()})


def _copies(docs, group_of, group_drop, threshold=0.7):
    res = near_duplicate_clusters(docs, threshold=threshold, group_of=group_of, group_drop=group_drop)
    return {frozenset(c.members) for c in res.clusters if len(c.members) >= 2}


@pytest.mark.parametrize("titled", ["stamped", "rewritten", "empty"])
def test_a_story_its_outlet_learned_still_finds_its_copy_elsewhere(titled):
    """The third independent read: a story on 10 of the 20 newest pages, each with its own short update and its own
    title, can be learned as that outlet's template (content alone cannot tell it from a paywall block, the fourth
    read). The reader then decides per pair: the copy at another outlet, which learned nothing, is still found."""
    story = _story(5, 150)
    bodies = [story + " " + _story(200 + i, 15) for i in range(10)] + [_story(300 + i, 80) for i in range(10)]
    head = {
        "stamped": [f"Live: the winter storm hits the coast {9 + i}:00" for i in range(10)],
        "rewritten": [f"{w} as the storm moves north" for w in _VOCAB[:10]],
        "empty": [""] * 10,
    }[titled]
    titles = head + [f"Other story number {i}" for i in range(10)]
    learned = outlet_furniture.repeated_shingles(bodies, titles=titles)
    docs = {"mine": bodies[0], "elsewhere": story}
    assert frozenset(docs) in _copies(docs, {"mine": 1, "elsewhere": 2}, {1: learned, 2: frozenset()})


def test_a_paywall_block_on_twelve_of_twenty_pages_is_learned():
    """The fourth independent read: a paywall block on part of an outlet's pages, over short ledes under their own
    titles, made those pages copies of each other (row 67 again) when the learning required whole-page groups."""
    paywall = " ".join(_RND.choice(_VOCAB) + str(_RND.randrange(1000)) for _ in range(250))
    locked = [_story(400 + i, 25) + "\n" + paywall for i in range(12)]
    free = [_story(500 + i, 120) for i in range(8)]
    titles = [f"Locked story {w} today" for w in _VOCAB[:12]] + [f"Free story {w} today" for w in _VOCAB[12:20]]
    learned = outlet_furniture.repeated_shingles(locked + free, titles=titles)
    assert len(shingles(paywall) & learned) >= 0.9 * len(shingles(paywall))
    docs = {f"p{i}": locked[i] for i in range(6)}
    assert _copies(docs, dict.fromkeys(docs, 1), {1: learned}) == set()
    assert _copies(docs, dict.fromkeys(docs, 1), {1: frozenset()})  # without it, they are


def test_a_title_the_whole_sample_shares_groups_nothing():
    """A site name stored as every page's title would merge every page and bring row 67 back."""
    pages = [_HEAVY + " " + _story(i, 20) for i in range(20)]
    assert shingles(_HEAVY) <= outlet_furniture.repeated_shingles(pages, titles=["Hufvudstadsbladet | Nyheter från Finland"] * 20)


def test_the_ingest_furniture_list_is_applied_first():
    """The ingest's app banner (an hbl.fi line) is on every page, but it is the ingest's list that names it; the
    learning reads the bodies without it, so the two never disagree (and one list is kept, not two)."""
    banner = "För att din app ska fortsätta fungera behöver du uppdatera den nu"
    bodies = [banner + "\n" + _story(i) for i in range(10)]
    assert not (shingles(banner) & outlet_furniture.repeated_shingles(bodies))
    assert shingles(banner) & outlet_furniture.repeated_shingles([b.replace("app ska", "app skall") for b in bodies])


def test_a_wire_footer_one_outlet_repeats_does_not_split_its_copy_elsewhere():
    """The independent read: two pages of different outlets are compared without only what BOTH outlets repeat."""
    footer = " ".join(_VOCAB[:60])
    story = _story(7, 80)
    docs = {"x": story + "\n" + footer, "y": story + "\n" + footer}
    learned = shingles(footer)  # learned at x's outlet only; y's small outlet learned nothing
    assert frozenset(docs) in _copies(docs, {"x": 1, "y": 2}, {1: learned, 2: frozenset()})
    assert frozenset(docs) in _copies(docs, {"x": 1, "y": 2}, {1: learned, 2: learned})
    assert frozenset(docs) in _copies(docs, {"x": 1, "y": 1}, {1: learned})


def test_two_pages_of_one_outlet_sharing_only_its_template_are_not_copies():
    docs = {"a": _TEMPLATE + " " + _HEAVY + " " + _story(1, 30), "b": _TEMPLATE + " " + _HEAVY + " " + _story(2, 30)}
    learned = shingles(_TEMPLATE + " " + _HEAVY)
    assert _copies(docs, {"a": 1, "b": 1}, {1: learned}) == set()
    assert _copies(docs, {"a": 1, "b": 2}, {1: learned, 2: frozenset()})  # what only one outlet learned is kept


def test_a_doc_emptied_by_the_drop_is_never_a_copy():
    docs = {"a": _TEMPLATE, "b": _TEMPLATE, "c": _story(1)}
    assert _copies(docs, dict.fromkeys(docs, 1), {1: shingles(_TEMPLATE)}) == set()
    assert any(len(c.members) == 2 for c in near_duplicate_clusters(docs, threshold=0.7).clusters)  # without it, they are


def test_the_memo_tells_two_drops_apart():
    docs = {"a": _TEMPLATE + " " + _story(1, 12), "b": _TEMPLATE + " " + _story(2, 12)}
    plain = near_duplicate_clusters(docs, threshold=0.5)
    assert any(len(c.members) == 2 for c in plain.clusters)
    assert _copies(docs, dict.fromkeys(docs, 1), {1: shingles(_TEMPLATE)}, threshold=0.5) == set()
    assert _copies(docs, {"a": 1, "b": 2}, {1: shingles(_TEMPLATE)}, threshold=0.5)  # other groups, other memo entry


def test_the_pair_mode_refuses_more_docs_than_it_compares_exactly():
    docs = {str(i): _story(i, 10) for i in range(near_dup.PAIR_MODE_MAX + 1)}
    with pytest.raises(ValueError):
        near_duplicate_clusters(docs, group_of=dict.fromkeys(docs, 1), group_drop={})


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
        assert outlet_furniture.outlet_furniture_keywords(s, 1) == {1, 2}  # the whole set, from the cache
        outlet_furniture.clear_cache()
        assert outlet_furniture.outlet_furniture_keywords(s, 1, [1], min_articles=13) == set()  # too few articles
        assert outlet_furniture.outlet_furniture_keywords(s, None, [1]) == set()
