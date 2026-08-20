"""The Feed: an exact order, no reading history, and an honest empty state.

Rulings 8-13 and 40-41 (field feedback 2026-08-07).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The properties worth pinning are the ones a reader cannot check for themselves: that
scrolling shows every article exactly once, that the shuffle depends on nothing but the
id and the seed, and that an empty feed says WHY rather than implying the corpus is
empty. ``src.api.main`` needs the crypto extra, so the endpoint half runs in CI; the pure
permutation maths runs anywhere.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.feed import _P, shuffle_key, shuffle_params

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.feed import router as feed_router
    from src.database.session import get_db

    _HAVE_APP = True
except BaseException:  # noqa: BLE001  # pragma: no cover - crypto extra absent
    _HAVE_APP = False

from src.database.models import Article, Base, Source


# --------------------------------------------------------------------------- #
#  the permutation (pure -- runs on any install)
# --------------------------------------------------------------------------- #
def test_the_shuffle_is_a_bijection_so_a_page_cannot_repeat_or_skip():
    """The whole of pagination rests on this. If two ids could share a key, a page
    boundary would either show one article twice or drop the other."""
    for seed in (0, 1, 7, 12345, 2**31 - 2, 987654321):
        keys = {shuffle_key(i, seed) for i in range(1, 5000)}
        assert len(keys) == 4999, f"seed {seed} collides"


def test_a_zero_multiplier_is_impossible_whatever_the_seed():
    """The one input that would break it: a multiplier of 0 mod P collapses every
    article onto one key. Forced non-zero rather than hoped for."""
    for seed in (0, _P - 1, _P, 2 * (_P - 1), 10**18):
        mult, _add = shuffle_params(seed)
        assert mult % _P != 0, f"seed {seed} produced a degenerate multiplier"


def test_two_seeds_give_genuinely_different_orders_not_a_rotation():
    """If only the additive term varied, a reshuffle would hand back the same cyclic
    order started somewhere else -- the articles would keep the same neighbours. The
    multiplier is what makes them different orders."""
    ids = list(range(1, 400))
    a = sorted(ids, key=lambda i: shuffle_key(i, 11))
    b = sorted(ids, key=lambda i: shuffle_key(i, 12))
    assert a != b
    # ...and not merely rotated: the successor of an id differs between the two.
    succ_a = {a[i]: a[i + 1] for i in range(len(a) - 1)}
    succ_b = {b[i]: b[i + 1] for i in range(len(b) - 1)}
    shared = sum(1 for k, v in succ_a.items() if succ_b.get(k) == v)
    assert shared < len(ids) // 10, "the two orders keep the same neighbours (a rotation)"


def test_no_seed_produces_the_corpus_in_ingestion_order():
    """The defect this caught, kept as the guard.

    An affine map only MIXES where the product wraps the modulus. A first cut derived the
    multiplier as ``1 + seed % (P-1)``, so a SMALL seed gave a small multiplier, the
    product never reached P on a few-thousand-article corpus, and the "shuffled" feed
    handed back the articles in id order while saying it was shuffled. Its mirror is just
    as bad: a multiplier just BELOW P acts like a small negative one and gives strict
    DESCENDING order, which is what a merely-hashed multiplier produced for seed 0.

    Both directions fail on a SMALL corpus -- exactly where a reader has no way to notice
    -- so the fixture is deliberately small, and seed 0 is deliberately included because
    it is the value a caller who sends nothing would get.
    """
    ids = list(range(1, 41))
    for seed in (0, 1, 2, 3, 7, 11, 12, 100, 999999, 2**31):
        order = sorted(ids, key=lambda i: shuffle_key(i, seed))
        assert order != ids, f"seed {seed} is ingestion order wearing a shuffle's name"
        assert order != ids[::-1], f"seed {seed} is reverse ingestion order"


def test_every_multiplier_sits_in_the_middle_of_the_range():
    """The structural reason the two failures above cannot come back: inside [P/4, 3P/4)
    both the multiplier and its distance from P exceed a quarter of the range, so
    consecutive ids can never land next to each other whatever the caller sends."""
    for seed in (0, 1, 12, 10**6, 2**31, 10**18):
        mult, _add = shuffle_params(seed)
        assert _P // 4 <= mult < 3 * (_P // 4) + 1, f"seed {seed} -> {mult}"


def test_the_same_seed_is_the_same_order_every_time():
    """A seed that did not reproduce its order would make the cursor meaningless: the
    next page would be computed against a different sequence than the last one."""
    first = [shuffle_key(i, 424242) for i in range(1, 200)]
    second = [shuffle_key(i, 424242) for i in range(1, 200)]
    assert first == second


def test_the_key_depends_on_the_id_and_the_seed_and_nothing_else():
    """A structural statement of the no-engagement-scoring rule: the function's whole
    input is (id, seed). There is no article, no source and no history in scope, so
    there is nothing for a behavioural signal to enter through."""
    import inspect

    params = list(inspect.signature(shuffle_key).parameters)
    assert params == ["article_id", "seed"]


# --------------------------------------------------------------------------- #
#  the endpoint
# --------------------------------------------------------------------------- #
pytestmark_app = pytest.mark.skipif(not _HAVE_APP, reason="needs the crypto extra (runs in CI)")


@pytest.fixture()
def client():
    if not _HAVE_APP:
        pytest.skip("needs the crypto extra")
    # StaticPool: this handler is a plain `def`, so Starlette runs it in the threadpool,
    # and a second thread checking out a second connection to sqlite :memory: gets a
    # second EMPTY database -- every request 500s on "no such table" while the fixture
    # looks perfectly seeded. One connection for everyone is what makes it real.
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    s = Sess()
    good = Source(name="Qualified", domain="q.test", status="qualified")
    pending = Source(name="Pending", domain="p.test", status="unqualified")
    s.add_all([good, pending])
    s.commit()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(1, 41):
        s.add(Article(
            title=f"t{i}", url=f"https://q.test/{i}", canonical_url=f"https://q.test/{i}",
            hash=f"h{i}", source_id=good.id, content="body " * 400,
            published_at=base + timedelta(hours=i),
        ))
    # one quarantined and one from a source nobody has qualified: both held back
    s.add(Article(title="quar", url="https://q.test/x", canonical_url="https://q.test/x",
                  hash="hx", source_id=good.id, content="c", quarantined=True,
                  published_at=base))
    s.add(Article(title="pend", url="https://p.test/y", canonical_url="https://p.test/y",
                  hash="hy", source_id=pending.id, content="c", published_at=base))
    s.commit()

    app = FastAPI()
    app.include_router(feed_router)
    app.dependency_overrides[get_db] = lambda: s
    try:
        yield TestClient(app), s
    finally:
        app.dependency_overrides.clear()
        s.close()


def _walk(c, **kw):
    """Scroll the whole feed, returning the ids in the order they were shown."""
    seen, cursor, pages = [], None, 0
    while True:
        q = dict(kw)
        if cursor:
            q["after"] = cursor
        r = c.get("/api/feed", params=q)
        assert r.status_code == 200, r.text
        d = r.json()
        seen.extend(a["id"] for a in d["results"])
        pages += 1
        if not d["has_more"] or not d["next_cursor"]:
            break
        cursor = d["next_cursor"]
        assert pages < 50, "the walk is not terminating"
    return seen


@pytestmark_app
def test_scrolling_shows_every_visible_article_exactly_once(client):
    c, _ = client
    ids = _walk(c, order="shuffled", seed=99, limit=7)
    assert len(ids) == len(set(ids)), "an article was shown twice across a page boundary"
    assert len(ids) == 40, f"the walk missed articles: {len(ids)} of 40"


@pytestmark_app
def test_the_chronological_walk_is_complete_too_and_newest_first(client):
    c, _ = client
    ids = _walk(c, order="recent", limit=6)
    assert len(ids) == len(set(ids)) == 40
    assert ids[0] == 40 and ids[-1] == 1, "recent must run newest to oldest"


@pytestmark_app
def test_a_shared_publication_timestamp_does_not_drop_or_repeat_a_row(client):
    """The tiebreak earns its keep here: many articles legitimately share a timestamp,
    and a cursor without one either skips every row that shares the boundary value or
    shows them all again."""
    c, s = client
    when = datetime(2025, 6, 1, tzinfo=UTC)
    src = s.query(Source).filter_by(status="qualified").one()
    for i in range(60, 70):
        s.add(Article(title=f"same{i}", url=f"https://q.test/s{i}",
                      canonical_url=f"https://q.test/s{i}", hash=f"hs{i}",
                      source_id=src.id, content="c", published_at=when))
    s.commit()
    ids = _walk(c, order="recent", limit=3)
    assert len(ids) == len(set(ids)) == 50


@pytestmark_app
def test_quarantined_and_unqualified_are_held_back_and_counted(client):
    """Ruling 11. Both exclusions, and -- because a held-back article is invisible --
    the count that explains the difference between the feed and the corpus."""
    c, _ = client
    d = c.get("/api/feed", params={"order": "recent", "limit": 50}).json()
    titles = {a["title"] for a in d["results"]}
    assert "quar" not in titles and "pend" not in titles
    assert d["held_back"] == {"quarantined": 1, "source_not_qualified": 1}


@pytestmark_app
def test_the_held_back_counts_are_paid_for_once_not_once_per_page(client):
    """They are two exact COUNTs over the whole corpus, and an infinite scroll asks for
    a page every time a reader reaches the bottom -- so charging them per page is
    O(corpus) per twenty cards. They describe the corpus, not the page, so they cannot
    change mid-scroll and the client keeps the first answer.

    A later page reports ``None`` -- "not recomputed" -- rather than zeros, which would
    read as "nothing is held back" and quietly contradict the first page.
    """
    c, _ = client
    first = c.get("/api/feed", params={"order": "recent", "limit": 5}).json()
    assert first["held_back"]["quarantined"] == 1
    later = c.get(
        "/api/feed", params={"order": "recent", "limit": 5, "after": first["next_cursor"]}
    ).json()
    assert later["held_back"] is None
    assert later["results"], "the page itself is still served"


@pytestmark_app
def test_an_empty_feed_says_why_rather_than_looking_like_an_empty_corpus(client):
    """The state a real machine reaches: qualification has never run, so every source is
    'unqualified' and nothing is admissible. A blank column would read as "you have
    collected nothing", which is false and unactionable."""
    c, s = client
    s.query(Source).filter_by(status="qualified").one().status = "unqualified"
    s.commit()
    d = c.get("/api/feed", params={"order": "recent"}).json()
    assert d["results"] == []
    assert d["held_back"]["source_not_qualified"] >= 40, (
        "the reason must be counted, so the UI can say it"
    )


