"""/api/briefing counts the corpus ONCE per request, not three times (D4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field diagnostics 2026-09-11. `/api/briefing` measured p95 60,113.8 ms, and it ran the
SAME `SELECT count(Article.id)` THREE times per request: once in `_is_cache_stale`, and
twice more inside `corpus_tier`, which called `_corpus_articles` and `_is_young` and each
counted independently. Over a 1.34M-row table that is three full index scans for one
number that cannot change mid-request.

NOT THE MECHANISM THE BRIEF PROPOSED, and the difference is worth keeping. It looked for
"a second pool acquisition or a retry", on the strength of three routes landing within
700 ms of exactly 60 s = 2x `pool_timeout`. There is no second acquisition anywhere:
none of those routes opens a second session on the request thread, and the ~60 s is
`OO_STATEMENT_TIMEOUT_S` -- a deliberate single statement deadline that merely happens to
sit at twice the pool timeout. `/api/insights/latest` and `/api/insights/trending-windows`
are working as designed and are untouched. This route had a real duplicate-work defect.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.database.models import Base


@pytest.fixture()
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()


def _article_counts(statements: list[str]) -> int:
    """How many times the corpus-size COUNT was actually issued."""
    n = 0
    for q in statements:
        low = " ".join(q.lower().split())
        if "count(articles.id)" in low and "from articles" in low and "join" not in low:
            n += 1
    return n


def _recording(session) -> list[str]:
    seen: list[str] = []

    @event.listens_for(session.get_bind(), "before_cursor_execute")
    def _rec(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        seen.append(statement)

    return seen


def test_corpus_tier_counts_the_corpus_once(session):
    """corpus_tier alone used to count TWICE -- once directly and once via _is_young."""
    from src.briefing.producers import corpus_tier

    seen = _recording(session)
    tier = corpus_tier(session)

    assert _article_counts(seen) == 1, (
        f"corpus_tier issued {_article_counts(seen)} corpus COUNTs, expected 1"
    )
    assert tier["tier"] in ("early", "developing", "established")
    assert tier["articles"] == 0


def test_corpus_tier_accepts_a_count_the_caller_already_paid_for(session):
    """The threading half: given the number, it must issue NO corpus count at all."""
    from src.briefing.producers import corpus_tier

    seen = _recording(session)
    tier = corpus_tier(session, article_count=1_341_182)

    assert _article_counts(seen) == 0, "a supplied count must not be re-counted"
    assert tier["articles"] == 1_341_182          # and it is actually USED, not ignored


def test_corpus_tier_default_is_unchanged_for_every_other_caller(session):
    """The optional parameter must not alter the verdict any existing caller gets."""
    from src.briefing.producers import _corpus_articles, corpus_tier

    a = corpus_tier(session)
    b = corpus_tier(session, article_count=_corpus_articles(session))
    assert a == b


def test_get_briefing_counts_the_corpus_at_most_once(session, monkeypatch):
    """The end-to-end assertion: one request, at most one corpus COUNT."""
    from src.briefing import service

    monkeypatch.setattr(service, "_read_cache", lambda: {
        "generated_at": "2026-09-11T00:00:00Z", "cards": [], "article_count": 0,
    })
    monkeypatch.setattr(service, "_refresh_status", lambda: {})

    seen = _recording(session)
    view = service.get_briefing(session)

    n = _article_counts(seen)
    assert n <= 1, f"/api/briefing issued {n} corpus COUNTs for one request, expected <= 1"
    assert "corpus_tier" in view


def test_is_cache_stale_still_counts_when_given_nothing(session):
    """The default path must keep working for callers that do not pass a count."""
    from src.briefing.service import _is_cache_stale

    seen = _recording(session)
    assert _is_cache_stale(session, {"article_count": 0}) is False
    assert _article_counts(seen) == 1
