"""The two article-list indexes, built once at start-up where the operator can see them (R128).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer ruled it 2026-10-06 (question 34, answer a): ``idx_article_language_published (language,
published_at)`` and ``idx_article_title_nocase (title COLLATE NOCASE)``, built at the next start while the app is
still offline, with the progress in the task manager. What is pinned here, against REAL SQLite stores:

  * the plans: the language filter and both directions of the title sort read ONLY the index (no row, no sort step),
    and the answers are identical with and without the indexes (only cost changes);
  * the collation is the reason: a plain index on ``title`` cannot serve ``ORDER BY title COLLATE NOCASE``;
  * ``init_db`` leaves them out and the ``article-indexes`` boot step builds them: one statement each, under the
    write gate, in a task-manager job with ``index N of M`` and no Cancel, after the check of the data files and
    before the warm-up;
  * the refusals: switch off, a damaged corpus file, too little free space (a failed row with the numbers); an
    unreadable free-space figure is NOT a refusal; a statement that fails leaves no half index;
  * the stamp alignment reads no drift for the title index in any state, and names the language one as the
    transient difference until the step has built it (both pinned so a change is noticed);
  * the migration is the same statement as the self-heal, chained on the head it was written against.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

from src.api import boot_sequence
from src.database import article_indexes as ai
from src.database import damage
from src.database.damage import FILE_CORPUS, DamageRegistry
from src.database.maintenance import DEFERRED_INDEXES, HOT_INDEXES, ensure_hot_indexes
from src.database.models import Article, Base, Source
from src.jobs.background import Framed
from tests.js_source_helper import python_function_source

ROOT = Path(__file__).resolve().parents[1]
LANG = "idx_article_language_published"
TITLE = "idx_article_title_nocase"
LANGS = ["en", "fr", "de", "es", "ru"]


# --------------------------------------------------------------------------- #
#  fixtures: a real store the way a store made before this change looks (no deferred index)
# --------------------------------------------------------------------------- #
def _store(tmp_path: Path, rows: int = 600, name: str = "corpus.db"):
    """A real SQLite store with ``rows`` articles, built from the models, then with the two deferred indexes
    DROPPED: the state of a store created before this change, which is what the boot step builds them on."""
    eng = create_engine(f"sqlite:///{tmp_path / name}")
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    with S() as s:
        s.add(Source(name="s", domain="example.org"))
        s.flush()
        src_id = s.execute(select(Source.id)).scalar_one()
        for i in range(rows):
            s.add(
                Article(
                    url=f"https://example.org/{i}",
                    canonical_url=f"https://example.org/{i}",
                    source_id=src_id,
                    content="x" * 200,
                    hash=f"h{i}",
                    # mixed case on purpose: the NOCASE order differs from the binary one
                    title=("Zeta " if i % 3 == 0 else "apple " if i % 3 == 1 else "Mango ") + str(i % 97),
                    language=LANGS[i % len(LANGS)],
                    published_at=None if i % 11 == 0 else _date(i),
                )
            )
        s.commit()
    with eng.begin() as c:
        for n in (LANG, TITLE):
            c.execute(text(f"DROP INDEX IF EXISTS {n}"))
    return eng


def _date(i: int):
    from datetime import datetime, timedelta

    return datetime(2026, 1, 1) + timedelta(hours=(i * 7919) % 5000)


def _names(eng) -> set[str]:
    with eng.connect() as c:
        return {r[0] for r in c.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}


def _plan(eng, sql: str) -> list[str]:
    with eng.connect() as c:
        return [r[3] for r in c.execute(text("EXPLAIN QUERY PLAN " + sql))]


def _render(eng, q) -> str:
    return str(q.statement.compile(eng, compile_kwargs={"literal_binds": True}))


def _lang_ids(eng, S):
    with S() as s:
        q = (
            s.query(Article.id)
            .filter(Article.id.notin_(select(Article.id).where(Article.quarantined.is_(True))))
            .filter(Article.language == "en")
            .order_by(Article.published_at.desc(), Article.id.desc())
            .limit(100)
        )
        return _render(eng, q)


def _title_ids(eng, S, *, descending: bool):
    with S() as s:
        col = Article.title.collate("NOCASE")
        q = (
            s.query(Article.id)
            .filter(Article.id.notin_(select(Article.id).where(Article.quarantined.is_(True))))
            .order_by(col.desc() if descending else col.asc(), Article.id.desc())
            .limit(100)
        )
        return _render(eng, q)


def _ids(eng, sql: str) -> list[int]:
    with eng.connect() as c:
        return [r[0] for r in c.execute(text(sql))]


@pytest.fixture
def eng(tmp_path):
    e = _store(tmp_path)
    yield e
    e.dispose()


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    ai._reset_for_tests()
    # a registry of its own, nothing latched: the module's global one may carry another test's state
    monkeypatch.setattr(damage, "registry", DamageRegistry(path_fn=lambda: tmp_path / "database-damage.json"))
    monkeypatch.delenv("OO_ARTICLE_INDEXES", raising=False)
    yield
    boot_sequence._reset()


class _Ctx:
    """The job context's progress surface, recording what the task manager would be told."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def set_progress(self, **kw):
        self.calls.append(kw)


