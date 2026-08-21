"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

T13 slice 1 — the omnibar endpoint: index-backed federation over articles
(FTS5), keywords, sources, wiki pages and law documents; first three per
group with the TRUE totals disclosed; a half-typed Boolean query falls back
to a phrase match instead of a 400 (mid-typing is not an error condition).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def omni_seed(client):
    from src.database.models import Article, Keyword, LawDocument, Source, WikiPage
    from src.database.session import session_scope

    with session_scope() as s:
        src = Source(name="Omnibar Gazette", domain="omnibargazette.example")
        s.add(src)
        s.flush()
        art_ids = []
        for i in range(4):
            a = Article(
                url=f"https://omnibargazette.example/{i}",
                canonical_url=f"https://omnibargazette.example/{i}",
                source_id=src.id,
                title=f"Quokkafloss report {i}",
                content=f"the quokkafloss situation, instalment {i}",
                language="en",
                hash=f"omni{i}" + "c" * 59,
                published_at=datetime.now(UTC),
            )
            s.add(a)
            s.flush()
            art_ids.append(a.id)
        kw = Keyword(term="quokkafloss", normalized_term="quokkafloss", frequency=7)
        s.add(kw)
        wp = WikiPage(wiki="en", title="Quokkafloss (disambiguation)")
        s.add(wp)
        ld = LawDocument(jurisdiction="eu", title="Quokkafloss Directive 2026",
                         url="https://example.eu/quokkafloss")
        s.add(ld)
        s.flush()
        ids = {"src": src.id, "arts": art_ids, "kw": kw.id, "wp": wp.id, "ld": ld.id}
    yield ids
    with session_scope() as s:
        for aid in ids["arts"]:
            s.execute(text(f"DELETE FROM articles WHERE id = {aid}"))  # noqa: S608
        s.execute(text(f"DELETE FROM keywords WHERE id = {ids['kw']}"))  # noqa: S608
        s.execute(text(f"DELETE FROM wiki_pages WHERE id = {ids['wp']}"))  # noqa: S608
        s.execute(text(f"DELETE FROM law_documents WHERE id = {ids['ld']}"))  # noqa: S608
        s.execute(text(f"DELETE FROM sources WHERE id = {ids['src']}"))  # noqa: S608


def _group(d, kind):
    return next(g for g in d["groups"] if g["kind"] == kind)


def test_omni_federates_with_disclosed_totals(client, omni_seed):
    d = client.get("/api/search/omni", params={"q": "quokkafloss"}).json()
    assert d["per_group"] == 3
    arts = _group(d, "articles")
    assert arts["total"] == 4, arts  # 4 matched, 3 shown -- the truth is disclosed
    assert len(arts["items"]) == 3
    assert arts["items"][0]["url"].startswith("/api/articles/")  # LOCAL reader first
    kws = _group(d, "keywords")
    assert kws["total"] >= 1
    assert any(i["normalized_term"] == "quokkafloss" for i in kws["items"])
    assert _group(d, "sources")["total"] == 0  # name does not contain the term
    assert any(i["title"].startswith("Quokkafloss") for i in _group(d, "wiki")["items"])
    assert any(i["jurisdiction"] == "eu" for i in _group(d, "law")["items"])
    assert "index-backed" in d["method"]


def test_omni_excludes_quarantined_articles_from_both_items_and_total(client, omni_seed):
    """A quarantined article is the app's OWN "this is a list, not an article" verdict.

    Two properties, and the second is the one that regressed elsewhere: the row must
    not surface, AND the disclosed ``total`` must count the same set the items come
    from. /api/articles applies this condition always, so an omnibar total that still
    counted quarantined rows would state a number the user cannot reach by opening the
    full search -- the exact property ``source_type_facets`` once claimed and did not
    keep (ledger, 2026-08-02).
    """
    from src.database.models import Article
    from src.database.session import session_scope

    before = client.get("/api/search/omni", params={"q": "quokkafloss"}).json()
    assert _group(before, "articles")["total"] == 4

    with session_scope() as s:
        s.get(Article, omni_seed["arts"][0]).quarantined = True

    after = _group(client.get("/api/search/omni", params={"q": "quokkafloss"}).json(), "articles")
    assert after["total"] == 3, "the quarantined article must leave the disclosed total"
    shown = {int(i["url"].rsplit("/", 2)[-2]) for i in after["items"]}
    assert omni_seed["arts"][0] not in shown, "a quarantined article must not be listed"


def test_watch_matcher_excludes_quarantined_articles(client, omni_seed):
    """A watch does not merely display a result -- it raises a Lead card. Alerting on
    content the app judged not-an-article manufactures a signal out of nav soup."""
    from src.analytics.watches import _fts_matcher
    from src.database.models import Article
    from src.database.session import session_scope

    with session_scope() as s:
        assert len(_fts_matcher(s, "quokkafloss")) == 4
        s.get(Article, omni_seed["arts"][0]).quarantined = True
    with session_scope() as s:
        ids = _fts_matcher(s, "quokkafloss")
    assert omni_seed["arts"][0] not in ids
    assert len(ids) == 3


