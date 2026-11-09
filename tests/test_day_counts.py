"""The per-day keyword counts trending reads (R623, R625): exact against the live sum, after every way a mention
can be added, deleted or moved.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE PROPERTY: whatever happened to the mentions since the table was built, ``windowed_counts`` answers either
``None`` (trending reads live) or EXACTLY the live ``SUM(count)`` per keyword over the window. Each scenario is
checked twice: as it happens in the app (where a re-index, a prune and a keyword fold also bump the corpus epoch,
so the table falls dark until it is rebuilt) and with the epoch put back by hand, so the triggers ALONE must keep
it exact (R625: "do not rely on the backstop alone").
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from src.analytics import day_counts
from src.analytics.corpus_epoch import CORPUS_EPOCH_KEY, get_corpus_epoch
from src.analytics.extract import BaselineExtractor
from src.analytics.store import index_article, prune_orphan_keywords, reindex_articles
from src.database.models import Article, Base, DerivedMeta, Keyword, KeywordMention, Source

LO, HI = date(2026, 1, 1), date(2026, 12, 31)

_TEXTS = [
    "Climate policy and trade dominated the summit. Climate policy again.",
    "Trade talks stalled while the summit discussed energy prices and climate.",
    "Energy prices rose; the central bank discussed inflation and trade.",
    "Inflation and energy dominated the debate in parliament this week.",
]


def _engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'dc.db'}", future=True, connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _fk(dbapi, _rec):  # the live app's connections run with foreign keys ON (cascades fire)
        dbapi.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(eng)
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        assert day_counts.install(conn) == {"triggers": 2}
    return eng


def _corpus(tmp_path, n=8):
    eng = _engine(tmp_path)
    s = sessionmaker(bind=eng, future=True)()
    s.add(Source(name="S", domain="x.test", country="fr"))
    s.commit()
    ex = BaselineExtractor()
    for i in range(n):
        a = Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1, title="T",
            content=_TEXTS[i % len(_TEXTS)], hash=f"h{i}", country="fr", language="en",
            published_at=datetime(2026, 3, 1 + i % 4, tzinfo=UTC), created_at=datetime.now(UTC),
        )
        s.add(a)
        s.flush()
        index_article(s, a, extractor=ex, country="fr")
    s.commit()
    return eng, s, ex


def _add(s, ex, i, day):
    a = Article(
        url=f"https://x.test/n{i}", canonical_url=f"https://x.test/n{i}", source_id=1, title="T",
        content=_TEXTS[i % len(_TEXTS)], hash=f"n{i}", country="fr", language="en",
        published_at=datetime(2026, 3, day, tzinfo=UTC), created_at=datetime.now(UTC),
    )
    s.add(a)
    s.flush()
    index_article(s, a, extractor=ex, country="fr")
    s.commit()
    return a


def _live(s, lo=LO, hi=HI) -> dict[int, int]:
    return {
        int(k): int(v)
        for k, v in s.execute(
            text(
                "SELECT keyword_id, SUM(count) FROM keyword_mentions WHERE observed_on >= :lo AND observed_on <= :hi "
                "GROUP BY keyword_id"
            ),
            {"lo": lo.isoformat(), "hi": hi.isoformat()},
        )
    }


def _served(s, lo=LO, hi=HI):
    s.info.pop("keyword_day_counts", None)  # a fresh request
    s.commit()
    return day_counts.windowed_counts(s, lo=lo, hi=hi)


def _build(eng):
    assert day_counts.build(eng)["outcome"] == "built"


def _exact(s, *, windows=((LO, HI), (date(2026, 3, 2), date(2026, 3, 3)), (date(2026, 3, 4), date(2026, 3, 4)))):
    for lo, hi in windows:
        got = _served(s, lo, hi)
        assert got is not None, (lo, hi)
        assert got == _live(s, lo, hi), (lo, hi)


def _put_epoch_back(s, eng):
    """Undo the epoch bump the app's mutator made, so only the triggers stand between the table and a wrong number."""
    with eng.connect() as conn:
        built = conn.exec_driver_sql("SELECT built_epoch FROM keyword_day_state WHERE id = 1").scalar()
    row = s.get(DerivedMeta, CORPUS_EPOCH_KEY)
    if row is None:
        assert built == 0
        return
    row.value = str(built)
    s.commit()


