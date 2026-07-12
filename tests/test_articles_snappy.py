"""
S2.5 — /api/articles snappiness: the endpoint no longer freezes the event loop and
no longer materializes the whole FTS match through the codec.

- The handlers are plain ``def`` (Starlette threadpool), so the synchronous DB +
  SQLCipher-codec work never runs on the single event loop (the documented
  unlock/restore/task-manager freeze family).
- The FTS path resolves surviving ids (fts ∩ filters) in the final order via an
  id-only query, then loads FULL rows for the PAGE only — content is decrypted for
  <= limit rows, not the whole (up to 20k) match.
- The unfiltered browse total is a data-aware cached COUNT(*) (P1.3).

``src.api.main`` needs the crypto extra, so the behavioral tests run in CI.
"""

from __future__ import annotations

import inspect

import pytest

# --------------------------------------------------------------------------- #
# Freeze fix: the handlers are synchronous (threadpool), not async (event loop)
# --------------------------------------------------------------------------- #


def test_article_handlers_are_synchronous_off_the_event_loop():
    """A def handler runs in the Starlette threadpool; an async def would run the
    blocking codec work ON the single event loop and freeze the whole server."""
    from src.api import main

    src = inspect.getsource(main)
    for name in ("search_articles", "export_articles", "view_article"):
        assert f"def {name}(" in src, f"{name} missing"
        assert f"async def {name}(" not in src, (
            f"{name} is async def — its blocking codec work would freeze the event loop"
        )


# --------------------------------------------------------------------------- #
# Over-fetch bound + data-aware browse count (behavioral, needs the crypto extra)
# --------------------------------------------------------------------------- #

try:
    from src.api.main import app  # noqa: E402
    from src.database.fts import ensure_fts  # noqa: E402
    from src.database.session import get_db  # noqa: E402

    _HAVE_MAIN = True
except BaseException:  # noqa: BLE001 - crypto extra absent in the bare sandbox
    _HAVE_MAIN = False

_needs_main = pytest.mark.skipif(not _HAVE_MAIN, reason="src.api.main needs the crypto extra (CI)")


@pytest.fixture()
def client(tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Article, Base, Source

    engine = create_engine(
        f"sqlite:///{tmp_path / 'snappy.db'}", future=True,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    ensure_fts(engine)
    TestSession = sessionmaker(bind=engine, future=True)
    with TestSession() as s:
        src = Source(name="S", domain="s.example")
        s.add(src)
        s.flush()
        sid = src.id
        # 12 articles all containing the term "widget" (so one query matches all 12).
        for i in range(12):
            s.add(Article(
                url=f"https://s.example/{i}", canonical_url=f"https://s.example/{i}",
                source_id=sid, title=f"T{i:02d}", content=f"a widget story number {i}",
                hash=f"{i:064d}", language="en",
            ))
        s.commit()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        c._TestSession = TestSession  # for the count-cache test to write directly
        yield c
    app.dependency_overrides.clear()


@_needs_main
def test_fts_paginates_and_totals_all_matches(client):
    """A query matching 12 articles with limit=5: total counts ALL 12 (not just the
    page), and exactly 5 are returned — the over-fetch bound loads only the page."""
    r = client.get("/api/articles", params={"query": "widget", "limit": 5})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 12
    assert len(data["results"]) == 5
    # The next page continues without overlap (pagination is by the ordered id list).
    r2 = client.get("/api/articles", params={"query": "widget", "limit": 5, "offset": 5})
    ids1 = {row["id"] for row in data["results"]}
    ids2 = {row["id"] for row in r2.json()["results"]}
    assert not (ids1 & ids2)
    assert len(ids2) == 5


@_needs_main
def test_fts_metadata_sort_still_correct_through_the_over_fetch_bound(client):
    """A title sort over the FTS match orders by title (asc), paginated — the id-only
    sort-column query mirrors the old full-row Python sort."""
    r = client.get("/api/articles",
                    params={"query": "widget", "sort_by": "title", "sort_dir": "asc", "limit": 3})
    titles = [row["title"] for row in r.json()["results"]]
    assert titles == ["T00", "T01", "T02"]


@_needs_main
def test_browse_total_is_data_aware_cached_and_never_stale(client):
    """The unfiltered browse total is served from a data-version cache — correct, and
    a subsequent write bumps PRAGMA data_version so it is never stale."""
    from src.database.models import Article, Source

    r = client.get("/api/articles")  # no query -> browse path -> cached COUNT(*)
    assert r.json()["total"] == 12
    # Write a new article on a fresh connection; the data_version probe must see it.
    with client._TestSession() as s:
        sid = s.query(Source).first().id
        s.add(Article(url="https://s.example/x", canonical_url="https://s.example/x",
                      source_id=sid, title="T99", content="another widget",
                      hash="x".ljust(64, "0"), language="en"))
        s.commit()
    r2 = client.get("/api/articles")
    assert r2.json()["total"] == 13, "the cached count went stale through a write"


@_needs_main
def test_browse_total_cache_actually_stores_a_hit(client):
    """Skeptic finding (2026-07-12): _cached persists DICT payloads only, so passing it a
    scalar int made the cache a silent no-op (recompute every page). Assert the count dict
    is really stored under the data-version key — a HIT, not just a fresh live recompute."""
    from src.api import insights, main

    # A browse call over the fixture's own session/bind.
    with client._TestSession() as db:
        n1 = main._browse_total_cached(db)
        assert n1 == 12
        bind = db.get_bind()
        dv = insights._data_version(bind)
        assert dv is not None
        # The dict-wrapped value must be persisted (before the fix this was None).
        stored = insights._read_cache.get(f"articles-total|{id(bind)}|{dv}")
        assert stored is not None and stored.get("count") == 12
        # A second call with no intervening write returns the same value from the store.
        assert main._browse_total_cached(db) == 12