# --------------------------------------------------------------------------- #
#  the plans, and the answers
# --------------------------------------------------------------------------- #
def test_the_language_filter_and_both_title_sorts_read_only_the_index(eng):
    S = sessionmaker(bind=eng)
    before = {
        "lang": _plan(eng, _lang_ids(eng, S)),
        "t_desc": _plan(eng, _title_ids(eng, S, descending=True)),
    }
    # the negative control: without the indexes these shapes sort (the work the indexes remove)
    assert any("TEMP B-TREE" in p for p in before["lang"]), before["lang"]
    assert any("TEMP B-TREE" in p for p in before["t_desc"]), before["t_desc"]
    ensure_hot_indexes(eng)
    lang = _plan(eng, _lang_ids(eng, S))
    assert any(f"USING COVERING INDEX {LANG}" in p for p in lang), lang
    assert not any("TEMP B-TREE FOR ORDER BY" in p for p in lang), lang
    for descending in (True, False):
        plan = _plan(eng, _title_ids(eng, S, descending=descending))
        assert any(f"USING COVERING INDEX {TITLE}" in p for p in plan), plan
        assert not any("TEMP B-TREE FOR ORDER BY" in p for p in plan), plan


def test_the_answers_are_identical_with_and_without_the_indexes(eng):
    """Only cost may change: the same ids in the same order, ties and NULL dates included."""
    S = sessionmaker(bind=eng)
    shapes = {
        "lang": _lang_ids(eng, S),
        "t_desc": _title_ids(eng, S, descending=True),
        "t_asc": _title_ids(eng, S, descending=False),
    }
    without = {k: _ids(eng, v) for k, v in shapes.items()}
    assert all(len(v) == 100 for v in without.values())
    ensure_hot_indexes(eng)
    with_ = {k: _ids(eng, v) for k, v in shapes.items()}
    assert with_ == without


def test_a_plain_title_index_cannot_serve_the_nocase_sort(eng):
    """The collation is the reason the index is declared COLLATE NOCASE: an index of another collation cannot give
    the order of this one, and the sort over every row stays."""
    S = sessionmaker(bind=eng)
    with eng.begin() as c:
        c.execute(text("CREATE INDEX idx_plain_title ON articles (title)"))
    plan = _plan(eng, _title_ids(eng, S, descending=True))
    # the planner may still scan it to read the titles, but it cannot take the ORDER from it: the sort stays
    assert any("TEMP B-TREE FOR ORDER BY" in p for p in plan), plan


# --------------------------------------------------------------------------- #
#  where each index is declared, and that init_db leaves them out
# --------------------------------------------------------------------------- #
def test_the_entries_the_model_the_deferral_and_the_migration_agree():
    assert ai.NAMES == (LANG, TITLE)
    assert frozenset(ai.NAMES) == DEFERRED_INDEXES
    assert all(n in HOT_INDEXES for n in ai.NAMES)
    on_model = {ix.name for ix in Article.__table__.indexes}
    assert set(ai.NAMES) <= on_model, "a HOT_INDEXES entry the model does not declare reads as schema drift"
    mig = _migration()
    assert HOT_INDEXES[LANG] == mig._LANGUAGE and HOT_INDEXES[TITLE] == mig._TITLE, (
        "the migration and the self-heal must be the same statements"
    )
    assert mig.revision == "c3a91f5e7b24" and mig.down_revision == "a7c9e1b3d5f7"


