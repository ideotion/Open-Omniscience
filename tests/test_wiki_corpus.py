"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

The living-source bridge (maintainer-ruled 2026-06-12): a watched Wikipedia
page IS an article — newest version in the corpus, full-text-searchable,
keyword-aggregated, When×Where×Who-anchored — re-indexed idempotently when
edits land, provenanced under one per-edition catalog source.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


WIKITEXT = (
    "{{Infobox drought|year=2026}}The '''Quagmire drought''' affected "
    "[[Nairobi]] in [[2026 in Kenya|2026]].<ref>some source</ref>\n"
    "== Impact ==\nCrops failed across the region."
)


def _cleanup(ids):
    from src.database.session import session_scope

    with session_scope() as s:
        if ids.get("article"):
            for tbl in ("keyword_mentions", "article_mentioned_places",
                        "article_mentioned_dates", "article_entities"):
                s.execute(text(f"DELETE FROM {tbl} WHERE article_id = {ids['article']}"))  # noqa: S608
            s.execute(text(f"DELETE FROM articles WHERE id = {ids['article']}"))  # noqa: S608
        if ids.get("page"):
            s.execute(text(f"DELETE FROM wiki_revisions WHERE page_id = {ids['page']}"))  # noqa: S608
            s.execute(text(f"DELETE FROM wiki_pages WHERE id = {ids['page']}"))  # noqa: S608
        if ids.get("source"):
            s.execute(text(f"DELETE FROM sources WHERE id = {ids['source']}"))  # noqa: S608


def test_plain_from_wikitext_strips_markup_keeps_meaning():
    from src.wiki.corpus import plain_from_wikitext

    plain = plain_from_wikitext(WIKITEXT)
    assert "Infobox" not in plain and "{{" not in plain
    assert "<ref>" not in plain and "some source" not in plain
    assert "Quagmire drought" in plain
    assert "Nairobi" in plain
    assert "2026" in plain and "2026 in Kenya" not in plain  # label kept, target dropped
    assert "Impact" in plain and "==" not in plain


def test_sync_makes_the_page_a_first_class_article(client):
    from src.database.fts import search_ids
    from src.database.models import Article, KeywordMention, WikiPage
    from src.database.session import session_scope
    from src.wiki.corpus import sync_page_to_corpus

    ids = {}
    try:
        with session_scope() as s:
            page = WikiPage(wiki="en", title="Quagmire drought",
                            baseline_revid=100, baseline_text=WIKITEXT,
                            last_revid=100, watched=True)
            s.add(page)
            s.flush()
            ids["page"] = page.id
            res = sync_page_to_corpus(s, page)
            assert res["status"] == "created"
            ids["article"] = res["article_id"]
            assert res["mentions"] > 0  # keywords anchored

            art = s.get(Article, res["article_id"])
            ids["source"] = art.source_id
            assert art.canonical_url == "https://en.wikipedia.org/wiki/Quagmire_drought"
            assert art.language == "en"
            assert art.source.domain == "en.wikipedia.org"
            assert "{{" not in (art.content or "")

            # keyword aggregation is live for the wiki article
            n_mentions = s.query(KeywordMention).filter_by(article_id=art.id).count()
            assert n_mentions == res["mentions"] > 0

            # and the page is in GENERAL full-text search like any article
            assert art.id in search_ids(s, "quagmire")

        # ...including the omnibar's articles group (not just the wiki group)
        d = client.get("/api/search/omni", params={"q": "quagmire"}).json()
        arts = next(g for g in d["groups"] if g["kind"] == "articles")
        assert any(i["article_id"] == ids["article"] for i in arts["items"])
    finally:
        _cleanup(ids)


def test_resync_follows_the_latest_version(client):
    from src.database.fts import search_ids
    from src.database.models import Article, WikiPage
    from src.database.session import session_scope
    from src.wiki.corpus import sync_page_to_corpus

    ids = {}
    try:
        with session_scope() as s:
            page = WikiPage(wiki="en", title="Quagmire reservoir",
                            baseline_revid=100, baseline_text=WIKITEXT,
                            last_revid=100, watched=True)
            s.add(page)
            s.flush()
            ids["page"] = page.id
            r1 = sync_page_to_corpus(s, page)
            ids["article"] = r1["article_id"]
            ids["source"] = s.get(Article, r1["article_id"]).source_id
            assert r1["revid"] == 100  # baseline anchored honestly

            # no edit -> idempotent, no churn
            assert sync_page_to_corpus(s, page)["status"] == "unchanged"

            # an edit lands: the tracker stores the NEW latest text + revid
            page.latest_text = WIKITEXT + " The xylophone relief plan began."
            page.latest_text_revid = 101
            page.last_revid = 101
            r3 = sync_page_to_corpus(s, page)
            assert r3["status"] == "updated" and r3["revid"] == 101
            art = s.get(Article, r1["article_id"])
            assert "xylophone" in art.content
            assert art.id in search_ids(s, "xylophone")  # search follows the edit
    finally:
        _cleanup(ids)


