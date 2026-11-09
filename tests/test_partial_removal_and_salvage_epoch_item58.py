"""Queue item 58: a newsletter removal that fails partway, and the salvage's epoch bump.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

(a) ``delete_imported_newsletters`` removes in chunks, each committed with a strict corpus-epoch bump. A chunk that failed (a delete
or its bump) escaped as whatever the failure was, and ``POST /api/newsletters/remove-imported`` answered a bare 500 while the earlier
chunks were already gone and the counters still counted them. Now the failed chunk is rolled back, the counters are refreshed for the
chunks removed, and the route answers 500 in the removal's own fixed words: how many of the articles it found are removed, how many
are left, and whether the counts were refreshed. The counters failing after a complete removal is said in a 200, not raised.

(b) ``repair._after_the_swap`` bumped the epoch non-strictly: a failure was swallowed inside the bump, which handed back the epoch the
damaged file already had, and the repair report showed it as if bumped. The bump is strict now, so a failure reads None and the log
names what lags. The per-day keyword counts are already marked unbuilt in the copy (pinned in tests/test_day_counts.py).

Everything runs through the real removal, the real write gate and the real route over a file-backed store; only the failures are
planted.
"""

from __future__ import annotations

import inspect
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy
from sqlalchemy import create_engine, event, func, text
from sqlalchemy.orm import sessionmaker

from src.database import writer
from src.database.models import Article, Base, Keyword, KeywordMention, Source
from src.ingest import email as email_mod
from src.ingest.email import (
    NEWSLETTER_COUNTS_NOT_REFRESHED,
    NEWSLETTER_SOURCE_DOMAINS,
    NewsletterRemovalStopped,
    delete_imported_newsletters,
    newsletter_removal_stopped_text,
)

