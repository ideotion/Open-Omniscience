"""Row 429: every path that deletes articles moves the keyword counters in the same transaction.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Three paths delete articles: a source delete (the ORM cascade), the live removal of imported newsletters (chunked
Core deletes), and the newsletter filter on a backup's snapshot copy (raw SQL on the copy). Before this row the
first left ``Keyword.mention_count``/``article_count`` counting the deleted mentions until a whole sweep, the second
until its closing refresh (and forever for a chunk committed before the process ended), and the third shipped the
stale counters inside the backup. Each test below checks the counters against the exact R101 aggregate.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest
from sqlalchemy import func
from sqlalchemy.orm import sessionmaker

from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article, remove_deleted_articles_from_keyword_counters
from src.database.models import Article, Base, Keyword, KeywordMention, Source
from tests._app_engine import app_sqlite_engine

_TEXTS = (
    "Election coverage and inflation in the newsletter today.",
    "Drought and climate policy from the mailbox digest, election inflation.",
    "Election coverage from the web about inflation worldwide.",
    "Climate policy and drought hit the election, inflation again and again inflation.",
)


def _session(url: str = ":memory:"):
    engine = app_sqlite_engine(url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True, autoflush=False)()


@pytest.fixture()
def db():
    return _session()


def _src(db, name, domain):
    s = Source(name=name, domain=domain, enabled=True)
    db.add(s)
    db.commit()
    return s


def _article(db, source_id, h, text_, *, quarantined=False):
    a = Article(
        url=f"https://x.test/{h}",
        canonical_url=f"https://x.test/{h}",
        source_id=source_id,
        title=f"T-{h}",
        content=text_,
        hash=h,
        language="en",
        published_at=datetime(2024, 3, 1, tzinfo=UTC),
        created_at=datetime.now(UTC),
    )
    db.add(a)
    db.commit()
    index_article(db, a, extractor=BaselineExtractor())
    if quarantined:
        # A quarantined article's mentions leave the counters (R101), as the quarantine job does it.
        from src.analytics.store import shift_keyword_counters_for_quarantine

        shift_keyword_counters_for_quarantine(db, [a.id], quarantined=True)
        a.quarantined = True
        db.commit()
    return a


def _exact(db) -> dict[int, tuple[int, int]]:
    """Every keyword's R101 truth: sum and distinct articles over mentions of articles that are not quarantined."""
    live = KeywordMention.article_id.not_in(db.query(Article.id).filter(Article.quarantined.is_(True)))
    agg = {
        k: (int(m or 0), int(a or 0))
        for k, m, a in db.query(
            KeywordMention.keyword_id, func.sum(KeywordMention.count), func.count(func.distinct(KeywordMention.article_id))
        )
        .filter(live)
        .group_by(KeywordMention.keyword_id)
    }
    return {k: agg.get(k, (0, 0)) for (k,) in db.query(Keyword.id)}


def _stored(db) -> dict[int, tuple[int, int]]:
    db.expire_all()
    return {k.id: (k.mention_count, k.article_count) for k in db.query(Keyword)}


def _seed(db):
    gone = _src(db, "Gone", "gone.test")
    kept = _src(db, "Kept", "kept.test")
    _article(db, gone.id, "g1", _TEXTS[0])
    _article(db, gone.id, "g2", _TEXTS[1])
    _article(db, gone.id, "g3", _TEXTS[3], quarantined=True)  # already out of the counters: never subtracted twice
    _article(db, kept.id, "k1", _TEXTS[2])
    _article(db, kept.id, "k2", _TEXTS[3])
    assert _stored(db) == _exact(db), "the seed starts exact"
    return gone, kept


# ---------------------------------------------------------------- the helper