def test_omni_wiki_group_searches_wikipedia_article_content(client):
    """Maintainer 2026-06-21: the unified search must also search Wikipedia ARTICLES.
    A wiki-edition corpus article (source xx.wikipedia.org) is found by CONTENT (FTS),
    surfaced in the wiki group as a reader link — not only by watched-page title."""
    from src.database.models import Article, Source
    from src.database.session import session_scope

    with session_scope() as s:
        wsrc = Source(name="Wikipedia (en)", domain="en.wikipedia.org")
        s.add(wsrc)
        s.flush()
        a = Article(
            url="https://en.wikipedia.org/wiki/Zorblax",
            canonical_url="https://en.wikipedia.org/wiki/Zorblax",
            source_id=wsrc.id,
            title="Zorblax",
            language="en",
            content="Zorblax is a fictional zibblequark studied only in tests.",
            hash="zwiki" + "d" * 59,
            published_at=datetime.now(UTC),
        )
        s.add(a)
        s.flush()
        aid, sid = a.id, wsrc.id
    try:
        d = client.get("/api/search/omni", params={"q": "zibblequark"}).json()
        wiki = _group(d, "wiki")
        assert wiki["total"] >= 1, wiki
        it = wiki["items"][0]
        assert it.get("article_id") == aid  # a CONTENT hit (not a title-only hit)
        assert it["url"] == f"/api/articles/{aid}/view"  # opens the LOCAL reader
        assert it["wiki"] == "en"  # edition parsed from the source domain
        assert "content match" in wiki["note"]
    finally:
        with session_scope() as s:
            s.execute(text(f"DELETE FROM articles WHERE id = {aid}"))  # noqa: S608
            s.execute(text(f"DELETE FROM sources WHERE id = {sid}"))  # noqa: S608


def test_omni_source_match_by_name_and_domain(client, omni_seed):
    d = client.get("/api/search/omni", params={"q": "omnibargazette"}).json()
    assert _group(d, "sources")["total"] == 1
    d2 = client.get("/api/search/omni", params={"q": "Omnibar Gaz"}).json()
    assert _group(d2, "sources")["total"] == 1


def test_omni_half_typed_boolean_is_not_an_error(client, omni_seed):
    r = client.get("/api/search/omni", params={"q": "quokkafloss AND"})
    assert r.status_code == 200
    arts = _group(r.json(), "articles")
    # Fallback path: either the phrase matched or it honestly reported
    # unsearchable -- never a 400 mid-keystroke.
    assert "note" in arts


@pytest.mark.parametrize("q", ["NOT foo", "...", "!!!"])
def test_omni_query_with_no_positive_content_is_empty_not_a_500(client, omni_seed, q):
    """A purely-negative or punctuation-only query must answer, not crash.

    ``search_ids`` returns ``None`` for "no positive content to search" -- DISTINCT
    from ``[]`` "searched, matched nothing" (``fts.build_match``). Two omnibar group
    helpers consumed that ``None`` unguarded: ``len(ids)`` in the articles group and
    ``ids[:cap]`` in the wiki group, both raising ``TypeError`` -> HTTP 500 on the
    flagship search bar for a Boolean the UI's own hint advertises. Found by the mypy
    paydown and live-reproduced 2026-08-20 before the fix.

    Asserted through the real endpoint because the claim is about what a user gets,
    not about a helper's return value.
    """
    r = client.get("/api/search/omni", params={"q": q})
    assert r.status_code == 200, f"{q!r} must not 500: {r.text[:300]}"
    d = r.json()
    arts = _group(d, "articles")
    assert arts["total"] == 0 and arts["items"] == []
    assert arts["note"], "an empty answer must SAY why it is empty"
    # The wiki group's own None path (a different crash: a slice, not len()).
    assert _group(d, "wiki")["total"] == 0


def test_omni_still_answers_a_real_query(client, omni_seed):
    """The negative-space twin of the test above.

    A guard that returned "no searchable terms" for EVERY query would satisfy the
    no-500 assertion while silently emptying the omnibar. This pins the other
    direction: real positive content still reaches its articles.
    """
    arts = _group(client.get("/api/search/omni", params={"q": "quokkafloss"}).json(), "articles")
    assert arts["total"] == 4 and len(arts["items"]) == 3


def test_omni_bounds_and_like_escape(client):
    assert client.get("/api/search/omni", params={"q": "a"}).status_code == 422
    assert client.get("/api/search/omni", params={"q": "x" * 201}).status_code == 422
    r = client.get("/api/search/omni", params={"q": "100% \\_certain_"})
    assert r.status_code == 200  # LIKE wildcards arrive escaped, never crash


