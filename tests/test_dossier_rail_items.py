"""Row 200 (S08-01 S2): the dossier's corpus rails list their rows, each with how it joined.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The brief: «each rail shows its own store's rows … evidence trails per item». The news, Wikipedia
and law rails carried a count only. Mostly refusals: a rail lists ONLY its own channel's articles; the
list is bounded and the count stays the whole count; an article that joined two ways says so and is
not counted twice; an undated article sorts last rather than being given a date; a name two items
share still joins nothing; no key of a row is a score. The fixtures are test_dossier_seed's own.
"""

from __future__ import annotations

from datetime import datetime

from src.database.models import ArticleEntity, ArticleMentionedPlace
from src.entities import dossier as DO
from tests.test_dossier_seed import ZED, _article, _rail, _source, db, lanes, rings, seeded  # noqa: F401

FORBIDDEN_KEY_PARTS = ("score", "rating", "ranking", "grade", "weight", "rank")


def test_each_corpus_rail_lists_its_own_articles_with_how_they_joined(db, seeded, lanes):  # noqa: F811
    d = DO.qid_dossier(db, ZED, "en")
    news, wiki, law = _rail(d, "news"), _rail(d, "wikipedia"), _rail(d, "law")
    assert [a["id"] for a in news["items"]] == [seeded["a1"]]
    assert [a["id"] for a in wiki["items"]] == [seeded["a2"]]
    assert [a["id"] for a in law["items"]] == [seeded["a3"]]
    assert news["items"][0] == {"id": seeded["a1"], "title": "Zedport harbour reop", "domain": "zz.example",
                                "published_at": "2026-03-01", "joined_by": ["entities"]}
    assert wiki["items"][0]["joined_by"] == ["keywords"]
    # an undated article keeps no date, never a made-up one
    assert law["items"][0]["published_at"] is None and law["items"][0]["joined_by"] == ["places"]
    # the Mercury article (a shared name) and the English-tagged keyword join nothing, so are listed nowhere
    listed = {a["id"] for r in (news, wiki, law) for a in r["items"]}
    assert seeded["a4"] not in listed and seeded["a5"] not in listed
    # no row of the dossier carries a weight of any kind
    for r in (news, wiki, law):
        for a in r["items"]:
            for key in a:
                assert not any(p in key.split("_") for p in FORBIDDEN_KEY_PARTS), key


def test_an_article_that_joined_two_ways_names_both_and_counts_once(db, seeded, lanes):  # noqa: F811
    db.add(ArticleMentionedPlace(article_id=seeded["a1"], name="Zedport", country="zz", kind="city", mentions=1))
    db.commit()
    news = _rail(DO.qid_dossier(db, ZED, "en"), "news")
    assert news["articles"] == 1 and len(news["items"]) == 1
    assert news["items"][0]["joined_by"] == ["entities", "places"]


def test_the_list_is_bounded_newest_first_undated_last_and_the_count_stays_whole(db, seeded, lanes):  # noqa: F811
    press = _source(db, "more.example", country="fr")
    n_more = DO._LIST_LIMIT + 5
    for i in range(n_more):
        when = None if i == 0 else datetime(2025, 1, 1 + (i % 28), i % 24)
        a = _article(db, press, f"Zedport item number {i:03d}.", when=when)
        db.add(ArticleEntity(article_id=a.id, name="Zedport", entity_class="organization", mentions=1))
    db.commit()
    news = _rail(DO.qid_dossier(db, ZED, "en"), "news")
    assert news["articles"] == 1 + n_more, "the count is every joined article, never the list's length"
    assert len(news["items"]) == DO._LIST_LIMIT
    dates = [a["published_at"] for a in news["items"]]
    assert dates[0] == "2026-03-01" and None not in dates, "newest first; the one undated article is past the cut"
    assert dates == sorted(dates, reverse=True)


def test_an_empty_dossier_lists_nothing_rather_than_failing(db, rings, lanes):  # noqa: F811
    d = DO.qid_dossier(db, "Q999999555", "en")
    assert all(_rail(d, k)["items"] == [] for k in ("news", "wikipedia", "law"))