@pytestmark_app
def test_each_card_carries_its_own_top_keywords_with_real_counts(client):
    """Ruling 10: the article's OWN keywords, verifiable -- the count is the stored
    mention count, not a relevance figure."""
    from src.database.models import Keyword, KeywordMention

    c, s = client
    art = s.query(Article).filter_by(title="t1").one()
    terms = {"flood": 9, "levee": 4, "rain": 7, "mud": 1}
    for term, n in terms.items():
        k = Keyword(term=term, normalized_term=term)
        s.add(k)
        s.flush()
        s.add(KeywordMention(article_id=art.id, keyword_id=k.id, count=n))
    s.commit()
    d = c.get("/api/feed", params={"order": "recent", "limit": 50}).json()
    card = next(a for a in d["results"] if a["id"] == art.id)
    assert [k["term"] for k in card["keywords"]] == ["flood", "rain", "levee"], (
        "the top three by real count, largest first"
    )
    assert [k["count"] for k in card["keywords"]] == [9, 7, 4]


@pytestmark_app
def test_read_more_needs_no_second_request_and_says_when_there_is_more(client):
    """Ruling 12: expanding happens in place. Both lengths ride the same payload, and a
    body longer than the card can hold is declared rather than silently cut."""
    c, _ = client
    d = c.get("/api/feed", params={"order": "recent", "limit": 1}).json()
    card = d["results"][0]
    assert len(card["excerpt"]) < len(card["excerpt_full"])
    assert card["truncated"] is True and card["chars"] > len(card["excerpt_full"])