def _table_rows(eng) -> dict[tuple[str, int], int]:
    with eng.connect() as conn:
        return {(str(d), int(k)): int(v) for d, k, v in conn.exec_driver_sql("SELECT observed_on, keyword_id, mentions FROM keyword_day_counts")}


def _truth(eng) -> dict[tuple[str, int], int]:
    with eng.connect() as conn:
        return {
            (str(d), int(k)): int(v)
            for d, k, v in conn.exec_driver_sql(
                "SELECT observed_on, keyword_id, SUM(count) FROM keyword_mentions WHERE observed_on IS NOT NULL "
                "GROUP BY observed_on, keyword_id"
            )
        }


# --------------------------------------------------------------------------- the build


def test_install_makes_no_counts_and_the_serve_reads_live_until_the_build(tmp_path):
    eng, s, _ex = _corpus(tmp_path)
    assert _table_rows(eng) == {}
    assert _served(s) is None  # not built: trending reads live
    _build(eng)
    assert _table_rows(eng) == _truth(eng)
    _exact(s)


def test_install_is_idempotent_and_replaces_a_changed_trigger(tmp_path):
    eng, s, _ex = _corpus(tmp_path)
    _build(eng)
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        assert day_counts.install(conn) == {"triggers": 0}
        assert day_counts.current(conn) is None
        conn.exec_driver_sql("DROP TRIGGER trg_keyword_day_dirty_au")
        conn.exec_driver_sql(
            "CREATE TRIGGER trg_keyword_day_dirty_au AFTER UPDATE ON keyword_mentions BEGIN SELECT 1; END"
        )
        assert day_counts.install(conn) == {"triggers": 1}
        # a missing or stale trigger means the table cannot know what happened meanwhile
        assert day_counts.current(conn) == "not-built"


def test_the_build_stops_and_resumes_from_its_cursor(tmp_path):
    eng, s, _ex = _corpus(tmp_path)

    class _Ctx:
        def __init__(self, stop_after):
            self.n, self.stop_after = 0, stop_after

        @property
        def stopping(self):
            return self.n >= self.stop_after

        def set_progress(self, **kw):
            if kw.get("done") is not None and kw.get("detail") is not None:
                self.n += 1

    assert day_counts.build(eng, _Ctx(2))["outcome"] == "stopped"
    with eng.connect() as conn:
        st = day_counts._state(conn)
        assert st["complete"] is False and str(st["cursor"]) == "2026-03-02"
    assert _served(s) is None
    r = day_counts.build(eng, _Ctx(99))
    assert r == {"outcome": "built", "days": 2}  # the two days left, not four
    assert _table_rows(eng) == _truth(eng)
    _exact(s)


def test_the_build_declines_without_the_date_index(tmp_path):
    eng, s, _ex = _corpus(tmp_path)
    with eng.connect() as conn:
        conn.exec_driver_sql("DROP INDEX ix_mention_date_keyword")
        conn.commit()
    assert day_counts.build(eng) == {"outcome": "declined", "reason": "no-date-index"}


# --------------------------------------------------------------------------- inserts: the tail


def test_new_articles_are_read_live_until_folded_then_from_the_table(tmp_path):
    eng, s, ex = _corpus(tmp_path)
    _build(eng)
    before = _table_rows(eng)
    _add(s, ex, 101, 2)
    _add(s, ex, 102, 9)  # a day the table has never seen
    assert _table_rows(eng) == before  # no insert trigger (R625)
    _exact(s)
    r = day_counts.fold_tail(eng)
    assert r["days"] == 2
    assert _table_rows(eng) == _truth(eng)
    with eng.connect() as conn:
        assert day_counts._state(conn)["watermark"] == conn.exec_driver_sql("SELECT max(id) FROM keyword_mentions").scalar()
    _exact(s)


