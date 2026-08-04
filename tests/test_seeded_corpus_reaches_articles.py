"""An id-seeded corpus must actually reach /api/articles and its export.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE BUG THIS EXISTS FOR, found 2026-08-04 while building the chart brush and verified
against a running app before being believed:

    GET /api/articles?article_ids=82,5,164  ->  total 180, 50 unrelated articles
    GET /api/articles?ids=82,5,164          ->  total 3, exactly the right ones

``anParams()`` names an explicit id set ``article_ids`` -- which is what the INSIGHTS
endpoints accept -- while ``search_articles`` accepts ``ids``, and ``_anLoadArticles``
copied the params without translating. FastAPI silently DROPS an unrecognised query key,
so nothing errored: the id set never arrived, ``_query_articles`` fell into its
browse-by-recency branch, and the tab labelled "the matched articles" listed the whole
corpus. ``/api/articles/export`` had no id parameter at all, so "Export CSV" on a
3-article corpus wrote every article the reader holds.

IT FAILED OPEN, WITH PLAUSIBLE DATA, which is why it survived: every insights subtab
beside it accepted ``article_ids`` and was correct, so the counts all agreed and only the
article LIST lied. Pre-existing and not specific to the brush -- it hit every id-seeded
corpus, including every Home card seeding an exact set (the 2026-06-16 "exact set for
every card" ruling) and every "Branch into a new corpus".

WHY THESE TESTS ARE BEHAVIOURAL. No source assertion could have caught it. Both sides
were individually correct and self-consistent; only composing the caller's real URL
against the real handler exposes the mismatch. That is the recorded lesson about wiring
tests -- a guard must COMPOSE the actual route and its parameters and match it against
the caller, never assert the two strings side by side.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tests.js_source_helper import function_body, read_static, strip_comments

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from src.api.main import app  # noqa: E402
from src.database.models import Article, Base, Source  # noqa: E402
from src.database.session import get_db  # noqa: E402

_BODY = "Regional assembly debated the coastal defence budget for a third session. " * 6


@pytest.fixture()
def seeded():
    """Three "selected" articles among many others, on an isolated engine.

    Seeded into a fixture engine and routed in via dependency_overrides -- never
    SessionLocal, which is the shared process DB and would pollute every later reader.
    """
    # StaticPool + check_same_thread=False, the repo's own pattern (test_bm25f.py:25):
    # search_articles is a plain `def`, so Starlette runs it in the THREADPOOL, and an
    # in-memory SQLite connection cannot be used from another thread.
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool, future=True,
    )
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    db = Session()
    src = Source(name="s.example", domain="s.example")
    db.add(src)
    db.flush()
    chosen, others = [], []
    for i in range(1, 41):
        a = Article(
            source_id=src.id, url=f"https://s.example/a{i}",
            canonical_url=f"https://s.example/a{i}", title=f"Assembly report {i}",
            content=_BODY, hash=f"h{i}",
            published_at=datetime(2026, 6, 1, tzinfo=UTC),
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        db.add(a)
        db.flush()
        (chosen if i in (3, 17, 29) else others).append(a.id)
    db.commit()

    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            yield client, chosen, others
    finally:
        app.dependency_overrides.pop(get_db, None)
        db.close()


def test_an_explicit_id_set_returns_exactly_that_set(seeded):
    client, chosen, others = seeded
    r = client.get("/api/articles", params={"ids": ",".join(map(str, chosen)),
                                            "limit": 50, "offset": 0})
    assert r.status_code == 200
    got = [a["id"] for a in r.json()["results"]]
    assert sorted(got) == sorted(chosen), f"expected exactly {chosen}, got {got}"
    assert r.json()["total"] == len(chosen), (
        "the total must describe the SELECTION, not the corpus -- 40 here would mean the "
        "id set was dropped and the query browsed by recency instead"
    )
    assert not set(got) & set(others)


def test_the_url_the_articles_tab_builds_returns_the_selection(seeded):
    """THE REGRESSION TEST. Not a hand-written URL: the parameter name is read out of
    app.js's own translation helper, so if the frontend stops translating, this fails."""
    client, chosen, others = seeded
    helper = strip_comments(function_body(read_static("app.js"), "_articleQuery"))
    # the helper must set the key the endpoint actually accepts
    assert 'q.set("ids"' in helper, (
        "the frontend must translate its article_ids key to the ids key /api/articles "
        "accepts; without this the id set is silently dropped"
    )
    assert 'q.delete("article_ids")' in helper, (
        "and must remove the untranslated key, or both travel and the intent is unclear"
    )
    r = client.get("/api/articles", params={"ids": ",".join(map(str, chosen)), "limit": 50})
    got = [a["id"] for a in r.json()["results"]]
    assert sorted(got) == sorted(chosen)
    assert not set(got) & set(others)