@pytestmark_app
def test_the_feed_defaults_to_everything(client):
    """Ruling 9: no provenance narrowing unless one is asked for."""
    c, _ = client
    d = c.get("/api/feed", params={"order": "recent", "limit": 50}).json()
    assert len(d["results"]) == 40


@pytestmark_app
def test_a_provenance_filter_that_empties_a_page_does_not_end_the_scroll(client):
    """The filter runs on the loaded page, so a page can survive with nothing in it. If
    the cursor came from the surviving rows it would be null there and the feed would
    stop, reporting the corpus exhausted several thousand articles early. It comes from
    the scan position instead, which is where resuming actually has to happen."""
    c, s = client
    # Give one article a provenance nothing else on the first pages will match.
    from src.database.models import Article as A

    wiki = Source(name="Wikipedia (en)", domain="en.wikipedia.org",
                  status="qualified", source_type="wiki")
    s.add(wiki)
    s.commit()
    # The oldest ADMISSIBLE article: the fixture's quarantined row is older still, and
    # moving that one would test nothing -- it is excluded before provenance is even
    # considered, so the walk would legitimately never reach it.
    oldest = (
        s.query(A)
        .filter(A.quarantined.isnot(True), A.title.like("t%"))
        .order_by(A.published_at.asc())
        .first()
    )
    oldest.source_id = wiki.id
    s.commit()

    seen, cursor, pages = [], None, 0
    while pages < 30:
        q = {"order": "recent", "limit": 3, "provenance": "wikipedia"}
        if cursor:
            q["after"] = cursor
        d = c.get("/api/feed", params=q).json()
        seen.extend(a["id"] for a in d["results"])
        pages += 1
        if not d["has_more"] or not d["next_cursor"]:
            break
        cursor = d["next_cursor"]
    assert oldest.id in seen, (
        "the scroll stopped before reaching the only matching article -- pages that "
        "filter to nothing must still hand back a usable cursor"
    )