def _migration():
    import importlib.util

    path = next((ROOT / "migrations" / "versions").glob("c3a91f5e7b24_*.py"))
    spec = importlib.util.spec_from_file_location("mig_c3a91f5e7b24", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_migration_is_in_the_head_chain_and_idempotent(eng):
    from alembic.script import ScriptDirectory

    from src.database.migrate import _alembic_config

    script = ScriptDirectory.from_config(_alembic_config())
    ancestry = {r.revision for r in script.iterate_revisions("heads", "base")}
    assert "c3a91f5e7b24" in ancestry
    assert len(script.get_heads()) == 1, "a second head: the migration chain forked"
    mig = _migration()
    with eng.begin() as c:
        for stmt in (mig._LANGUAGE, mig._TITLE, mig._LANGUAGE, mig._TITLE):  # twice: IF NOT EXISTS
            c.execute(text(stmt))
    assert {LANG, TITLE} <= _names(eng)


def test_the_hot_index_pass_init_db_runs_leaves_the_deferred_ones_to_the_step(eng):
    created = ensure_hot_indexes(eng, include_deferred=False)
    assert not ({LANG, TITLE} & set(created)) and not ({LANG, TITLE} & _names(eng))
    assert {LANG, TITLE} == set(ensure_hot_indexes(eng))  # every other caller keeps the whole map


def test_init_db_asks_for_the_pass_without_the_deferred_indexes():
    src = (ROOT / "src" / "database" / "session.py").read_text(encoding="utf-8")
    assert "ensure_hot_indexes(engine, include_deferred=False)" in src
    assert not re.search(r"ensure_hot_indexes\(engine\)\s*$", src, re.M), "a second, full pass would build them"


def test_a_fresh_store_gets_both_from_create_all_with_the_table(tmp_path):
    e = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    Base.metadata.create_all(e)
    assert {LANG, TITLE} <= _names(e)
    with e.connect() as c:
        sql = c.execute(text("SELECT sql FROM sqlite_master WHERE name=:n"), {"n": TITLE}).scalar()
    assert "NOCASE" in sql.upper(), sql
    assert ai.pending(e) == ("present", [])
    e.dispose()


# --------------------------------------------------------------------------- #
#  the stamp alignment
# --------------------------------------------------------------------------- #
def test_the_stamp_alignment_reads_no_drift_for_the_title_index_in_any_state(eng):
    from src.database.migrate import _schema_diffs_vs_head

    with eng.begin() as c:
        c.execute(text(HOT_INDEXES[LANG]))
    assert _schema_diffs_vs_head(eng) == [], "the title index absent: no difference"
    with eng.begin() as c:
        c.execute(text(HOT_INDEXES[TITLE]))
    assert _schema_diffs_vs_head(eng) == [], "both built: at head"


def test_the_language_index_absent_is_the_one_boot_transient_the_step_ends(eng):
    """Between init_db (which leaves it out) and the step that builds it the stamp alignment says
    schema-behind and keeps the stamp, which is harmless (its migration is IF NOT EXISTS); the next start finds
    the schema at head. Pinned so a change to that is noticed, not assumed."""
    from src.database.migrate import _schema_diffs_vs_head

    assert _schema_diffs_vs_head(eng) == [f"add_index:{LANG}"]
    ai.build_missing(eng)
    assert _schema_diffs_vs_head(eng) == []


# --------------------------------------------------------------------------- #
#  the build
# --------------------------------------------------------------------------- #
def test_the_build_makes_both_in_order_reports_progress_and_the_second_call_finds_them(eng):
    ctx = _Ctx()
    rep = ai.build_missing(eng, ctx)
    assert rep["outcome"] == "built" and list(rep["built"]) == [LANG, TITLE]
    assert {LANG, TITLE} <= _names(eng)
    assert [(c.get("done"), c.get("total")) for c in ctx.calls] == [(0, 2), (1, 2), (2, 2)]
    first = ctx.calls[0]["detail"]
    assert isinstance(first, Framed) and first.i18n == ai.FRAME_BUILDING and first.vars == {"index": 1, "total": 2}
    assert "1 of 2" in str(first)
    assert ai.build_missing(eng)["outcome"] == "present"
    snap = ai.snapshot()
    assert snap["outcome"] == "present"


def test_only_the_missing_one_is_built(eng):
    with eng.begin() as c:
        c.execute(text(HOT_INDEXES[LANG]))
    rep = ai.build_missing(eng, _Ctx())
    assert list(rep["built"]) == [TITLE]


def test_each_statement_runs_under_the_write_gate_so_writers_queue_instead_of_erroring(eng):
    from src.database.writer import write_gate

    held: list[bool] = []

    @event.listens_for(eng, "before_cursor_execute")
    def _watch(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("CREATE INDEX", "ANALYZE")):
            held.append(write_gate.held_by_current_thread())

    ai.build_missing(eng)
    assert held == [True, True, True, True], "the two builds and the two ANALYZE of their statistics (sqlite_stat1 is a write)"
    assert not write_gate.held_by_current_thread(), "the gate must be released when the build returns"


def test_a_writer_that_comes_during_the_build_waits_for_the_gate(eng):
    from src.database.writer import WriteGateBusy, write_lock

    seen: list[str] = []

    @event.listens_for(eng, "before_cursor_execute")
    def _during(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("CREATE INDEX") and not seen:
            def other():
                try:
                    with write_lock(timeout=0.2):
                        seen.append("got it")
                except WriteGateBusy:
                    seen.append("queued")

            t = threading.Thread(target=other)
            t.start()
            t.join(5)

    ai.build_missing(eng)
    assert seen == ["queued"]


def test_the_switch_leaves_the_store_as_it_was(eng, monkeypatch):
    monkeypatch.setenv("OO_ARTICLE_INDEXES", "0")
    assert ai.build_missing(eng)["outcome"] == "skipped"
    assert not ({LANG, TITLE} & _names(eng))
    assert ai.run_now_and_wait(eng) == "skipped"


def test_a_store_without_an_articles_table_is_skipped(tmp_path):
    e = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    with e.begin() as c:
        c.execute(text("CREATE TABLE other (id INTEGER PRIMARY KEY)"))
    assert ai.build_missing(e)["outcome"] == "skipped"
    e.dispose()


def test_a_corpus_file_paused_as_damaged_is_declined_and_nothing_is_written(eng, monkeypatch):
    monkeypatch.setattr(damage.registry, "writes_paused", lambda key: key == FILE_CORPUS)
    rep = ai.build_missing(eng)
    assert rep["outcome"] == "declined" and "damaged" in rep["reason"]
    assert not ({LANG, TITLE} & _names(eng))
    assert ai.run_now_and_wait(eng) == "declined"


def test_too_little_free_space_refuses_with_the_numbers_and_the_job_row_says_so(eng, monkeypatch):
    class Usage:
        free = 1_000

    monkeypatch.setattr(ai.shutil, "disk_usage", lambda where: Usage)
    with pytest.raises(ai.Declined) as exc:
        ai.build_missing(eng)
    msg = str(exc.value)
    assert "1,000 bytes free" in msg and "restart" in msg and "600 articles" in msg
    assert ai.snapshot()["outcome"] == "declined" and ai.snapshot()["preflight"]["sufficient"] is False
    assert not ({LANG, TITLE} & _names(eng))
    assert ai.run_now_and_wait(eng) == "declined"
    st = ai.ARTICLE_INDEX_JOB.status()
    assert st["state"] == "error" and "1,000 bytes free" in (st["error"] or "")
    assert "1,000 bytes free" in ai.snapshot()["reason"], "the snapshot lost the reason for the refusal"


def test_a_refusal_for_space_reaches_the_row_as_a_keyed_detail_in_the_job_list(eng, monkeypatch):
    """The deep read's S2: the English error is drawn by no renderer for this kind; the detail frame is, and it is a key
    in every locale (test_the_label_and_the_progress_frame_are_keys_in_every_locale)."""
    from src.api import jobs as jobs_api

    class Usage:
        free = 200_000

    monkeypatch.setattr(ai.shutil, "disk_usage", lambda where: Usage)
    assert ai.run_now_and_wait(eng) == "declined"
    row = next(j for j in jobs_api.list_jobs()["jobs"] if j["id"] == "article-indexes")
    assert row["detail_i18n"] == ai.FRAME_NO_ROOM, row
    assert row["detail_vars"] == {"free": 0, "needed": 1, "rows": 600}, row["detail_vars"]  # whole MB: free rounded down, needed up
    assert row["detail"] == ai.FRAME_NO_ROOM.format(**row["detail_vars"])


def test_an_unreadable_free_space_figure_is_not_a_refusal(eng, monkeypatch):
    def boom(where):
        raise OSError("statvfs failed")

    monkeypatch.setattr(ai.shutil, "disk_usage", boom)
    rep = ai.build_missing(eng)
    assert rep["outcome"] == "built" and rep["preflight"]["sufficient"] is None


def test_the_space_asked_scales_with_the_articles_and_names_what_it_protects(eng):
    rep = ai.preflight(eng, 1_500_000)
    assert ai.BYTES_PER_ARTICLE == 400 and ai.RAM_BYTES_PER_ARTICLE == 125, "a figure changed: update the words that quote it"
    assert rep["needed_bytes"] == 1_500_000 * ai.BYTES_PER_ARTICLE
    assert "write-ahead log" in rep["method"] and f"about {ai.BYTES_PER_ARTICLE} bytes per article" in rep["method"]
    assert f"about {ai.RAM_BYTES_PER_ARTICLE} bytes per article" in rep["method"], "the RAM the sort holds is not said"
    assert rep["ram_estimate_bytes"] == 1_500_000 * ai.RAM_BYTES_PER_ARTICLE
    big = ai.preflight(eng, 10**15)
    assert big["sufficient"] is False and big["short_on"] and "bytes free" in big["detail"]
    assert str(ai.BYTES_PER_ARTICLE) in big["detail"]


def test_only_the_database_volume_is_measured_because_the_sort_never_writes_a_temporary_file(eng, monkeypatch):
    """The deep read's S1: every connection sets ``temp_store=MEMORY``, so the temp volume is not written to and a
    shortfall there would point the operator at a volume the build never touches."""
    asked: list[str] = []
    real = ai.shutil.disk_usage

    def spy(where):
        asked.append(str(where))
        return real(where)

    monkeypatch.setattr(ai.shutil, "disk_usage", spy)
    rep = ai.preflight(eng, 1_000)
    assert set(rep["free_bytes"]) == {"database"} and len(asked) == 1, (rep["free_bytes"], asked)


def test_a_statement_that_fails_is_failed_leaves_no_half_index_and_the_next_try_builds_the_rest(eng, monkeypatch):
    monkeypatch.setitem(HOT_INDEXES, TITLE, "CREATE INDEX IF NOT EXISTS idx_article_title_nocase ON articles (nope)")
    with pytest.raises(Exception):  # noqa: B017 - the driver's own error class
        ai.build_missing(eng)
    assert ai.snapshot()["outcome"] == "failed"
    names = _names(eng)
    assert LANG in names and TITLE not in names
    monkeypatch.undo()
    rep = ai.build_missing(eng)
    assert rep["outcome"] == "built" and list(rep["built"]) == [TITLE]


def test_the_planner_gets_statistics_for_the_new_indexes_and_only_those(eng):
    ai.build_missing(eng)
    with eng.connect() as c:
        have = {r[0] for r in c.execute(text("SELECT idx FROM sqlite_stat1"))}
    assert {LANG, TITLE} <= have


def test_a_store_made_by_create_all_serves_the_nocase_sort_from_its_index(tmp_path):
    """create_all spells the collation through SQLAlchemy (``COLLATE "NOCASE"``), the self-heal as
    ``COLLATE NOCASE``: both must be the NOCASE order the list asks for."""
    e = create_engine(f"sqlite:///{tmp_path / 'fresh2.db'}")
    Base.metadata.create_all(e)
    S = sessionmaker(bind=e)
    plan = _plan(e, _title_ids(e, S, descending=True))
    assert any(f"USING COVERING INDEX {TITLE}" in p for p in plan), plan
    e.dispose()


# --------------------------------------------------------------------------- #
#  the task-manager job
# --------------------------------------------------------------------------- #
def test_a_store_with_nothing_to_build_starts_no_job(eng):
    ai.build_missing(eng)
    ai.ARTICLE_INDEX_JOB._state = "idle"  # as at process start
    assert ai.run_now_and_wait(eng) == "present"
    assert ai.ARTICLE_INDEX_JOB.status()["state"] == "idle", "a row would flash by in the task manager"


def test_the_build_is_a_listed_job_with_progress_a_writer_and_no_cancel(eng, monkeypatch):
    from src.api import jobs as jobs_api

    inside, release = threading.Event(), threading.Event()
    real = ai.build_missing

    def slow(engine, ctx=None):
        inside.set()
        release.wait(10)
        return real(engine, ctx)

    monkeypatch.setattr(ai, "build_missing", slow)
    out: dict = {}
    t = threading.Thread(target=lambda: out.setdefault("o", ai.run_now_and_wait(eng)))
    t.start()
    assert inside.wait(10)
    try:
        listing = jobs_api.list_jobs()
        row = next(j for j in listing["jobs"] if j["id"] == "article-indexes")
        assert row["state"] == "running" and row["label"] == ai.LABEL and row["actions"] == []
        assert listing["db_writers_busy"] is True, "collection must be told something is writing"
        assert ai.ARTICLE_INDEX_JOB.is_writer is True, "offline maintenance reads this to hold off"
        assert "article-indexes" in jobs_api._DB_WRITER_KINDS
    finally:
        release.set()
        t.join(20)
    assert out["o"] == "built"
    assert not any(j["id"] == "article-indexes" for j in jobs_api.list_jobs()["jobs"]), "a finished job leaves the list"


def test_the_job_row_carries_the_framed_progress_line(eng):
    from src.api import jobs as jobs_api

    seen: dict = {}

    @event.listens_for(eng, "before_cursor_execute")
    def _look(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("CREATE INDEX") and "row" not in seen:
            seen["row"] = next(j for j in jobs_api.list_jobs()["jobs"] if j["id"] == "article-indexes")

    assert ai.run_now_and_wait(eng) == "built"
    row = seen["row"]
    assert row["detail_i18n"] == ai.FRAME_BUILDING and row["detail_vars"] == {"index": 1, "total": 2}
    assert row["progress"]["total"] == 2


def test_the_snapshot_is_a_copy_at_every_depth_and_a_second_run_carries_nothing_of_the_first(eng, monkeypatch):
    class Usage:
        free = 1_000

    real = ai.shutil.disk_usage
    monkeypatch.setattr(ai.shutil, "disk_usage", lambda where: Usage)
    with pytest.raises(ai.Declined):
        ai.build_missing(eng)
    snap = ai.snapshot()
    snap["preflight"]["free_bytes"]["database"] = -1
    assert ai.snapshot()["preflight"]["free_bytes"]["database"] == 1_000, "the caller shares state with the module"
    monkeypatch.setattr(ai.shutil, "disk_usage", real)
    ai.build_missing(eng)
    after = ai.snapshot()
    assert after["outcome"] == "built" and "reason" not in after, "the refused run's reason outlived the run that followed"


def test_a_worker_thread_that_cannot_start_leaves_no_phantom_running_job(eng, monkeypatch):
    """The deep read's N1: ``start`` set the state to running before ``Thread.start`` and never gave it back, so the job
    stayed running for the life of the process (``db_writers_busy`` true, offline maintenance declining) and the step read
    the failure as "already running"."""
    import types

    from src.api import jobs as jobs_api
    from src.jobs import background

    class Boom:
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(
        background, "threading",
        types.SimpleNamespace(Thread=Boom, RLock=threading.RLock, Lock=threading.Lock, Event=threading.Event),
    )
    assert ai.run_now_and_wait(eng) == "failed"
    st = ai.ARTICLE_INDEX_JOB.status()
    assert st["state"] == "error" and "could not start" in (st["error"] or ""), st
    assert ai.ARTICLE_INDEX_JOB.join(0.5) is True
    assert jobs_api.list_jobs()["db_writers_busy"] is False


def test_join_waits_for_the_worker_and_is_true_when_none_ever_ran():
    from src.jobs.background import BackgroundJob

    release = threading.Event()
    job = BackgroundJob("t-join", "t", lambda ctx: release.wait(10))
    assert job.join() is True
    job.start()
    assert job.join(0.05) is False
    release.set()
    assert job.join(10) is True


# --------------------------------------------------------------------------- #
#  the boot step
# --------------------------------------------------------------------------- #
def test_the_step_comes_after_the_check_and_before_the_warm_up_inside_the_warm_window():
    assert boot_sequence.STEPS[:3] == ("verify-database", "article-indexes", "warm-cache")
    src = (ROOT / "src" / "api" / "boot_sequence.py").read_text(encoding="utf-8")
    run = python_function_source(src, "run")
    assert run.index("_verify_database") < run.index("_article_indexes") < run.index("warm,")
    assert run.index("_article_indexes") < run.index('_STATE["warm"] = "done"'), (
        "the build is inside the window in which a serve-kicked rollup declines"
    )


@pytest.mark.parametrize(
    ("outcome", "state"),
    [("built", "done"), ("present", "skipped"), ("skipped", "skipped"), ("declined", "declined"), ("failed", "failed")],
)
def test_each_outcome_is_its_own_state_in_the_snapshot(outcome, state, monkeypatch):
    monkeypatch.setattr(ai, "run_now_and_wait", lambda *a, **k: outcome)
    monkeypatch.setattr(boot_sequence, "_verify_database", lambda: (_ for _ in ()).throw(boot_sequence._Skipped()))
    monkeypatch.setattr(boot_sequence, "_rollup_first_build", lambda: None)
    monkeypatch.setattr(boot_sequence, "_start_reindex", lambda: None)
    boot_sequence._reset()
    boot_sequence.run(lambda: None)
    rows = {r["step"]: r for r in boot_sequence.snapshot()["steps"]}
    assert rows["article-indexes"]["state"] == state
    assert rows["warm-cache"]["state"] == "done", "a declined or failed build never holds the next step"


def test_the_step_builds_for_real_and_the_snapshot_says_what_it_did(eng, monkeypatch):
    from src.database import session

    monkeypatch.setattr(session, "engine", eng)
    monkeypatch.setattr(boot_sequence, "_verify_database", lambda: (_ for _ in ()).throw(boot_sequence._Skipped()))
    monkeypatch.setattr(boot_sequence, "_rollup_first_build", lambda: None)
    monkeypatch.setattr(boot_sequence, "_start_reindex", lambda: None)
    boot_sequence._reset()
    warmed: list[set[str]] = []
    boot_sequence.run(lambda: warmed.append({LANG, TITLE} & _names(eng)))
    assert warmed == [{LANG, TITLE}], "the warm-up started before the indexes existed"
    snap = boot_sequence.snapshot()
    assert {r["step"]: r["state"] for r in snap["steps"]}["article-indexes"] == "done"
    block = snap["article_indexes"]
    assert block["outcome"] == "built" and set(block["built"]) == {LANG, TITLE} and block["rows_bound"] == 600
    assert "gate_wait_s" in block and block["preflight"]["needed_bytes"] == 600 * ai.BYTES_PER_ARTICLE


def test_a_second_start_finds_them_and_the_step_is_skipped(eng, monkeypatch):
    from src.database import session

    monkeypatch.setattr(session, "engine", eng)
    ai.build_missing(eng)
    monkeypatch.setattr(boot_sequence, "_verify_database", lambda: (_ for _ in ()).throw(boot_sequence._Skipped()))
    monkeypatch.setattr(boot_sequence, "_rollup_first_build", lambda: None)
    monkeypatch.setattr(boot_sequence, "_start_reindex", lambda: None)
    boot_sequence._reset()
    boot_sequence.run(lambda: None)
    assert {r["step"]: r["state"] for r in boot_sequence.snapshot()["steps"]}["article-indexes"] == "skipped"


def test_a_serve_kicked_build_during_the_window_is_told_the_index_build_may_be_what_it_waits_for():
    with boot_sequence._LOCK:
        boot_sequence._STATE["warm"] = "running"
    try:
        verdict = boot_sequence.heavy_step_verdict()
    finally:
        boot_sequence._reset()
    assert verdict and verdict["reason"] == "boot_order" and "index build" in verdict["detail"], verdict


# --------------------------------------------------------------------------- #
#  the words, in the twelve languages
# --------------------------------------------------------------------------- #
def test_the_label_and_the_progress_frame_are_keys_in_every_locale():
    import json

    for p in sorted((ROOT / "src" / "static" / "locales").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        assert ai.LABEL in d and ai.FRAME_BUILDING in d and ai.FRAME_NO_ROOM in d, p.name
        frame, room = d[ai.FRAME_BUILDING], d[ai.FRAME_NO_ROOM]
        assert "{index}" in frame and "{total}" in frame, p.name
        assert all(f"{{{v}}}" in room for v in ("free", "needed", "rows")), p.name
        if p.stem != "en":
            assert frame != ai.FRAME_BUILDING and d[ai.LABEL] != ai.LABEL, f"{p.name}: left in English"
            assert room != ai.FRAME_NO_ROOM, f"{p.name}: the refusal is left in English"
    assert ai.FRAME_BUILDING.format(index=1, total=2).startswith("Building the indexes that keep the article list fast: 1 of 2")
    assert "anything the app saves waits" in ai.FRAME_BUILDING, "every gated write waits, not only a new article's"


def test_the_switch_is_documented_in_the_manual():
    manual = (ROOT / "docs" / "USER_MANUAL.md").read_text(encoding="utf-8")
    assert "OO_ARTICLE_INDEXES" in manual