#: What a planted failure says: it must never reach the route's answer.
_NEEDLE = "item58-needle-5513"

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def db(tmp_path):
    """A file-backed session with the real gate handlers, autoflush off like the app's."""
    engine = create_engine(f"sqlite:///{tmp_path / 'item58.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, future=True)
    event.listen(maker, "before_flush", writer._on_before_flush)
    event.listen(maker, "do_orm_execute", writer._on_orm_execute)
    event.listen(maker, "after_transaction_end", writer._on_after_transaction_end)
    s = maker()
    s.add(Source(name="Web", domain="news.test"))
    s.commit()
    s._item58_engine = engine  # type: ignore[attr-defined]
    yield s
    s.close()
    engine.dispose()


def _persisted(db, sql: str):
    """What a commit made durable, read on a FRESH connection."""
    with db._item58_engine.connect() as c:  # type: ignore[attr-defined]
        return c.execute(text(sql)).fetchall()


def _article(db, h, source_id):
    a = Article(
        url=f"https://x.test/{h}",
        canonical_url=f"https://x.test/{h}",
        source_id=source_id,
        title=f"T-{h}",
        content=f"body {h}",
        hash=h,
        language="en",
        published_at=datetime(2024, 3, 1, tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(a)
    db.commit()
    return a


def _seed(db, n: int):
    """``n`` imported newsletters and one web article, each with one mention of one keyword; counters exact."""
    nl = Source(name="NL", domain=NEWSLETTER_SOURCE_DOMAINS[0], enabled=False)
    db.add(nl)
    db.commit()
    kw = Keyword(term="k", normalized_term="k")
    db.add(kw)
    db.commit()
    ids = []
    for i in range(n):
        a = _article(db, f"n{i}", nl.id)
        db.add(KeywordMention(keyword_id=kw.id, article_id=a.id, count=1))
        ids.append(a.id)
    keep = _article(db, "keep", 1)
    db.add(KeywordMention(keyword_id=kw.id, article_id=keep.id, count=1))
    kw.mention_count = n + 1
    kw.article_count = n + 1
    db.commit()
    return ids, keep.id


def _epoch(db) -> int:
    rows = _persisted(db, "SELECT value FROM derived_meta WHERE key = 'corpus_epoch'")
    return int(rows[0][0]) if rows else 0


def _fail_the_articles_delete(db, monkeypatch, nth: int):
    """The ``nth`` chunk's article DELETE raises, with the needle in its words."""
    real_execute = db.execute
    seen = {"n": 0}

    def _execute(stmt, *a, **k):
        if isinstance(stmt, sqlalchemy.sql.dml.Delete) and stmt.table.name == "articles":
            seen["n"] += 1
            if seen["n"] == nth:
                raise RuntimeError(f"planted delete failure {_NEEDLE}")
        return real_execute(stmt, *a, **k)

    monkeypatch.setattr(db, "execute", _execute)
    return real_execute


def _live_counts(db):
    db.expire_all()
    kw = db.query(Keyword).one()
    live_m = db.query(func.coalesce(func.sum(KeywordMention.count), 0)).filter_by(keyword_id=kw.id).scalar()
    live_a = db.query(func.count(func.distinct(KeywordMention.article_id))).filter_by(keyword_id=kw.id).scalar()
    return (kw.mention_count, kw.article_count), (live_m, live_a)


# --------------------------------------------------------------------------------------------------
# (a) the removal's own words
# --------------------------------------------------------------------------------------------------


def test_a_chunk_that_fails_stops_the_removal_with_the_counts_and_none_of_the_failures_words(db, monkeypatch):
    ids, keep_id = _seed(db, 5)
    monkeypatch.setattr(email_mod, "_NEWSLETTER_DELETE_CHUNK", 2)  # chunks of 2, 2, 1
    real_execute = _fail_the_articles_delete(db, monkeypatch, 3)

    with pytest.raises(NewsletterRemovalStopped) as info:
        delete_imported_newsletters(db)
    monkeypatch.setattr(db, "execute", real_execute)
    stop = info.value
    assert (stop.removed, stop.total, stop.counts_refreshed) == (4, 5, True)
    assert str(stop) == (
        "The removal stopped after removing 4 of the 5 imported newsletter articles; the other 1 is still in your corpus. "
        "Run the removal again to remove it."
    )
    assert _NEEDLE not in str(stop)
    assert stop.__cause__ is None and stop.__context__ is None, "the failure (a driver's error, perhaps) rides the words"
    assert isinstance(stop, RuntimeError), "a caller that caught the failure as a RuntimeError still does"

    # The two chunks before the failure are committed; the third was rolled back whole, dependents included.
    assert {r[0] for r in _persisted(db, "SELECT id FROM articles")} == {ids[4], keep_id}
    assert {r[0] for r in _persisted(db, "SELECT article_id FROM keyword_mentions")} == {ids[4], keep_id}
    # The counters were refreshed for the chunks that were removed.
    stored, live = _live_counts(db)
    assert stored == live == (2, 2)

    # Running it again removes exactly what is left.
    out = delete_imported_newsletters(db)
    assert out["removed_articles"] == 1 and out["counts_refreshed"] is True and "note" not in out
    assert {r[0] for r in _persisted(db, "SELECT id FROM articles")} == {keep_id}


def test_a_failed_epoch_bump_on_a_later_chunk_rolls_that_chunk_back_and_says_how_many_are_removed(db, monkeypatch):
    """The case the queue names: the strict bump of the second chunk fails, so its deletes roll back with it."""
    ids, keep_id = _seed(db, 4)
    monkeypatch.setattr(email_mod, "_NEWSLETTER_DELETE_CHUNK", 2)
    from src.analytics import corpus_epoch

    real_bump = corpus_epoch.bump_corpus_epoch
    calls = {"n": 0}

    def _bump(session, *, reason="", strict=False):
        calls["n"] += 1
        if calls["n"] == 2:
            assert strict, "the removal's bump is strict"
            real_commit = session.commit

            def _commit():
                session.commit = real_commit  # once
                raise sqlalchemy.exc.OperationalError("COMMIT", {}, Exception(f"disk I/O error {_NEEDLE}"))

            session.commit = _commit
        return real_bump(session, reason=reason, strict=strict)

    monkeypatch.setattr(corpus_epoch, "bump_corpus_epoch", _bump)
    e0 = _epoch(db)
    with pytest.raises(NewsletterRemovalStopped) as info:
        delete_imported_newsletters(db)
    assert (info.value.removed, info.value.total) == (2, 4)
    assert "2 of the 4" in str(info.value) and "the other 2 are still in your corpus" in str(info.value)
    assert _NEEDLE not in str(info.value)
    assert _epoch(db) == e0 + 1, "the first chunk's bump landed and the second's did not"
    assert {r[0] for r in _persisted(db, "SELECT id FROM articles")} == {ids[2], ids[3], keep_id}
    stored, live = _live_counts(db)
    assert stored == live == (3, 3)


def test_a_failure_in_the_first_chunk_says_nothing_was_removed(db, monkeypatch):
    ids, keep_id = _seed(db, 3)
    monkeypatch.setattr(email_mod, "_NEWSLETTER_DELETE_CHUNK", 2)
    _fail_the_articles_delete(db, monkeypatch, 1)
    refreshes = []
    monkeypatch.setattr(email_mod, "_refresh_counts_after_removal", lambda s: refreshes.append(1) or True)
    e0 = _epoch(db)

    with pytest.raises(NewsletterRemovalStopped) as info:
        delete_imported_newsletters(db)
    assert (info.value.removed, info.value.total) == (0, 3)
    assert str(info.value) == (
        "The removal stopped before it removed any of the 3 imported newsletter articles; all of them are still in your corpus. "
        "Run the removal again."
    )
    assert refreshes == [], "nothing was removed, so no counter is stale"
    assert _epoch(db) == e0
    assert len(_persisted(db, "SELECT id FROM articles")) == 4


def test_counts_that_could_not_be_refreshed_after_a_partial_removal_are_said(db, monkeypatch, caplog):
    _seed(db, 5)
    monkeypatch.setattr(email_mod, "_NEWSLETTER_DELETE_CHUNK", 2)
    _fail_the_articles_delete(db, monkeypatch, 2)
    from src.analytics import store

    def _no_backfill(session):
        raise RuntimeError("planted counter failure")

    monkeypatch.setattr(store, "backfill_keyword_counters", _no_backfill)
    with caplog.at_level(logging.WARNING), pytest.raises(NewsletterRemovalStopped) as info:
        delete_imported_newsletters(db)
    assert (info.value.removed, info.value.total, info.value.counts_refreshed) == (2, 5, False)
    assert str(info.value).endswith(
        "the other 3 are still in your corpus. Run the removal again to remove them. "
        "Until then, some keyword and source counts may read high."
    )
    assert "imported-newsletter removal stopped after removing 2 of 5 articles" in caplog.text
    assert "the keyword and source counts were not refreshed" in caplog.text


def test_a_complete_removal_whose_counts_could_not_be_refreshed_answers_with_a_note_not_an_error(db, monkeypatch):
    ids, keep_id = _seed(db, 3)
    from src.analytics import store

    def _no_backfill(session):
        raise RuntimeError("planted counter failure")

    monkeypatch.setattr(store, "backfill_keyword_counters", _no_backfill)
    out = delete_imported_newsletters(db)
    assert out["removed_articles"] == 3
    assert out["counts_refreshed"] is False and out["note"] == NEWSLETTER_COUNTS_NOT_REFRESHED
    assert {r[0] for r in _persisted(db, "SELECT id FROM articles")} == {keep_id}


def test_the_words_are_built_from_the_counts_only():
    assert newsletter_removal_stopped_text(1, 2, counts_refreshed=True) == (
        "The removal stopped after removing 1 of the 2 imported newsletter articles; the other 1 is still in your corpus. "
        "Run the removal again to remove it."
    )
    assert "Until then" not in newsletter_removal_stopped_text(0, 2, counts_refreshed=False), "nothing removed, nothing stale"
    sig = inspect.signature(newsletter_removal_stopped_text)
    assert list(sig.parameters) == ["removed", "total", "counts_refreshed"], "no parameter could carry a failure's text"


# --------------------------------------------------------------------------------------------------
# (a) the route
# --------------------------------------------------------------------------------------------------


@pytest.fixture()
def client(db, monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.database.session import get_db
    from src.ingest import activate_kill_switch, clear_kill_switch

    def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    activate_kill_switch()
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
    finally:
        clear_kill_switch()
        app.dependency_overrides.clear()


def test_the_route_answers_a_partial_removal_in_the_removals_own_words(db, client, monkeypatch):
    ids, keep_id = _seed(db, 3)
    monkeypatch.setattr(email_mod, "_NEWSLETTER_DELETE_CHUNK", 2)
    real_execute = _fail_the_articles_delete(db, monkeypatch, 2)

    r = client.post("/api/newsletters/remove-imported", json={"confirm": True})
    assert r.status_code == 500, r.text
    assert r.json() == {
        "detail": "The removal stopped after removing 2 of the 3 imported newsletter articles; the other 1 is still in your "
        "corpus. Run the removal again to remove it."
    }
    assert _NEEDLE not in r.text

    monkeypatch.setattr(db, "execute", real_execute)
    assert client.get("/api/newsletters/imported-count").json() == {"count": 1}
    r = client.post("/api/newsletters/remove-imported", json={"confirm": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["removed"] is True and body["removed_articles"] == 1 and body["counts_refreshed"] is True
    assert "note" not in body
    assert {r_[0] for r_ in _persisted(db, "SELECT id FROM articles")} == {keep_id}


def test_the_settings_panel_shows_what_is_left_and_the_note_as_text():
    js = (ROOT / "src" / "static" / "app-settings.js").read_text(encoding="utf-8")
    start = js.index("async function removeImportedNewsletters(")
    body = js[start : js.index("\n    }\n", start)]
    fin = body[body.index("} finally {") :]
    assert "loadNewsletterRemoveCount()" in fin, "the count is refreshed after a removal that stopped partway too"
    assert "w.textContent = d.note" in body, "the server's note is set as text, never parsed as markup"
    assert not re.search(r"innerHTML[^;]*d\.note", body)


# --------------------------------------------------------------------------------------------------
# (b) the salvage's epoch bump
# --------------------------------------------------------------------------------------------------


def _scoped(db, monkeypatch):
    """``session_scope`` over the test's store, as the repair's post-steps open it."""
    import contextlib

    from src.database import session as session_mod

    @contextlib.contextmanager
    def _scope():
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise

    monkeypatch.setattr(session_mod, "session_scope", _scope)


def test_a_salvage_epoch_bump_that_fails_reads_none_not_the_epoch_the_damaged_file_had(db, monkeypatch, caplog):
    from src.analytics.corpus_epoch import bump_corpus_epoch
    from src.database import repair

    for _ in range(4):
        bump_corpus_epoch(db, reason="seed")
    assert _epoch(db) == 4
    _scoped(db, monkeypatch)
    real_commit = db.commit

    def _commit():
        db.commit = real_commit  # the bump's commit fails once; the source-count step after it commits
        raise sqlalchemy.exc.OperationalError("COMMIT", {}, Exception(f"disk I/O error {_NEEDLE}"))

    monkeypatch.setattr(db, "commit", _commit)
    with caplog.at_level(logging.DEBUG):
        out = repair._after_the_swap()
    assert out["corpus_epoch"] is None, "a swallowed failure handed back the old epoch, which read as bumped"
    assert out["source_counts_cleared"] == 1, "the next step still ran"
    assert _epoch(db) == 4
    assert (
        "database repair: the corpus epoch was not bumped (OperationalError); the keyword rollup may count rows the repair "
        "could not keep until the next epoch bump"
    ) in caplog.text
    assert _NEEDLE not in caplog.text, "the repair logs the type only"


def test_a_salvage_epoch_bump_that_works_reads_the_new_epoch(db, monkeypatch):
    from src.database import repair

    _scoped(db, monkeypatch)
    e0 = _epoch(db)
    out = repair._after_the_swap()
    assert out["corpus_epoch"] == e0 + 1 == _epoch(db)


def test_the_salvage_bump_is_strict():
    from src.database import repair

    src = " ".join(inspect.getsource(repair._after_the_swap).split())
    assert 'bump_corpus_epoch(session, reason="salvage", strict=True)' in src