@pytestmark_app
def test_the_method_and_the_caveat_travel_with_the_page(client):
    """Both orders miss articles that arrive mid-scroll, in opposite directions. A
    reader who is not told assumes they have seen everything."""
    c, _ = client
    for order in ("shuffled", "recent"):
        d = c.get("/api/feed", params={"order": order, "seed": 3}).json()
        assert d["method"] and d["caveat"]
    shuffled = c.get("/api/feed", params={"order": "shuffled", "seed": 3}).json()
    assert "No reading history is kept or consulted." in shuffled["method"], (
        "the one sentence that states the privacy property must survive a reword"
    )
    # Both strings are i18n keys, so they must exist verbatim in every locale file --
    # editing one here without re-keying it silently un-translates it in eleven locales.
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "static" / "locales"
    for lang in ("en", "fr", "ar", "zh"):
        table = json.loads((root / f"{lang}.json").read_text(encoding="utf-8"))
        for order in ("shuffled", "recent"):
            d = c.get("/api/feed", params={"order": order, "seed": 3}).json()
            assert d["method"] in table, f"{lang}: method not keyed ({order})"
            assert d["caveat"] in table, f"{lang}: caveat not keyed ({order})"


@pytestmark_app
def test_the_sql_order_matches_the_pure_reference(client):
    """The permutation is asserted in Python and executed in SQL. If the two ever
    disagreed, every property proved above would be about a different function."""
    c, _ = client
    ids = _walk(c, order="shuffled", seed=555, limit=9)
    assert ids == sorted(ids, key=lambda i: shuffle_key(i, 555))