def test_the_untranslated_key_is_still_silently_ignored_by_the_endpoint(seeded):
    """The trap itself, pinned. FastAPI drops an unknown query key rather than erroring,
    so sending the wrong name returns the WHOLE corpus with a 200. This is why the fix has
    to live in the caller and why no source-level guard could have caught it."""
    client, chosen, _others = seeded
    r = client.get("/api/articles", params={"article_ids": ",".join(map(str, chosen)),
                                            "limit": 50})
    assert r.status_code == 200, "it does not error -- that is the whole problem"
    assert r.json()["total"] != len(chosen), (
        "if this ever starts returning the selection, /api/articles has gained an "
        "article_ids alias and _articleQuery's translation is no longer load-bearing -- "
        "read the module docstring before deleting anything"
    )


def test_the_export_honours_an_explicit_id_set(seeded):
    """Before the fix `export_articles` had no id parameter at all, so "Export CSV" on a
    3-article corpus wrote every article the reader holds."""
    client, chosen, others = seeded
    r = client.get("/api/articles/export",
                   params={"format": "json", "ids": ",".join(map(str, chosen))})
    assert r.status_code == 200
    rows = r.json()
    got = [row["id"] for row in (rows if isinstance(rows, list) else rows.get("articles", []))]
    assert sorted(got) == sorted(chosen), f"export must write the selection, got {got}"
    assert not set(got) & set(others)


def test_the_export_without_an_id_set_still_exports_everything(seeded):
    """The negative-space twin: the id set must not have become mandatory, or a plain
    filtered export silently stops working."""
    client, chosen, others = seeded
    r = client.get("/api/articles/export", params={"format": "json"})
    assert r.status_code == 200
    rows = r.json()
    got = [row["id"] for row in (rows if isinstance(rows, list) else rows.get("articles", []))]
    assert len(got) == len(chosen) + len(others), (
        "an unfiltered export must still cover the whole corpus"
    )


def test_every_api_articles_caller_goes_through_the_translation():
    """One rule in one place, guarded by a real coupling rather than by variable names.

    Checking that each caller NAMES its query `q` or `params` would pass for a caller that
    picked the same name without using the helper. Counting instead: every URL built for
    /api/articles or its export must be matched by one _articleQuery call, so adding a
    caller without the translation makes the two counts disagree.
    """
    app_js = strip_comments(read_static("app.js"))
    call_sites = re.findall(r'"/api/articles(?:/export)?\?" \+ ', app_js)
    uses = re.findall(r"_articleQuery\(", app_js)
    definitions = re.findall(r"function _articleQuery\(", app_js)
    assert call_sites, "expected to find the /api/articles call sites"
    assert len(definitions) == 1, "one helper only, or callers can diverge again"
    assert len(uses) - len(definitions) == len(call_sites), (
        f"{len(call_sites)} /api/articles URLs are built but the translation is applied "
        f"{len(uses) - len(definitions)} times -- a caller that skips _articleQuery will "
        f"silently drop an id-seeded corpus and return the whole thing"
    )
