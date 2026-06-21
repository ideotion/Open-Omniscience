"""Advanced-search sort by metadata (brief §2.D — "important", thinner corpus creation).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Orders articles by a chosen METADATA field (date|source|title|language) in both the
browse (no-query) and FTS (text-query) paths — an honest metadata ordering, never a
relevance/quality score. ``src.api.main`` needs the crypto extra, so these run in CI.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    from src.api.main import _query_articles  # noqa: E402

    _HAVE_MAIN = True
except BaseException:  # noqa: BLE001  # pragma: no cover - crypto extra/native ext absent in the bare sandbox
    _HAVE_MAIN = False

from src.database.models import Article, Base, Source  # noqa: E402

pytestmark = pytest.mark.skipif(not _HAVE_MAIN, reason="src.api.main needs the crypto extra (runs in CI)")


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    srcs = {
        "Zeta": Source(name="Zeta", domain="z.test"),
        "Alpha": Source(name="Alpha", domain="a.test"),
        "Mid": Source(name="Mid", domain="m.test"),
    }
    s.add_all(srcs.values())
    s.commit()
    rows = [
        ("Banana", "fr", "Zeta", "2024-01-01"),
        ("apple", "en", "Alpha", "2024-03-01"),
        ("Cherry", "de", "Mid", "2024-02-01"),
    ]
    for i, (title, lang, src, when) in enumerate(rows):
        s.add(
            Article(
                url=f"https://x.test/{i}",
                canonical_url=f"https://x.test/{i}",
                source_id=srcs[src].id,
                title=title,
                content="shared news content for the corpus",
                hash=f"h{i}".ljust(64, "0"),
                language=lang,
                published_at=datetime.fromisoformat(when).replace(tzinfo=UTC),
            )
        )
    s.commit()
    return s


def _titles(db, **kw):
    rows, _ = _query_articles(
        db, query=kw.pop("query", None), source=None, start_date=None, end_date=None,
        language=None, tags=None, limit=100, offset=0, **kw,
    )
    return [a.title for a in rows]


def test_browse_sort_by_title(db):
    assert _titles(db, sort_by="title", sort_dir="asc") == ["apple", "Banana", "Cherry"]
    assert _titles(db, sort_by="title", sort_dir="desc") == ["Cherry", "Banana", "apple"]


def test_browse_sort_by_date(db):
    assert _titles(db, sort_by="date", sort_dir="asc") == ["Banana", "Cherry", "apple"]
    # default direction is desc
    assert _titles(db, sort_by="date") == ["apple", "Cherry", "Banana"]


def test_browse_sort_by_source_and_language(db):
    assert _titles(db, sort_by="source", sort_dir="asc") == ["apple", "Cherry", "Banana"]  # Alpha,Mid,Zeta
    assert _titles(db, sort_by="language", sort_dir="asc") == ["Cherry", "apple", "Banana"]  # de,en,fr


def test_default_browse_is_recency(db):
    # No sort_by -> newest first (the prior behaviour, unchanged).
    assert _titles(db) == ["apple", "Cherry", "Banana"]


def test_fts_path_sort_overrides_relevance(db):
    from src.database.fts import ensure_fts

    ensure_fts(db.get_bind())
    db.execute(__import__("sqlalchemy").text("INSERT INTO article_fts(article_fts) VALUES ('rebuild')"))
    db.commit()
    # A text query normally orders by relevance; sort_by reorders by metadata.
    assert _titles(db, query="news", sort_by="title", sort_dir="asc") == ["apple", "Banana", "Cherry"]