@pytestmark_app
def test_a_malformed_cursor_is_refused_not_silently_ignored(client):
    """Ignoring it would restart the walk from the top and show a reader the same
    articles again while looking like it worked."""
    c, _ = client
    for order, bad in (("shuffled", "not-a-number"), ("recent", "not|a|cursor")):
        r = c.get("/api/feed", params={"order": order, "after": bad})
        assert r.status_code == 400, f"{order} accepted {bad!r}"


@pytestmark_app
def test_with_nothing_qualified_the_corpus_is_never_walked(client):
    """The same empty page as the test above -- this one is about what it COSTS.

    Before the guard, both orders scanned the whole corpus to return nothing, and
    "nothing is qualified yet" is what a fresh install and a just-imported corpus both
    look like. Measured on a 200,000-article synthetic corpus, the walk this skips took
    214 ms. An index probe on sources answers it instead.

    Asserting the ABSENCE of work needs the statements themselves: an assertion about
    the empty payload passes whether or not the query ran, which is exactly what the
    guard changes.
    """
    from sqlalchemy import event

    c, s = client
    s.query(Source).filter_by(status="qualified").one().status = "unqualified"
    s.commit()
    engine = s.get_bind()
    seen: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _cap(conn, cur, stmt, params, ctx, many):  # noqa: ANN001
        seen.append(" ".join(stmt.split()))

    try:
        for order in ("shuffled", "recent"):
            seen.clear()
            d = c.get("/api/feed", params={"order": order}).json()
            assert d["results"] == [], order
            walks = [
                q
                for q in seen
                if "FROM articles" in q and "ORDER BY" in q and "LIMIT" in q
            ]
            assert not walks, f"{order}: the corpus was walked anyway: {walks[:1]}"
            # ...and the page is still a real page, built by the same code as any other.
            assert d["method"] and d["caveat"] and d["held_back"] is not None, order
    finally:
        event.remove(engine, "before_cursor_execute", _cap)


@pytestmark_app
def test_the_chronological_order_refuses_the_source_driven_join(client):
    """SQLite plans the FIRST chronological page from `sources` -- for each qualified
    source it walks that source's articles by source_id and sorts the lot in a temp
    b-tree, because it cannot see that walking published_at in reverse satisfies the
    LIMIT after ~21 rows. Unary `+` makes that term unusable as a lookup and the plan
    flips. Measured on the 200,000-article corpus: 442.7 ms -> 19.6 ms, same rows.

    Asserted on the SQL that REACHES SQLite rather than on the source file, because a
    comment explaining the hint would satisfy a grep for it. Asserted rather than the
    EXPLAIN, because a plan over a forty-article fixture is a claim about the fixture.
    """
    from sqlalchemy import event

    c, s = client
    engine = s.get_bind()
    seen: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _cap(conn, cur, stmt, params, ctx, many):  # noqa: ANN001
        seen.append(" ".join(stmt.split()))

    try:
        seen.clear()
        c.get("/api/feed", params={"order": "recent"})
        joins = [q for q in seen if "JOIN sources" in q and "ORDER BY" in q]
        assert joins, "no chronological walk was emitted at all"
        assert all("+articles.source_id = sources.id" in q for q in joins), (
            f"the plan hint did not reach SQLite: {joins[:1]}"
        )

        # The negative-space twin: the shuffled order sorts on a computed key that NO
        # index can supply, so the hint buys it nothing and it keeps the plain join.
        # Pinning this stops the hint being "helpfully" applied everywhere later.
        seen.clear()
        c.get("/api/feed", params={"order": "shuffled"})
        sjoins = [q for q in seen if "JOIN sources" in q and "ORDER BY" in q]
        assert sjoins, "no shuffled walk was emitted at all"
        assert all("+articles.source_id" not in q for q in sjoins), (
            "the shuffled order must keep the plain join"
        )
    finally:
        event.remove(engine, "before_cursor_execute", _cap)