def test_the_articles_total_is_a_count_even_when_the_candidate_cap_is_filled(
    client, omni_seed, monkeypatch
):
    """A capped list must never be reported as a TOTAL.

    ``search_ids`` takes a ``limit`` (default ``MAX_CANDIDATES`` = 20000), and this
    group used to publish ``len(ids)``. On any corpus where a common term matches
    more than that, the omnibar therefore displayed a flat 20000 as "total" -- a cap
    wearing a count's name, which the maintainer's 2026-07-18 ruling forbids outright
    ("a cap may bound which EXAMPLES are listed; it must never bound a displayed
    NUMBER") and whose sweep for further instances this is one result of.

    Reaching the branch by seeding 20001 articles would be absurd, so the CAP is
    compressed instead of the claim -- but it has to be compressed at BOTH ends to
    discriminate anything. Lowering only the module constant is not enough:
    ``search_ids``'s ``limit`` is a default argument bound at definition time, so the
    fetch still returned all four rows and ``len(ids)`` was still exact. A first draft
    did exactly that and PASSED against the reverted fix -- vacuous, because the
    fixture never reached the state the guard is about. The list must genuinely be
    TRUNCATED, so ``search_ids`` is stubbed to return the first two of the four real
    matches: then ``len(ids)`` is 2 and only a real count can answer 4.
    """
    from src.api import search_omni

    monkeypatch.setattr(search_omni, "MAX_CANDIDATES", 2)
    real_ids = search_omni.search_ids
    real_total = search_omni.search_total

    def _capped(db, q, **kw):  # what a filled candidate cap actually looks like
        return (real_ids(db, q, **kw) or [])[:2]

    calls: list[str] = []

    def _spy(db, q, **kw):
        calls.append(q)
        return real_total(db, q, **kw)

    monkeypatch.setattr(search_omni, "search_ids", _capped)
    monkeypatch.setattr(search_omni, "search_total", _spy)

    arts = _group(client.get("/api/search/omni", params={"q": "quokkafloss"}).json(), "articles")
    assert arts["total"] == 4, arts  # the exact count, NOT the cap of 2
    assert len(arts["items"]) == 2  # the truncated candidate list still bounds display
    assert calls, "the exact-count query must run once the cap is filled"


def test_under_the_cap_the_total_costs_no_extra_query(client, omni_seed, monkeypatch):
    """The negative-space twin: the common case must be unchanged, not merely correct.

    Under the cap ``len(ids)`` IS exact, so paying for a second count(*) would be a
    real regression on every ordinary keystroke -- measured at 96 ms on a 300k-doc
    fixture for a broad term. A fix that counted unconditionally would satisfy the
    test above and quietly slow the endpoint it was meant to help.
    """
    from src.api import search_omni

    calls: list[str] = []
    monkeypatch.setattr(
        search_omni, "search_total", lambda db, q, **kw: calls.append(q) or 0
    )

    arts = _group(client.get("/api/search/omni", params={"q": "quokkafloss"}).json(), "articles")
    assert arts["total"] == 4
    assert calls == [], "under the cap the count is already exact -- no extra query"


def test_the_corpus_fts_search_runs_once_per_keystroke_not_once_per_group(
    client, omni_seed, monkeypatch
):
    """Articles and wiki need the SAME ranked fetch; it used to be run twice.

    This module's own docstring named the cost ("runs 2x full FTS ``search_ids``").
    On a term matching most of the corpus that fetch is the omnibar's dominant cost
    (measured 415 ms on a 300k-doc fixture), so running it once halves the dominant
    term. Asserting the call COUNT is the only way to see it: both spellings return
    identical payloads.
    """
    from src.api import search_omni

    calls: list[str] = []
    real = search_omni.search_ids

    def _spy(db, q, **kw):
        calls.append(q)
        return real(db, q, **kw)

    monkeypatch.setattr(search_omni, "search_ids", _spy)

    r = client.get("/api/search/omni", params={"q": "quokkafloss"})
    assert r.status_code == 200
    assert len(calls) == 1, f"expected ONE shared corpus FTS search, got {calls}"


def test_a_query_with_no_positive_content_is_unsearchable_not_zero_matches(client):
    """``search_ids`` answers ``None`` -- not ``[]`` -- for a query with no searchable
    positive content, and the two mean different things: "this placed no constraint"
    versus "we searched and nothing matched". Reporting the first as ``total: 0``
    would be a fabricated zero, and the previous code did worse than that: it took
    ``len(None)``, which raised inside the per-group guard. Both FTS-backed groups did
    it, so a query like ``--`` came back carrying only keywords/sources/law -- the
    omnibar answering as though articles and Wikipedia had never been searched, with
    nothing in the payload saying so. Confirmed by driving the pre-fix shape (groups
    were ``['keywords', 'sources', 'law']``), not inferred from reading it.
    """
    r = client.get("/api/search/omni", params={"q": "--"})
    assert r.status_code == 200
    arts = _group(r.json(), "articles")  # present at all: the group is not dropped
    assert arts["total"] == 0
    assert arts["note"] == "query not searchable as typed"
    assert arts["items"] == []


def test_the_wiki_group_states_its_bound_as_a_field_not_only_as_prose(client, omni_seed):
    """The wiki content total is bounded by construction (a scan window over the
    ranked hits), so the bound travels as machine-readable fields -- a renderer must
    not have to sniff a substring out of the note to know the number is a floor."""
    wiki = _group(client.get("/api/search/omni", params={"q": "quokkafloss"}).json(), "wiki")
    if "bounded" in wiki:  # present only on the content-match branch
        assert isinstance(wiki["bounded"], bool)
        assert isinstance(wiki["scanned"], int)