def test_missing_and_textless_pages_are_skipped_honestly():
    from src.database.models import WikiPage
    from src.database.session import session_scope
    from src.wiki.corpus import sync_page_to_corpus

    with session_scope() as s:
        gone = WikiPage(wiki="en", title="Qq gone", missing=True, watched=True)
        bare = WikiPage(wiki="en", title="Qq bare", watched=True)
        s.add_all([gone, bare])
        s.flush()
        try:
            assert sync_page_to_corpus(s, gone)["status"] == "skipped-missing"
            assert sync_page_to_corpus(s, bare)["status"] == "skipped-no-text"
        finally:
            s.execute(text(f"DELETE FROM wiki_pages WHERE id IN ({gone.id}, {bare.id})"))  # noqa: S608


def test_backfill_endpoint_runs(client):
    d = client.post("/api/wiki/corpus/sync").json()
    assert {"pages", "created", "updated", "unchanged", "skipped"} <= set(d.keys())


def test_tracker_stores_per_revision_full_text():
    """The storage ruling (maintainer-agreed 2026-06-12): every tracked
    revision keeps its FULL TEXT, batched in one call; latest_text comes from
    the newest revision of the batch — exact versions, no diff replay."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base, WikiRevision
    from src.wiki.track import ensure_page, update_page

    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()

    class TextClient:
        def __init__(self):
            self.batched_revids = None

        def fetch_current_text(self, wiki, title):
            return {"revid": 100, "text": "v100 text", "size": 9, "pageid": 1}

        def fetch_revisions(self, wiki, title, *, limit=20, older_than=None):
            return [
                {"revid": 102, "parent_revid": 101, "size": 12},
                {"revid": 101, "parent_revid": 100, "size": 10},
            ]

        def fetch_compare(self, wiki, a, b):
            return {"added": "x", "removed": "", "added_bytes": 1, "removed_bytes": 0}

        def fetch_revision_texts(self, wiki, revids):
            self.batched_revids = list(revids)
            return {101: "v101 text", 102: "v102 newest text"}

    client = TextClient()
    page = ensure_page(db, "en", "Versioned")
    update_page(db, client, page)  # baseline at 100
    res = update_page(db, client, page)  # two new revisions
    assert res["new"] == 2
    assert client.batched_revids == [101, 102]  # ONE batched call, ordered

    texts = {r.revid: r.full_text for r in db.query(WikiRevision).all()}
    assert texts == {101: "v101 text", 102: "v102 newest text"}
    assert page.latest_text == "v102 newest text"
    assert page.latest_text_revid == 102


def test_revision_text_fetch_failure_keeps_revisions():
    """A text-fetch failure stores the revisions WITHOUT text (NULL says so)
    and falls back to fetch_current_text for the latest — never drops edits."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base, WikiRevision
    from src.wiki.track import ensure_page, update_page

    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()

    class FailingTextClient:
        def __init__(self):
            self.calls = 0

        def fetch_current_text(self, wiki, title):
            self.calls += 1
            rev = 100 if self.calls == 1 else 101
            return {"revid": rev, "text": f"v{rev} current", "size": 9, "pageid": 1}

        def fetch_revisions(self, wiki, title, *, limit=20, older_than=None):
            return [{"revid": 101, "parent_revid": 100, "size": 10}]

        def fetch_compare(self, wiki, a, b):
            return {"added": "", "removed": "", "added_bytes": 0, "removed_bytes": 0}

        def fetch_revision_texts(self, wiki, revids):
            raise RuntimeError("upstream hiccup")

    page = ensure_page(db, "en", "Flaky")
    client = FailingTextClient()
    update_page(db, client, page)  # baseline
    res = update_page(db, client, page)
    assert res["new"] == 1
    row = db.query(WikiRevision).one()
    assert row.full_text is None  # honest partial, not a fabricated text
    assert page.latest_text == "v101 current"  # the fallback still refreshed
    assert page.latest_text_revid == 101