def test_the_helper_subtracts_only_articles_that_are_not_quarantined(db):
    gone, _ = _seed(db)
    ids = [a for (a,) in db.query(Article.id).filter(Article.source_id == gone.id)]
    out = remove_deleted_articles_from_keyword_counters(db, ids)
    assert out["articles"] == 2, "g3 is quarantined, so only g1 and g2 move the counters"
    db.query(KeywordMention).filter(KeywordMention.article_id.in_(ids)).delete(synchronize_session=False)
    db.query(Article).filter(Article.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    assert _stored(db) == _exact(db)
    assert out["clamped"] == 0


def test_the_helper_with_no_ids_moves_nothing(db):
    _seed(db)
    before = _stored(db)
    assert remove_deleted_articles_from_keyword_counters(db, [])["articles"] == 0
    db.commit()
    assert _stored(db) == before


# ---------------------------------------------------------------- path 1: a source delete (ORM cascade)


def test_a_source_delete_leaves_every_counter_exact(db):
    from src.database.source_manager import SourceManager

    gone, kept = _seed(db)
    assert SourceManager(session=db).delete_source(gone.id) is True
    assert db.query(Article).filter(Article.source_id == gone.id).count() == 0
    stored, exact = _stored(db), _exact(db)
    assert stored == exact
    assert any(v != (0, 0) for v in exact.values()), "the kept source's keywords still count"


def test_a_source_delete_whose_epoch_bump_fails_moves_no_counter(db, monkeypatch):
    import src.analytics.corpus_epoch as ce
    from src.database.source_manager import SourceManager

    gone, _ = _seed(db)
    before = _stored(db)

    def _fail(session, **_kw):
        session.rollback()
        raise RuntimeError("bump failed")

    monkeypatch.setattr(ce, "bump_corpus_epoch", _fail)
    with pytest.raises(RuntimeError):
        SourceManager(session=db).delete_source(gone.id)
    db.rollback()
    assert db.query(Article).filter(Article.source_id == gone.id).count() == 3, "the delete rolled back"
    assert _stored(db) == before, "and the counter move with it"


# ---------------------------------------------------------------- path 2: the live newsletter removal (chunked)


def _seed_newsletters(db):
    nl = _src(db, "Imported newsletters (.eml)", "newsletters.import.local")
    web = _src(db, "Web", "news.test")
    for i, t in enumerate(_TEXTS):
        _article(db, nl.id, f"n{i}", t)
    _article(db, nl.id, "nq", _TEXTS[1], quarantined=True)
    _article(db, web.id, "w1", _TEXTS[2])
    _article(db, web.id, "w2", _TEXTS[3])
    assert _stored(db) == _exact(db)
    return nl, web


def test_each_newsletter_chunk_moves_the_counters_in_its_own_transaction(db, monkeypatch):
    """The closing whole refresh is skipped, so only the per-chunk move can make the counters exact."""
    import src.ingest.email as email_mod

    _seed_newsletters(db)
    monkeypatch.setattr(email_mod, "_NEWSLETTER_DELETE_CHUNK", 2)
    monkeypatch.setattr(email_mod, "_refresh_counts_after_removal", lambda s: True)
    out = email_mod.delete_imported_newsletters(db)
    assert out["removed_articles"] == 5
    assert _stored(db) == _exact(db)


def test_a_newsletter_removal_that_stops_leaves_the_committed_chunks_counters_exact(db, monkeypatch):
    import src.analytics.corpus_epoch as ce
    import src.ingest.email as email_mod

    _seed_newsletters(db)
    monkeypatch.setattr(email_mod, "_NEWSLETTER_DELETE_CHUNK", 2)
    monkeypatch.setattr(email_mod, "_refresh_counts_after_removal", lambda s: True)
    real = ce.bump_corpus_epoch
    calls = {"n": 0}

    def _second_fails(session, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            session.rollback()
            raise RuntimeError("bump failed")
        return real(session, **kw)

    monkeypatch.setattr(ce, "bump_corpus_epoch", _second_fails)
    with pytest.raises(email_mod.NewsletterRemovalStopped) as info:
        email_mod.delete_imported_newsletters(db)
    assert info.value.removed == 2
    db.rollback()
    assert _stored(db) == _exact(db), "the first chunk moved its counters; the failed one rolled its move back"


# ---------------------------------------------------------------- path 3: the newsletter filter on a backup's snapshot copy


def test_the_backup_copy_without_newsletters_carries_exact_counters(tmp_path):
    from src.backup.artifact import _drop_newsletter_articles

    path = tmp_path / "snap.db"
    db = _session(str(path))
    _seed_newsletters(db)
    db.close()
    db.get_bind().dispose()

    assert _drop_newsletter_articles(path) == 5
    check = _session(str(path))
    assert check.query(Article).count() == 2
    assert _stored(check) == _exact(check)


def test_the_backup_copy_recount_tolerates_a_copy_without_counter_columns(tmp_path):
    from src.backup.artifact import _recount_keywords

    con = sqlite3.connect(str(tmp_path / "old.db"))
    con.executescript(
        "CREATE TABLE keywords (id INTEGER PRIMARY KEY, normalized TEXT);"
        "CREATE TABLE articles (id INTEGER PRIMARY KEY);"
        "CREATE TABLE keyword_mentions (keyword_id INTEGER, article_id INTEGER, count INTEGER);"
        "INSERT INTO keywords VALUES (1, 'a');"
    )
    _recount_keywords(con.cursor(), [1])  # nothing to recount, and no error
    assert con.execute("SELECT normalized FROM keywords").fetchall() == [("a",)]
    con.close()


# ---------------------------------------------------------------- a fourth delete, guarded rather than counted


def test_the_attach_undo_checks_and_deletes_its_empty_sources_under_one_gate_hold():
    """``newsletter_attach_undo`` deletes ladder sources it found empty. The delete cascades to any article on the source,
    so the emptiness check and the delete must sit under one hold of the gate: an import attaching an article between an
    ungated check and the flush would be deleted with the source, its mentions with it, and no counter moved."""
    import inspect

    from src.api import ingestion

    src = inspect.getsource(ingestion.newsletter_attach_undo)
    tail = src[src.index("deleted: list[str] = []") :]
    gate = tail.index("with write_lock():")
    assert gate < tail.index("still = db.query(Article.id)") < tail.index("db.delete(src)") < tail.index("db.commit()")
    body = tail[gate : tail.index("from src.analytics.store import reconcile_source_counters")]
    for line in body.splitlines()[1:]:
        if line.strip() and not line.lstrip().startswith("#"):
            assert line.startswith(" " * 8), f"left the gate's block before the commit: {line!r}"


# ---------------------------------------------------------------- row 430: the copy's per-day keyword counts


def _day_rows(con) -> dict[tuple[str, int], int]:
    return {(str(d), int(k)): int(m) for d, k, m in con.execute("SELECT observed_on, keyword_id, mentions FROM keyword_day_counts")}


def _day_truth(con) -> dict[tuple[str, int], int]:
    return {
        (str(d), int(k)): int(m)
        for d, k, m in con.execute(
            "SELECT observed_on, keyword_id, SUM(count) FROM keyword_mentions WHERE observed_on IS NOT NULL"
            " AND article_id NOT IN (SELECT id FROM articles WHERE quarantined IS 1) GROUP BY observed_on, keyword_id"
        )
    }


def test_the_backup_copy_without_newsletters_carries_no_newsletter_day_counts(tmp_path):
    """Row 430: the copy's ``keyword_day_counts`` is rebuilt for the days the newsletters' mentions fell on, so the file
    holds no per-day count of a mention it left out, and the days' stale marks the delete trigger set are cleared."""
    from src.analytics.day_counts import install
    from src.backup.artifact import _drop_newsletter_articles

    path = tmp_path / "snap.db"
    db = _session(str(path))
    _seed_newsletters(db)
    with db.get_bind().begin() as conn:
        install(conn)
        # A built table: every day of every mention, as the build writes it.
        conn.exec_driver_sql(
            "INSERT INTO keyword_day_counts (observed_on, keyword_id, mentions) SELECT observed_on, keyword_id, SUM(count)"
            " FROM keyword_mentions WHERE observed_on IS NOT NULL"
            " AND article_id NOT IN (SELECT id FROM articles WHERE quarantined IS 1) GROUP BY observed_on, keyword_id"
        )
    db.close()
    db.get_bind().dispose()

    con = sqlite3.connect(str(path))
    before = _day_rows(con)
    assert before, "the seed has dated mentions"
    con.close()

    assert _drop_newsletter_articles(path) == 5
    con = sqlite3.connect(str(path))
    try:
        after, truth = _day_rows(con), _day_truth(con)
        assert after == truth
        assert after != before, "the newsletters' mentions were counted before"
        assert con.execute("SELECT COUNT(*) FROM keyword_day_dirty").fetchone()[0] == 0
    finally:
        con.close()


def test_a_day_the_copy_never_built_is_left_for_its_build(tmp_path):
    from src.backup.artifact import _recount_days

    con = sqlite3.connect(str(tmp_path / "c.db"))
    con.executescript(
        "CREATE TABLE articles (id INTEGER PRIMARY KEY, quarantined BOOLEAN);"
        "CREATE TABLE keyword_mentions (keyword_id INTEGER, article_id INTEGER, count INTEGER, observed_on DATE);"
        "CREATE TABLE keyword_day_counts (observed_on DATE, keyword_id INTEGER, mentions INTEGER);"
        "CREATE TABLE keyword_day_dirty (observed_on DATE PRIMARY KEY);"
        "INSERT INTO articles VALUES (1, 0);"
        "INSERT INTO keyword_mentions VALUES (7, 1, 3, '2024-03-01');"
        "INSERT INTO keyword_day_dirty VALUES ('2024-03-01');"
    )
    tables = ["articles", "keyword_mentions", "keyword_day_counts", "keyword_day_dirty"]
    _recount_days(con.cursor(), tables, ["2024-03-01"])
    assert con.execute("SELECT COUNT(*) FROM keyword_day_counts").fetchone()[0] == 0, "nothing written for an unbuilt day"
    assert con.execute("SELECT COUNT(*) FROM keyword_day_dirty").fetchone()[0] == 1, "its mark stays for the build"
    con.close()