def test_a_top_id_given_again_after_a_delete_is_still_counted(tmp_path):
    """SQLite gives a new row max(id) + 1: delete the top mentions and the next insert takes ids BELOW the watermark."""
    eng, s, ex = _corpus(tmp_path)
    _build(eng)
    with eng.connect() as conn:
        top = conn.exec_driver_sql("SELECT max(id) FROM keyword_mentions").scalar()
        last_article = conn.exec_driver_sql("SELECT article_id FROM keyword_mentions WHERE id = ?", (top,)).scalar()
    s.execute(text("DELETE FROM articles WHERE id = :a"), {"a": last_article})  # cascades its mentions (the top ids)
    s.commit()
    with eng.connect() as conn:
        floor = day_counts._state(conn)["reuse_floor"]
        assert floor is not None and floor <= top
    _add(s, ex, 201, 3)  # takes the freed ids
    with eng.connect() as conn:
        assert conn.exec_driver_sql("SELECT min(id) FROM keyword_mentions WHERE id >= ?", (floor,)).scalar() <= top
    _exact(s)
    day_counts.fold_tail(eng)
    assert _table_rows(eng) == _truth(eng)
    _exact(s)


# --------------------------------------------------------------------------- deletes and moves: the triggers


@pytest.mark.parametrize("epoch_back", [False, True], ids=["as-the-app-does", "triggers-alone"])
def test_a_reindex_rewriting_rows_in_place(tmp_path, epoch_back):
    eng, s, ex = _corpus(tmp_path)
    _build(eng)

    class _Doubling(BaselineExtractor):
        """Every count doubled and no term added: the re-index rewrites rows IN PLACE (UPDATE, same ids), so no new
        id lands in the tail and only the update trigger can say which days changed."""

        def extract(self, text_, *a, **kw):
            return [dataclasses.replace(t, count=t.count * 2) for t in super().extract(text_, *a, **kw)]

    ids = [a.id for a in s.query(Article).order_by(Article.id).limit(3)]
    e0 = get_corpus_epoch(s)
    with eng.connect() as conn:
        top = conn.exec_driver_sql("SELECT max(id) FROM keyword_mentions").scalar()
    reindex_articles(s, extractor=_Doubling(), article_ids=ids)
    s.commit()
    with eng.connect() as conn:  # the scenario fired: rows changed in place, nothing new in the tail
        assert conn.exec_driver_sql("SELECT max(id) FROM keyword_mentions").scalar() == top
        assert conn.exec_driver_sql("SELECT count(*) FROM keyword_day_dirty").scalar() > 0
    if epoch_back:
        _put_epoch_back(s, eng)
        _exact(s)
    else:
        assert get_corpus_epoch(s) != e0
        assert _served(s) is None  # the epoch moved: live until the rebuild
        assert day_counts.fold_tail(eng) == {"rebuild": "epoch-moved", "job": "started"}
        assert day_counts.DAY_COUNTS_JOB.join(30)
        assert day_counts.DAY_COUNTS_JOB.status()["state"] == "done"
    day_counts.fold_tail(eng)
    assert _table_rows(eng) == _truth(eng)
    _exact(s)


@pytest.mark.parametrize("epoch_back", [False, True], ids=["as-the-app-does", "triggers-alone"])
def test_cascade_deletes_from_an_article_and_a_keyword(tmp_path, epoch_back):
    eng, s, _ex = _corpus(tmp_path)
    _build(eng)
    s.delete(s.query(Article).order_by(Article.id).first())  # FK cascade to its mentions
    s.commit()
    kw = s.query(Keyword).filter(Keyword.normalized_term.like("%energy%")).first()
    assert kw is not None
    s.execute(text("DELETE FROM keywords WHERE id = :k"), {"k": kw.id})  # FK cascade to every mention of it
    s.commit()
    if not epoch_back:
        prune_orphan_keywords(s)  # the app's own prune also bumps the epoch
        s.commit()
        if get_corpus_epoch(s) != 0:
            assert _served(s) is None
            _build(eng)
    _exact(s)
    day_counts.fold_tail(eng)
    assert _table_rows(eng) == _truth(eng)


def test_a_keyword_fold_moving_rows_to_another_keyword_and_merging_counts(tmp_path):
    """keyword_fold's two writes, with the epoch left alone: UPDATE keyword_id (a move), and a duplicate's count
    added to the row it lands on, then the duplicate deleted."""
    eng, s, _ex = _corpus(tmp_path)
    _build(eng)
    a, b = s.execute(
        text(
            "SELECT m1.keyword_id, m2.keyword_id FROM keyword_mentions m1 JOIN keyword_mentions m2 "
            "ON m2.article_id = m1.article_id AND m2.keyword_id <> m1.keyword_id "
            "WHERE EXISTS (SELECT 1 FROM keyword_mentions x WHERE x.keyword_id = m1.keyword_id AND NOT EXISTS "
            "(SELECT 1 FROM keyword_mentions y WHERE y.keyword_id = m2.keyword_id AND y.article_id = x.article_id)) "
            "LIMIT 1"
        )
    ).one()
    # rows of keyword a on articles where b has none: moved
    moved = s.execute(
        text(
            "UPDATE keyword_mentions SET keyword_id = :b WHERE keyword_id = :a AND article_id NOT IN "
            "(SELECT article_id FROM keyword_mentions WHERE keyword_id = :b)"
        ),
        {"a": a, "b": b},
    )
    assert moved.rowcount > 0  # the scenario fired
    s.commit()
    _exact(s)  # the move alone (the update trigger)
    # the rest: merged into b's row, then deleted
    s.execute(
        text(
            "UPDATE keyword_mentions SET count = count + (SELECT m2.count FROM keyword_mentions m2 WHERE m2.keyword_id = :a "
            "AND m2.article_id = keyword_mentions.article_id) WHERE keyword_id = :b AND article_id IN "
            "(SELECT article_id FROM keyword_mentions WHERE keyword_id = :a)"
        ),
        {"a": a, "b": b},
    )
    s.execute(text("DELETE FROM keyword_mentions WHERE keyword_id = :a"), {"a": a})
    s.commit()
    assert get_corpus_epoch(s) == 0
    _exact(s)
    day_counts.fold_tail(eng)
    assert _table_rows(eng) == _truth(eng)


def test_a_row_moved_to_another_day_and_a_day_emptied(tmp_path):
    eng, s, _ex = _corpus(tmp_path)
    _build(eng)
    s.execute(text("UPDATE keyword_mentions SET observed_on = '2026-03-20' WHERE observed_on = '2026-03-01'"))
    s.execute(text("UPDATE keyword_mentions SET observed_on = NULL WHERE observed_on = '2026-03-02'"))
    s.commit()
    with eng.connect() as conn:
        dirty = {str(r[0]) for r in conn.exec_driver_sql("SELECT observed_on FROM keyword_day_dirty")}
    assert dirty == {"2026-03-01", "2026-03-02", "2026-03-20"}
    _exact(s)
    day_counts.fold_tail(eng)
    assert _table_rows(eng) == _truth(eng)
    with eng.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM keyword_day_dirty").scalar() == 0


def test_an_update_that_changes_nothing_marks_nothing(tmp_path):
    eng, s, _ex = _corpus(tmp_path)
    _build(eng)
    s.execute(text("UPDATE keyword_mentions SET count = count, first_offset = first_offset"))
    s.commit()
    with eng.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM keyword_day_dirty").scalar() == 0


# --------------------------------------------------------------------------- the serve's refusals


def test_the_serve_refuses_what_it_cannot_answer_exactly(tmp_path, monkeypatch):
    eng, s, ex = _corpus(tmp_path)
    _build(eng)
    assert _served(s) is not None
    monkeypatch.setattr(day_counts, "MAX_LIVE_DAYS", 0)
    _add(s, ex, 301, 2)
    assert _served(s) is None  # one stale day in the window, cap 0
    monkeypatch.setattr(day_counts, "MAX_LIVE_DAYS", 8)
    monkeypatch.setattr(day_counts, "MAX_TAIL_ROWS", 0)
    assert _served(s) is None  # the tail is past its cap
    monkeypatch.setattr(day_counts, "MAX_TAIL_ROWS", 250_000)
    monkeypatch.setattr(day_counts, "BACKSTOP_S", -1)
    assert _served(s) is None  # past the backstop
    with eng.connect() as conn:
        assert day_counts.current(conn) == "backstop"


def test_the_serve_writes_nothing(tmp_path):
    eng, s, ex = _corpus(tmp_path)
    _build(eng)
    _add(s, ex, 401, 2)
    s.execute(text("DELETE FROM keyword_mentions WHERE observed_on = '2026-03-03'"))
    s.commit()
    seen: list[str] = []

    @event.listens_for(eng, "before_cursor_execute")
    def _watch(_c, _cur, statement, *_a):
        seen.append(statement.lstrip().split()[0].upper())

    assert _served(s) is not None
    assert not {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP"} & set(seen), seen


def test_trending_answers_the_same_from_the_table_and_live(tmp_path, monkeypatch):
    from src.analytics import queries

    monkeypatch.setenv("OO_COLUMNAR_SERVE", "0")
    eng, s, ex = _corpus(tmp_path, n=12)
    _build(eng)
    _add(s, ex, 501, 4)
    end = date(2026, 3, 5)
    served = queries.trending(s, window_days=2, baseline_days=2, end=end, min_recent=1)
    assert served.get("basis", {}).get("source") == "day-counts"
    monkeypatch.setattr(day_counts, "windowed_counts", lambda *a, **k: None)
    live = queries.trending(s, window_days=2, baseline_days=2, end=end, min_recent=1)
    assert "basis" not in live
    for key in ("terms", "scanned", "keywords_with_recent_mentions", "count"):
        assert served[key] == live[key], key
    assert served["terms"], "the scenario must rank something"


def test_a_country_filter_always_reads_live(tmp_path, monkeypatch):
    from src.analytics import queries

    monkeypatch.setenv("OO_COLUMNAR_SERVE", "0")
    eng, s, _ex = _corpus(tmp_path)
    _build(eng)
    calls: list = []
    monkeypatch.setattr(day_counts, "windowed_counts", lambda *a, **k: calls.append(1))
    queries.trending(s, window_days=2, baseline_days=2, end=date(2026, 3, 5), country="fr")
    assert calls == []


def test_the_real_keyword_fold_job_with_the_epoch_put_back(tmp_path, monkeypatch):
    """The app's own fold (src/analytics/keyword_fold.py), not a copy of its statements: it bumps the epoch, and
    with that bump undone the triggers alone keep the counts exact."""
    from src.analytics.lemma import lemmatizer_available

    if not lemmatizer_available():
        pytest.skip("simplemma not importable here")
    from tests.test_keyword_fold import _corpus as fold_corpus
    from tests.test_keyword_fold import _run_fold

    eng, s = fold_corpus(tmp_path, "fold.db", lemma=False, monkeypatch=monkeypatch)
    s.commit()
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        day_counts.install(conn)
    _build(eng)
    e0 = get_corpus_epoch(s)
    _run_fold(tmp_path, eng, monkeypatch)
    s.expire_all()
    assert get_corpus_epoch(s) != e0  # the fold bumps the epoch (keyword_fold.py)
    assert _served(s) is None
    with eng.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM keyword_day_dirty").scalar() > 0  # the fold moved rows
    _put_epoch_back(s, eng)
    _exact(s, windows=((LO, HI),))
    day_counts.fold_tail(eng)
    assert _table_rows(eng) == _truth(eng)


# --------------------------------------------------------------------------- the export lane's read (2026-11-09)


def test_a_fold_after_a_top_delete_does_not_hide_the_next_insert(tmp_path):
    """Gap 1 of the read: the newest article goes (no epoch bump, as a source delete), a fold runs, THEN a new row
    takes a freed id. The fold must not have left the watermark above max(id)."""
    eng, s, ex = _corpus(tmp_path)
    _build(eng)
    newest = s.query(Article).order_by(Article.id.desc()).first()
    s.delete(newest)
    s.commit()
    r = day_counts.fold_tail(eng)
    assert r["floor_cleared"] is True
    with eng.connect() as conn:
        st = day_counts._state(conn)
        top = conn.exec_driver_sql("SELECT max(id) FROM keyword_mentions").scalar()
    assert st["watermark"] == top and st["reuse_floor"] is None
    _add(s, ex, 601, 1)  # takes ids at and above top + 1, which the deleted rows had
    _exact(s)
    day_counts.fold_tail(eng)
    assert _table_rows(eng) == _truth(eng)
    _exact(s)


def test_a_top_delete_while_a_fold_works_keeps_the_floor(tmp_path):
    """A delete from the top and an insert into the freed ids WHILE the fold runs: the floor must survive the fold."""
    eng, s, ex = _corpus(tmp_path)
    _build(eng)
    _add(s, ex, 701, 2)  # a tail, so the fold has days to walk
    _add(s, ex, 702, 3)
    fired = []

    def _meanwhile():
        if not fired:
            fired.append(1)
            s.delete(s.query(Article).order_by(Article.id.desc()).first())
            s.commit()
            _add(s, ex, 703, 4)
        return False

    r = day_counts.fold_tail(eng, should_stop=_meanwhile)
    assert fired and r["floor_cleared"] is False
    _exact(s)
    day_counts.fold_tail(eng)
    assert _table_rows(eng) == _truth(eng)
    _exact(s)


def test_a_remade_trigger_rebuilds_from_scratch_rather_than_resuming(tmp_path):
    """Gap 2 of the read: while the delete trigger was missing a delete went unmarked; install must make the next
    build start over, not resume from its last day and call the table current."""
    eng, s, _ex = _corpus(tmp_path)
    _build(eng)
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("DROP TRIGGER trg_keyword_day_dirty_ad")
    s.delete(s.query(Article).order_by(Article.id).first())
    s.commit()
    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        assert day_counts.install(conn) == {"triggers": 1}
        assert day_counts.current(conn) == "not-built"
    r = day_counts.build(eng)
    assert r["outcome"] == "built" and r["days"] == len({d for d, _k in _truth(eng)})
    assert _table_rows(eng) == _truth(eng)
    _exact(s)


def test_the_unbuilt_mark_a_salvage_writes_rebuilds_from_scratch(tmp_path):
    eng, s, _ex = _corpus(tmp_path)
    _build(eng)
    with eng.connect() as conn:  # a salvaged copy that lost a day's counts
        conn.exec_driver_sql("DELETE FROM keyword_day_counts WHERE observed_on = '2026-03-02'")
        conn.exec_driver_sql(day_counts.UNBUILT_SQL)
        conn.commit()
    r = day_counts.build(eng)
    assert r["outcome"] == "built" and r["days"] == 4
    assert _table_rows(eng) == _truth(eng)


def test_salvage_writes_the_same_unbuilt_mark():
    import inspect

    from src.database import salvage

    body = " ".join(inspect.getsource(salvage.Salvage._finish).split()).replace('" "', "")
    assert " ".join(day_counts.UNBUILT_SQL.split()) in body  # salvage knows no app module, so it carries a copy


# --------------------------------------------------------------------------- Steward 1's read (2026-11-09): the wiring


def test_init_db_installs_the_triggers_and_the_state_row():
    from src.database import session as db_session

    db_session.init_db()
    with db_session.engine.connect() as conn:
        names = {r[0] for r in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert set(day_counts.TRIGGERS) <= names
        assert conn.exec_driver_sql("SELECT count(*) FROM keyword_day_state WHERE id = 1").scalar() == 1


def test_the_idle_maintenance_folds_the_counts(monkeypatch):
    from src.database.session import init_db
    from src.scheduler import maintenance as maint

    init_db()
    seen: list = []
    monkeypatch.setattr(maint, "_backlog_busy_reason", lambda: None)
    monkeypatch.setattr(day_counts, "fold_tail", lambda engine, should_stop=None: seen.append(engine) or {"days": 0})
    out = maint.run_idle_maintenance()
    assert out["day_counts"] == {"days": 0} and len(seen) == 1


def test_the_idle_maintenance_stands_back_while_a_rewrite_runs(monkeypatch):
    from src.database.session import init_db
    from src.scheduler import maintenance as maint

    init_db()
    monkeypatch.setattr(maint, "_backlog_busy_reason", lambda: "reindex_running")
    monkeypatch.setattr(day_counts, "fold_tail", lambda *a, **k: pytest.fail("folded during a re-index"))
    assert maint.run_idle_maintenance()["day_counts"] == {"skipped": "reindex_running"}


def test_the_boot_queues_the_build_unless_a_reindex_resumes(monkeypatch):
    from src.api import boot_sequence as bs
    from src.backup import volume_job

    seen: list[str] = []
    monkeypatch.setenv("OO_NO_SCHEDULER", "0")
    monkeypatch.delenv("OO_DAY_COUNTS_AUTOBUILD", raising=False)
    monkeypatch.setenv("OO_TITLE_INDEX_AUTOBUILD", "0")
    monkeypatch.setattr(day_counts, "start_build_if_needed", lambda engine=None: seen.append("queued") or "started")
    monkeypatch.setattr(volume_job, "start_reindex_drain", lambda: (False, "test"))
    bs._reset()
    with pytest.raises(bs._Skipped):
        bs._start_reindex()  # no re-index pending
    assert seen == ["queued"]
    bs._reset()
    monkeypatch.setitem(bs._STATE, "reindex_pending", 12)  # restored after the test
    with pytest.raises(bs._Skipped):
        bs._start_reindex()  # a re-index resumes: its drain would move the epoch under the build
    assert seen == ["queued"]
    bs._reset()
    monkeypatch.setenv("OO_DAY_COUNTS_AUTOBUILD", "0")
    bs._queue_day_counts()
    assert seen == ["queued"]


def test_the_serve_gives_up_at_trendings_read_deadline(tmp_path):
    import time

    eng, s, ex = _corpus(tmp_path)
    _build(eng)
    _add(s, ex, 801, 2)  # one stale day to read live
    s.info.pop("keyword_day_counts", None)
    assert day_counts.windowed_counts(s, lo=LO, hi=HI, deadline=time.monotonic() - 1) is None
    s.info.pop("keyword_day_counts", None)
    assert day_counts.windowed_counts(s, lo=LO, hi=HI, deadline=time.monotonic() + 60) == _live(s)


def test_an_observed_on_with_a_time_part_is_still_its_day():
    assert day_counts._day("2026-03-02 00:00:00.000000") == date(2026, 3, 2)
    assert day_counts._day(date(2026, 3, 2)) == date(2026, 3, 2)


# --------------------------------------------------------------------------- R632: the prune leaves the epoch alone


def test_a_prune_of_mention_less_keywords_changes_no_sum_and_rebuilds_nothing(tmp_path):
    eng, s, _ex = _corpus(tmp_path)
    _build(eng)
    top = s.query(Keyword).order_by(Keyword.id.desc()).first().id
    s.add(Keyword(id=top + 10, term="zz-orphan", normalized_term="zz-orphan"))  # a mention-less keyword...
    s.commit()
    s.add(Keyword(id=top + 20, term="zz-keeper", normalized_term="zz-keeper"))  # ...below the top id, so no id is freed
    s.commit()
    s.add(KeywordMention(keyword_id=top + 20, article_id=s.query(Article.id).first()[0], count=1, observed_on=date(2026, 3, 1)))
    s.commit()
    day_counts.fold_tail(eng)
    e0, before = get_corpus_epoch(s), _table_rows(eng)
    r = prune_orphan_keywords(s)
    s.commit()
    assert r["pruned"] == 1 and r["epoch_bumped"] is False
    assert get_corpus_epoch(s) == e0  # no rebuild
    assert _table_rows(eng) == before  # the sums are unchanged
    with eng.connect() as conn:
        assert day_counts.current(conn) is None
    _exact(s)


def test_a_prune_fails_closed_when_the_counts_still_counted_the_keyword(tmp_path):
    eng, s, _ex = _corpus(tmp_path)
    _build(eng)
    top = s.query(Keyword).order_by(Keyword.id.desc()).first().id
    s.add(Keyword(id=top + 10, term="zz-orphan", normalized_term="zz-orphan"))
    s.add(Keyword(id=top + 20, term="zz-keeper", normalized_term="zz-keeper"))
    s.commit()
    s.add(KeywordMention(keyword_id=top + 20, article_id=s.query(Article.id).first()[0], count=1, observed_on=date(2026, 3, 1)))
    s.commit()
    day_counts.fold_tail(eng)
    with eng.connect() as conn:  # counts that are wrong: they count the orphan
        conn.exec_driver_sql("INSERT INTO keyword_day_counts VALUES ('2026-03-01', ?, 3)", (top + 10,))
        conn.commit()
    e0 = get_corpus_epoch(s)
    r = prune_orphan_keywords(s)
    assert r["pruned"] == 1 and r["epoch_bumped"] is True
    assert get_corpus_epoch(s) == e0 + 1  # the counts are rebuilt
    with eng.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM keyword_day_counts WHERE keyword_id = ?", (top + 10,)).scalar() == 0


def test_a_prune_of_the_top_keyword_id_still_bumps_the_epoch(tmp_path):
    """The id SQLite would give the next new keyword: the columnar rollup's keyword_meta would keep the old term."""
    eng, s, _ex = _corpus(tmp_path)
    top = s.query(Keyword).order_by(Keyword.id.desc()).first().id
    s.add(Keyword(id=top + 10, term="zz-orphan", normalized_term="zz-orphan"))
    s.commit()
    e0 = get_corpus_epoch(s)
    r = prune_orphan_keywords(s)
    assert r["pruned"] == 1 and r["epoch_bumped"] is True and get_corpus_epoch(s) == e0 + 1
